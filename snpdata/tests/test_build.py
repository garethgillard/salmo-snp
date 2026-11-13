"""The release build on the test fixture: the manifest, the known-loci catalogue, streaming the public VCFs without
genotypes, and parsing the AQUA-FAANG trackhub. Offline, except the release/dev check (SNPSCORE_DEV=1)."""
import gzip
import json
from pathlib import Path

import duckdb
import pytest

from snpdata import build, trackhub
from snpscore import load_weights

DATA = Path(__file__).resolve().parent.parent
FIXTURE = DATA / "tests" / "fixture"


@pytest.fixture(scope="module")
def release(tmp_path_factory):
    return build(DATA / "layers.yaml", FIXTURE, tmp_path_factory.mktemp("release") / "test")


def test_catalogue_text_is_for_users():
    """Caveats and notes are shown to users as they are: no editorial instructions or to-dos."""
    catalog = list(__import__("csv").DictReader(open(DATA / "catalog" / "known_loci.tsv"), delimiter="\t"))
    for r in catalog:
        text = f"{r['caveat']} {r['note']}"
        assert not __import__("re").search(r"(?i)never show|do not show|\btodo\b|\bfixme\b|\btbd\b|\bask G\b|\bG to\b", text), r["id"]


def test_sites_only_drops_genotypes(tmp_path):
    """fetch streams the 504-fish VCF through sites_only: sample names and genotypes never reach the output."""
    from snpdata.build import sites_only
    src = tmp_path / "SYNTHETIC.vcf.gz"
    with gzip.open(src, "wt") as f:  # the last line has no newline
        f.write('##fileformat=VCFv4.2\n##INFO=<ID=AF,Number=A,Type=Float,Description="x">\n'
                '##INFO=<ID=DR2,Number=A,Type=Float,Description="x">\n##FORMAT=<ID=GT,Number=1,Type=String,Description="x">\n'
                "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tfishA\tfishB\n"
                "25\t100\t.\tC\tT\t.\tPASS\tAF=0.25;DR2=0.9\tGT\t0|1\t0|0\n25\t200\trs1\tG\tA\t.\tPASS\tDR2=0.5;AF=0.5\tGT\t1|1\t0|0")
    out = tmp_path / "sites.vcf.gz"
    sites_only(src.as_uri(), out, ["AF"])
    lines = gzip.open(out, "rt").read().splitlines()
    assert [x for x in lines if not x.startswith("##")] == ["#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO",
                                                         "25\t100\t.\tC\tT\t.\tPASS\tAF=0.25", "25\t200\trs1\tG\tA\t.\tPASS\tAF=0.5"]
    assert '##INFO=<ID=AF,Number=A,Type=Float,Description="x">' in lines
    assert not any(w in x for x in lines for w in ("fishA", "fishB", "GT", "DR2", "0|1"))
    sites_only(src.as_uri(), out, ["AC", "AN", "NS", "AF", "MAF"], count_gt=True)  # no usable AF: count the genotypes
    lines = gzip.open(out, "rt").read().splitlines()
    assert [x.split("\t")[7] for x in lines if not x.startswith("#")] == ["AC=1;AN=4;NS=2;AF=0.25;MAF=0.25",
                                                                        "AC=2;AN=4;NS=2;AF=0.5;MAF=0.5"]
    assert sum(x.startswith("##INFO=<ID=AF,") for x in lines) == 1  # the counted AF replaces the file's own
    assert not any(w in x for x in lines for w in ("fishA", "fishB", "0|1", "1|1"))


def test_manifest(release):
    m = json.loads((release / "manifest.json").read_text())
    assert list(m["chrom_sizes"]) == ["1", "9", "21", "25", "26"]
    assert all(len(l["sha256"]) == 64 and l["synthetic"] is False for l in m["layers"])
    assert {"catalog.window", "molqtl.max_bf"} <= set(m["provisional"])
    assert {"active_states", "weights", "presets"} <= set(load_weights()["provisional"])  # the rules live in snpscore
    layers = {l["name"]: l for l in m["layers"]}
    assert "Bertolotti" in layers["public_af"]["population"] and "European farmed" not in json.dumps(m)
    assert layers["molqtl"]["licence"].startswith("redistribution agreed") and len(layers["molqtl"]["urls"]) == 9
    assert m["rsid"]["rows"] > 0 and m["catalog"]["rows"] == 40
    assert m["duckdb_version"] == duckdb.__version__ and list(m["files"]) == ["tracks.yaml"]
    aliases = dict(duckdb.sql(f"SELECT alias, chrom FROM read_parquet('{release / 'alias.parquet'}')").fetchall())
    assert aliases["nc_059466.1"] == aliases["ssa25"] == aliases["chr25"] == aliases["hg993284"] == "25"


