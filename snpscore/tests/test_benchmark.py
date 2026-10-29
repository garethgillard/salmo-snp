from pathlib import Path

import duckdb
import pytest

from snpscore import InputError
from snpdata import build
from snpscore.benchmark import benchmark_sets, molqtl_spec, ratio_interval, wilson
from snpscore.pool import build_pool

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT.parent / "snpdata"  # the release build: layers.yaml, fixture, prep/, catalogue, data/, release/
FIXTURE = DATA / "tests" / "fixture"


@pytest.fixture(scope="module")
def release(tmp_path_factory):
    out = build(DATA / "layers.yaml", FIXTURE, tmp_path_factory.mktemp("release") / "test")
    build_pool(out, FIXTURE / "12_samples_genotype_filtered_on_504.vcf.gz", assay=True, threads=2, memory_limit="1GB")
    return out


def test_intervals():
    low, high = wilson(5, 10)
    assert low == pytest.approx(0.2366, abs=1e-4) and high == pytest.approx(0.7634, abs=1e-4)
    assert wilson(0, 0) == (None, None) and wilson(0, 20)[0] == 0
    low, high = ratio_interval(10, 100, 10, 1000)  # 10x, Katz log interval
    assert low == pytest.approx(4.27, abs=0.01) and high == pytest.approx(23.45, abs=0.01)
    assert ratio_interval(0, 10, 3, 100)[0] > 0  # a zero count still gives an interval


def test_specs():
    assert molqtl_spec("molqtl") == (None, None) and molqtl_spec("molqtl:ca") == ("ca", None)
    assert molqtl_spec("molqtl:e:Liver") == ("e", "Liver") and molqtl_spec("molqtl:Gill") == (None, "Gill")
    assert molqtl_spec("benchmark/known_loci.tsv") is None
    with pytest.raises(InputError):
        molqtl_spec("molqtl:x:y")


def test_molqtl_positives_and_matched_controls(release, tmp_path):
    out = tmp_path / "benchmark_molqtl.tsv"
    sets = benchmark_sets(["molqtl:ca", "molqtl:e"], None, release, out, controls=3, by_tissue=True)
    assert "molqtl:ca" in sets and "molqtl:e" in sets and any(name.count(":") == 2 for name in sets)
    trait, rows = sets["molqtl:ca"]
    features = {r[0]: r for r in rows}
    n = rows[0][1]
    assert trait == "all" and n > 0 and rows[0][2] == 3 * n  # enough background in every distance and MAF bin
    assert "molqtl" not in features  # the positives' own layer is not a feature
    for r in rows:  # shares sit inside their intervals
        assert r[8] <= r[3] <= r[9] and r[10] <= r[4] <= r[11]
    liver = [name for name in sets if name.endswith(":Liver")]
    assert liver and all(sets[name][0] == "liver" for name in liver)  # one-tissue sets use the tissue's preset
    lines = out.read_text().splitlines()
    assert lines[0].startswith("# snpscore benchmark") and any("winner's curse" in x for x in lines if x.startswith("#"))
    header = next(x for x in lines if not x.startswith("#")).split("\t")
    assert header[:5] == ["set", "trait", "feature", "positives", "controls"] and "enrichment_high" in header
    with pytest.raises(InputError, match="tissue"):
        benchmark_sets(["molqtl:ca:Kidney"], None, release)


def test_file_positives_with_the_pool(release):
    trait, rows = benchmark_sets([DATA / "catalog" / "known_loci.tsv"], None, release)["known_loci"]
    features = {r[0]: r for r in rows}
    assert features["region_class = CDS"][3] > 0 and "tier <= 2" in features and "evidence = active" in features
    columns = duckdb.sql(f"DESCRIBE SELECT * FROM '{release / 'pool' / 'pool.parquet'}'").fetchall()
    if any(c[0].endswith("_consequence") for c in columns):  # the pool was built with the coding step (vgll3 Met54Thr)
        assert any(f.endswith("_consequence = missense_variant") and r[3] > 0 for f, r in features.items())
