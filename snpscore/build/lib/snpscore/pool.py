"""Public background pool (P3.1): every public 12-fish site annotated against a release, with the tier for every trait
preset, in <release>/pool/pool.parquet, and the background shares the dashboard compares uploads with in
<release>/pool/background.json. annotate never reads the pool (it only reads files the manifest names)."""
from __future__ import annotations

import datetime
import json
import tempfile
import time
import uuid
from pathlib import Path

from .annotate import annotate, connect
from .assay import breakdown
from .formats import lit, q
from .score import load_weights, scored

FLAGS = ("chromatin", "regbuild", "gerp", "blacklist", "lore", "public_af", "strand_ambiguous")  # boolean columns
MAF_EDGES = tuple(i / 20 for i in range(1, 10))  # MAF histogram: [0, 0.05), [0.05, 0.1), ..., [0.45, 0.5]


def maf_bin_sql(maf):
    """SQL for the MAF histogram bin (0-9; NULL when `maf`, an SQL expression, is NULL): the number of MAF_EDGES at or
    below it, so bin i holds exactly the rows that the filters 'MAF >= <its lower edge>' and 'MAF < <its upper edge>'
    keep, with the edges written as in those filters (0.15, not 3 * 0.05). The last bin includes 0.5."""
    return "(" + " + ".join(f"({maf} >= {e:g})::INTEGER" for e in MAF_EDGES) + ")"


def build_pool(release_dir, background, assay=False, threads=4, memory_limit="4GB", progress=None):
    """Annotate the public sites in `background` (a VCF) against the release, without sequence checks unless `assay`,
    and write pool/pool.parquet (annotate columns, tier columns for the 'all' preset, then tier__<preset> and
    tier_score__<preset> for every preset) and pool/background.json. Returns the pool folder."""
    release = Path(release_dir).resolve()
    out = release / "pool"
    out.mkdir(exist_ok=True)
    t0, step = time.time(), progress or (lambda stage: None)
    # The full annotate output is temporary: it goes to a folder outside the release, removed when done
    with tempfile.TemporaryDirectory(prefix="snpscore-pool-") as work:
        work = Path(work).resolve()
        annotate(background, release, work / "annotated.parquet", "all", sequence=assay, progress=step, threads=threads,
                 memory_limit=memory_limit)
        step("pool")
        validation = json.loads((work / "annotated.validation.json").read_text())
        weights, manifest = load_weights(), json.loads((release / "manifest.json").read_text())
        synthetic = [l["name"] for l in manifest["layers"] if l.get("synthetic")]
        con = connect([work], out, threads, memory_limit)
        con.execute(f"CREATE TABLE a AS SELECT * FROM read_parquet({lit(work / 'annotated.parquet')}, file_row_number=true)")
        columns = [r[0] for r in con.execute("DESCRIBE a").fetchall()]
        presets = list(weights["presets"]) if weights else []
        for i, p in enumerate(presets):  # one narrow table per preset, joined back on the row number
            con.execute(f"""CREATE TABLE t{i} AS SELECT file_row_number, tier AS {q('tier__' + p)},
                            tier_score AS {q('tier_score__' + p)} FROM ({scored('a', weights, columns, p, synthetic)})""")
        joins = "".join(f" JOIN t{i} USING (file_row_number)" for i in range(len(presets)))
        tmp = out / f".pool-{uuid.uuid4().hex}.parquet"
        try:
            con.execute(f"""COPY (SELECT * EXCLUDE (file_row_number) FROM a{joins} ORDER BY file_row_number)
                            TO {lit(tmp)} (FORMAT parquet)""")
            tmp.replace(out / "pool.parquet")
        finally:  # a failed COPY leaves no partial file in the release
            tmp.unlink(missing_ok=True)
        summary = background_summary(con, f"read_parquet({lit(out / 'pool.parquet')})", weights)
        con.close()
    summary.update(release=manifest["version"], created=datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                   source=Path(background).name, rows_read=validation["rows_read"], rejected=validation["rejected"],
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
