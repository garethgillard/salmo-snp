"""The user's own population (snpportal.lib.population, ROADMAP I9): counts from genotypes or a frequency table, an
exact HWE test, and nothing but counts written."""
import duckdb
import pytest

from snpportal.lib import population

HEADER = "##fileformat=VCFv4.2\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tf1\tf2\tf3\tf4\n"


def test_hwe_exact():
    assert population.hwe_p(50, 25, 25) == pytest.approx(1.0)  # the expected split at p = 0.5
    assert population.hwe_p(0, 50, 50) < 1e-20  # no heterozygotes at all
    assert population.hwe_p(100, 0, 0) < 1e-20  # only heterozygotes
    assert population.hwe_p(0, 0, 0) is None
    assert population.hwe_p(40, 30, 30) > population.hwe_p(30, 35, 35)  # further from HWE, smaller p


def test_counts_from_genotypes_keep_no_genotypes(tmp_path):
    vcf = tmp_path / "genotypes_SYNTHETIC.vcf"
    vcf.write_text(HEADER + "ssa25\t28996360\t.\tC\tT\t.\t.\t.\tGT:DP\t0/0:9\t0|1:8\t1/1:7\t./.:0\n"
                   "25\t28998410\t.\tC\tG,A\t.\t.\t.\tGT\t0/1\t0/2\t0/0\t0/0\n")  # multiallelic: left out
    info = population.count(vcf, tmp_path, tmp_path / "pop.parquet")
    assert info == {"format": "VCF genotypes", "sites": 1, "fish": 4}
    con = duckdb.connect()
    cols = [c for c, in con.execute(f"SELECT column_name FROM (DESCRIBE SELECT * FROM '{tmp_path / 'pop.parquet'}')").fetchall()]
    assert tuple(cols) == population.COLUMNS  # counts only: no sample or genotype columns
    row = con.execute(f"SELECT * FROM '{tmp_path / 'pop.parquet'}'").fetchall()[0]
    assert row[:4] == ("ssa25", 28996360, "C", "T")  # no release alias table here, so the name stays
    assert row[4:8] == (0.5, 0.5, 3, 0.75)  # af, maf, fish called, call rate


def test_frequency_table(tmp_path):
    t = tmp_path / "freqs.csv"
    t.write_text("CHR,BP,REF,ALT,ALT_FREQ,N\n25,28996360,C,T,0.8,120\n25,bad,C,T,0.1,3\n")
    population.count(t, tmp_path, tmp_path / "pop.parquet")
    assert duckdb.execute(f"SELECT chrom, pos, af, maf, n FROM '{tmp_path / 'pop.parquet'}'").fetchall() == [("25", 28996360, 0.8, 0.2, 120)]
    bad = tmp_path / "none.tsv"
    bad.write_text("a\tb\n1\t2\n")
    with pytest.raises(population.InputError):
        population.count(bad, tmp_path, tmp_path / "x.parquet")
