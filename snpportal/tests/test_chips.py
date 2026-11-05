"""Several chips compared, and a chip upgraded (snpportal.lib.panel.chip_matrix and upgrade, ROADMAP I11), on small
SYNTHETIC chips."""
import duckdb

from snpportal.lib import panel


def parquet(path, sql):
    duckdb.execute(f"COPY ({sql}) TO '{path}' (FORMAT parquet)")
    return path


def test_chip_matrix(tmp_path):
    a = parquet(tmp_path / "a.parquet", "SELECT '1' AS chrom, unnest([100000, 200000, 300000, 5000000]) AS pos, NULL::VARCHAR AS id")
    b = parquet(tmp_path / "b.parquet", "SELECT '1' AS chrom, unnest([100005, 250000]) AS pos, NULL::VARCHAR AS id")
    pool = parquet(tmp_path / "pool.parquet", "SELECT '1' AS chrom, unnest([100000, 300000]) AS pos, unnest([1, 4]) AS tier__all, "
                                              "unnest(['CDS', NULL]) AS region_class, unnest([0.2, 0.01]) AS public_af_maf")
    m = panel.chip_matrix([("A", a), ("B", b)], pool=pool, chrom_sizes={"1": 10_000_000}, window_bp=10, gap_bp=1_000_000)
    first = m["rows"][0]
    assert (first["markers"], first["per_mb"], first["median_kb"]) == (4, 0.4, 100.0)
    assert first["gaps"] == 2  # 300 kb to 5 Mb, and 5 Mb to the chromosome's end
    assert (first["public"], first["tier12"], first["coding"], first["maf05"]) == (2, 1, 1, 1)
    assert m["overlap"] == [("A", [4, 1]), ("B", [1, 2])]  # 100,000 and 100,005 are within 10 bp


def test_upgrade(tmp_path):
    chip = parquet(tmp_path / "chip.parquet", "SELECT '1' AS chrom, unnest([1000000, 1100000, 1200000]) AS pos, "
                                              "unnest(['m1', 'm2', 'm3']) AS id")
    qc = parquet(tmp_path / "qc.parquet", "SELECT '1' AS chrom, unnest([1000000, 1100000]) AS pos, unnest([0.99, 0.70]) AS call_rate, "
                                          "unnest([0.5, 0.5]) AS hwe_p")
    cand = parquet(tmp_path / "cand.parquet", "SELECT '1' AS chrom, unnest([1105000, 1150000, 4000000, 2600000]) AS pos, "
                                              "unnest(['near', 'b', 'gap', 'c']) AS id, unnest([1, 2, 3, 1]) AS tier, "
                                              "unnest([9, 4, 2, 8]) AS tier_score")
    rows = panel.upgrade(chip, cand, qc=qc, n_target=4, min_call_rate=0.95, min_hwe_p=1e-6, min_spacing_bp=20000,
                         gap_bp=1_000_000, chrom_sizes={"1": 5_000_000})
    actions = {r["id"]: (r["action"], r["reason"]) for r in rows}
    assert actions["m1"] == ("keep", "passes") and actions["m3"] == ("keep", "no QC data: kept")
    assert actions["m2"] == ("drop", "call rate 0.70 < 0.95")
    # 2 kept, then 2 added: first the candidates in the gap from 1.2 Mb to the chromosome's end, the best tier first
    # ('c' at 2.6 Mb, then 'gap' at 4 Mb, 1.4 Mb from it); 'near' and 'b' between the kept markers wait
    assert [(r["id"], r["reason"]) for r in rows if r["action"] == "add"] == [("c", "fills a chip gap"), ("gap", "fills a chip gap")]
