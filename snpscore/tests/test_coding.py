"""Coding consequence (VEP-lite, snpscore.coding) on the fixture release, whose genome has real sequence around vgll3
(chr25, + strand) and bco1l (chr26, - strand). Every expected value below was checked against the Ensembl VEP REST
API (release 116) on 2026-10-07; VEP computes the stop_lost extension length (p.Ter357ArgextTer14), coding writes
extTer?. The SNPs are built from the fixture genome's codons: synthetic test inputs, not breeder data."""
import json
from pathlib import Path

import duckdb
import pytest
import yaml

from snpscore import annotate, build, scored
from snpscore.coding import COLUMNS

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixture"
VGLL3, BCO1L = "ENSSSAT00000230965", "ENSSSAT00000139328"  # canonical transcripts of vgll3 (+) and bco1l (-)
# First codon not ATG (no other CDS there): TAC with a 5' UTR (+), AAG without one (-, a 5'-incomplete model)
TAC, AAG = "ENSSSAT00000230643", "ENSSSAT00000139339"
# Published vgll3 Met54Thr (Ayllon 2015) is Thr46Met on the Ensembl 116 canonical transcript: the published residue
# numbers are 8 ahead (Asn323Lys = Asn315Lys too; the catalogue note records it)
VGLL3_PUBLISHED_OFFSET = 8
CASES = [  # id, chrom, pos, ref, alt, consequence, hgvsp, codons, transcript
    ("vgll3_Met54Thr", "25", 28996360, "C", "T", "missense_variant", "p.Thr46Met", "aCg/aTg", VGLL3),
    ("synonymous", "25", 28996361, "G", "A", "synonymous_variant", "p.Thr46=", "acG/acA", VGLL3),
    ("stop_gained", "25", 28995900, "C", "T", "stop_gained", "p.Gln2Ter", "Cag/Tag", VGLL3),
    ("start_lost", "25", 28995897, "A", "G", "start_lost", "p.Met1?", "Atg/Gtg", VGLL3),
    ("stop_lost", "25", 28998678, "T", "C", "stop_lost", "p.Ter357ArgextTer?", "Tga/Cga", VGLL3),
    ("across_exons", "25", 28997926, "A", "C", "missense_variant", "p.Asp154Ala", "gAt/gCt", VGLL3),  # 28996683 + 28997926-7
    ("minus_stop_gained", "26", 19140203, "T", "A", "stop_gained", "p.Lys352Ter", "Aag/Tag", BCO1L),
    ("minus_synonymous", "26", 19140204, "G", "A", "synonymous_variant", "p.Asn351=", "aaC/aaT", BCO1L),
    ("minus_across_exons", "26", 19141752, "C", "A", "missense_variant", "p.Gly23Val", "gGa/gTa", BCO1L),
    ("splice_donor", "25", 28996684, "G", "A", "splice_donor_variant", None, None, VGLL3),
    ("splice_acceptor", "25", 28996318, "A", "G", "splice_acceptor_variant", None, None, VGLL3),
    ("minus_splice_donor", "26", 19140142, "A", "G", "splice_donor_variant", None, None, BCO1L),
    ("minus_splice_acceptor", "26", 19140415, "T", "G", "splice_acceptor_variant", None, None, BCO1L),
    ("codon1_missense", "9", 23852226, "T", "C", "start_lost", "p.Tyr1?", "Tac/Cac", TAC),  # VEP: any change of codon 1
    ("codon1_stop", "9", 23852228, "C", "A", "stop_gained", "p.Tyr1?", "taC/taA", TAC),  # VEP: stop_gained,start_lost
    ("codon1_synonymous_utr", "9", 23852228, "C", "T", "start_lost", "p.Tyr1?", "taC/taT", TAC),
    ("minus_codon1_missense", "26", 19142225, "T", "C", "start_lost", "p.Lys1?", "Aag/Gag", AAG),
    ("minus_codon1_synonymous", "26", 19142223, "C", "T", "synonymous_variant", "p.Lys1=", "aaG/aaA", AAG),  # no 5' UTR
]


@pytest.fixture(scope="module")
def release(tmp_path_factory):
    return build(ROOT / "layers.yaml", FIXTURE, tmp_path_factory.mktemp("release") / "test")


