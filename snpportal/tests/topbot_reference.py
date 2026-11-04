"""Reference implementation of Illumina's TOP/BOT strand and A/B allele rule,
checked against every example in Illumina tech note 370-2006-018
(https://www.illumina.com/documents/products/technotes/technote_topbot.pdf).
Written independently of snpscore during the research sweep (docs/RESEARCH.md section 5) and kept unchanged as the
oracle for tests/test_vendor.py."""
from __future__ import annotations

import re

AT, CG = set("AT"), set("CG")


def _unambiguous(a: str, b: str) -> bool:
    # Tech note footnote: unambiguous pairs are A/G, A/C, T/C, T/G
    return (a in AT and b in CG) or (a in CG and b in AT)


def topbot(seq: str):
    """seq like 'ACG[A/T]TTA'. Returns (strand, allele_a, allele_b) for the
    sequence as written, or (None, None, None) if undeterminable (Illumina code 103)."""
    m = re.fullmatch(r"([A-Za-z]*)\[([ACGT])/([ACGT])\]([A-Za-z]*)", seq.strip())
    if not m:
        raise ValueError("need exactly one [X/Y] SNP: " + seq)
    left, x, y, right = m.group(1).upper(), m.group(2), m.group(3), m.group(4).upper()
    alleles = {x, y}
    if len(alleles) != 2:
        raise ValueError("not a SNP")
    if _unambiguous(x, y):
        if "A" in alleles:  # A with C or G -> TOP, Allele A = A
            return "TOP", "A", (alleles - {"A"}).pop()
        return "BOT", "T", (alleles - {"T"}).pop()  # T with C or G -> BOT, Allele A = T
    # [A/T] or [C/G]: walk n-i / n+i until an unambiguous pair
    for i in range(1, min(len(left), len(right)) + 1):
        five, three = left[-i], right[i - 1]
        if _unambiguous(five, three):
            strand = "TOP" if five in AT else "BOT"  # A/T base on the 5' side -> TOP
            if alleles == AT:
                return (strand, "A", "T") if strand == "TOP" else (strand, "T", "A")
            return (strand, "C", "G") if strand == "TOP" else (strand, "G", "C")
    return None, None, None


# (name, sequence, strand, allele A, allele B) from Tables 1-3 of the tech note
CASES = [
    ("rs363040", "AGGAGGCTAG[G/T]CTCGCAGAGC", "BOT", "T", "G"),
    ("rs536477", "GAGATTTAGG[A/G]AAAGATGTGA", "TOP", "A", "G"),
    ("rs684517", "ACCAGGTACT[C/T]TGAACTTTAC", "BOT", "T", "C"),
    ("rs2034107", "CATCTCCCCC[A/C]AAATCAGTTT", "TOP", "A", "C"),
    ("rs1535632", "ACGGGGACAG[A/T]TATGTTAACT", "BOT", "T", "A"),
    ("rs363334", "ATGAGTGAAT[C/G]AAGCACTATT", "TOP", "C", "G"),
    ("rs7101540", "AAATTCAGAT[A/T]CAGAATCTTT", "TOP", "A", "T"),
    ("rs7113791", "GATGGACAGG[A/T]TGACCTCTAG", "BOT", "T", "A"),
    ("rs778833", "GGTTAAATGT[C/G]AAGGTGAGCT", "BOT", "G", "C"),
    ("rs4933195", "ATGCTAATAA[A/T]ACATTAAAGT", "TOP", "A", "T"),
    ("rs903997", "ATGAGAAAGT[C/G]TGAGAGTGCA", "TOP", "C", "G"),
    ("rs1942968", "CTACATGACT[C/G]TTTATGTTAC", "BOT", "G", "C"),
    ("fig1_derived", "ATTAC[A/T]TTATT", "BOT", "T", "A"),  # Figure 1 gives only the n-1|n+1 C/T pair; strand derived by the rule
    ("SNP1_Assembly1", "GGACCCGCAA[G/A]GAGGGCGCGG", "TOP", "A", "G"),
    ("SNP1_Assembly2", "CCGCGCCCTC[C/T]TTGCGGGTCC", "BOT", "T", "C"),
    ("SNP2_Assembly1", "GGTAGCCTGA[A/T]ACCCCCAAGA", "TOP", "A", "T"),
    ("SNP2_Assembly2", "TCTTGGGGGT[A/T]TCAGGCTACC", "BOT", "T", "A"),
]

if __name__ == "__main__":
    bad = 0
    for name, seq, *want in CASES:
        got = list(topbot(seq))
        ok = got == want
        bad += not ok
        print("%-16s %-28s want %-14s got %-14s %s" % (name, seq, "/".join(want), "/".join(map(str, got)), "ok" if ok else "MISMATCH"))
    print("%d/%d match" % (len(CASES) - bad, len(CASES)))
