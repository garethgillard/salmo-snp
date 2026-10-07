"""Benchmark a release: how often positive SNPs hit each layer, evidence term, region class, coding consequence and
tier, against matched controls, with 95% intervals.

Positives: a SNP file (the known-loci catalogue by default), or the release's nf-RASQUAL molQTL lead SNPs given as
'molqtl[:ca|e][:Tissue]' (ca = caQTL, e = eQTL; leads with BF below the layer's max_bf, which is all the layer holds).
Controls: `controls` per positive from a public background (the release's pool/pool.parquet, or a VCF annotated here),
matched on distance to the nearest gene (DISTANCE_BIN) and public MAF bin (504-fish panel, bins of 0.05 as in the
pool's histogram); positives without a public MAF are matched on distance only. Tiers and evidence terms are recomputed
for the trait from the release's weights.yaml, for positives and controls alike. Coding consequence rows need
consequence columns in the background (a pool built with --assay); SNP-file positives are then annotated with the genome.
Intervals: Wilson for shares; Katz log for enrichment (share_pos / share_ctrl), with 0.5 added to each count when
one is 0. They treat the controls as a simple random sample (they are stratified), so they are approximate."""
from __future__ import annotations

import datetime
import json
import math
import tempfile
from pathlib import Path

from .annotate import annotate, connect
from .formats import InputError, lit, q
from .pool import maf_bin_sql
from .score import load_weights, scored

DISTANCE_BIN = """CASE WHEN gene_distance IS NULL THEN '>1Mb' WHEN gene_distance = 0 THEN 'in gene'
                       WHEN gene_distance <= 5000 THEN '<=5kb' WHEN gene_distance <= 20000 THEN '<=20kb'
                       WHEN gene_distance <= 100000 THEN '<=100kb' ELSE '<=1Mb' END"""
KINDS = {"ca": "caQTL", "e": "eQTL"}
Z = 1.959964  # 95%
COLUMNS = ["feature", "positives", "controls", "share_pos", "share_ctrl", "enrichment", "hits_pos", "hits_ctrl",
           "share_pos_low", "share_pos_high", "share_ctrl_low", "share_ctrl_high", "enrichment_low", "enrichment_high"]


def wilson(k, n):
    """95% Wilson interval of the share k / n."""
    if not n:
        return None, None
    p, d = k / n, 1 + Z * Z / n
    mid, half = (p + Z * Z / (2 * n)) / d, Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / d
    return max(0.0, mid - half), min(1.0, mid + half)


def ratio_interval(a, n1, c, n2):
    """95% interval of (a / n1) / (c / n2), Katz log method; 0.5 is added to every count when a or c is 0."""
    if not n1 or not n2:
        return None, None
    if a == 0 or c == 0:
        a, c, n1, n2 = a + 0.5, c + 0.5, n1 + 1, n2 + 1
    ratio, se = (a / n1) / (c / n2), math.sqrt(max(1 / a - 1 / n1 + 1 / c - 1 / n2, 0))
    return ratio * math.exp(-Z * se), ratio * math.exp(Z * se)


def molqtl_spec(spec):
    """(kind, tissue) of 'molqtl[:ca|e][:Tissue]', None for either when not given; None when `spec` is a file."""
    parts = str(spec).split(":")
    if parts[0] != "molqtl" or Path(str(spec)).exists():
        return None
    kind = parts[1] if len(parts) > 1 and parts[1] in KINDS else None
    rest = parts[2 if kind else 1:]
    if len(rest) > 1 or (rest and not rest[0].isalpha()):
        raise InputError(f"Positives '{spec}': use molqtl, molqtl:ca, molqtl:e, molqtl:ca:<Tissue> or molqtl:<Tissue>")
    return kind, rest[0] if rest else None


def set_name(kind, tissue):
    return ":".join(["molqtl"] + [x for x in (kind, tissue) if x])


