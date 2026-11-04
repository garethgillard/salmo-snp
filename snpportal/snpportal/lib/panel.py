"""Panel designer (P6.3) and chip comparison (P6.6) on annotated SNPs (annotate output, a job's view or the pool).

design(): an evenly spread backbone (the best SNP in each genome-length-proportional bin) plus a functional fill by
design_score, under min spacing (bp, and optionally cM from the genetic map columns), MAF, assay, flag, per-gene and
per-element (AQUA-FAANG peak) caps. Defaults come from the weights.yaml 'design' block (PROVISIONAL). Ties always go
to the lower row number, so the same input and parameters give the same panel (and the same hash). The summary carries
the vendors' panel-level checks (vendor_checks: Illumina Infinium bins, markers within 60 bp).
compare(): on_chip, dist_to_chip, near_chip and novel_functional per SNP, the counts, and the chip's gaps with the
best SNP to fill each one (from the list, else the pool)."""
from __future__ import annotations

import bisect
import hashlib
import json
from pathlib import Path

from snpscore import assay
from snpscore.annotate import connect, read_snps
from snpscore.formats import InputError, lit, q
from snpscore.score import scored

DEFAULTS = {  # PROVISIONAL; weights.yaml 'design' overrides these
    "n_target": 384, "backbone_fraction": 0.5, "min_spacing": 20000, "min_maf": 0.05, "max_per_gene": 2,
    "max_per_element": 1, "require_assay_pass": False, "exclude_flags": ["blacklist"],
    "score": {"tier": 1.0, "assay": 0.3, "maf": 0.3}, "chip_window": 10000, "chip_gap": 1000000,
    "min_spacing_cm": None,  # also keep markers this many cM apart (needs annotate's cm_male / cm_female columns)
    "cm_map": "mean",  # which map: female, male or mean (sex-averaged); the male map is short on chr 2, 8 and 17
    "upgrade_min_call_rate": 0.95, "upgrade_min_hwe_p": 1e-6,  # upgrade(): QC of the chip's markers in your population
}
CM_MAPS = {"female": "try_cast(cm_female AS DOUBLE)", "male": "try_cast(cm_male AS DOUBLE)",
           "mean": "(coalesce(cm_male, cm_female) + coalesce(cm_female, cm_male)) / 2"}
INFINIUM_I_MIN, INFINIUM_I_POLYPLOID, INFINIUM_II_MIN = 100, 200, 1000  # Illumina error 111, warning 604 (vendor rules)
CLOSE_BP = 60  # Illumina warning 340: another listed polymorphism within 60 nt
PAGE = 20000  # functional fill reads the sorted candidates in batches of this many rows
PER_BIN = 25  # backbone: candidates tried per bin
TEXT = ("chrom", "id", "ref", "alt", "genome_base")  # columns read as text from a TSV/CSV source
CHIP_MAX = 3_000_000  # read_chip refuses longer chip lists (a small .gz can hold billions of rows)


def settings(weights=None, **given):
    """The design parameters: DEFAULTS, then weights.yaml 'design', then the given values that are not None."""
    p = {**DEFAULTS, **((weights or {}).get("design") or {})}
    p.update({k: v for k, v in given.items() if v is not None})
    p["exclude_flags"] = sorted(set(p["exclude_flags"] or []))
    p["must_include"] = sorted(set(p.get("must_include") or []))
    return p


