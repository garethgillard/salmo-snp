"""Vendor export rules (R2, docs/RESEARCH.md section 5): TOP/BOT against Illumina's published examples (topbot_reference.py
is the oracle), vendor-safe locus names, numeric build, chromosome 0, flank lengths and templates, upper-case IUPAC
neighbours, sidecar provenance, the assay rules (per-side flank variants, base-specific runs, repeat share, Illumina
code 103) and the panel-level checks (Infinium bins, markers within 60 bp, spacing in cM)."""
import csv
import io
import re

import duckdb
import pytest

from snpscore import assay
from snpportal.lib import export, panel
from snpscore.formats import InputError
from test_tools import annotated, release, rows  # noqa: F401 (module fixtures)
from topbot_reference import CASES, topbot

VGLL3 = "GCTGGGTGTTTACAGTAGGATGCAGCAGGACAGCA[C/T]GGAGCAGCAGTTTCCAGGGCGGAGACAGCAACAGC"  # docs/RESEARCH.md section 5
BACKGROUND = "ACGTTGCAAGCTTCGATCAG" * 2  # GC 0.5, longest run 2
RC = str.maketrans("ACGTacgt[]", "TGCAtgca][")


def parts(seq):
    """'L[X/Y]R' -> (X, Y, L, R)"""
    left, x, y, right = re.fullmatch(r"([A-Za-z]*)\[(\w)/(\w)\]([A-Za-z]*)", seq).groups()
    return x, y, left, right


def lines(path):
    return [line for line in path.read_text().splitlines() if not line.startswith("#")]


# TOP/BOT

@pytest.mark.parametrize("name, seq, strand, a, b", CASES)
def test_top_bot_matches_illumina_examples(name, seq, strand, a, b):
    assert export.top_bot(*parts(seq)) == (strand, a, b) == topbot(seq)
    flip = seq.translate(RC)[::-1]  # the reverse complement: TOP <-> BOT, the same alleles A and B (complemented)
    assert export.top_bot(*parts(flip)) == ({"TOP": "BOT", "BOT": "TOP"}[strand], a.translate(RC), b.translate(RC))


def test_top_bot_cannot_be_determined():
    for seq in ("ATAT[A/T]ATAT", "GCGC[C/G]GCGC", "AT[A/T]ATATAT", "RYAT[A/T]ATKM"):  # pairs run out (IUPAC skipped)
        assert topbot(seq) == (None, None, None) and export.top_bot(*parts(seq))[0] is None
    assert export.top_bot("A", "AT", "", "")[0] is None


def test_vgll3_test_vector(annotated):  # noqa: F811
    r = rows(annotated["snps.tsv"], "id = 'vgll3_Met54Thr'")[0]
    assert r["assay_flank"] == VGLL3 and r["assay_gc"] == pytest.approx(0.59, abs=0.005) and r["assay_homopolymer"] == 3 and r["assay_n"] == 0
    assert export.top_bot(*parts(VGLL3)) == topbot(VGLL3) == ("BOT", "T", "C")


# Vendor files

