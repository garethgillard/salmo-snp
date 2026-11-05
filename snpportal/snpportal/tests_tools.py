"""Breeder tools (P6.3 panel designer, P6.4 exports, P6.6 chip comparison) on jobs scored from snpscore's fixture,
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
from django.test import Client, SimpleTestCase, override_settings
from django.urls import reverse

import snpdata
import snpscore
from snpscore.fasta import Fasta

from . import jobs, panel, tools
from .tests import boosted_links

SNPSCORE = Path(__file__).resolve().parents[2] / "snpscore"
DATA = SNPSCORE.parent / "snpdata"  # layers.yaml, the fixture, prep/, the catalogue, data/ and release/
FIXTURE = DATA / "tests" / "fixture"
SVG = re.compile(r"<svg .*?</svg>", re.S)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rows(path, where="true"):
    rel = duckdb.sql(f"SELECT * FROM read_parquet('{path}') WHERE {where}")
    return [dict(zip(rel.columns, r)) for r in rel.fetchall()]


def body(response):
    return b"".join(response.streaming_content) if response.streaming else response.content


@skipUnless(FIXTURE.exists(), "needs snpscore/ next to snpportal/")
class ToolsTest(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tmp = tempfile.TemporaryDirectory()
        release = Path(cls.tmp.name) / "release"
        if os.environ.get("SNPPORTAL_TEST_RELEASE"):
            shutil.copytree(os.environ["SNPPORTAL_TEST_RELEASE"], release)
        else:
            snpdata.build(DATA / "layers.yaml", FIXTURE, release)
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
        self.assertContains(page, "Panel markers along the genome")  # one figure
        self.assertEqual(html.count("<figure "), 1)
        self.assertContains(page, '<details class="sp-more"><summary>Advanced settings</summary>')  # closed: all at their defaults
        changed = self.client.get(url.replace("per_gene=2", "per_gene=3"))
        self.assertContains(changed, '<details class="sp-more" open><summary>Advanced settings (1 active)</summary>')
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
        self.assertIn(f"Panel: {tools.panel_name(info)}", report)  # the printable report's panel summary
        self.assertIn(tools.panel_line(info["summary"]), report)
        heading = html[html.index('id="panel-h"'):html.index("</h2>", html.index('id="panel-h"'))]
        self.assertNotIn(h, heading)  # named by its markers, never by a hash

    def test_design_panel(self):
        table = self.client.get(self.url, {"tab": "table", "tier": "1-2"}).content.decode()  # the Table keeps the selection
        n = int(re.search(r"Add to panel \(([\d,]+)\)", table).group(1).replace(",", ""))
        added = self.client.post(reverse("snpportal:panel_add", args=[self.key]))  # the cart: the whole selection
        self.assertIn(f"added={n}", added.url)
        cookie = added.cookies[panel.COOKIE]
        self.assertTrue(cookie["httponly"])
        page = self.client.get(reverse("snpportal:design_panel")).content.decode()
        self.assertIn(f"<strong>{n:,}</strong> SNPs in the panel", page)
        self.assertIn("Tier 1, 2", page)  # the source's selection
        self.assertNotIn(cookie.value, page)  # the panel is named by its cookie only, never in a page or URL
        self.assertIn("Your panel is empty", Client().get(reverse("snpportal:design_panel")).content.decode())  # another browser
        self.assertEqual(Client().get(reverse("snpportal:panel_download"), {"format": "tsv"}).status_code, 404)
        tsv = body(self.client.get(reverse("snpportal:panel_download"), {"format": "tsv", "plain": "1"})).decode()
        self.assertEqual(len([x for x in tsv.splitlines() if x and not x.startswith("#")]) - 1, n)
        self.assertNotIn("panel_source", tsv.splitlines()[0])  # the panel's own columns stay out
        key = re.search(r'name="drop" value="([^"]+)"', page).group(1)  # drop one SNP by hand, then put it back
        self.client.post(reverse("snpportal:panel_change"), {"drop": key})
        self.assertIn(f"{n - 1:,} kept, 1 dropped", self.client.get(reverse("snpportal:design_panel")).content.decode())
        tsv = body(self.client.get(reverse("snpportal:panel_download"), {"format": "tsv", "plain": "1"})).decode()
        self.assertEqual(len([x for x in tsv.splitlines() if x and not x.startswith("#")]) - 1, n - 1)
        self.client.post(reverse("snpportal:panel_change"), {"keep": key})
        self.assertIn(f"{n:,} kept</span>", self.client.get(reverse("snpportal:design_panel")).content.decode())
        self.client.post(reverse("snpportal:panel_add", args=[self.key]))  # the same selection again: no SNP twice
        self.assertIn(f"<strong>{n:,}</strong> SNPs in the panel; {n:,} in more than one source",
                      self.client.get(reverse("snpportal:design_panel")).content.decode())
        d = jobs.results_dir() / f"panel-{cookie.value}"
        os.utime(d / "created", (1, 1))  # 24 hours on: gone for its browser too, and cleanup removes it
        self.assertIn("Your panel is empty", self.client.get(reverse("snpportal:design_panel")).content.decode())
        jobs.cleanup()
        self.assertFalse(d.exists())
        self.client.get(self.url, {"tab": "table"})  # the whole list again, for the other tests

    def test_chips_side_by_side_and_upgrade(self):  # I11, with SYNTHETIC chips
        self.client.get(self.url, {"tab": "table"})  # the whole list as the selection
        self.client.post(reverse("snpportal:panel_add", args=[self.key]))
        change = reverse("snpportal:panel_change")
        a = SimpleUploadedFile("a_SYNTHETIC.tsv", b"chrom\tpos\n9\t23007708\n9\t23008875\n9\t23200000\n1\t110987765\n")
        self.client.post(change, {"chip": a})
        b = SimpleUploadedFile("b_SYNTHETIC.tsv", b"chrom\tpos\n9\t23007708\n9\t23500000\n")
        self.client.post(change, {"chip": b, "extra": "1", "chip_name": "Vendor B"})
        page = self.client.get(reverse("snpportal:design_panel")).content.decode()
        self.assertIn("Other chips: <strong>Vendor B</strong> (2 markers)", page)
        self.assertIn("Near Vendor B", page)
        self.assertIn('<th scope="row">This panel</th>', page)
        self.assertIn("Compared with your chip", page)  # the panel's chip is still the first one
        page = self.client.get(reverse("snpportal:design_panel"), {"upgrade": "1", "n": "10"}).content.decode()
        self.assertIn("<b>4</b><span>markers kept</span>", page)  # no population of yours: every marker kept
        self.assertIn("dropped (no QC data)", page)
        tsv = self.client.get(reverse("snpportal:panel_upgrade"), {"n": "10"}).content.decode()
        self.assertIn("# no population of yours", tsv)
        self.assertIn("# SYNTHETIC", tsv)
        table = [line.split("\t") for line in tsv.splitlines() if not line.startswith("#")]
        self.assertEqual(table[0], ["chrom", "pos", "id", "action", "reason", "tier"])
        out = {}
        for chrom, pos, _, action, _, _ in table[1:]:
            out.setdefault(chrom, []).append((int(pos), action))
        self.assertEqual(sum(x == "keep" for ps in out.values() for _, x in ps), 4)
        self.assertTrue(5 <= sum(len(ps) for ps in out.values()) <= 10)  # added up to 10
        spacing = panel.snp_panel.settings(jobs.weights())["min_spacing"]
        for ps in out.values():  # every SNP added is far enough from the others and from the markers kept
            ps.sort()
            self.assertTrue(all(q - p >= spacing for (p, x), (q, y) in zip(ps, ps[1:]) if "add" in (x, y)))
        self.client.post(change, {"chip_extra_remove": "vendor_b"})
        self.assertNotIn("Other chips", self.client.get(reverse("snpportal:design_panel")).content.decode())
        self.assertEqual(Client().get(reverse("snpportal:panel_upgrade")).status_code, 404)  # another browser: no panel

    def test_panel_parameters(self):
        self.client.get(self.url, {"tab": "table"})  # the Panel designs from the Table selection: the whole list
        con = jobs.connect([self.d])
        must = con.execute(f"SELECT id FROM read_parquet('{self.d / 'result.parquet'}') WHERE id IS NOT NULL AND id <> '.' "
                           "ORDER BY pos DESC LIMIT 1").fetchone()[0]
        posted = self.client.post(reverse("snpportal:panel_design", args=[self.key]),
                                  {"design": "1", "n": "5", "spacing_kb": "50", "must": f"{must}, nope_1"})
        self.assertNotIn(must, posted.url)  # must-include ids are the user's SNP names: never in a URL
        page = self.client.get(posted.url)
        self.assertContains(page, "Must-include ids not in this list: nope_1")
        self.assertContains(page, f'name="must" value="{must}')  # the form shows them again, from the saved panel
        h = re.search(r'scope=panel-([0-9a-f]{16})', page.content.decode()).group(1)
        self.assertIn(f"panel={h}", posted.url)
        other = self.client.get(posted.url.replace("trait=all", "trait=maturation"))  # another trait: the same parameters
        self.assertContains(other, f'name="must" value="{must}')
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
        self.assertContains(self.client.get(url + "?tab=panel"), 'id="selected-h"')
        self.assertEqual(self.client.get(reverse("snpportal:download", args=[url.split("/")[-2]]), {"scope": "all", "format": "kasp"}).status_code, 200)

    def test_chip_placed_by_flank(self):  # I18: a SYNTHETIC manifest on 'another assembly', placed by its flank sequences
        self.client.get(self.url, {"tab": "table"})
        self.client.post(reverse("snpportal:panel_add", args=[self.key]))
        genome = Fasta(FIXTURE / "Salmo_salar.Ssal_v3.1.dna_sm.toplevel.fa.gz")
        sites = duckdb.sql(f"SELECT chrom, pos FROM read_parquet('{self.release / 'flank_keys.parquet'}') ORDER BY pos LIMIT 3").fetchall()
        lines = ["Name\tChr\tMapInfo\tSourceSeq"] + [
            f"m{i}\t1\t{100 + i}\t{genome.fetch(c, p - 41, p - 1)}[{genome.fetch(c, p - 1, p).upper()}/N]{genome.fetch(c, p, p + 40)}"
            for i, (c, p) in enumerate(sites)] + ["lost\t1\t999\t" + "ACGT" * 10 + "[A/G]" + "TTGA" * 10]
        name, chrom, pos, seq = lines[3].split("\t")  # m2's outermost base differs from the genome: not placed
        lines[3] = "\t".join([name, chrom, pos, ("A" if seq[0].upper() != "A" else "C") + seq[1:]])
        chip = SimpleUploadedFile("v2_chip_SYNTHETIC.tsv", ("\n".join(lines) + "\n").encode())
        self.client.post(reverse("snpportal:panel_change"), {"chip": chip, "by_flank": "1"})
        page = self.client.get(reverse("snpportal:design_panel")).content.decode()
        self.assertIn("Placed by flank sequence: 2 markers, each checked against the genome.", page)
        self.assertIn("Not placed: 1 not at a known variant site; 1 whose full flank differs from the genome", page)
        self.assertIn('name="by_flank"', page)
        plain = SimpleUploadedFile("plain_SYNTHETIC.tsv", b"chrom\tpos\n9\t23007708\n")
        response = self.client.post(reverse("snpportal:panel_change"), {"chip": plain, "by_flank": "1"})
        self.assertIn("chip_error=flank", response.url)  # no flank column

    def test_panel_purpose(self):  # I8: a purpose sets the designer's defaults; the panel, report and exports name it
        self.client.get(self.url, {"tab": "table"})
        page = self.client.get(self.url, {"tab": "panel", "purpose": "parentage"}).content.decode()
        self.assertIn("<strong title=", page)
        self.assertIn('name="purpose" value="parentage"', page)  # kept when the form is sent
        self.assertIn('list="sp-sizes"', page)  # the target sizes as suggestions
        h = re.search(r'scope=panel-([0-9a-f]{16})', page).group(1)
        info = jobs.read_json(self.d / "panels" / f"{h}.json")
        self.assertEqual((info["params"]["purpose"], info["params"]["min_spacing"], info["params"]["min_maf"]), ("parentage", 2_000_000, 0.3))
        self.assertIn("Parentage and traceability", page[page.index('id="panel-h"'):page.index("</h2>", page.index('id="panel-h"'))])
        picked = rows(self.d / "panels" / f"{h}.parquet")
        self.assertTrue(all(r["assay_status"] == "pass" for r in picked))  # the preset asks for assay pass only
        posted = self.client.post(reverse("snpportal:panel_design", args=[self.key]), {"design": "1", "purpose": "parentage", "n": "3"})
        self.assertEqual(jobs.read_json(self.d / "panels" / f"{re.search(r'panel=([0-9a-f]{16})', posted.url).group(1)}.json")
                         ["params"]["min_spacing"], 2_000_000)  # the form's blank fields keep the preset's numbers
        report = self.client.get(reverse("snpportal:report", args=[self.key]), {"trait": "all", "panel": h}).content.decode()
        self.assertIn("Designed with: purpose Parentage and traceability", report)
        tsv = body(self.client.get(reverse("snpportal:download", args=[self.key]), {"scope": f"panel-{h}", "format": "tsv"})).decode()
        self.assertIn("(purpose Parentage and traceability;", tsv)
        self.assertNotIn('name="purpose"', self.client.get(self.url, {"tab": "panel", "purpose": "nope"}).content.decode())

    def test_export_lists_recent_panels(self):
        """The Export tab lists the newest panel of each parameter set, newest first, at most 3, plus one asked for."""
        url, key = self.job()
        made = []
        for n in ("5", "6", "7", "8", "5"):  # the last one is cached: the first panel's file
            html = self.client.get(url, {"tab": "panel", "design": "1", "n": n}).content.decode()
            made.append(re.search(r'scope=panel-([0-9a-f]{16})', html).group(1))
        self.assertEqual(made[0], made[4])
        radios = re.compile(r'type="radio" name="scope" value="panel-([0-9a-f]{16})"')
        self.assertEqual(radios.findall(self.client.get(url, {"tab": "export"}).content.decode()), made[3:0:-1])
        old = self.client.get(url, {"tab": "export", "scope": f"panel-{made[0]}"}).content.decode()
        self.assertEqual(radios.findall(old), made[3:0:-1] + [made[0]])  # the Panel tab's export link still finds it
        self.assertIn(f'value="panel-{made[0]}" checked', old)

    def test_cm_spacing_and_vendor_checks(self):  # R5 and the Push 2 vendor checks
        page = self.client.get(self.url, {"tab": "panel", "design": "1", "n": "20", "spacing_kb": "0", "spacing_cm": "0.5",
                                          "cm_map": "female"})
        self.assertContains(page, 'name="spacing_cm" value="0.5"')
        self.assertContains(page, '<option value="female" selected>')
        self.assertRegex(page.content.decode(), r"median [\d.]+ cM")
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
        self.assertContains(export, 'checked> ' + tools.panel_name(info))  # the panel is the chosen scope
        self.assertContains(export, "Infinium bins: A/T")  # each vendor file with its own checks
        self.assertContains(export, "below Illumina")  # a 20-SNP panel is far below the Infinium bin minimums
        self.assertContains(export, "Ssa25p28996360")  # locus names and the lookup sidecar explained
        self.assertContains(export, "format=illumina.lookup")
        self.assertRegex(export.content.decode(), r'scope=all&amp;format=priors"[^>]*>Genomic-prediction priors, all [\d,]+ SNPs')
        report = self.client.get(reverse("snpportal:report", args=[self.key]), {"panel": h})
        self.assertContains(report, tools.panel_name(info))
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
            self.assertIn("_all", response["Content-Disposition"])  # a trait of older links is ignored: all conditions
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
        self.client.get(self.url, {"tab": "table", "tier": "1-2"})  # the Table keeps its selection
        page = self.client.get(self.url, {"tab": "export"})
        self.assertContains(page, f'value="filtered" checked> Table selection ({n:,})')  # the default when the Table has filters
        self.assertContains(page, f"of {n:,} included")
        self.assertEqual(boosted_links(page.content.decode()), {"?"})
        self.client.get(self.url, {"tab": "table"})  # the whole list again
        # A panel, Parquet with its provenance, and the bundle
        html = self.client.get(self.url + "?tab=panel").content.decode()
        h = re.search(r'scope=panel-([0-9a-f]{16})', html).group(1)
        n_panel = jobs.read_json(self.d / "panels" / f"{h}.json")["summary"]["n_selected"]
        panel_tsv = body(self.client.get(download, {"scope": f"panel-{h}", "format": "tsv", "plain": "1"})).decode()
        self.assertEqual(len(panel_tsv.splitlines()) - 1, n_panel)
        self.assertIn("selection_reason", panel_tsv.splitlines()[0])
        parquet = Path(self.tmp.name) / "export.parquet"
        parquet.write_bytes(body(self.client.get(download, {"scope": f"panel-{h}", "format": "parquet"})))
        meta = duckdb.execute(f"SELECT value FROM parquet_kv_metadata('{parquet}') WHERE key = 'provenance'").fetchall()[0][0]
        self.assertIn(b"panel " + h.encode(), meta)
        z = zipfile.ZipFile(io.BytesIO(body(self.client.get(download, {"scope": f"panel-{h}", "format": "bundle"}))))
        names = set(z.namelist())
        self.assertTrue({"manifest.json", "weights.yaml", "methods.txt", "provenance.txt", "README.txt",
                         "figures/panel-coverage.svg", "vendor_checks.txt"} <= names, names)  # the Export tab's checks travel too
        self.assertIn("kasp: ", z.read("vendor_checks.txt").decode())
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
        self.assertContains(page, "Your selection compared with the demo chip")
        self.assertContains(page, "novel functional")
        self.assertContains(page, "Largest chip gaps")
        s = jobs.read_json(d / "chip.json")["results"]["all"]["summary"]
        self.assertEqual(s["shared"] + s["novel_functional"] + s["other"], s["total"])
        self.assertGreater(s["shared"], 0)
        self.assertGreaterEqual(s["gaps"], 1)  # the planted gap
        svg = re.search(r'<svg .*?</svg>', page.content.decode().split('id="fig-chip-coverage"')[1], re.S).group(0)
        self.assertIn("SYNTHETIC test data", svg)  # said in the figure's description (downloads keep it)
        overview = self.client.get(url).content.decode()
        self.assertNotIn("SYNTHETIC data", overview)  # only the chip is synthetic: no page line, but the figure says so
        self.assertIn("demo chip markers", overview)  # chip ticks on the ideogram
        self.assertIn("SYNTHETIC test data", overview.split('id="fig-ideogram"')[1])  # the ideogram's <desc>
        # The Table tab's 'not near the chip' filter keeps fewer SNPs
        table = self.client.get(url, {"tab": "table", "hide_near_chip": "1"}).content.decode()
        self.assertIn("filtered from", table)
        by_gene = self.client.get(url, {"tab": "table", "hide_near_chip": "1", "sort": "gene"})  # sorted on the raw result:
        self.assertContains(by_gene, "filtered from")  # the chip column still counts
        self.assertEqual(len(list(d.glob("chip_rows_*.parquet"))), 1)  # the chip columns, made once per chip
        self.assertIn('name="hide_near_chip"', self.client.get(url, {"tab": "table"}).content.decode())
        # The 'not near the chip' exclusion leaves fewer candidates
        base = self.client.get(url, {"tab": "panel", "design": "1"}).content.decode()
        near = self.client.get(url, {"tab": "panel", "design": "1", "exclude": "near_chip"}).content.decode()
        candidates = [jobs.read_json(d / "panels" / f"{re.search(r'scope=panel-([0-9a-f]{16})', x).group(1)}.json")["summary"]["n_candidates"]
                      for x in (base, near)]
        self.assertLess(candidates[1], candidates[0])
        # Exports of the list gain the chip columns and the SYNTHETIC line
        text = body(self.client.get(reverse("snpportal:download", args=[key]), {"scope": "all", "format": "tsv"})).decode()
        self.assertIn("SYNTHETIC", "\n".join(line for line in text.splitlines() if line.startswith("#")))
        self.assertIn("novel_functional", next(line for line in text.splitlines() if not line.startswith("#")))
        self.client.post(chip, {"remove": "1"})
        self.assertFalse((d / "chip.parquet").exists() or list(d.glob("chip_rows_*")))
        self.assertNotContains(self.client.get(url), "demo chip markers")
        # An uploaded chip (a SYNTHETIC PLINK .bim from fixture positions), a wrong type and an unreadable file
        positions = duckdb.sql(f"SELECT chrom, pos FROM read_parquet('{d / 'result.parquet'}') ORDER BY chrom, pos LIMIT 40").fetchall()
        bim = "".join(f"{c}\tm{i}\t0\t{p}\tA\tG\n" for i, (c, p) in enumerate(positions))
        self.client.post(chip, {"chip": SimpleUploadedFile("chip_SYNTHETIC.bim", bim.encode())})
        info = jobs.read_json(d / "chip.json")
        self.assertEqual(info["kept"], 40)
        self.assertTrue(info["synthetic"])  # SYNTHETIC in its name
        self.assertContains(self.client.get(url + "?tab=panel"), "Your selection compared with the uploaded chip")
        wrong = self.client.post(chip, {"chip": SimpleUploadedFile("chip.pdf", b"%PDF")})
        self.assertIn("chip_error=type", wrong.url)
        with override_settings(SNPPORTAL_MAX_CHIP_SNPS=39):  # longer chips are refused with the cap in the message
            big = self.client.post(chip, {"chip": SimpleUploadedFile("chip_SYNTHETIC.bim", bim.encode())})
            self.assertIn("chip_error=rows", big.url)
            self.assertContains(self.client.get(big.url), "The chip file has more than 39 markers.")
        self.assertEqual(jobs.read_json(d / "chip.json")["kept"], 40)  # the chip already attached stays
        junk = self.client.post(chip, {"chip": SimpleUploadedFile("chip.tsv", b"hello\tworld\n1\t2\n")})
        self.assertIn("chip_error=", junk.url)
        self.assertContains(self.client.get(junk.url), "sp-status-fail")
        self.assertFalse([p for p in d.iterdir() if p.name.startswith(".chip")])  # no upload left behind
        self.assertFalse([p for p in jobs.results_dir().iterdir() if p.name.startswith(".upload-")])