def benchmark(positives, background, release_dir, out_path=None, controls=10, trait="all", seed=1):
    """Rows (feature, positives, controls, share_pos, share_ctrl, enrichment, hits_pos, hits_ctrl, share_pos_low,
    share_pos_high, share_ctrl_low, share_ctrl_high, enrichment_low, enrichment_high) for one positive set; `out_path`
    also writes them as TSV (see benchmark_sets)."""
    return next(iter(benchmark_sets([positives], background, release_dir, out_path, controls, trait, seed).values()))[1]


def benchmark_sets(specs, background, release_dir, out_path=None, controls=10, trait="all", seed=1, by_tissue=False):
    """{set: (trait, rows)} for each positive set in `specs` (SNP files, named by their stem, or molqtl specs). With
    by_tissue, a molqtl spec also runs each kind and kind:tissue under it. A one-tissue molQTL set is scored with that
    tissue's preset when `trait` is 'all' and weights.yaml has one (Liver -> liver). background: a VCF, an annotated
    parquet such as the pool, or None for <release>/pool/pool.parquet. `out_path` gets one TSV with '#' lines on how
    it was made, then set, trait and the row columns."""
    release = Path(release_dir).resolve()
    manifest = json.loads((release / "manifest.json").read_text())
    weights = load_weights(release)
    synthetic = [x["name"] for x in manifest["layers"] if x.get("synthetic")]
    layer = next((x for x in manifest["layers"] if x["name"] == "molqtl"), None)
    background = Path(background).resolve() if background else release / "pool" / "pool.parquet"
    if not background.exists():
        raise InputError("No background SNPs: run 'snpscore pool' for this release, or give a background VCF")
    results = {}
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp).resolve()
        if background.suffix != ".parquet":
            annotate(background, release, tmp / "bg.parquet", sequence=False)
        source = background if background.suffix == ".parquet" else tmp / "bg.parquet"
        con = connect([tmp, release, source.parent], tmp)
        con.execute(f"CREATE VIEW bg AS {binned(f'read_parquet({lit(source)}, file_row_number=true)', con)}")
        con.execute(f"CREATE TABLE keys AS SELECT file_row_number AS _row, chrom, pos, _dbin, _mbin, "
                    f"hash(chrom, pos, {int(seed)}) AS _h FROM bg")
        coded = any(is_consequence(r[0]) for r in con.execute("DESCRIBE bg").fetchall())  # e.g. a pool built with --assay
        for name, path, kind, tissue in expand(specs, by_tissue, con, layer):
            presets = (weights or {}).get("presets") or {}
            set_trait = tissue.lower() if tissue and trait == "all" and tissue.lower() in presets else trait
            if path:
                annotated = tmp / "pos.parquet"
                annotate(path, release, annotated, set_trait, sequence=coded)  # coding consequence needs the genome
                con.execute(f"CREATE OR REPLACE TABLE pos AS {binned(f'read_parquet({lit(annotated)})', con)}")
            else:
                con.execute(f"CREATE OR REPLACE TABLE pos AS SELECT * FROM bg WHERE {molqtl_filter(kind, tissue, layer)}")
            match(con, controls)
            rows = compare(con, weights, set_trait, synthetic, molqtl=not path)
            results[name] = (set_trait, rows)
        con.close()
    if out_path:
        write(out_path, results, manifest, source, controls, seed, layer)
    return results


def is_consequence(column):
    """A coding consequence column (consequence, coding_consequence, ...): compared value by value."""
    return column == "consequence" or column.endswith("_consequence")


def binned(table, con):
    """SELECT from `table` adding _dbin (distance to the nearest gene) and _mbin (public MAF bin 0-9, NULL if none)."""
    columns = {r[0] for r in con.execute(f"DESCRIBE SELECT * FROM {table}").fetchall()}
    maf = maf_bin_sql("public_af_maf") if "public_af_maf" in columns else "NULL::INTEGER"
    return f"SELECT *, {DISTANCE_BIN} AS _dbin, {maf} AS _mbin FROM {table}"


