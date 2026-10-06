from pathlib import Path

import duckdb
import pytest

from snpscore import annotate, build

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixture"


@pytest.fixture(scope="module")
def release(tmp_path_factory):
    return build(ROOT / "layers.yaml", FIXTURE, tmp_path_factory.mktemp("release") / "test")


def read(path):
    rel = duckdb.sql(f"SELECT * FROM read_parquet('{path}')")
    return [dict(zip(rel.columns, row)) for row in rel.fetchall()]


def test_known_positions(release, tmp_path):
    # Hand-picked positions in tests/fixture/snps.tsv (peak 21:32141080-32141371 in BED coordinates)
    rows = {r["id"]: r for r in read(annotate(FIXTURE / "snps.tsv", release, tmp_path / "out.parquet"))}
    assert rows["in_vgll3"]["gene_name"] == "vgll3" and rows["in_vgll3"]["gene_distance"] == 0
    assert rows["peak_first_base"]["chromatin"] and not rows["before_peak"]["chromatin"]
    assert rows["blacklisted"]["blacklist"] and rows["lore"]["lore"]


def test_vcf_input(release, tmp_path):
    rows = read(annotate(FIXTURE / "snps.vcf", release, tmp_path / "out.parquet"))
    in_peak = sum(r["chromatin"] for r in rows)
    assert len(rows) == 1118 and 0 < in_peak < len(rows)


def test_wrong_assembly_names(release, tmp_path):
    bad = tmp_path / "bad.tsv"
    bad.write_text("chrom\tpos\nssa21\t33005000\n")
    with pytest.raises(ValueError):
        annotate(bad, release, tmp_path / "out.tsv")