@pytest.mark.dev
@pytest.mark.skipif(__import__("os").environ.get("SNPSCORE_DEV") != "1", reason="needs release/dev (SNPSCORE_DEV=1)")
def test_dev_release_push2():
    from snpscore import rsid
    dev = DATA / "release" / "dev"
    con = duckdb.connect()
    af = con.execute(f"SELECT af, aquafaang12_af FROM read_parquet('{dev / 'public_af.parquet'}') WHERE chrom = '25' AND \"end\" = 28996360").fetchone()
    assert af == (0.480159, 0.67)
    # The paper's significant features per tissue (BF < 0.1), counted back from the per-SNP lists
    counts = dict(con.execute(f"""SELECT f, count(*) FROM (SELECT regexp_extract(unnest(string_split(features, '; ')),
                                  '^([A-Za-z]+ [a-z]+) ', 1) AS f FROM read_parquet('{dev / 'molqtl.parquet'}')) GROUP BY 1""").fetchall())
    assert {k: counts[k] for k in ("Liver e", "Liver ca", "Brain e", "Brain ca")} == {"Liver e": 276, "Liver ca": 308,
                                                                                    "Brain e": 711, "Brain ca": 507}
    assert "Gill ca" not in counts
    assert con.execute(f"""SELECT count(*) FROM read_parquet('{dev / 'cm.parquet'}')
                           WHERE male_next < male OR female_next < female""").fetchone()[0] == 0
    assert rsid(dev, "rs863754587")["v2_pos"] == 28656101
    assert (dev / "demo" / "gwas_maturation_SYNTHETIC.tsv").exists()


TRACKDB = """track ATAC_bigWig
superTrack off
shortLabel bigWig

track ATAC_bigWig_AtlanticSalmon_ATAC_Gill_Mature_Male_R2_mLb_clN_bigWig
bigDataUrl ATAC/bigWig/AtlanticSalmon_ATAC_Gill_Mature_Male_R2.mLb.clN.bigWig
type bigWig
parent ATAC_bigWig


track RNA_bigWig_x
bigDataUrl RNA/bigWig/AtlanticSalmon_RNA_Liver_Immature_Female_R3.reverse.bigWig
type bigWig

track ChIP_bigWig_x
bigDataUrl ChIP/bigWig/AtlanticSalmon_ChIP-input_MidGastrulation_R1.bigWig
type bigWig

track ATAC_bam_x
bigDataUrl ATAC/bam/AtlanticSalmon_ATAC_Brain_Immature_Female_R1.mLb.clN.sorted.bam
type bam
"""


CHROMHMM = """chromatin_states/AtlanticSalmon/BodyMap/AtlanticSalmon_Brain_Immature_Female.bb
chromatin_states/AtlanticSalmon/DevMap/AtlanticSalmon_LateBlastulation.bb
"""


def test_parse_trackdb():
    gill, rna, chip = trackhub.parse_trackdb(TRACKDB, trackhub.HUB + "BodyMap/", "BodyMap")
    assert gill["id"] == "ATAC_Gill_Mature_Male_R2" and gill["chromatin_condition"] is None
    assert (gill["tissue"], gill["maturity"], gill["sex"], gill["replicate"]) == ("Gill", "Mature", "Male", "R2")
    assert gill["url"] == trackhub.HUB + "BodyMap/ATAC/bigWig/AtlanticSalmon_ATAC_Gill_Mature_Male_R2.mLb.clN.bigWig"
    assert rna["strand"] == "-" and rna["chromatin_condition"] == "chromatin_Liver_Immature_Female"
    assert (chip["assay"], chip["tissue"], chip["stage"], chip["chromatin_condition"]) == (
        "Input", "Embryo", "MidGastrulation", "chromatin_MidGastrulation")
    brain, blast = trackhub.parse_bigbeds(CHROMHMM, "https://salmobase.org/datafiles/datasets/Aqua-Faang/")
    assert (brain["id"], brain["source"], brain["kind"], brain["chromatin_condition"]) == (
        "ChromHMM_Brain_Immature_Female", "BodyMap", "bigBed", "chromatin_Brain_Immature_Female")
    assert (blast["tissue"], blast["stage"]) == ("Embryo", "LateBlastulation")
    assert blast["url"] == "https://salmobase.org/datafiles/datasets/Aqua-Faang/" + CHROMHMM.split()[1]


