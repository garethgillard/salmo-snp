"""A release of another species (rainbow trout, USDA_OmykA_1.1): annotate takes the chromosomes, aliases and assembly
names from the release, and the public pool samples its sites. The fixture is two small regions (snpdata
prep/make_fixture_trout.py): chromosome 28 12.00-12.22 Mb (greb1l, rock1) and Y 5.95-6.05 Mb (sdY)."""
import json
from pathlib import Path

import duckdb
import pytest

from snpdata import build
from snpscore import InputError, annotate, pool

DATA = Path(__file__).resolve().parent.parent.parent / "snpdata"


@pytest.fixture(scope="module")
def trout(tmp_path_factory):
    return build(DATA / "rainbow_trout" / "layers.yaml", DATA / "tests" / "fixture_trout", tmp_path_factory.mktemp("release") / "trout-test")


def test_annotate_trout(trout, tmp_path):
    src = tmp_path / "snps.tsv"
    src.write_text("chrom\tpos\nomy28\t12029722\nNC_048592.1\t12150000\nY\t6002000\n29\t100\n")
    out = annotate(src, trout, tmp_path / "out.parquet")
    rows = duckdb.sql(f"SELECT chrom, pos, gene_id, region_class, ss4r_ohnolog_chrom, tier FROM read_parquet('{out}') ORDER BY pos").fetchall()
    assert [r[:3] for r in rows] == [("Y", 6002000, "ENSOMYG00000068768"), ("28", 12029722, "ENSOMYG00000036625"),
                                     ("28", 12150000, "ENSOMYG00000036817")]  # sdY, greb1l, rock1
    assert rows[1][3] == "CDS" and rows[1][4] == "8" and rows[1][5] <= 2  # greb1l's Ss4R duplicate is on chromosome 8
    report = json.loads((tmp_path / "out.validation.json").read_text())
    assert report["rejected"] == {"unknown_chrom": 1}  # the Arlee assembly has no chromosome 29
    bad = tmp_path / "bad.tsv"
    bad.write_text("chrom\tpos\nssa25\t100\n")
    with pytest.raises(InputError, match="USDA_OmykA_1.1 chromosomes 1-32 or their aliases .*omy32"):
        annotate(bad, trout, tmp_path / "bad.parquet")


def test_trout_pool_samples_the_public_sites(trout, tmp_path, monkeypatch):
    """Without the 12 AQUA-FAANG fish's column, the pool takes an even sample of at most MAX_SITES public sites."""
    sites = duckdb.sql(f"SELECT count(*) FROM read_parquet('{trout / 'public_af.parquet'}')").fetchall()[0][0]
    monkeypatch.setattr(pool, "MAX_SITES", sites // 4)
    target = pool.release_sites(trout, tmp_path)
    n = len(target.read_text().splitlines()) - 1
    assert 0 < n < sites / 2
