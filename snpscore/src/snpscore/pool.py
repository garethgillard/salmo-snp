"""Public background pool (P3.1): public sites annotated against a release, with the tier for every trait preset, in
<release>/pool/pool.parquet, and the background shares the dashboard compares uploads with in
<release>/pool/background.json. annotate never reads the pool (it only reads files the manifest names).

The sites come from the release itself (public_af.parquet; SITES picks which), so any install can build it (ROADMAP
I3), or from a VCF. The pool is a cache of the current weights: background.json records the weights' sha256 and the
snpscore version, and stale() says when it needs building again."""
from __future__ import annotations

import datetime
import hashlib
import json
import tempfile
import time
import uuid
from pathlib import Path

from .annotate import annotate, connect, genome_location
from .assay import breakdown
from .formats import lit, q
from .score import load_weights, rules_file, scored

FLAGS = ("chromatin", "regbuild", "gerp", "pike", "blacklist", "lore", "public_af", "strand_ambiguous")  # boolean columns
MAF_EDGES = tuple(i / 20 for i in range(1, 10))  # MAF histogram: [0, 0.05), [0.05, 0.1), ..., [0.45, 0.5]
# The release's public sites in the pool (DECISIONS #15; G, 2026-11-21): 'panel', the common ones (public MAF at least the
# panel designer's design.min_maf in weights.yaml, which picks its candidates from the pool), all of them up to MAX_SITES,
# else an even sample, the same sites every time. Salmon: the 3.4M of the 504-fish panel's 7.6M sites, on every
# chromosome; rainbow trout: a sample of the 462 fish's 13.5M. Or 'aquafaang12', the sites of the 12 AQUA-FAANG fish's
# VCF (salmon only: 1.6M, but 70 on chromosome 10 and none past 105 Mb on chromosome 1; the pool until 2026-11-21).
SITES = "panel"
MAX_SITES = 4_000_000
CHUNK = 1_500_000  # sites per annotate run (3.4M salmon sites at once need more than 4 GB with 4 threads)


def stamp():
    """What a pool depends on besides the release: the sha256 of the rules in use (score.rules_file), the snpscore
    version and the site rule."""
    from importlib.metadata import PackageNotFoundError, version
    try:
        v = version("snpscore")
    except PackageNotFoundError:
        v = "unknown"
    return {"weights_sha256": hashlib.sha256(rules_file().read_bytes()).hexdigest(), "snpscore_version": v,
            "sites_rule": f"{SITES}: public MAF >= design.min_maf, at most {MAX_SITES}"}  # a new rule: every pool stale


def stale(release_dir):
    """True when the release has no pool, or one built for another release version, with other weights, another
    snpscore version or another site rule."""
    release = Path(release_dir)
    try:
        made = json.loads((release / "pool" / "background.json").read_text())
        version = json.loads((release / "manifest.json").read_text())["version"]
    except (OSError, ValueError, KeyError):
        return True
    return (not (release / "pool" / "pool.parquet").exists() or made.get("release") != version
            or any(made.get(k) != v for k, v in stamp().items()))


