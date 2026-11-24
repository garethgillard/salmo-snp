"""Structural variants (snpscore.sv): coordinates from every input layout, evidence by overlap, and the rule that ties
it to SNP scoring: a 1-bp SV scores as a SNP without alleles at that base."""
import json
from pathlib import Path

import duckdb
import pytest

from snpdata import build
from snpscore import InputError, annotate, annotate_svs, load_weights

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT.parent / "snpdata"
FIXTURE = DATA / "tests" / "fixture"


@pytest.fixture(scope="module")
def release(tmp_path_factory):
    return build(DATA / "layers.yaml", FIXTURE, tmp_path_factory.mktemp("release") / "test")


def read(path):
    rel = duckdb.sql(f"SELECT * FROM read_parquet('{path}')")
    return [dict(zip(rel.columns, row)) for row in rel.fetchall()]


def run(release, tmp_path, name, text):
    (tmp_path / name).write_text(text)
    out = annotate_svs(tmp_path / name, release, tmp_path / f"{name}.parquet")
    report = json.loads(out.with_name(out.stem + ".validation.json").read_text())
    return {r["id"]: r for r in read(out)}, report


def test_coordinates_of_every_layout(release, tmp_path):
    # VCF: POS is the padding base of <DEL> and ACGT>A; END or SVLEN gives the end; insertions and breakends are junctions
    vcf, report = run(release, tmp_path, "svs.vcf", "##fileformat=VCFv4.2\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
                      "25\t28996000\tdel\tN\t<DEL>\t.\tPASS\tSVTYPE=DEL;END=28997000;SVLEN=-1000\n"
                      "ssa25\t28996000\tdup\tN\t<DUP>\t.\tPASS\tSVLEN=2000\n"
                      "25\t28990000\tins\tN\t<INS>\t.\tPASS\tSVTYPE=INS;SVLEN=300\n"
                      "25\t28996359\tseq\tCTTA\tC\t.\tPASS\t.\n"
                      "21\t33000000\tbnd\tN\tN[25:3000[\t.\tPASS\tSVTYPE=BND\n"
                      "25\t28996360\tsnv\tC\tT\t.\tPASS\t.\n"
                      "25\t28996000\tnoend\tN\t<INV>\t.\tPASS\tSVTYPE=INV\n"
                      "99\t100\tunknown\tN\t<DEL>\t.\tPASS\tEND=200\n"
                      "25\t28996000\tagain\tN\t<DEL>\t.\tPASS\tSVTYPE=DEL;END=28997000\n")
    span = {k: (r["pos"], r["end"], r["svtype"]) for k, r in vcf.items()}
    assert span == {"del": (28996001, 28997000, "DEL"), "dup": (28996001, 28998000, "DUP"), "ins": (28990000, 28990001, "INS"),
                    "seq": (28996360, 28996362, "DEL"), "bnd": (33000000, 33000001, "BND"), "snv": (28996360, 28996360, "SNV")}
    assert vcf["del"]["length"] == 1000 and vcf["del"]["svlen"] == 1000 and vcf["dup"]["chrom"] == "25"
    assert report["rejected"] == {"bad_end": 1, "duplicate": 1, "unknown_chrom": 1} and report["format"] == "vcf"
    # BED: 0-based start (a zero-length interval is a junction); tables and headerless lines: 1-based, inclusive
    bed, _ = run(release, tmp_path, "svs.bed", "track name=x\n25\t28995999\t28997000\tb\n25\t28990000\t28990000\tpoint\n")
    assert (bed["b"]["pos"], bed["b"]["end"], bed["point"]["pos"], bed["point"]["end"]) == (28996000, 28997000, 28990000, 28990001)
    table, report = run(release, tmp_path, "svs.csv", "Chromosome,Start,Stop,Name,Type,Caller\n25,28996000,28997000,t,deletion,x\n"
                        "25,28996000,,len,DEL,x\n")
    assert (table["t"]["pos"], table["t"]["end"], table["t"]["svtype"], table["t"]["in_Caller"]) == (28996000, 28997000, "DEL", "x")
    assert report["rejected"] == {"bad_end": 1}  # an empty end and no length
    sized, _ = run(release, tmp_path, "sized.tsv", "chrom\tpos\tsvlen\tid\n25\t28996000\t-500\ts\n")
    assert (sized["s"]["pos"], sized["s"]["end"]) == (28996000, 28996499)
    lines, report = run(release, tmp_path, "lines.txt", "25 28996000 28997000 DUP mine\n25:28,996,001-28,997,000 x\n")
    assert report["format"] == "noheader" and (lines["mine"]["svtype"], lines["mine"]["end"]) == ("DUP", 28997000)
    regions, report = run(release, tmp_path, "regions.txt", "25:28,996,001-28,997,000 DEL r1\n26:15.0-15.1\n")
    assert (regions["r1"]["pos"], regions["r1"]["svtype"], report["rejected"]) == (28996001, "DEL", {"bad_pos": 1})
    with pytest.raises(InputError, match="no end"):
        run(release, tmp_path, "nothing.tsv", "chrom\tstart\tname\n25\t1\tx\n")


