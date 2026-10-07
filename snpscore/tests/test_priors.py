"""P6.5 genomic-prediction priors zip on the fixture: BayesRC classes in input order, GFBLUP/MultiBLUP sets, LDAK
partitions, the 0/1 annotation matrix, README counts, names for SNPs without an id and the PROVISIONAL order knob."""
import csv
import io
import sys
import zipfile

import duckdb
import pytest
import yaml

from snpscore import cli, export
from snpscore.formats import InputError
from test_tools import annotated, release, rows  # noqa: F401 (module fixtures)


def unzip(path):
    with zipfile.ZipFile(path) as z:
        return {name: z.read(name).decode() for name in z.namelist()}


def table(text):
    return list(csv.DictReader(io.StringIO(text), delimiter="\t"))


def test_priors_zip(release, annotated, tmp_path):  # noqa: F811
    out = tmp_path / export.filename("priors", "test", "maturation")
    assert out.name == "snpscore_test_maturation_priors.zip"
    stats = export.export(annotated["snps.vcf"], "priors", out, release, "maturation")
    files, snps = unzip(out), rows(annotated["snps.vcf"])
    # One class per SNP, in input order, named by the list's ids
    classes = [line.split("\t") for line in files["bayesrc_classes.txt"].splitlines()]
    assert len(classes) == len(snps) == stats["rows"] == 2519
    assert [name for name, _ in classes] == [s["id"] for s in snps]
    # annot.tsv: 0/1 columns apart from CHR, BP, SNP and tier_score; per-condition active flags
    annot = table(files["annot.tsv"])
    head = list(annot[0])
    assert head[:3] == ["CHR", "BP", "SNP"] and "active_Brain_Mature_Male" in head and "tier_score" in head
    assert all(r[c] in ("0", "1") for r in annot for c in head if c not in ("CHR", "BP", "SNP", "tier_score"))
    assert [r["SNP"] for r in annot] == [name for name, _ in classes]
    cats = list(stats["categories"])
    assert cats == ["tier1_2", "active", "coding", "constrained", "regulatory", "none"]
    weights = yaml.safe_load((release / "weights.yaml").read_text())
    assert all((r["tier1_2"] == "1") == (int(r["tier_score"]) >= weights["tiers"][1]) for r in annot)  # maturation tiers
    assert all((r["none"] == "1") == (not any(r[c] == "1" for c in cats[:-1])) for r in annot)
    # README counts match the table, the sets and the partitions
    readme = files["README.txt"]
    for c in cats:
        n = sum(r[c] == "1" for r in annot)
        assert n == stats["categories"][c] and f"  {c}: {n:,} SNPs" in readme
        assert len(files[f"sets/{c}.txt"].splitlines()) == n
    assert stats["categories"]["none"] < 2519 and "PROVISIONAL" in readme and "doi:10.1186/s12864-016-2443-6" in readme
    parts = [files[f"ldak_partitions/partition{k}"].splitlines() for k, _, _ in stats["classes"]]
    assert sorted(x for p in parts for x in p) == sorted(name for name, _ in classes)  # disjoint, all SNPs
    for (k, c, n), part in zip(stats["classes"], parts):
        assert len(part) == n and f"  class {k}: {c}, {n:,} SNPs" in readme
        assert {name for name, cls in classes if cls == str(k)} == set(part)
    assert stats["classes"][-1][1] == "none" and "snp_lookup.tsv" not in files and "methods.txt" in files
    assert not any(line.startswith("#") for name, text in files.items() if name != "README.txt" for line in text.splitlines())
    assert [p.name for p in tmp_path.iterdir()] == [out.name]  # no temp files left


def test_priors_names_order_and_categories(release, annotated, tmp_path):  # noqa: F811
    """A connection's view in any order, SNPs without ids (vendor-safe names in snp_lookup.tsv), coding
    consequences when the result has them, and the weights.yaml 'priors: order' knob."""
    con = duckdb.connect()
    src = f"read_parquet('{annotated['snps.vcf']}', file_row_number=true)"
    planted = ("CASE WHEN region_class = 'CDS' THEN CASE WHEN file_row_number % 2 = 0 THEN 'missense_variant' "
               "ELSE 'synonymous_variant' END END AS coding_consequence")
    had = "coding_consequence" in [d[0] for d in con.execute(f"SELECT * FROM {src} LIMIT 0").description]  # P4.5
    con.execute(f"""CREATE VIEW v AS SELECT * REPLACE (CASE WHEN file_row_number % 3 = 0 THEN NULL
                        WHEN file_row_number % 3 = 1 THEN '.' ELSE id END AS id{', ' + planted if had else ''})
                    {'' if had else ', ' + planted} FROM {src} ORDER BY random()""")
    weights = yaml.safe_load((release / "weights.yaml").read_text())
    weights["priors"] = {"order": ["coding", "active", "tier1_2"]}
    stats = export.priors(con, tmp_path / "p.zip", release, "liver", weights=weights)
    files = unzip(tmp_path / "p.zip")
    names = [line.split("\t")[0] for line in files["bayesrc_classes.txt"].splitlines()]
    snps = rows(annotated["snps.vcf"])
    assert names[2] == snps[2]["id"] and names[0] == export.locus_name(snps[0]["chrom"], snps[0]["pos"], {"1", "9"})
    assert len(set(names)) == len(names) == 2519
    lookup = table(files["snp_lookup.tsv"])
    assert len(lookup) == sum(i % 3 != 2 for i in range(2519)) and lookup[0]["SNP"] == names[0]
    assert list(stats["categories"]) == ["coding", "active", "tier1_2", "none"]
    cds = [i for i, s in enumerate(snps) if s["region_class"] == "CDS"]
    assert stats["categories"]["coding"] == sum(i % 2 == 0 for i in cds) < len(cds)  # missense only
    assert [c for _, c, _ in stats["classes"]][:2] == ["coding", "active"]
    assert ("Liver" in files["README.txt"] and con.execute("SELECT count(*) FROM duckdb_tables() WHERE table_name = '_priors'")
            .fetchone()[0] == 0)
    stats = export.priors(con, tmp_path / "q.zip", release, "liver", categories=["constrained"])
    assert list(stats["categories"]) == ["constrained", "none"]
    with pytest.raises(InputError, match="Unknown prior categories"):
        export.priors(con, tmp_path / "r.zip", release, categories=["enhancer"])


def test_priors_cli(release, annotated, tmp_path, monkeypatch, capsys):  # noqa: F811
    monkeypatch.setattr(sys, "argv", ["snpscore", "export", str(annotated["snps.vcf"]), "--release", str(release),
                                      "--format", "priors", "-o", str(tmp_path / "p.zip")])
    cli.main()
    assert "2519 SNPs" in capsys.readouterr().out
    assert zipfile.ZipFile(tmp_path / "p.zip").namelist()[0] == "README.txt"