def release_sites(release, work, sites=SITES):
    """The release's public sites (public_af.parquet) as chrom, pos, ref, alt tables in genome order, for annotate: one
    TSV per run of whole chromosomes with at most CHUNK sites (a larger chromosome is a part of its own)."""
    con = connect([release], work)
    table = f"read_parquet({lit(release / 'public_af.parquet')})"
    columns = [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM {table}").fetchall()]
    keep = "true"
    if sites == "aquafaang12" and "aquafaang12_af" in columns:
        keep = "aquafaang12_af IS NOT NULL"
    elif "maf" in columns:
        keep = f"maf >= {float(((load_weights() or {}).get('design') or {}).get('min_maf', 0))}"
    rows = con.execute(f"SELECT count(*) FROM {table} WHERE {keep}").fetchall()[0][0]
    if rows > MAX_SITES:
        keep += f" AND hash(chrom, \"end\") % {-(-rows // MAX_SITES)} = 0"
    parts = []  # [[chromosomes], sites]
    for chrom, n in con.execute(f"""SELECT chrom, count(*) FROM {table} WHERE {keep} GROUP BY chrom
                                    ORDER BY TRY_CAST(chrom AS INTEGER), chrom""").fetchall():
        if not parts or parts[-1][1] + n > CHUNK:
            parts.append([[], 0])
        parts[-1][0].append(chrom)
        parts[-1][1] += n
    targets = []
    for i, (chroms, _) in enumerate(parts or [[[], 0]]):
        targets.append(work / f"sites_{i}.tsv")
        where = f"chrom IN ({', '.join(lit(c) for c in chroms)})" if chroms else "false"
        con.execute(f"""COPY (SELECT chrom, "end" AS pos, ref, alt FROM {table} WHERE {keep} AND {where}
                        ORDER BY TRY_CAST(chrom AS INTEGER), chrom, pos, ref, alt)
                        TO {lit(targets[-1])} (HEADER, DELIMITER '\t')""")
    con.close()
    return targets


def maf_bin_sql(maf):
    """SQL for the MAF histogram bin (0-9; NULL when `maf`, an SQL expression, is NULL): the number of MAF_EDGES at or
    below it, so bin i holds exactly the rows that the filters 'MAF >= <its lower edge>' and 'MAF < <its upper edge>'
    keep, with the edges written as in those filters (0.15, not 3 * 0.05). The last bin includes 0.5."""
    return "(" + " + ".join(f"({maf} >= {e:g})::INTEGER" for e in MAF_EDGES) + ")"


def local_genome(release_dir):
    """Whether the release's genome is on this computer (annotate.genome_location), so the sequence step can read all
    of it: a remote genome gives a sample of reference checks and no coding consequences."""
    location = genome_location(json.loads((Path(release_dir) / "manifest.json").read_text()))
    return bool(location) and "://" not in location


def build_pool(release_dir, background=None, assay=None, threads=4, memory_limit="4GB", progress=None, sites=SITES):
    """Annotate the public sites in `background` (a VCF; None: the release's own public_af sites, `sites`) against
    the release and write pool/pool.parquet (annotate columns, tier columns for the 'all' preset, then tier__<preset>
    and tier_score__<preset> for every preset) and pool/background.json. Returns the pool folder. `assay`: the sequence
    step (reference check, assay QC, coding consequences): True, False, or None for whenever the genome is on this
    computer (local_genome), so that a pool has coding consequences and the synonymous weight applies to it as to
    uploads (G, 2026-11-26)."""
    release = Path(release_dir).resolve()
    if assay is None:
        assay = local_genome(release)
    out = release / "pool"
    out.mkdir(exist_ok=True)
    t0, step = time.time(), progress or (lambda stage: None)
    # The full annotate output is temporary: it goes to a folder outside the release, removed when done
    with tempfile.TemporaryDirectory(prefix="snpscore-pool-") as work:
        work = Path(work).resolve()
        source = Path(background).name if background else f"public_af.parquet ({sites})"
        parts = [background] if background else release_sites(release, work, sites)
        weights, manifest = load_weights(), json.loads((release / "manifest.json").read_text())
        synthetic = [l["name"] for l in manifest["layers"] if l.get("synthetic")]
        presets = list(weights["presets"]) if weights else []
        rows_read, rejected, pieces = 0, {}, []
        for k, part in enumerate(parts):  # one annotate run per part: memory grows with the sites annotated at once
            annotated = work / f"annotated_{k}.parquet"
            annotate(part, release, annotated, "all", sequence=assay, progress=step, threads=threads,
                     memory_limit=memory_limit)
            step("pool")
            validation = json.loads((work / f"annotated_{k}.validation.json").read_text())
            rows_read += validation["rows_read"]
            for reason, n in validation["rejected"].items():
                rejected[reason] = rejected.get(reason, 0) + n
            con = connect([work], out, threads, memory_limit)
            con.execute(f"CREATE TABLE a AS SELECT * FROM read_parquet({lit(annotated)}, file_row_number=true)")
            columns = [r[0] for r in con.execute("DESCRIBE a").fetchall()]
            for i, p in enumerate(presets):  # one narrow table per preset, joined back on the row number
                con.execute(f"""CREATE TABLE t{i} AS SELECT file_row_number, tier AS {q('tier__' + p)},
                                tier_score AS {q('tier_score__' + p)} FROM ({scored('a', weights, columns, p, synthetic)})""")
            joins = "".join(f" JOIN t{i} USING (file_row_number)" for i in range(len(presets)))
            pieces.append(work / f"pool_{k}.parquet")
            con.execute(f"""COPY (SELECT * EXCLUDE (file_row_number) FROM a{joins} ORDER BY file_row_number)
                            TO {lit(pieces[-1])} (FORMAT parquet)""")
            con.close()
            annotated.unlink()
        con = connect([work], out, threads, memory_limit)
        tmp = out / f".pool-{uuid.uuid4().hex}.parquet"
        try:  # DuckDB reads a file list in its order, so the parts stay in genome order
            con.execute(f"""COPY (SELECT * FROM read_parquet([{', '.join(lit(p) for p in pieces)}]))
                            TO {lit(tmp)} (FORMAT parquet)""")
            tmp.replace(out / "pool.parquet")
        finally:  # a failed COPY leaves no partial file in the release
            tmp.unlink(missing_ok=True)
        summary = background_summary(con, f"read_parquet({lit(out / 'pool.parquet')})", weights)
        con.close()
    created = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    summary.update(release=manifest["version"], created=created, **stamp(),
                   source=source, rows_read=rows_read, rejected=rejected,
                   assay_checked=bool(assay), seconds=round(time.time() - t0, 1))
    (out / "background.json").write_text(json.dumps(summary, indent=2))
    return out


def shares(rows):
    """{key: {'n': count, 'share': count / total}} from (key, count) rows; the shares sum to 1."""
    total = sum(n for _, n in rows) or 1
    return {str(k): {"n": n, "share": round(n / total, 6)} for k, n in rows}


def background_summary(con, table, weights):
    """Counts and shares of the pool for the dashboard. Each of tiers[preset], region_class, maf_histogram and
    assay_status is one category whose shares sum to 1; active_by_condition, flags and assay_reasons (warn and fail
    reasons by name, a site counted once per reason) are independent shares (the share of sites with that property)."""
    columns = [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM {table}").fetchall()]
    n = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]

    def grouped(expr):
        return con.execute(f"SELECT {expr} AS k, count(*) FROM {table} GROUP BY 1 ORDER BY 1 NULLS LAST").fetchall()

    presets = list(weights["presets"]) if weights else []
    summary = {"n_sites": n, "tiers": {p: shares(grouped(q("tier__" + p))) for p in presets}}
    if "region_class" in columns:
        summary["region_class"] = shares(grouped("coalesce(region_class, 'intergenic')"))
    maf = next((c for c in ("public_af_maf", "maf") if c in columns), None)
    if maf:  # bins as the portal's MAF filters cut them: maf_bin_sql of least(af, 1 - af), keyed '0.15-0.20'
        x = f"TRY_CAST({q(maf)} AS DOUBLE)"
        b = maf_bin_sql(f"least({x}, 1 - {x})")
        summary["maf_histogram"] = shares(grouped(
            f"CASE WHEN {x} IS NULL THEN 'unknown' ELSE printf('%.2f-%.2f', {b} / 20, ({b} + 1) / 20) END"))
    conditions = [c for c in columns if c.startswith("chromatin_") and c not in ("chromatin_id", "chromatin_summary")]
    if conditions and n and weights:
        states = ", ".join(lit(s) for s in weights["active_states"])
        active = con.execute(f"SELECT {', '.join(f'avg(coalesce({q(c)} IN ({states}), false)::INT)' for c in conditions)} "
                             f"FROM {table}").fetchone()
        summary["active_by_condition"] = {c[len("chromatin_"):]: round(v, 6) for c, v in zip(conditions, active)}
    flags = [c for c in FLAGS if c in columns]
    if flags and n:
        values = con.execute(f"SELECT {', '.join(f'avg(coalesce({q(c)}, false)::INT)' for c in flags)} FROM {table}").fetchone()
        summary["flags"] = {c: round(v, 6) for c, v in zip(flags, values)}
    if "assay_status" in columns:
        summary["assay_status"] = shares(grouped("assay_status"))
        reasons = breakdown(con, f"(SELECT assay_reasons FROM {table} WHERE assay_status IN ('warn', 'fail'))")
        summary["assay_reasons"] = {k: {"n": v, "share": round(v / n, 6)} for k, v in reasons.items()}  # of all sites
    return summary
