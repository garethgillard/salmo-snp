"""Benchmark a release: how often positive SNPs hit each layer, region class and tier, against matched controls.
Controls are drawn from a background SNP set, matched on distance to the nearest gene (bins below)."""
from __future__ import annotations

import tempfile
from pathlib import Path

from .annotate import annotate, connect
from .formats import lit, q

DISTANCE_BIN = """CASE WHEN gene_distance IS NULL THEN '>1Mb' WHEN gene_distance = 0 THEN 'in gene'
                       WHEN gene_distance <= 5000 THEN '<=5kb' WHEN gene_distance <= 20000 THEN '<=20kb'
                       WHEN gene_distance <= 100000 THEN '<=100kb' ELSE '<=1Mb' END"""


def benchmark(positives, background, release_dir, out_path=None, controls=10, trait="all", seed=1):
    """Return (and optionally write as TSV) rows of feature, positives, controls, share_pos, share_ctrl, enrichment."""
    with tempfile.TemporaryDirectory() as tmp:
        annotate(positives, release_dir, f"{tmp}/pos.parquet", trait)
        annotate(background, release_dir, f"{tmp}/bg.parquet", trait)
        con = connect([tmp], tmp)
        tmp = Path(tmp).resolve()
        con.execute(f"CREATE TABLE pos AS SELECT *, {DISTANCE_BIN} AS bin FROM read_parquet({lit(tmp / 'pos.parquet')})")
        con.execute(f"""CREATE TABLE ctrl AS SELECT * FROM (
            SELECT b.*, row_number() OVER (PARTITION BY b.bin ORDER BY hash(b.chrom, b.pos, {seed})) AS k, n.need
            FROM (SELECT *, {DISTANCE_BIN} AS bin FROM read_parquet({lit(tmp / 'bg.parquet')})) b
            JOIN (SELECT bin, count(*) * {controls} AS need FROM pos GROUP BY bin) n USING (bin)
            ANTI JOIN pos p ON b.chrom = p.chrom AND b.pos = p.pos
        ) WHERE k <= need""")

    pos_cols = dict(con.execute("SELECT column_name, column_type FROM (DESCRIBE pos)").fetchall())
    ctrl_cols = dict(con.execute("SELECT column_name, column_type FROM (DESCRIBE ctrl)").fetchall())
    features = [q(c) for c, t in pos_cols.items() if t == "BOOLEAN" and ctrl_cols.get(c) == "BOOLEAN"]
    if "region_class" in pos_cols:
        classes = con.execute("""SELECT DISTINCT region_class FROM (SELECT region_class FROM pos UNION ALL
                                 SELECT region_class FROM ctrl) WHERE region_class IS NOT NULL ORDER BY 1""").fetchall()
        features += [f"region_class = {lit(c)}" for c, in classes]
    if "tier" in pos_cols:
        features += [f"tier <= {t}" for t in (1, 2, 3)]
    share = "avg(coalesce({}, false)::INT)"
    rows = con.execute(" UNION ALL ".join(
        f"""SELECT {lit(f.replace('"', '').replace("'", ''))} AS feature,
                   (SELECT count(*) FROM pos) AS positives, (SELECT count(*) FROM ctrl) AS controls,
                   (SELECT {share.format(f)} FROM pos) AS share_pos, (SELECT {share.format(f)} FROM ctrl) AS share_ctrl"""
        for f in features)).fetchall()
    rows = [r + (r[3] / r[4] if r[4] else None,) for r in rows]
    if out_path:
        header = "feature\tpositives\tcontrols\tshare_pos\tshare_ctrl\tenrichment\n"
        Path(out_path).write_text(header + "".join("\t".join("" if v is None else str(round(v, 4) if isinstance(v, float) else v)
                                                             for v in r) + "\n" for r in rows))
    return rows
