"""Probe uniqueness against the Ss4R duplicate (snpportal.lib.uniqueness, ROADMAP I10) on SYNTHETIC sequence: a copy of
one flank with 2 mismatches and an exact reverse-complement copy of the other are found; a SNP with no copy has none."""
import random

from snpportal.lib import uniqueness


class Genome:  # snpscore.fasta.Fasta's fetch(), on sequences in memory
    def __init__(self, seqs):
        self.seqs = seqs

    def fetch(self, chrom, start, end):
        return self.seqs[chrom][max(0, start):end]


def test_flanks_found_on_both_strands():
    rnd = random.Random(1)
    seq = lambda n: "".join(rnd.choice("ACGT") for _ in range(n))  # noqa: E731
    one, two = seq(200_000), seq(200_000)
    pos = 100_000  # 1-based: one[pos - 1] is the SNP's base
    left, right = one[pos - 36:pos - 1], one[pos:pos + 35]
    copy = list(left)
    copy[3], copy[20] = ("A" if copy[3] != "A" else "C"), ("G" if copy[20] != "G" else "T")  # 2 mismatches
    two = two[:55_000] + "".join(copy) + two[55_035:120_000] + uniqueness.revcomp(right) + two[120_035:]
    genes = {"G2": ("2", 50_000, 60_000), "G3": ("2", 150_000, 151_000)}
    fasta = Genome({"1": one, "2": two})
    snps = [{"key": "a", "chrom": "1", "pos": pos, "gene_distance": 0, "ohnologs": ["G2"], "assay_flank": None},
            {"key": "b", "chrom": "1", "pos": pos, "gene_distance": 70_000, "ohnologs": ["G2"],  # wider: reaches 120 kb
             "assay_flank": f"{left.lower()}[{one[pos - 1]}/N]{right}"},
            {"key": "c", "chrom": "1", "pos": 30_000, "gene_distance": 0, "ohnologs": ["G3"], "assay_flank": None},
            {"key": "d", "chrom": "1", "pos": 30_000, "gene_distance": 0, "ohnologs": [], "assay_flank": None}]
    out = uniqueness.scan(snps, genes, fasta)
    assert out["a"]["paralog_left"] == round(33 / 35, 3) and out["a"]["paralog_right"] is None  # 120 kb is beyond 60 kb + 50 kb
    assert out["a"]["paralog_identity"] is None  # the right flank is clean: a probe there is unique
    assert (out["b"]["paralog_left"], out["b"]["paralog_right"], out["b"]["paralog_identity"]) == (round(33 / 35, 3), 1.0, round(33 / 35, 3))
    assert out["b"]["paralog_at"] == "2:120,001-" and out["b"]["paralog_gene"] == "G2"  # the exact copy, on the minus strand
    assert set(out["c"].values()) == {None}  # random sequence: checked, no close copy
    assert "d" not in out  # no Ss4R duplicate gene: not checked
    assert uniqueness.best_match("ACGTACGTAC" * 3 + "ACGTA", "T" * 100) is None
    assert uniqueness.flanks("acgt[A/G]TTGCA", 3) == ("CGT", "TTG")