def test_vendor_files(release, annotated, tmp_path):  # noqa: F811
    out = {}
    for fmt in ("illumina", "axiom", "kasp"):
        out[fmt] = tmp_path / f"{fmt}.csv"
        result = export.export(annotated["snps.vcf"], fmt, out[fmt], release, "maturation", include_failed=True)
        assert result["files"] == [f"{fmt}.csv", f"{fmt}.csv.provenance.txt", f"{fmt}.csv.lookup.tsv"]
        text = out[fmt].read_text()
        assert "#" not in text and text.splitlines()[0].split(",") == export.TEMPLATES[fmt][export.VENDORS[fmt]["template"]]
    ill = list(csv.DictReader(out["illumina"].open()))
    assert {(r["Genome_Build_Version"], r["Species"], r["Force_Infinium_I"]) for r in ill} == {("0", "Other", "FALSE")}
    # Locus names: letters and digits, <= 20 characters, not rs/cg, unique; your ids are in the lookup
    names = [r["Locus_Name"] for r in ill]
    assert len(set(names)) == len(names) and all(re.fullmatch(r"[A-Za-z0-9]{1,20}", n) and n[:2].lower() not in ("rs", "cg")
                                                  for n in names)
    lookup = list(csv.DictReader(io.StringIO("\n".join(lines(tmp_path / "illumina.csv.lookup.tsv"))), delimiter="\t"))
    assert [r["locus_name"] for r in lookup] == names and all(r["id"] for r in lookup)
    # Sequences: 60 bp a side, upper case, neighbours as IUPAC codes; TOP/BOT as the oracle says, or code 103 noted
    for r, x in zip(ill, lookup):
        a, b, left, right = parts(r["Sequence"])
        assert len(left) == len(right) == 60 and r["Sequence"] == r["Sequence"].upper()
        assert (x["topbot"] or None, x["allele_a"] or None) == topbot(r["Sequence"])[:2]
        assert (not x["topbot"]) == (assay.TOPBOT_103 in (x["export_notes"] or ""))
    assert any(set(r["Sequence"]) & set("RYSWKM") for r in ill)
    kasp = list(csv.DictReader(out["kasp"].open()))
    assert all(len(parts(r["Sequence"])[2]) == 50 and re.fullmatch(r"\d+:\d+", r["Position"]) for r in kasp)
    axiom = list(csv.DictReader(out["axiom"].open()))
    assert all(len(r["Sequence"]) == 35 + 5 + 35 for r in axiom)
    # Without include_failed, Illumina leaves out assay fail/not_checked and code 103 SNPs, and says so in the sidecar
    result = export.export(annotated["snps.vcf"], "illumina", tmp_path / "strict.csv", release, "maturation")
    side = (tmp_path / "strict.csv.provenance.txt").read_text()
    assert result["rows"] < len(ill) and "left out" in side and "Genome_Build_Version 0" in side and "GCA_905237065.2" in side
    assert all(line.startswith("# ") for line in side.splitlines())
    assert any("Infinium" in w for w in result["warnings"]) and "warning: Illumina Infinium" in side


def test_vendor_rows_templates_and_scaffolds():
    manifest = {"version": "dev", "chrom_sizes": {"25": 1}}
    rec = dict(locus_name=export.locus_name("CAJNNT010000123.1", 512, {"25"}), chrom="CAJNNT010000123.1", pos=512,
               ref="A", alt="G", left="C" * 60, right="T" * 60)
    assert rec["locus_name"] == "Ssa0p512" and export.locus_name("25", 28996360, {"25"}) == "Ssa25p28996360"
    head, (row,) = export.vendor_rows("illumina", [rec], manifest)
    r = dict(zip(head, row))
    assert (r["Chromosome"], r["Coordinate"], r["Source_Version"], r["Replication_Count"]) == ("0", 0, 0, 1)  # no contig names
    assert export.vendor_rows("illumina", [rec], {"version": "3.1"}, "iselect-2016")[0][-2:] == ["Force_Infinium_I", "Species"]
    assert export.vendor_rows("illumina", [rec], {"version": "3.1"})[1][0][7] == "3.1"
    head, (row,) = export.vendor_rows("kasp", [rec], manifest)
    assert head == ["SNP ID", "Sequence", "Position"] and row[2] == "CAJNNT010000123.1:512"


def test_flank_lengths_and_templates(release, annotated, tmp_path):  # noqa: F811
    for fmt, flank in (("kasp", 40), ("kasp", 101), ("illumina", 50), ("axiom", 50)):
        with pytest.raises(InputError):
            export.export(annotated["snps.tsv"], fmt, tmp_path / "x.csv", release, flank=flank)
    with pytest.raises(InputError):
        export.export(annotated["snps.tsv"], "illumina", tmp_path / "x.csv", release, template="v0")
    export.export(annotated["snps.tsv"], "kasp", tmp_path / "k.csv", release, flank=100, sidecars=False)
    (row,) = list(csv.DictReader((tmp_path / "k.csv").open()))
    assert len(parts(row["Sequence"])[2]) == 100 and not (tmp_path / "k.csv.lookup.tsv").exists()


# Assay rules on hand-made windows (lower case in li/ri marks a public neighbour, as assay.window writes them)

def qc(lw=BACKGROUND[:35], rw=BACKGROUND[5:40], ref="C", alt="T", li=None, ri=None, **rules):
    con = duckdb.connect()
    con.execute("CREATE TABLE s AS SELECT 0 AS idx, ?::VARCHAR AS ref, ?::VARCHAR AS alt, 'ok' AS ref_check", [ref, alt])
    con.execute("CREATE TABLE w AS SELECT 0 AS idx, ?::VARCHAR AS base, ?::VARCHAR AS lw, ?::VARCHAR AS rw, "
                "?::VARCHAR AS li, ?::VARCHAR AS ri, NULL::VARCHAR AS pub", [ref, lw, rw, li or lw.upper(), ri or rw.upper()])
    cur = con.execute(assay.assay_sql("s", "w", assay.rules({"assay": rules}), ["ref", "alt", "ref_check"]))
    return dict(zip([d[0] for d in cur.description], cur.fetchone()))