def run(release, tmp_path, lines, header="id\tchrom\tpos\tref\talt"):
    snps = tmp_path / "snps.tsv"
    snps.write_text(header + "\n" + "".join("\t".join(map(str, line)) + "\n" for line in lines))
    out = annotate(snps, release, tmp_path / "out.parquet")
    rel = duckdb.sql(f"SELECT * FROM read_parquet('{out}')")
    return {r["id"]: r for r in (dict(zip(rel.columns, row)) for row in rel.fetchall())}, out


def test_consequences(release, tmp_path):
    rows, out = run(release, tmp_path, [c[:5] for c in CASES])
    for name, chrom, pos, ref, alt, consequence, hgvsp, codons, transcript in CASES:
        r = rows[name]
        assert (r["coding_consequence"], r["coding_hgvsp"], r["coding_codons"], r["coding_transcript"], r["coding_note"]) == \
            (consequence, hgvsp, codons, transcript, None), name
    assert rows["vgll3_Met54Thr"]["coding_aa_pos"] + VGLL3_PUBLISHED_OFFSET == 54
    assert rows["minus_stop_gained"]["coding_aa_pos"] == 352 and rows["splice_donor"]["coding_aa_pos"] is None
    assert rows["vgll3_Met54Thr"]["tier_evidence"].startswith("missense p.Thr46Met")
    assert rows["minus_splice_donor"]["tier_evidence"].startswith("splice donor")
    report = json.loads(out.with_name("out.validation.json").read_text())["coding"]
    assert report["missense_variant"] == 3 and report["splice_donor_variant"] == 2


def test_alleles(release, tmp_path):
    rows, _ = run(release, tmp_path, [("no_alt", "25", 28996360, "C", ""), ("other_strand", "25", 28996360, "G", "A"),
                                      ("swapped", "25", 28996360, "T", "C"), ("two_alts", "25", 28996360, "C", "T,G"),
                                      ("mismatch", "25", 28996360, "A", "T")])
    got = {k: (r["coding_consequence"], r["coding_hgvsp"], r["coding_note"]) for k, r in rows.items()}
    assert got == {"no_alt": ("missense_variant", "p.Thr46Met", "alt allele from the public panel"),  # the 504-fish site C/T
                   "other_strand": ("missense_variant", "p.Thr46Met", None),
                   "swapped": ("missense_variant", "p.Thr46Met", None),  # HGVS is always relative to the reference
                   "two_alts": ("missense_variant", "p.Thr46Met", "first of several alt alleles"),
                   "mismatch": ("coding_sequence_variant", None, "alleles do not match the genome")}
    rows, _ = run(release, tmp_path, [("25", 28996360, "position_only"), ("25", 28996365, "no_panel_site")],
                  header="chrom\tpos\tid")
    got = {k: (r["coding_consequence"], r["coding_hgvsp"], r["coding_aa_pos"], r["coding_note"]) for k, r in rows.items()}
    assert got == {"position_only": ("missense_variant", "p.Thr46Met", 46, "alleles from the public panel"),  # its C/T
                   "no_panel_site": ("coding_sequence_variant", None, 48, "alleles unknown")}
    assert rows["no_panel_site"]["tier_evidence"].startswith("CDS")


def test_tiers_unchanged(release, tmp_path):
    # The coding weight counts every CDS change but synonymous ones, the synonymous weight (equal by default) the rest
    rows, out = run(release, tmp_path, [c[:5] for c in CASES])
    weights = yaml.safe_load((Path(release) / "weights.yaml").read_text())
    con = duckdb.connect()
    con.execute(f"CREATE TABLE a AS SELECT * FROM read_parquet('{out}')")
    columns = [c for c, in con.execute("SELECT column_name FROM (DESCRIBE a)").fetchall()]
    con.execute(f"CREATE TABLE old AS SELECT * EXCLUDE ({', '.join(COLUMNS)}) FROM a")  # as before coding.py
    old = con.execute(f"SELECT id, tier, tier_score FROM ({scored('old', weights, [c for c in columns if c not in COLUMNS], 'all')})").fetchall()
    assert sorted(old) == sorted((k, r["tier"], r["tier_score"]) for k, r in rows.items())
    assert {"term": "synonymous", "weight": weights["weights"]["coding"]} in rows["synonymous"]["tier_terms"]
    lower = {**weights, "weights": {**weights["weights"], "synonymous": 0}}
    new = dict(con.execute(f"SELECT id, tier_score FROM ({scored('a', lower, columns, 'all')})").fetchall())
    assert {k for k, r in rows.items() if new[k] != r["tier_score"]} == {"synonymous", "minus_synonymous",
                                                                         "minus_codon1_synonymous"}