def expand(specs, by_tissue, con, layer):
    """(set name, file or None, kind, tissue) for each positive set, molQTL sets in the order kind, then kind:tissue."""
    pairs = []
    if layer:  # (kind, tissue) pairs present in the layer's features: '<Tissue> <kind> <feature> (BF ..., pi ...)'
        pairs = con.execute("""SELECT DISTINCT split_part(x, ' ', 2), split_part(x, ' ', 1) FROM
                               (SELECT unnest(string_split(molqtl_features, '; ')) AS x FROM bg WHERE molqtl)
                               ORDER BY 1, 2""").fetchall()
    out = {}
    for spec in specs:
        parsed = molqtl_spec(spec)
        if parsed is None:
            out[Path(spec).stem] = (str(spec), None, None)
            continue
        if not layer:
            raise InputError("This release has no molqtl layer")
        kind, tissue = parsed
        tissues = {t.lower(): t for _, t in pairs}
        if tissue and tissue.lower() not in tissues:
            raise InputError(f"No molQTL tissue '{tissue}'. Choose from: {', '.join(sorted(tissues.values()))}")
        tissue = tissues.get((tissue or "").lower())
        if kind and tissue and (kind, tissue) not in pairs:
            raise InputError(f"No {KINDS[kind]} lead SNPs in {tissue}")
        wanted = [(kind, tissue)]
        if by_tissue:
            wanted += [(k, None) for k in sorted({k for k, _ in pairs}) if kind is None and tissue is None]
            wanted += [(k, t) for k, t in pairs if kind in (None, k) and tissue in (None, t)]
        for k, t in wanted:
            out.setdefault(set_name(k, t), (None, k, t))
    return [(name, *rest) for name, rest in out.items()]


def molqtl_filter(kind, tissue, layer):
    """SQL condition on annotated SNPs: a molQTL lead (of `kind` in `tissue` when given) with BF below max_bf."""
    cond = ["molqtl"]
    if layer.get("max_bf") is not None:
        cond.append(f"molqtl_best_bf < {float(layer['max_bf'])!r}")
    test = [f"split_part(x, ' ', {i}) = {lit(v)}" for i, v in ((2, kind), (1, tissue)) if v]
    if test:  # one of its features is of that kind and tissue: '<Tissue> <kind> <feature> (BF ..., pi ...)'
        cond.append(f"len(list_filter(string_split(molqtl_features, '; '), x -> {' AND '.join(test)})) > 0")
    return " AND ".join(cond)


def match(con, controls):
    """Table ctrl: `controls` background SNPs per positive in the same distance and MAF bin (distance only for
    positives without a public MAF), never a positive's position, chosen by a seeded hash."""
    con.execute(f"CREATE OR REPLACE TABLE need AS SELECT _dbin, _mbin, count(*) * {int(controls)} AS need FROM pos GROUP BY ALL")

    def draw(on, partition, extra=""):
        return f"""SELECT _row FROM (
            SELECT k._row, n.need, row_number() OVER (PARTITION BY {partition} ORDER BY k._h, k._row) AS _k
            FROM keys k JOIN need n ON {on} ANTI JOIN pos p ON k.chrom = p.chrom AND k.pos = p.pos {extra}) WHERE _k <= need"""
    con.execute(f"""CREATE OR REPLACE TABLE chosen AS
        WITH known AS ({draw('k._dbin = n._dbin AND k._mbin = n._mbin', 'k._dbin, k._mbin')})
        SELECT _row FROM known UNION ALL
        {draw('k._dbin = n._dbin AND n._mbin IS NULL', 'k._dbin', 'ANTI JOIN known c ON k._row = c._row')}""")
    con.execute("CREATE OR REPLACE TABLE ctrl AS SELECT * FROM bg SEMI JOIN chosen c ON bg.file_row_number = c._row")