def test_assay_rules():
    assert qc()["assay_status"] == "pass"
    left, right = "y" + BACKGROUND[1:35], "r" + BACKGROUND[6:40]
    # Neighbours: upper-case IUPAC in assay_flank; per side, one clean side is enough (Axiom)
    one = qc(li=left)
    assert one["assay_status"] == "pass" and one["assay_flank"].startswith("Y") and one["assay_flank"] == one["assay_flank"].upper()
    assert qc(li=left, flank_variants_per_side=False)["assay_reasons"] == "flank variants 1"
    assert qc(li=left, ri=right)["assay_reasons"] == "flank variants on both sides 1 + 1"
    # Base-specific runs (optional): G/C > 4, A/T > 6
    g5 = BACKGROUND[:29] + "GGGGGA"
    assert qc(lw=g5)["assay_status"] == "pass"
    assert qc(lw=g5, homopolymer_by_base={"G": 4, "C": 4, "A": 6, "T": 6})["assay_reasons"] == "G run 5"
    # Repeat share: only a high share warns (default 0.9)
    assert qc(lw=BACKGROUND[:35].lower())["assay_status"] == "pass"  # 0.5
    assert qc(lw=BACKGROUND[:35].lower(), rw=BACKGROUND[5:40].lower())["assay_reasons"] == "repeat 1.0"
    # A/T or C/G with no TOP/BOT strand in the flanks: Illumina code 103
    at = qc(lw="TA" * 17 + "T", rw="AT" * 17 + "A", ref="A", alt="T", warn_flags=[])
    assert at["assay_reasons"].endswith(assay.TOPBOT_103)
    assert assay.TOPBOT_103 not in (qc(ref="A", alt="T", warn_flags=[])["assay_reasons"] or "")


def test_breakdown():
    con = duckdb.connect()
    con.execute("CREATE TABLE t AS SELECT * FROM (VALUES ('repeat 0.97; GC 0.8'), ('repeat 1.0'), (NULL), "
                "('flank variants on both sides 1 + 2; TOP/BOT cannot be determined (Illumina code 103)')) v(assay_reasons)")
    assert assay.breakdown(con, "t") == {"repeat": 2, "GC": 1, "TOP/BOT cannot be determined": 1,
                                         "flank variants on both sides": 1}


# Panel-level checks

def test_vendor_checks():
    snps = [("1", 100 * i, "A", "T") for i in range(1, 51)] + [("2", 1000, "C", "T"), ("2", 1060, "G", "A"), ("3", 5, None, None)]
    c = panel.vendor_checks(snps)
    assert c["infinium_bins"] == {"A": 50, "B": 0, "C": 2, "unknown": 1} and c["close_pairs"] == 1
    text = " ".join(c["warnings"])
    assert "50 A/T SNPs in Infinium I bin A" in text and "bin C" in text and "within 60 bp" in text and "bin B" not in text
    assert panel.vendor_checks([("1", i * 100, "A", "T") for i in range(150)])["warnings"][0].endswith("(warning 604)")


def test_panel_spacing_in_cm(annotated, release, tmp_path):  # noqa: F811
    a = panel.design(annotated["snps.vcf"], "maturation", n_target=60, min_spacing_bp=0, min_spacing_cm=0.01,
                     out=tmp_path / "cm.parquet")
    picked = rows(tmp_path / "cm.parquet")
    by_chrom = {}
    for r in picked:
        by_chrom.setdefault(r["chrom"], []).append((r["pos"], (r["cm_male"] + r["cm_female"]) / 2))
    gaps = [y[1] - x[1] for p in by_chrom.values() for x, y in zip(sorted(p), sorted(p)[1:])]
    assert gaps and min(gaps) >= 0.01 - 1e-9 and a["summary"]["spacing_cm"]["min"] >= 0.01 - 1e-9
    assert a["params"]["cm_map"] == "mean" and a["summary"]["binding"] in (None, "min_spacing_cm")
    female = panel.design(annotated["snps.vcf"], "maturation", n_target=60, min_spacing_bp=0, min_spacing_cm=0.01,
                          cm_map="female")
    assert female["hash"] != a["hash"]
    bare = tmp_path / "bare.parquet"
    duckdb.sql(f"COPY (SELECT * EXCLUDE (cm, cm_male, cm_female) FROM read_parquet('{annotated['snps.vcf']}')) TO '{bare}'")
    with pytest.raises(InputError):
        panel.design(bare, "maturation", min_spacing_cm=0.01)