def params_hash(params):
    """Short stable hash of a parameter dict (panels/<hash>.parquet in a job folder)."""
    return hashlib.sha256(json.dumps(params, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _file(path):
    path = Path(path).resolve()
    if not path.is_file():
        raise InputError(f"The file {path.name} was not found.")
    return path


def _relation(con, path):
    """read_parquet (with file_row_number) or read_csv of a file. TEXT columns of a TSV/CSV are read as text: chromosome
    names look like numbers, and a column of T alleles like booleans."""
    path = _file(path)
    if path.suffix == ".parquet":
        return f"read_parquet({lit(path)}, file_row_number=true)"
    csv = f"read_csv({lit(path)}, header=true{{}})"
    names = _types(con, csv.format(", all_varchar=true"))
    types = ", ".join(f"{lit(c)}: 'VARCHAR'" for c in TEXT if c in names)
    return csv.format(f", types={{{types}}}" if types else "")


def _types(con, rel):
    return dict(con.execute(f"SELECT column_name, column_type FROM (DESCRIBE SELECT * FROM {rel})").fetchall())


def _open(source, table, read=(), out=None, preset=None, weights=None, synthetic=()):
    """(connection, relation SQL with _row = the row number, column types) for a parquet/TSV path (a sandboxed
    connection that may also read the folders `read` and write out's folder) or a connection and a table name.
    A path holds the tiers of the preset it was annotated with: without tier__<preset> columns, its tier columns are
    recomputed for `preset` with `weights` (the manifest's `synthetic` layers never count)."""
    if isinstance(source, (str, Path)):
        path = _file(source)
        con = connect([path.parent, *read], Path(out).resolve().parent if out else None)
        rel = _relation(con, path)
    else:
        con, rel = source, table
    columns = _types(con, rel)
    if isinstance(source, (str, Path)) and preset and weights and "tier" in columns and f"tier__{preset}" not in columns:
        rel = f"({scored(rel, weights, list(columns), preset, synthetic)})"
        columns = _types(con, rel)
    row = "file_row_number" if "file_row_number" in columns else "row_number() OVER () - 1"
    return con, f"(SELECT {row} AS _row, * FROM {rel})", columns


def _tier_cols(columns, preset):
    """(tier, tier_score) column names for a preset: tier__<preset> from tiers.parquet or the pool, else tier."""
    if preset and f"tier__{preset}" in columns:
        return q(f"tier__{preset}"), q(f"tier_score__{preset}")
    if "tier" not in columns:
        raise InputError("These SNPs have no tier columns: annotate them with snpscore first.")
    return "tier", "tier_score"


def _maf(columns):
    """SQL for the SNP's minor allele frequency: your maf or af column, else the public MAF."""
    if "maf" in columns:
        return "try_cast(maf AS DOUBLE)"
    if "af" in columns:
        return "least(try_cast(af AS DOUBLE), 1 - try_cast(af AS DOUBLE))"
    return "public_af_maf" if "public_af_maf" in columns else "NULL::DOUBLE"


def _flag(name, kind):
    return f"coalesce({q(name)}, false)" if kind == "BOOLEAN" else f"coalesce(try_cast({q(name)} AS DOUBLE), 0) > 0"


def vendor_checks(snps):
    """Panel-level vendor checks of [(chrom, pos, ref, alt)] (alleles may be None): {'infinium_bins': {A: A/T SNPs,
    B: C/G SNPs (Infinium I, two bead types), C: the other SNPs (Infinium II), unknown: alleles unknown},
    'close_pairs': markers within CLOSE_BP of the previous one, 'warnings': [text]}. An Illumina Infinium design can't
    be ordered with 1-99 SNPs in bin A or B or 1-999 in bin C (error 111); 200 are recommended in A and B for
    polyploids (warning 604), which salmon partly is."""
    bins, positions = {"A": 0, "B": 0, "C": 0, "unknown": 0}, {}
    for chrom, pos, ref, alt in snps:
        pair = {str(ref or "").upper(), str(alt or "").upper()}
        ok = len(pair) == 2 and pair <= set("ACGT")
        bins["A" if pair == {"A", "T"} else "B" if pair == {"C", "G"} else "C" if ok else "unknown"] += 1
        positions.setdefault(chrom, []).append(pos)
    close = sum(b - a <= CLOSE_BP for p in positions.values() for a, b in zip(sorted(p), sorted(p)[1:]))
    warnings = []
    for b, kind in (("A", "A/T"), ("B", "C/G")):
        if 0 < bins[b] < INFINIUM_I_MIN:
            warnings.append(f"Illumina Infinium: {bins[b]} {kind} SNPs in Infinium I bin {b}, but a used bin needs at least "
                            f"{INFINIUM_I_MIN} (error 111): add more, or exclude A/T and C/G SNPs (strand_ambiguous)")
        elif INFINIUM_I_MIN <= bins[b] < INFINIUM_I_POLYPLOID:
            warnings.append(f"Illumina Infinium: {bins[b]} {kind} SNPs in Infinium I bin {b}, under the {INFINIUM_I_POLYPLOID} "
                            "recommended for polyploid species (warning 604)")
    if 0 < bins["C"] < INFINIUM_II_MIN:
        warnings.append(f"Illumina Infinium: {bins['C']} SNPs in Infinium II bin C, but a used bin needs at least "
                        f"{INFINIUM_II_MIN:,} (error 111)")
    if close:
        warnings.append(f"{close} markers within {CLOSE_BP} bp of another (Illumina warning 340; Thermo Fisher: "
                        "interfering SNPs can be as close as 10 bases)")
    return {"infinium_bins": bins, "close_pairs": close, "warnings": warnings}


def design(source, preset="all", n_target=None, min_spacing_bp=None, min_maf=None, backbone_fraction=None,
           max_per_gene=None, max_per_element=None, require_assay_pass=None, exclude_flags=None, must_include=None,
           weights=None, chrom_sizes=None, table="v", out=None, min_spacing_cm=None, cm_map=None, synthetic=()):
    """Choose a panel from annotated SNPs: `source` is a parquet/TSV path or a DuckDB connection with `table`.
    Parameters left None come from weights['design'] (else DEFAULTS). `exclude_flags` are column names: rows where
    they are true (or > 0 for counts, e.g. flank_variants) are dropped; `must_include` ids are always selected first.
    `chrom_sizes` (manifest) sets the backbone bins (default: the largest position per chromosome). With
    `min_spacing_cm`, markers are also kept that many cM apart on the `cm_map` map (female, male or mean of annotate's
    cm_female and cm_male; SNPs beyond the first or last map marker take that marker's cM, and on a chromosome without
    a map they are left out). A path's tiers are recomputed for `preset` with `weights` when it has no tier__<preset>
    columns (see _open). Writes the selected rows (all columns plus selection_reason, panel_rank, design_score) to
    `out` if given.
    Returns {'params', 'hash', 'summary', 'selected': [{row, chrom, pos, id, selection_reason, panel_rank,
    design_score, tier}]}; selection_reason is must_include, backbone, functional (tier 1-3) or fill (tier 4)."""
    p = settings(weights, n_target=n_target, min_spacing=min_spacing_bp, min_maf=min_maf,
                 backbone_fraction=backbone_fraction, max_per_gene=max_per_gene, max_per_element=max_per_element,
                 require_assay_pass=require_assay_pass, exclude_flags=exclude_flags, must_include=must_include,
                 min_spacing_cm=min_spacing_cm, cm_map=cm_map)
    p["preset"] = preset
    con, rel, columns = _open(source, table, out=out, preset=preset, weights=weights, synthetic=synthetic)
    tier, tier_score = _tier_cols(columns, preset)
    cm_spacing = None if p["min_spacing_cm"] is None else float(p["min_spacing_cm"])
    if cm_spacing is not None and not {"cm_male", "cm_female"} <= set(columns):
        raise InputError("Spacing in cM needs the genetic map columns cm_male and cm_female: annotate with a release "
                         "that has the cm layer.")
    if p["cm_map"] not in CM_MAPS:
        raise InputError(f"Unknown genetic map '{p['cm_map']}'. Choose from: {', '.join(CM_MAPS)}")
    w = p["score"]
    col = lambda c: q(c) if c in columns else "NULL"  # noqa: E731
    keep = [f"NOT {_flag(f, columns[f])}" for f in p["exclude_flags"] if f in columns]
    if "assay_status" in columns:
        keep.append("assay_status = 'pass'" if p["require_assay_pass"] else "coalesce(assay_status, '') <> 'fail'")
    keep.append(f"_maf IS NULL OR _maf >= {float(p['min_maf'])}")
    must = f"{col('id')} IN ({', '.join(lit(i) for i in p['must_include'])})" if p["must_include"] and "id" in columns else "false"
    src = f"(SELECT *, {_maf(columns)} AS _maf, {must} AS _must, NULL::DOUBLE AS _cm FROM {rel})"
    if cm_spacing is not None:  # beyond the first or last map marker, that marker's cM; NULL on a chromosome without a map
        src = f"""(SELECT * EXCLUDE (_cm), coalesce(_cm, CASE WHEN pos < min(CASE WHEN _cm IS NOT NULL THEN pos END) OVER c
                   THEN min(_cm) OVER c ELSE max(_cm) OVER c END) AS _cm
                   FROM (SELECT * EXCLUDE (_cm), {CM_MAPS[p['cm_map']]} AS _cm FROM {src}) WINDOW c AS (PARTITION BY chrom))"""
        keep.append("_cm IS NOT NULL")
    con.execute(f"""CREATE OR REPLACE TEMP TABLE _cand AS
        SELECT _row, chrom, pos, {col('id')}::VARCHAR AS id, {col('gene_id')}::VARCHAR AS gene,
               {col('chromatin_id')}::VARCHAR AS element, {col('ref')}::VARCHAR AS ref, {col('alt')}::VARCHAR AS alt,
               {tier} AS tier, _cm, _must, ({' AND '.join(f'({k})' for k in keep)}) AS _ok,
               round({float(w['tier'])} * coalesce({tier_score}, 0) / greatest(max({tier_score}) OVER (), 1)
                     + {float(w['assay'])} * CASE {col('assay_status')} WHEN 'pass' THEN 1 WHEN 'warn' THEN 0.5 ELSE 0 END
                     + {float(w['maf'])} * least(coalesce(_maf, 0) / 0.5, 1), 6) AS design_score
        FROM {src}""")
    n_rows, n_ok = con.execute("SELECT count(*), count(*) FILTER (WHERE _ok OR _must) FROM _cand").fetchone()
    sizes = dict(chrom_sizes or {})
    for c, m in con.execute("SELECT chrom, max(pos) FROM _cand GROUP BY 1").fetchall():
        sizes[c] = max(sizes.get(c, 0), m)

    chosen, placed, placed_cm, per_gene, per_element, skipped = {}, {}, {}, {}, {}, {}
    n, spacing = int(p["n_target"]), float(p["min_spacing"])

    def take(row, chrom, pos, cm, gene, element, reason, force=False):
        """Select a candidate if it keeps the spacing and the caps (must_include: always). Returns True if taken.
        Positions are kept sorted per chromosome with their cM, which never decreases along a chromosome."""
        if row in chosen or len(chosen) >= n:
            return False
        near, cms = placed.setdefault(chrom, []), placed_cm.setdefault(chrom, [])
        i = bisect.bisect_left(near, pos)
        nb = [j for j in (i - 1, i) if 0 <= j < len(near)]
        why = ("min_spacing" if any(abs(near[j] - pos) < spacing for j in nb) else
               "min_spacing_cm" if cm_spacing is not None and cm is not None and any(
                   cms[j] is not None and abs(cms[j] - cm) < cm_spacing for j in nb) else
               "max_per_gene" if gene and per_gene.get(gene, 0) >= p["max_per_gene"] else
               "max_per_element" if element and per_element.get(element, 0) >= p["max_per_element"] else None)
        if why and not force:
            skipped[why] = skipped.get(why, 0) + 1
            return False
        near.insert(i, pos)
        cms.insert(i, cm)
        per_gene[gene] = per_gene.get(gene, 0) + 1
        per_element[element] = per_element.get(element, 0) + 1
        chosen[row] = reason
        return True

    for r in con.execute("SELECT _row, chrom, pos, _cm, gene, element FROM _cand WHERE _must ORDER BY _row").fetchall():
        take(*r, "must_include", force=True)
    # Backbone: bins per chromosome proportional to its length (largest remainder, so they add up to n_backbone)
    n_bb = min(n, round(n * float(p["backbone_fraction"])))
    total = sum(sizes.values()) or 1
    quota = {c: n_bb * s / total for c, s in sizes.items()}
    bins = {c: int(v) for c, v in quota.items()}
    for c in sorted(quota, key=lambda c: (-(quota[c] - bins[c]), c))[:n_bb - sum(bins.values())]:
        bins[c] += 1
    values = ", ".join(f"({lit(c)}, {k}, {sizes[c]})" for c, k in sorted(bins.items()) if k)
    if values:  # the best candidates of each bin, in genome order; the first that fits takes the bin
        filled, n_backbone = set(), 0
        for row, chrom, pos, cm, gene, element, b in con.execute(f"""
                SELECT _row, chrom, pos, _cm, gene, element, bin FROM (
                    SELECT c.*, least(floor(c.pos * b.k / b.len), b.k - 1)::BIGINT AS bin
                    FROM _cand c JOIN (VALUES {values}) b(chrom, k, len) USING (chrom) WHERE c._ok)
                QUALIFY row_number() OVER (PARTITION BY chrom, bin ORDER BY design_score DESC, _row) <= {PER_BIN}
                ORDER BY chrom, bin, design_score DESC, _row""").fetchall():
            if (chrom, b) not in filled and n_backbone < n_bb and take(row, chrom, pos, cm, gene, element, "backbone"):
                filled.add((chrom, b))
                n_backbone += 1
    # Functional fill: the best design_score first, sorted once and read in batches
    ranked = con.execute("SELECT _row, chrom, pos, _cm, gene, element, tier FROM _cand WHERE _ok ORDER BY design_score DESC, _row")
    while len(chosen) < n:
        page = ranked.fetchmany(PAGE)
        for row, chrom, pos, cm, gene, element, t in page:
            take(row, chrom, pos, cm, gene, element, "functional" if t is not None and t <= 3 else "fill")
            if len(chosen) >= n:
                break
        if len(page) < PAGE:
            break
    return _finish(con, rel, columns, p, chosen, sizes, n_rows, n_ok, skipped, out)


def _finish(con, rel, columns, p, chosen, sizes, n_rows, n_ok, skipped, out):
    """The selection as table _sel, the summary, and the rows written to `out`."""
    picks = ",".join(f"{row}:{reason}:{i + 1}" for i, (row, reason) in enumerate(chosen.items()))
    con.execute("""CREATE OR REPLACE TEMP TABLE _sel AS
        SELECT c.*, s.selection_reason, s.panel_rank FROM (
            SELECT split_part(x, ':', 1)::BIGINT AS _row, split_part(x, ':', 2) AS selection_reason,
                   split_part(x, ':', 3)::INTEGER AS panel_rank
            FROM (SELECT unnest(string_split(?, ',')) AS x) WHERE x <> '') s JOIN _cand c USING (_row)""", [picks])

    def rows(sql):
        return con.execute(sql).fetchall()

    gaps = """SELECT chrom, pos AS start, coalesce(lead(pos) OVER w, {end}) AS "end"
              FROM (SELECT chrom, pos FROM _sel UNION ALL SELECT chrom, 0 FROM (VALUES {chroms}) t(chrom)) WINDOW w AS
              (PARTITION BY chrom ORDER BY pos)"""
    chroms = ", ".join(f"({lit(c)})" for c in sorted(sizes))
    ends = " ".join(f"WHEN {lit(c)} THEN {s}" for c, s in sizes.items())
    gap_sql = gaps.format(end=f"CASE chrom {ends} END", chroms=chroms) if sizes else "SELECT 1 AS chrom, 0 AS start, 0 AS \"end\" WHERE false"
    spacing, spacing_cm = (rows(f"""SELECT min(d), median(d), max(d) FROM (
        SELECT {x} AS d FROM _sel) WHERE d IS NOT NULL""")[0] for x in (
        "pos - lag(pos) OVER (PARTITION BY chrom ORDER BY pos)", "round(_cm - lag(_cm) OVER (PARTITION BY chrom ORDER BY pos), 4)"))
    checks = vendor_checks(rows("SELECT chrom, pos, ref, alt FROM _sel ORDER BY panel_rank"))
    summary = {
        "preset": p["preset"], "n_target": p["n_target"], "n_selected": len(chosen), "n_rows": n_rows,
        "n_candidates": n_ok,
        "reasons": dict(rows("SELECT selection_reason, count(*) FROM _sel GROUP BY 1 ORDER BY 1")),
        "tiers": {str(t): c for t, c in rows("SELECT tier, count(*) FROM _sel GROUP BY 1 ORDER BY 1 NULLS LAST")},
        "per_chromosome": [{"chrom": c, "n": k, "length": sizes.get(c)} for c, k in rows(
            "SELECT chrom, count(*) FROM _sel GROUP BY 1 ORDER BY try_cast(chrom AS INTEGER), chrom")],
        "spacing": dict(zip(("min", "median", "max"), spacing)),
        **({"spacing_cm": dict(zip(("min", "median", "max"), spacing_cm))} if p["min_spacing_cm"] is not None else {}),
        "largest_gaps": [{"chrom": c, "start": s, "end": e, "size": e - s} for c, s, e in rows(
            f"SELECT chrom, start, \"end\" FROM ({gap_sql}) WHERE \"end\" > start ORDER BY \"end\" - start DESC, chrom, start LIMIT 10")],
        "missing_must_include": sorted(set(p["must_include"]) - {r[0] for r in rows(
            "SELECT id FROM _sel WHERE selection_reason = 'must_include'")}),
        "binding": None,
        "infinium_bins": checks["infinium_bins"], "close_pairs": checks["close_pairs"], "warnings": checks["warnings"],
    }
    if "region_class" in columns:
        summary["region_class"] = dict(rows(f"""SELECT coalesce(region_class, 'intergenic'), count(*) FROM {rel}
                                                SEMI JOIN _sel USING (_row) GROUP BY 1 ORDER BY 1"""))
    if "assay_status" in columns:
        summary["assay_status"] = dict(rows(f"SELECT assay_status, count(*) FROM {rel} SEMI JOIN _sel USING (_row) GROUP BY 1 ORDER BY 1"))
    if "assay_reasons" in columns:
        summary["assay_reasons"] = assay.breakdown(con, f"(SELECT assay_reasons FROM {rel} SEMI JOIN _sel USING (_row))")
    if len(chosen) < int(p["n_target"]):
        summary["binding"] = (f"only {n_ok:,} SNPs pass the filters (min_maf, assay, exclude_flags)"
                              if n_ok < int(p["n_target"]) else max(sorted(skipped), key=skipped.get) if skipped else None)
    selected = [dict(zip(("row", "chrom", "pos", "id", "selection_reason", "panel_rank", "design_score", "tier"), r))
                for r in rows("SELECT _row, chrom, pos, id, selection_reason, panel_rank, design_score, tier FROM _sel ORDER BY panel_rank")]
    digest = params_hash({"params": p, "selected": [(s["row"], s["selection_reason"]) for s in selected]})
    if out:
        drop = ", ".join(c for c in ("_row", "file_row_number") if c == "_row" or c in columns)
        con.execute(f"""COPY (SELECT t._row AS source_row, t.* EXCLUDE ({drop}), s.selection_reason, s.panel_rank, s.design_score
                              FROM {rel} t JOIN _sel s USING (_row) ORDER BY s.panel_rank)
                        TO {lit(Path(out).resolve())} (FORMAT parquet)""")
    return {"params": p, "hash": digest, "summary": summary, "selected": selected}


def compare_sql(rel, chip, window_bp, tier="tier"):
    """SQL adding on_chip, dist_to_chip (bp to the nearest chip SNP on the chromosome; NULL if none), near_chip
    (within window_bp) and novel_functional (tier 1-2 and not near the chip) to `rel`. `chip` has chrom, pos."""
    return f"""
        WITH c AS (SELECT DISTINCT chrom, pos::BIGINT AS pos FROM {chip})
        SELECT * EXCLUDE (_up, _down),
               least(pos - _up, _down - pos) AS dist_to_chip, coalesce(_up = pos, false) AS on_chip,
               coalesce(least(pos - _up, _down - pos) <= {int(window_bp)}, false) AS near_chip,
               coalesce({tier} <= 2, false) AND NOT coalesce(least(pos - _up, _down - pos) <= {int(window_bp)}, false)
                   AS novel_functional
        FROM (SELECT t.*, u.pos AS _up, d.pos AS _down
              FROM {rel} t ASOF LEFT JOIN c u ON t.chrom = u.chrom AND t.pos >= u.pos
                           ASOF LEFT JOIN c d ON t.chrom = d.chrom AND t.pos <= d.pos)"""


def _narrow(rel, columns, preset):
    """SQL with _row, chrom, pos, id, tier, score, maf of annotated SNPs (for choosing the best SNP in a region)."""
    tier, score = _tier_cols(columns, preset)
    ident = "id::VARCHAR" if "id" in columns else "NULL::VARCHAR"
    return f"(SELECT _row, chrom, pos, {ident} AS id, {tier} AS tier, {score} AS score, {_maf(columns)} AS maf FROM {rel})"


def compare(source, chip, preset="all", window_bp=None, gap_bp=None, pool=None, weights=None, chrom_sizes=None,
            table="v", synthetic=()):
    """Compare annotated SNPs with a chip: `chip` is a parquet/TSV with chrom and pos (see read_chip) or a table in
    the source's connection; `pool` the release's pool/pool.parquet (optional). With a path source the files may be
    in other folders, and its tiers are recomputed for `preset` as in design(); with a connection, it must be allowed
    to read them.
    Returns {'summary': {total, shared, novel_functional, other, chip_snps, window_bp, gap_bp, gaps}, 'gaps':
    [{chrom, start, end, size, filler}]}: chip gaps longer than gap_bp (also from a chromosome end when chrom_sizes are
    given), largest first, each with the best SNP inside it from the list (lowest tier, then highest tier_score,
    then MAF, then row), else from the pool, else None. compare_sql() gives the per-SNP columns."""
    p = settings(weights, chip_window=window_bp, chip_gap=gap_bp)
    extra = [Path(x).resolve().parent for x in (chip, pool) if x and Path(str(x)).is_file()]
    con, rel, columns = _open(source, table, extra, preset=preset, weights=weights, synthetic=synthetic)
    if isinstance(source, (str, Path)) or Path(str(chip)).is_file():  # else a table in the source's connection
        chip = _relation(con, chip)
    con.execute(f"CREATE OR REPLACE TEMP TABLE _chip AS SELECT DISTINCT chrom::VARCHAR AS chrom, pos::BIGINT AS pos FROM {chip}")
    tier = _tier_cols(columns, preset)[0]
    total, shared, novel = con.execute(f"""SELECT count(*), count(*) FILTER (WHERE on_chip), count(*) FILTER (WHERE novel_functional)
                                          FROM ({compare_sql(rel, '_chip', p['chip_window'], tier)})""").fetchone()
    sizes = dict(chrom_sizes or {})
    ends = "".join(f" WHEN {lit(c)} THEN {int(n)}" for c, n in sizes.items())
    starts = f" UNION ALL SELECT unnest([{', '.join(lit(c) for c in sizes)}]), 0" if sizes else ""
    con.execute(f"""CREATE OR REPLACE TEMP TABLE _gaps AS SELECT * FROM (
        SELECT chrom, pos AS start, coalesce(lead(pos) OVER (PARTITION BY chrom ORDER BY pos),
                                             {f'CASE chrom{ends} END' if sizes else 'NULL'}) AS "end"
        FROM (SELECT DISTINCT * FROM (SELECT chrom, pos FROM _chip{starts})))
        WHERE "end" - start > {int(p['chip_gap'])}""")

    def best(candidates):  # {(chrom, start): filler} for the gaps
        return {(c, s): {"chrom": c, "pos": pos, "id": i, "tier": t} for c, s, pos, i, t in con.execute(f"""
            SELECT g.chrom, g.start, c.pos, c.id, c.tier FROM _gaps g JOIN {candidates} c
                ON c.chrom = g.chrom AND c.pos > g.start AND c.pos < g."end"
            QUALIFY row_number() OVER (PARTITION BY g.chrom, g.start ORDER BY c.tier, c.score DESC, c.maf DESC NULLS LAST,
                                       c._row) = 1""").fetchall()}

    found = {k: {**v, "source": "list"} for k, v in best(_narrow(rel, columns, preset)).items()}
    if pool:
        pool_rel = f"(SELECT file_row_number AS _row, * FROM read_parquet({lit(Path(pool).resolve())}, file_row_number=true))"
        pool_cols = [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM {pool_rel}").fetchall()]
        found = {**{k: {**v, "source": "pool"} for k, v in best(_narrow(pool_rel, pool_cols, preset)).items()}, **found}
    gaps = [{"chrom": c, "start": s, "end": e, "size": e - s, "filler": found.get((c, s))} for c, s, e in con.execute(
        'SELECT chrom, start, "end" FROM _gaps ORDER BY "end" - start DESC, chrom, start').fetchall()]
    n_chip = con.execute("SELECT count(*) FROM _chip").fetchone()[0]
    summary = {"total": total, "shared": shared, "novel_functional": novel, "other": total - shared - novel,
               "chip_snps": n_chip, "window_bp": p["chip_window"], "gap_bp": p["chip_gap"], "gaps": len(gaps)}
    return {"summary": summary, "gaps": gaps}


def read_chip(chip_path, release_dir, out_path, max_snps=CHIP_MAX):
    """Read a chip's SNP list (any snpscore input layout: manifest, PLINK, VCF, table) through the release's chromosome
    aliases and write chrom, pos, id to out_path (parquet). Returns the validation counts. A list with more than
    `max_snps` rows raises TooMany, an InputError (reading stops there)."""
    path, release, out = Path(chip_path).resolve(), Path(release_dir).resolve(), Path(out_path).resolve()
    manifest = json.loads((release / "manifest.json").read_text())
    con = connect([path.parent, release], out.parent)
    try:
        alias = release / "alias.parquet"
        report = read_snps(con, path, manifest.get("chrom_sizes") or [], alias if alias.exists() else None, max_snps)
        ident = "id" if "id" in [r[0] for r in con.execute("DESCRIBE snps").fetchall()] else "NULL::VARCHAR AS id"
        con.execute(f"COPY (SELECT chrom, pos, {ident} FROM snps ORDER BY idx) TO {lit(out)} (FORMAT parquet)")
    finally:
        con.close()
    return report


def chip_matrix(chips, pool=None, chrom_sizes=None, window_bp=10_000, gap_bp=1_000_000):
    """Several chips side by side (ROADMAP I11). chips: [(label, parquet with chrom, pos)]; pool: the release's
    pool/pool.parquet, which gives the functional content of the markers that are public sites. Returns {rows: [{label,
    markers, per_mb, median_kb, gaps, public, tier12, coding, maf05}], overlap: [(label, [markers within window_bp of a
    marker of each chip, in chips' order])]}. Gaps count stretches over gap_bp, chromosome ends included."""
    files = [Path(p).resolve() for _, p in chips] + ([Path(pool).resolve()] if pool else [])
    con = connect(sorted({f.parent for f in files}))
    sizes = {str(k): int(v) for k, v in (chrom_sizes or {}).items()}
    genome_mb = sum(sizes.values()) / 1e6 if sizes else None
    ends = "".join(f" WHEN {lit(c)} THEN {n}" for c, n in sizes.items())
    for i, (_, path) in enumerate(chips):
        con.execute(f"CREATE TEMP TABLE c{i} AS SELECT DISTINCT chrom::VARCHAR AS chrom, pos::BIGINT AS pos "
                    f"FROM read_parquet({lit(Path(path).resolve())})")
    rows = []
    for i, (label, _) in enumerate(chips):
        n, median = con.execute(f"""SELECT count(*), median(d) FROM (SELECT pos - lag(pos) OVER (PARTITION BY chrom ORDER BY pos)
                                     AS d FROM c{i})""").fetchall()[0]
        gaps = con.execute(f"""SELECT count(*) FROM (SELECT coalesce(lead(pos) OVER w, {f'CASE chrom{ends} END' if sizes else 'NULL'})
                                   - pos AS g FROM (SELECT chrom, pos FROM c{i}{''.join(f" UNION ALL SELECT {lit(c)}, 0" for c in sizes)})
                                   WINDOW w AS (PARTITION BY chrom ORDER BY pos)) WHERE g > {int(gap_bp)}""").fetchall()[0][0]
        row = {"label": label, "markers": n, "per_mb": round(n / genome_mb, 2) if genome_mb else None,
               "median_kb": None if median is None else round(median / 1000, 1), "gaps": gaps}
        if pool:
            cols = {r[0] for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet({lit(Path(pool).resolve())})").fetchall()}
            tier = "tier__all" if "tier__all" in cols else "tier"
            public, t12, coding, maf05 = con.execute(f"""
                SELECT count(*), count(*) FILTER (WHERE p.{tier} <= 2),
                       count(*) FILTER (WHERE {'p.region_class' if 'region_class' in cols else 'NULL'} = 'CDS'),
                       count(*) FILTER (WHERE {'p.public_af_maf' if 'public_af_maf' in cols else 'NULL'} >= 0.05)
                FROM c{i} c JOIN read_parquet({lit(Path(pool).resolve())}) p USING (chrom, pos)""").fetchall()[0]
            row.update(public=public, tier12=t12, coding=coding, maf05=maf05)
        rows.append(row)
    overlap = []
    for i, (label, _) in enumerate(chips):
        near = []
        for j in range(len(chips)):
            near.append(rows[i]["markers"] if i == j else con.execute(f"""
                SELECT count(*) FROM (SELECT a.pos, least(a.pos - u.pos, d.pos - a.pos) AS dist FROM c{i} a
                    ASOF LEFT JOIN c{j} u ON a.chrom = u.chrom AND a.pos >= u.pos
                    ASOF LEFT JOIN c{j} d ON a.chrom = d.chrom AND a.pos <= d.pos) WHERE dist <= {int(window_bp)}""").fetchall()[0][0])
        overlap.append((label, near))
    con.close()
    return {"rows": rows, "overlap": overlap}


def upgrade(chip, candidates, qc=None, n_target=None, min_call_rate=0.95, min_hwe_p=1e-6, min_spacing_bp=20_000,
            gap_bp=1_000_000, chrom_sizes=None, read=()):
    """Upgrade a chip (ROADMAP I11): keep its markers that pass the QC, drop the failing ones, then add candidates up to
    n_target (default: the chip's size), those inside the chip's gaps first, then by tier and tier score, each at
    least min_spacing_bp from every marker kept or added. chip: parquet with chrom, pos, id; candidates: parquet of
    annotated SNPs (chrom, pos, id, tier, tier_score); qc: parquet with chrom, pos, call_rate, hwe_p (the user's
    population, lib.population), or None (every marker kept). Returns [{chrom, pos, id, action (keep, drop, add),
    reason, tier}] in genome order, the dropped markers included."""
    files = [Path(x).resolve() for x in (chip, candidates, qc) if x]
    con = connect(sorted({f.parent for f in files} | {Path(r).resolve() for r in read}))
    q = (f"LEFT JOIN read_parquet({lit(Path(qc).resolve())}) q ON q.chrom = c.chrom::VARCHAR AND q.pos = c.pos::BIGINT"
         if qc else "")
    cr, hw = ("q.call_rate", "q.hwe_p") if qc else ("NULL::DOUBLE", "NULL::DOUBLE")
    markers = con.execute(f"""SELECT DISTINCT ON (c.chrom, c.pos) c.chrom::VARCHAR, c.pos::BIGINT, c.id::VARCHAR, {cr}, {hw}
                              FROM read_parquet({lit(Path(chip).resolve())}) c {q} ORDER BY c.chrom, c.pos""").fetchall()
    out, kept = [], {}
    for chrom, pos, ident, call_rate, hwe in markers:
        if call_rate is not None and call_rate < min_call_rate:
            out.append({"chrom": chrom, "pos": pos, "id": ident, "action": "drop", "tier": None,
                        "reason": f"call rate {call_rate:.2f} < {min_call_rate:g}"})
        elif hwe is not None and hwe < min_hwe_p:
            out.append({"chrom": chrom, "pos": pos, "id": ident, "action": "drop", "tier": None,
                        "reason": f"HWE p {hwe:.2g} < {min_hwe_p:g}"})
        else:
            out.append({"chrom": chrom, "pos": pos, "id": ident, "action": "keep", "tier": None,
                        "reason": "passes" if call_rate is not None else "no QC data: kept"})
            kept.setdefault(chrom, []).append(pos)
    target = int(n_target or len(markers))
    cand = con.execute(f"""SELECT chrom::VARCHAR, pos::BIGINT, id::VARCHAR, tier, tier_score
                           FROM read_parquet({lit(Path(candidates).resolve())})""").fetchall()
    con.close()
    taken = {c: sorted(ps) for c, ps in kept.items()}
    sizes = {str(k): int(v) for k, v in (chrom_sizes or {}).items()}

    def in_gap(chrom, pos):  # between two kept markers (or a chromosome end) more than gap_bp apart
        here = taken.get(chrom, [])
        i = bisect.bisect_left(here, pos)
        lo, hi = (here[i - 1] if i else 0), (here[i] if i < len(here) else sizes.get(chrom))
        return (hi - lo if hi is not None else pos - lo) > gap_bp
    cand = sorted(((c, p, i, t, s, in_gap(c, p)) for c, p, i, t, s in cand),
                  key=lambda r: (not r[5], 9 if r[3] is None else r[3], -(r[4] or 0), r[0], r[1]))
    n = sum(len(ps) for ps in taken.values())
    for chrom, pos, ident, tier, _, in_gap in cand:
        if n >= target:
            break
        here = taken.setdefault(chrom, [])
        i = bisect.bisect_left(here, pos)
        if (i < len(here) and here[i] - pos < min_spacing_bp) or (i and pos - here[i - 1] < min_spacing_bp):
            continue
        here.insert(i, pos)
        n += 1
        out.append({"chrom": chrom, "pos": pos, "id": ident, "action": "add", "tier": tier,
                    "reason": "fills a chip gap" if in_gap else f"tier {tier}" if tier else "candidate"})
    return sorted(out, key=lambda r: (int(r["chrom"]) if str(r["chrom"]).isdigit() else 99, str(r["chrom"]), r["pos"]))