def test_ncbi_transcripts(release):
    """RefSeq models on chromosomes 1-29 (accessions renamed through the alias table), exon and CDS parts only."""
    con = duckdb.connect()
    rows = con.execute(f"""SELECT DISTINCT chrom, part FROM read_parquet('{release / "transcripts_ncbi.parquet"}')""").fetchall()
    assert {c for c, _ in rows} == {"1", "9", "21", "25", "26"} and {p for _, p in rows} == {"exon", "CDS"}
    vgll3 = con.execute(f"""SELECT DISTINCT transcript_id, gene_id, strand FROM read_parquet('{release / "transcripts_ncbi.parquet"}')
                            WHERE gene_name = 'vgll3'""").fetchall()
    assert vgll3 == [("XM_014173901.2", "106586514", "+")]


def test_sha256sums(release):
    """SHA256SUMS lists every file of the release, as salmo-snp download fetches and checks them."""
    import hashlib
    sums = dict(reversed(line.split("  ", 1)) for line in (release / "SHA256SUMS").read_text().splitlines())
    files = {p.relative_to(release).as_posix() for p in release.rglob("*") if p.is_file() and p.name != "SHA256SUMS"}
    assert set(sums) == files and "manifest.json" in files and "catalog/known_loci.tsv" in files
    assert sums["manifest.json"] == hashlib.sha256((release / "manifest.json").read_bytes()).hexdigest()


def test_rainbow_trout_release(tmp_path):
    """The second species (rainbow_trout/layers.yaml on tests/fixture/rainbow_trout): its own assembly, chromosomes (Y among
    them), conditions, catalogue and example list; frequencies pooled over the cohorts' site files; build --reuse."""
    out = build(DATA / "rainbow_trout" / "layers.yaml", DATA / "tests" / "fixture" / "rainbow_trout", tmp_path / "trout-test")
    m = json.loads((out / "manifest.json").read_text())
    assert (m["species"]["key"], m["assembly"], list(m["chrom_sizes"])) == ("rainbow_trout", "USDA_OmykA_1.1", ["28", "Y"])
    layers = {l["name"]: l for l in m["layers"]}
    conditions = [c for c in layers["chromatin"]["columns"] if c not in ("summary", "id")]  # 17 genome-wide; those with a peak here
    assert {"Brain_Mature_Male", "Liver_Immature_Female", "LateBlastulation"} <= set(conditions) and not any("Gonad" in c for c in conditions)
    assert m["catalog"]["rows"] == 11 and [d["file"] for d in m["demo"]] == ["demo/known_loci.tsv", "demo/public_50k.vcf"]
    again = build(DATA / "rainbow_trout" / "layers.yaml", DATA / "tests" / "fixture" / "rainbow_trout", tmp_path / "again", reuse=out)
    reused = json.loads((again / "manifest.json").read_text())  # a rebuild that copies every unchanged layer
    assert [(l["name"], l["sha256"], l["rows"]) for l in reused["layers"]] == [(l["name"], l["sha256"], l["rows"]) for l in m["layers"]]
    assert reused["chrom_sizes"] == m["chrom_sizes"] and (again / "motif.meme").read_bytes() == (out / "motif.meme").read_bytes()
    assert m["rsid"]["older"] == "Omyk_1.0" and m["rsid"]["rows"] > 0 and m["flank_keys"]["rows"] > 0
    con = duckdb.connect()
    files = [str(DATA / "tests" / "fixture" / "rainbow_trout" / s) for s in layers["public_af"]["source_file"].split(", ")]
    assert len(files) >= 2
    chrom, pos, ac, an, af, maf = con.execute(f"""SELECT chrom, "end", ac, an, af, maf FROM read_parquet('{out / 'public_af.parquet'}')
                                                  ORDER BY an DESC, "end" LIMIT 1""").fetchone()
    counts = [0, 0]
    for path in files:  # the same site in each cohort's file: AC and AN add up
        for line in gzip.open(path, "rt"):
            f = line.split("\t")
            if f[0] == chrom and not line.startswith("#") and int(f[1]) == pos:
                info = dict(kv.split("=") for kv in f[7].strip().split(";"))
                counts = [counts[0] + int(info["AC"]), counts[1] + int(info["AN"])]
    assert counts == [ac, an] and af == round(ac / an, 6) and maf == round(min(ac, an - ac) / an, 6) and maf >= 0.01
    assert con.execute(f"SELECT count(*) FROM read_parquet('{out / 'public_af.parquet'}') WHERE chrom NOT IN ('28', 'Y')").fetchone()[0] == 0
    aliases = dict(con.execute(f"SELECT alias, chrom FROM read_parquet('{out / 'alias.parquet'}')").fetchall())
    assert (aliases["omy28"], aliases["nc_048592.1"], aliases["chry"]) == ("28", "28", "Y")
    assert con.execute(f"SELECT ohnolog_chrom FROM read_parquet('{out / 'ss4r.parquet'}') WHERE gene_id = 'ENSOMYG00000036625'").fetchone() == ("8",)