def test_overlap_evidence(release, tmp_path):
    weights = load_weights()
    rows, _ = run(release, tmp_path, "svs.tsv", "chrom\tstart\tend\tid\n"
                  "1\t110000790\t110006634\ttwo_peaks\n"      # the fixture's first two peaks on chromosome 1
                  "25\t28996000\t28997000\tvgll3_cds\n"       # vgll3's exon with Met54Thr
                  "21\t32050000\t33100000\twide\n"           # over blacklisted sequence and several genes
                  "26\t14000001\t14000010\tintergenic\n")
    # per condition, the strongest state of the peaks overlapped (active, then weak, then any): from the BED itself
    order = weights["active_states"] + weights["weak_states"]
    peaks = [line.split("\t") for line in (FIXTURE / "AtlanticSalmon_unified_peaks.bed").read_text().splitlines()]
    states = {}
    for chrom, start, end, labels, *_ in peaks:
        if chrom == "1" and int(start) < 110006634 and int(end) >= 110000790:
            for label in labels.split(","):
                condition, state = label.split(":")
                states.setdefault(condition, []).append(state)
    two = rows["two_peaks"]
    assert two["peaks"] == 2 and two["chromatin"]
    for condition, found in states.items():
        assert two[f"chromatin_{condition}"] == min(found, key=lambda s: order.index(s) if s in order else len(order))
    assert two["chromatin_Liver_Immature_Male"] == "Active_enhancer" and "active" in [t["term"] for t in two["tier_terms"]]
    cds = rows["vgll3_cds"]
    assert cds["region_class"] == "CDS" and cds["region_classes"].startswith("CDS,") and cds["gene_distance"] == 0
    assert cds["known_locus"] == "vgll3_Met54Thr" and cds["known_locus_dist"] == 0 and cds["tier"] <= 2
    assert {"term": "coding", "weight": weights["weights"]["coding"]} in cds["tier_terms"]
    wide = rows["wide"]
    assert wide["blacklist"] and wide["n_genes"] >= 2 and wide["genes"].count(",") == wide["n_genes"] - 1
    assert wide["gene_distance"] == 0 and wide["peaks"] > 2
    none = rows["intergenic"]
    assert not none["chromatin"] and none["region_class"] is None and none["n_genes"] in (0, None) and none["tier"] == 4
    # nothing that needs a base and its alleles
    assert not {"ref_check", "assay_status", "coding_consequence", "motif", "public_af", "flank_variants"} & set(cds)


def test_one_base_svs_score_as_snps(release, tmp_path):
    # The rule that ties SVs to SNPs: an SV of one base overlaps exactly what a SNP at that base is inside, so the same
    # positions as SNPs (without alleles) and as 1-bp SVs get the same layers and the same tiers.
    sites = [line.split("\t")[:2] for line in (FIXTURE / "snps.vcf").read_text().splitlines() if not line.startswith("#")][::7]
    (tmp_path / "pos.tsv").write_text("chrom\tpos\n" + "".join(f"{c}\t{p}\n" for c, p in sites))
    (tmp_path / "one.tsv").write_text("chrom\tstart\tend\n" + "".join(f"{c}\t{p}\t{p}\n" for c, p in sites))
    snps = read(annotate(tmp_path / "pos.tsv", release, tmp_path / "snps.parquet", sequence=False))
    svs = read(annotate_svs(tmp_path / "one.tsv", release, tmp_path / "svs.parquet"))
    assert len(snps) == len(svs) > 300
    same = [c for c in svs[0] if c in snps[0] and not c.startswith("known_") and c not in ("tier_evidence",)]
    assert {"tier", "tier_score", "region_class", "gene_id", "gene_distance", "gerp", "regbuild", "chromatin_Brain_Mature_Male",
            "molqtl"} <= set(same)
    for a, b in zip(snps, svs):
        assert {c: a[c] for c in same} == {c: b[c] for c in same}
