"""Breeder tools (P6.3 panel designer, P6.4 exports, P6.6 chip comparison) on jobs scored from salmo-snpscore's fixture,
run inline (SNPPORTAL_WORKERS=0): panel constraints and identical files for the same URL, every export format and scope
with provenance, the demo chip (SYNTHETIC everywhere it contributes) and an uploaded chip."""
import hashlib
import io
import logging
import os
import re
import shutil
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from unittest import skipUnless

import duckdb
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, override_settings
from django.urls import reverse

import snpscore
from snpscore.fasta import Fasta

from . import jobs, tools
from .tests import boosted_links

SNPSCORE = Path(__file__).resolve().parents[2] / "salmo-snpscore"
FIXTURE = SNPSCORE / "tests" / "fixture"
SVG = re.compile(r"<svg .*?</svg>", re.S)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rows(path, where="true"):
    rel = duckdb.sql(f"SELECT * FROM read_parquet('{path}') WHERE {where}")
    return [dict(zip(rel.columns, r)) for r in rel.fetchall()]


def body(response):
    return b"".join(response.streaming_content) if response.streaming else response.content


@skipUnless(FIXTURE.exists(), "needs the salmo-snpscore repo next to this one")
class ToolsTest(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tmp = tempfile.TemporaryDirectory()
        release = Path(cls.tmp.name) / "release"
        if os.environ.get("SNPPORTAL_TEST_RELEASE"):
            shutil.copytree(os.environ["SNPPORTAL_TEST_RELEASE"], release)
        else:
            snpscore.build(SNPSCORE / "layers.yaml", FIXTURE, release)
        cls.override = override_settings(SNPSCORE_RELEASE=str(release), SNPPORTAL_RESULTS_DIR=str(Path(cls.tmp.name) / "results"),
                                          SNPPORTAL_WORKERS=0)
        cls.override.enable()
        logging.disable(logging.WARNING)
        cls.release = release
        cls.url, cls.key = cls.job()
        cls.d = jobs.folder(cls.key)

    @classmethod
    def tearDownClass(cls):
        logging.disable(logging.NOTSET)
        cls.override.disable()
        cls.tmp.cleanup()
        super().tearDownClass()

    @classmethod
    def job(cls):
        with open(FIXTURE / "snps.vcf", "rb") as f:
            url = cls.client_class().post(reverse("snpportal:upload"), {"snps": f}).url.split("?")[0]
        return url, url.split("/")[-2]

    def panels(self, d=None):
        return sorted((d or self.d).joinpath("panels").glob("*.parquet"))

    def test_panel_tab_meets_the_constraints_and_gives_the_same_file(self):
        url = self.url + "?tab=panel&trait=maturation&design=1&n=60&spacing_kb=10&per_gene=2&per_element=1&exclude=blacklist"
        page = self.client.get(url)
        html = page.content.decode()
        self.assertContains(page, "Panel designer")
        self.assertEqual(page["Cache-Control"], "no-store, private")
        self.assertTrue(all(ET.fromstring(s) is not None for s in SVG.findall(html)))  # every figure is valid XML
        for name in ("Panel markers along the genome", "Tier mix of the panel", "Why each marker was chosen",
                     "Spacing between neighbouring markers", "Largest gaps in the panel"):
            self.assertContains(page, name)
        self.assertEqual(boosted_links(html), {"?"})  # boosted links stay on this page
        h = re.search(r'scope=panel-([0-9a-f]{16})', html).group(1)
        path = self.d / "panels" / f"{h}.parquet"
        picked = rows(path)
        info = jobs.read_json(path.with_suffix(".json"))
        self.assertEqual(len(picked), info["summary"]["n_selected"])
        self.assertTrue(len(picked) == 60 or info["summary"]["binding"])
        self.assertTrue(all(r["selection_reason"] in tools.REASONS for r in picked))
        by_chrom = {}
        for r in picked:
            by_chrom.setdefault(r["chrom"], []).append(r["pos"])
        self.assertTrue(all(b - a >= 10_000 for p in by_chrom.values() for a, b in zip(sorted(p), sorted(p)[1:])))
        for column, cap in (("gene_id", 2), ("chromatin_id", 1)):
            counts = {}
            for r in picked:
                if r[column]:
                    counts[r[column]] = counts.get(r[column], 0) + 1
            self.assertLessEqual(max(counts.values()), cap, column)
        self.assertFalse(any(r["blacklist"] for r in picked))
        self.assertEqual(oct(path.stat().st_mode & 0o777), "0o600")
        first = sha(path)
        self.client.get(url)  # cached: the same file
        self.assertEqual(sha(path), first)
        path.unlink()
        self.client.get(url)  # designed again: identical bytes
        self.assertEqual(sha(path), first)
        report = self.client.get(reverse("snpportal:report", args=[self.key]), {"trait": "maturation", "panel": h}).content.decode()
        self.assertIn(f"Panel <span class=\"sp-mono\">{h}</span>", report)  # the printable report's panel summary
        self.assertIn(f"<b>{info['summary']['n_selected']:,}</b><span>markers", report)

    def test_panel_parameters(self):
        con = jobs.connect([self.d])
        must = con.execute(f"SELECT id FROM read_parquet('{self.d / 'result.parquet'}') WHERE id IS NOT NULL AND id <> '.' "
                           "ORDER BY pos DESC LIMIT 1").fetchone()[0]
        page = self.client.get(self.url, {"tab": "panel", "design": "1", "n": "5", "spacing_kb": "50", "must": f"{must}, nope_1"})
        self.assertContains(page, "Must-include ids not in this list: nope_1")
        h = re.search(r'scope=panel-([0-9a-f]{16})', page.content.decode()).group(1)
        picked = rows(self.d / "panels" / f"{h}.parquet")
        self.assertIn((must, "must_include"), {(r["id"], r["selection_reason"]) for r in picked})
        self.assertLessEqual(len(picked), 5)
        big = self.client.get(self.url, {"tab": "panel", "design": "1", "n": "5000", "maf": "0.4"})
        self.assertContains(big, "the binding constraint is")
        odd = self.client.get(self.url, {"tab": "panel", "design": "1", "n": "abc", "maf": "9", "exclude": "not_a_column"})
        self.assertEqual(odd.status_code, 200)  # invalid values fall back to the defaults; unknown columns are ignored
        # A list with positions only (no id, ref or alt columns)
        lines = "".join(f"{c}\t{p}\n" for c, p in con.execute(f"SELECT chrom, pos FROM read_parquet('{self.d / 'result.parquet'}') "
                                                              "WHERE coalesce(assay_status, '') <> 'fail' LIMIT 30").fetchall())
        bare = self.client.post(reverse("snpportal:upload"), {"snps": SimpleUploadedFile("SYNTHETIC_bare.tsv", ("chrom\tpos\n" + lines).encode())})
        url = bare.url.split("?")[0]
        self.assertContains(self.client.get(url + "?tab=panel"), "Selected SNPs")
        self.assertEqual(self.client.get(reverse("snpportal:download", args=[url.split("/")[-2]]), {"scope": "all", "format": "kasp"}).status_code, 200)

    def test_cm_spacing_and_vendor_checks(self):  # R5 and the Push 2 vendor checks
        page = self.client.get(self.url, {"tab": "panel", "design": "1", "n": "20", "spacing_kb": "0", "spacing_cm": "0.5",
                                          "cm_map": "female"})
        self.assertContains(page, 'name="spacing_cm" value="0.5"')
        self.assertContains(page, '<option value="female" selected>')
        self.assertContains(page, "median spacing (cM)")
        self.assertContains(page, "Vendor checks: Infinium I bin A (A/T)")
        self.assertContains(page, "error 111")  # a 20-SNP panel is far below the Infinium bin minimums
        h = re.search(r'scope=panel-([0-9a-f]{16})', page.content.decode()).group(1)
        info = jobs.read_json(self.d / "panels" / f"{h}.json")
        self.assertEqual((info["params"]["min_spacing_cm"], info["params"]["cm_map"]), (0.5, "female"))
        by_chrom = {}
        for r in rows(self.d / "panels" / f"{h}.parquet", "cm_female IS NOT NULL"):
            by_chrom.setdefault(r["chrom"], []).append((r["pos"], r["cm_female"]))
        self.assertTrue(by_chrom)
        for picked in by_chrom.values():
            cms = [cm for _, cm in sorted(picked)]
            self.assertTrue(all(b - a >= 0.5 - 1e-9 for a, b in zip(cms, cms[1:])), cms)
        plain = self.client.get(self.url, {"tab": "panel", "design": "1", "n": "20", "spacing_cm": ""})
        h2 = re.search(r'scope=panel-([0-9a-f]{16})', plain.content.decode()).group(1)
        self.assertNotIn("min_spacing_cm", jobs.read_json(self.d / "panels" / f"{h2}.json")["params"])  # bp only: hash as before
        export = self.client.get(self.url, {"tab": "export", "scope": f"panel-{h}"})
        self.assertContains(export, "min spacing 0 bp and 0.5 cM")
        self.assertContains(export, "Vendor checks: Infinium I bin A (A/T)")
        self.assertContains(export, "Ssa25p28996360")  # locus names and the lookup sidecar explained
        self.assertContains(export, "lookup.tsv")
        report = self.client.get(reverse("snpportal:report", args=[self.key]), {"panel": h})
        self.assertContains(report, "error 111")
        con = jobs.connect([self.d])  # lists without alleles: the assay flank's (public) alleles, as in vendor files
        con.execute(f"CREATE VIEW x AS SELECT chrom, pos, assay_flank FROM read_parquet('{self.d / 'result.parquet'}') "
                    "WHERE assay_flank LIKE '%[A/T]%' LIMIT 3")
        self.assertEqual(tools.vendor_checks(con, "x")["infinium_bins"]["A"], 3)

    def test_panel_figure_downloads(self):
        html = self.client.get(self.url + "?tab=panel").content.decode()
        svg_url = re.search(r'href="([^"]*/tools/panel-coverage\.svg[^"]*)"', html).group(1).replace("&amp;", "&")
        svg = self.client.get(svg_url)
        self.assertEqual(svg["Content-Type"], "image/svg+xml")
        root = ET.fromstring(svg.content)
        self.assertIn("PROVISIONAL", root.find("{http://www.w3.org/2000/svg}desc").text)
        tsv = self.client.get(svg_url + "&format=tsv").content.decode()
        self.assertTrue(tsv.startswith("# "))
        self.assertIn("panel_rank\tchrom\tpos", tsv)
        self.assertEqual(self.client.get(svg_url.split("?")[0] + "?panel=0123456789abcdef").status_code, 404)
        self.assertEqual(self.client.get(reverse("snpportal:tool_figure", args=[self.key, "chip-coverage"])).status_code, 404)

    def test_exports(self):
        download = reverse("snpportal:download", args=[self.key])
        for fmt in ("tsv", "bed", "illumina", "axiom", "kasp"):
            response = self.client.get(download, {"scope": "all", "format": fmt, "trait": "maturation"})
            self.assertEqual(response.status_code, 200, fmt)
            self.assertIn("maturation", response["Content-Disposition"])
            text = body(response).decode()
            if fmt in tools.VENDORS and not text.startswith("#"):  # R2: vendor files hold no comment lines; a sidecar has them
                side = self.client.get(download, {"scope": "all", "format": f"{fmt}.provenance", "trait": "maturation"})
                self.assertIn(".provenance.txt", side["Content-Disposition"])
                text = body(side).decode()
            header = [line for line in text.splitlines() if line.startswith("#")]
            self.assertTrue(text.startswith("# ") and "PROVISIONAL" in "\n".join(header), fmt)
            self.assertIn(jobs.read(self.key)["manifest_sha256"], "\n".join(header))
            if fmt in tools.VENDORS:
                self.assertIn("layout to confirm", "\n".join(header))
        self.assertFalse([p.name for p in self.d.iterdir() if p.name.startswith(".export-")])  # no export or sidecar left behind
        illumina = [line.split(",") for line in body(self.client.get(download, {"scope": "all", "format": "illumina"})).decode()
                    .splitlines() if not line.startswith("#")]
        head, first = illumina[0], dict(zip(illumina[0], illumina[1]))
        self.assertEqual(head[:3], ["Locus_Name", "Target_Type", "Sequence"])
        left, right = first["Sequence"].split("[")[0], first["Sequence"].split("]")[1]
        genome = Fasta(FIXTURE / "Salmo_salar.Ssal_v3.1.dna_sm.toplevel.fa.gz")
        pos = int(first["Coordinate"])
        for got, want in ((left, genome.fetch(first["Chromosome"], pos - 61, pos - 1)), (right, genome.fetch(first["Chromosome"], pos, pos + 60))):
            self.assertEqual(len(got), 60)
            self.assertTrue(all(g == w for g, w in zip(got, want.upper()) if g in "ACGT"))  # neighbours are IUPAC codes
        plain = body(self.client.get(download, {"scope": "all", "format": "tsv", "plain": "1"})).decode()
        self.assertTrue(plain.startswith("chrom\tpos"))
        # The filtered table: the same filters as the Table tab
        con = jobs.connect([self.d])
        n = con.execute(f"SELECT count(*) FROM read_parquet('{self.d / 'tiers.parquet'}') WHERE tier__all <= 2").fetchone()[0]
        filtered = body(self.client.get(download, {"scope": "filtered", "format": "tsv", "tier": "1-2", "plain": "1"})).decode()
        self.assertEqual(len(filtered.splitlines()) - 1, n)
        page = self.client.get(self.url, {"tab": "export", "tier": "1-2"})
        self.assertContains(page, f"The filtered table: Tier 1–2 <span class=\"sp-muted\">({n:,} SNPs)")
        self.assertEqual(boosted_links(page.content.decode()), {"?"})
        # A panel, Parquet with its provenance, and the bundle
        html = self.client.get(self.url + "?tab=panel").content.decode()
        h = re.search(r'scope=panel-([0-9a-f]{16})', html).group(1)
        n_panel = jobs.read_json(self.d / "panels" / f"{h}.json")["summary"]["n_selected"]
        panel_tsv = body(self.client.get(download, {"scope": f"panel-{h}", "format": "tsv", "plain": "1"})).decode()
        self.assertEqual(len(panel_tsv.splitlines()) - 1, n_panel)
        self.assertIn("selection_reason", panel_tsv.splitlines()[0])
        parquet = Path(self.tmp.name) / "export.parquet"
        parquet.write_bytes(body(self.client.get(download, {"scope": f"panel-{h}", "format": "parquet"})))
        meta = duckdb.sql(f"SELECT value FROM parquet_kv_metadata('{parquet}') WHERE key = 'provenance'").fetchone()[0]
        self.assertIn(b"panel " + h.encode(), meta)
        z = zipfile.ZipFile(io.BytesIO(body(self.client.get(download, {"scope": f"panel-{h}", "format": "bundle"}))))
        names = set(z.namelist())
        self.assertTrue({"manifest.json", "weights.yaml", "methods.txt", "provenance.txt", "README.txt",
                         "figures/panel-coverage.svg"} <= names, names)
        self.assertTrue(any(name.endswith("_illumina.csv") for name in names))
        self.assertEqual(self.client.get(download, {"scope": "panel-0123456789abcdef", "format": "tsv"}).status_code, 404)
        with override_settings(SNPPORTAL_MAX_VENDOR_SNPS=10):
            self.assertEqual(self.client.get(download, {"scope": "all", "format": "kasp"}).status_code, 400)
        self.assertFalse(list(self.d.glob(".export-*")))  # temp files are gone

    def test_demo_chip_and_uploaded_chip(self):
        url, key = self.job()  # a job of its own: the chip changes its exports
        d = jobs.folder(key)
        chip = reverse("snpportal:chip", args=[key])
        self.assertEqual(self.client.get(chip).status_code, 405)
        response = self.client.post(chip, {"demo": "1", "trait": "all"})
        self.assertRedirects(response, f"{url}?tab=panel&trait=all#chip", fetch_redirect_response=False)
        self.assertTrue((d / "chip.parquet").exists())
        page = self.client.get(url + "?tab=panel")
        self.assertContains(page, "sp-badge-syn")
        self.assertContains(page, "novel functional")
        self.assertContains(page, "Chip gaps over 1 Mb")
        s = jobs.read_json(d / "chip.json")["results"]["all"]["summary"]
        self.assertEqual(s["shared"] + s["novel_functional"] + s["other"], s["total"])
        self.assertGreater(s["shared"], 0)
        self.assertGreaterEqual(s["gaps"], 1)  # the planted gap
        svg = re.search(r'<svg .*?</svg>', page.content.decode().split('id="fig-chip-coverage"')[1], re.S).group(0)
        self.assertIn(">SYNTHETIC</text>", svg)  # the watermark
        overview = self.client.get(url).content.decode()
        self.assertIn("the demo chip on the Panel tab", overview)  # every tab says SYNTHETIC
        self.assertIn("demo chip markers", overview)  # chip ticks on the ideogram
        # The Table tab's 'not near the chip' filter keeps fewer SNPs
        table = self.client.get(url, {"tab": "table", "hide_near_chip": "1"}).content.decode()
        self.assertIn("filtered from", table)
        self.assertIn('name="hide_near_chip"', self.client.get(url, {"tab": "table"}).content.decode())
        # The 'not near the chip' exclusion leaves fewer candidates
        base = self.client.get(url, {"tab": "panel", "design": "1"}).content.decode()
        near = self.client.get(url, {"tab": "panel", "design": "1", "exclude": "near_chip"}).content.decode()
        candidates = [int(re.search(r"<b>([\d,]+)</b><span>candidates", x).group(1).replace(",", "")) for x in (base, near)]
        self.assertLess(candidates[1], candidates[0])
        # Exports of the list gain the chip columns and the SYNTHETIC line
        text = body(self.client.get(reverse("snpportal:download", args=[key]), {"scope": "all", "format": "tsv"})).decode()
        self.assertIn("SYNTHETIC", "\n".join(line for line in text.splitlines() if line.startswith("#")))
        self.assertIn("novel_functional", next(line for line in text.splitlines() if not line.startswith("#")))
        self.client.post(chip, {"remove": "1"})
        self.assertFalse((d / "chip.parquet").exists())
        self.assertNotContains(self.client.get(url), "the demo chip on the Panel tab")
        # An uploaded chip (a SYNTHETIC PLINK .bim from fixture positions), a wrong type and an unreadable file
        positions = duckdb.sql(f"SELECT chrom, pos FROM read_parquet('{d / 'result.parquet'}') ORDER BY chrom, pos LIMIT 40").fetchall()
        bim = "".join(f"{c}\tm{i}\t0\t{p}\tA\tG\n" for i, (c, p) in enumerate(positions))
        self.client.post(chip, {"chip": SimpleUploadedFile("chip_SYNTHETIC.bim", bim.encode())})
        info = jobs.read_json(d / "chip.json")
        self.assertEqual(info["kept"], 40)
        self.assertTrue(info["synthetic"])  # SYNTHETIC in its name
        self.assertContains(self.client.get(url + "?tab=panel"), "Uploaded chip: 40 markers")
        wrong = self.client.post(chip, {"chip": SimpleUploadedFile("chip.pdf", b"%PDF")})
        self.assertIn("chip_error=type", wrong.url)
        junk = self.client.post(chip, {"chip": SimpleUploadedFile("chip.tsv", b"hello\tworld\n1\t2\n")})
        self.assertIn("chip_error=", junk.url)
        self.assertContains(self.client.get(junk.url), "sp-status-fail")
        self.assertFalse([p for p in d.iterdir() if p.name.startswith(".chip")])  # no upload left behind
        self.assertFalse([p for p in jobs.results_dir().iterdir() if p.name.startswith(".upload-")])