def compare(con, weights, trait, synthetic, molqtl=False):
    """Rows (see benchmark) comparing pos with ctrl, after recomputing both tables' tiers for `trait`."""
    for t in ("pos", "ctrl"):
        columns = [r[0] for r in con.execute(f"DESCRIBE {t}").fetchall()]
        body = scored(t, weights, columns, trait, synthetic) if weights else f"SELECT * FROM {t}"
        con.execute(f"CREATE OR REPLACE TABLE {t}_s AS {body}")
    pos = dict(con.execute("SELECT column_name, column_type FROM (DESCRIBE pos_s)").fetchall())
    ctrl = dict(con.execute("SELECT column_name, column_type FROM (DESCRIBE ctrl_s)").fetchall())
    both = [c for c in pos if c in ctrl]
    features = [(c, q(c)) for c in both if pos[c] == ctrl[c] == "BOOLEAN" and not (molqtl and c == "molqtl")]
    if "tier_terms" in both and weights:
        features += [(f"evidence = {term}", f"list_contains(list_transform(tier_terms, x -> x.term), {lit(term)})")
                     for term in weights["weights"] if not (molqtl and term == "molqtl")]
    categories = [c for c in both if c == "region_class" or is_consequence(c)]
    for c in categories:
        if pos[c] == ctrl[c] == "VARCHAR":
            values = con.execute(f"""SELECT DISTINCT v FROM (SELECT {q(c)} AS v FROM pos_s UNION ALL SELECT {q(c)} FROM ctrl_s)
                                     WHERE v IS NOT NULL ORDER BY 1""").fetchall()
            features += [(f"{c} = {v}", f"{q(c)} = {lit(v)}") for v, in values]
    if "tier" in both:
        features += [(f"tier <= {t}", f"tier <= {t}") for t in range(1, len((weights or {}).get("tiers") or [5, 3, 1]) + 1)]
    counts = ", ".join(f"count_if(coalesce({sql}, false))" for _, sql in features)
    hp = con.execute(f"SELECT count(*), {counts} FROM pos_s").fetchone()
    hc = con.execute(f"SELECT count(*), {counts} FROM ctrl_s").fetchone()
    n1, n2, rows = hp[0], hc[0], []
    for (label, _), a, c in zip(features, hp[1:], hc[1:]):
        if not a and not c:  # nothing to compare (e.g. active_elsewhere for the 'all' preset)
            continue
        sp, sc = (a / n1 if n1 else None), (c / n2 if n2 else None)
        rows.append((label, n1, n2, sp, sc, sp / sc if sp is not None and sc else None, a, c,
                     *wilson(a, n1), *wilson(c, n2), *ratio_interval(a, n1, c, n2)))
    return rows


def write(out_path, results, manifest, background, controls, seed, layer):
    """One TSV for all sets, with '#' lines saying how it was made."""
    sets = "; ".join(f"{name} n = {rows[0][1] if rows else 0}" for name, (_, rows) in results.items())
    head = [f"snpscore benchmark; release {manifest.get('version')}; {datetime.date.today().isoformat()}",
            f"positive sets: {sets}",
            f"controls: {controls} per positive from {background.name}, matched on distance to the nearest gene (in gene, "
            "<=5kb, <=20kb, <=100kb, <=1Mb, >1Mb) and public MAF bin (0.05; no public MAF: distance only); seed "
            f"{seed}; tiers and evidence recomputed for each set's trait (PROVISIONAL weights)",
            "95% intervals: Wilson (shares), Katz log (enrichment; 0.5 added to each count when one is 0); approximate"]
    if any(name.startswith("molqtl") for name in results):
        head.append(f"molqtl: nf-RASQUAL lead SNPs in 12 fish with BF < {layer.get('max_bf')} (PROVISIONAL; winner's curse); "
                    "caQTLs are called on the same AQUA-FAANG ATAC data as the chromatin layer, so chromatin enrichment "
                    "among them is partly expected; eQTLs are the fairer test")

    def cell(v):
        return "" if v is None else str(round(v, 4)) if isinstance(v, float) else str(v)
    lines = ["# " + h for h in head] + ["\t".join(["set", "trait"] + COLUMNS)]
    lines += ["\t".join([name, trait] + [cell(v) for v in r]) for name, (trait, rows) in results.items() for r in rows]
    Path(out_path).write_text("\n".join(lines) + "\n")
