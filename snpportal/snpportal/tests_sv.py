"""Structural variants on the portal, on a release built from snpscore's fixture with jobs run inline: the Score page's
tab and examples, an uploaded VCF, pasted regions, the results tabs, the card, the exports and what SV jobs leave out."""
import logging
import re
import shutil
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import skipUnless

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, override_settings
from django.urls import reverse

import snpdata

from . import jobs

DATA = Path(__file__).resolve().parents[2] / "snpdata"
FIXTURE = DATA / "tests" / "fixture"
VCF = ("##fileformat=VCFv4.2\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
       "25\t28996000\tdel_vgll3\tN\t<DEL>\t.\tPASS\tSVTYPE=DEL;END=28997000;SVLEN=-1000\n"  # vgll3's CDS and a peak
       "21\t32141000\tdup_peak\tN\t<DUP>\t.\tPASS\tSVTYPE=DUP;END=32142000\n"
       "25\t28990000\tins1\tN\t<INS>\t.\tPASS\tSVTYPE=INS;SVLEN=300\n"
       "26\t14000000\tfar\tN\t<DEL>\t.\tPASS\tSVTYPE=DEL;END=14000100\n"
       "26\t14000000\tno_end\tN\t<INV>\t.\tPASS\tSVTYPE=INV\n")


@skipUnless(FIXTURE.exists(), "needs snpscore/ next to snpportal/")
class SVTest(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tmp = tempfile.TemporaryDirectory()
        release = Path(cls.tmp.name) / "release"
        snpdata.build(DATA / "layers.yaml", FIXTURE, release)
        cls.override = override_settings(SNPSCORE_RELEASE=str(release), SNPPORTAL_RESULTS_DIR=str(Path(cls.tmp.name) / "results"),
                                          SNPPORTAL_WORKERS=0)
        cls.override.enable()
        logging.disable(logging.WARNING)
        upload = SimpleUploadedFile("svs.vcf", VCF.encode())
        cls.url = cls.client_class().post(reverse("snpportal:upload"), {"kind": "sv", "svs": upload}).url.split("?")[0]
        cls.key = cls.url.split("/")[-2]

    @classmethod
    def tearDownClass(cls):
        cls.override.disable()
        logging.disable(logging.NOTSET)
        shutil.rmtree(cls.tmp.name, ignore_errors=True)
        super().tearDownClass()

    def test_score_page_has_the_tab_and_examples(self):
        page = self.client.get(reverse("snpportal:upload")).content.decode()
        self.assertIn('id="pane-sv"', page)
        self.assertIn('name="sv_paste"', page)
        self.assertRegex(page, r'name="kind" value="sv">\s*<button[^>]+value="svs_demo_SYNTHETIC"')  # the example posts as SVs

    def test_uploaded_svs_are_scored_by_overlap(self):
        job = jobs.read(self.key)
        self.assertEqual((job["state"], job["input_kind"], job["n_rows"]), ("done", "sv", 4))  # no_end is rejected
        overview = self.client.get(self.url).content.decode()
        self.assertIn("4 SVs", overview)
        self.assertNotIn("4 SNPs", overview)
        self.assertIn('<span>salmo-snp</span>', overview)  # the site's name stays
        self.assertIn("no valid end", overview)  # the upload QC names the rejected row's reason
        for svg in re.findall(r'<svg (?!class="sp-i").*?</svg>', overview, re.S):
            ET.fromstring(svg)
        table = self.client.get(self.url, {"tab": "table"}).content.decode()
        self.assertIn("25:28,996,001–28,997,000", table)  # the SV's span beside its id
        self.assertIn(">Size<", table)
        self.assertIn("DEL 1.0 kb", table)
        self.assertNotIn('form="add-panel"', table)  # panels are SNP markers
        self.assertNotIn(">MAF<", table)  # nothing at single bases: no frequencies, no assay check
        self.assertNotIn(">Assay<", table)

    def test_card_and_browser(self):
        row = next(i for i, r in enumerate(self._rows()) if r[0] == "del_vgll3")
        card = self.client.get(reverse("snpportal:card", args=[self.key, row]), HTTP_HX_REQUEST="true").content.decode()
        self.assertIn("Gene regions it overlaps", card)
        self.assertIn("CDS", card)
        self.assertIn("vgll3_Met54Thr", card)  # the known SNP inside it
        self.assertIn(">SV<", card)  # the mini browser's band
        browser = self.client.get(reverse("snpportal:locus_svg"), {"key": self.key, "row": row})
        self.assertEqual(browser.status_code, 200)
        self.assertIn("<rect", browser.content.decode())

    def test_exports(self):
        tsv = b"".join(self.client.get(reverse("snpportal:download", args=[self.key])).streaming_content).decode()
        self.assertIn("snpscore sv <your list>", tsv)  # the provenance names the SV command
        header = next(line for line in tsv.splitlines() if not line.startswith("#")).split("\t")
        self.assertTrue({"chrom", "pos", "end", "length", "svtype", "tier", "genes", "region_classes"} <= set(header))
        bed = b"".join(self.client.get(reverse("snpportal:download", args=[self.key]), {"format": "bed", "scope": "all"})
                       .streaming_content).decode()
        self.assertIn("25\t28996000\t28997000\tdel_vgll3", bed)  # BED over the SV's span
        self.assertEqual(self.client.get(reverse("snpportal:download", args=[self.key]), {"format": "kasp", "scope": "all"}).status_code, 404)
        export = self.client.get(self.url, {"tab": "export"}).content.decode()
        self.assertNotIn("KASP", export)
        self.assertNotIn("Design a panel", export)
        report = self.client.get(reverse("snpportal:report", args=[self.key])).content.decode()
        self.assertIn("Top 4 SVs", report)
        self.assertIn("A structural variant gets the evidence of everything it overlaps", report)
        self.assertIn("25:28,996,001–28,997,000", report)
        added = self.client.post(reverse("snpportal:panel_add", args=[self.key]))
        self.assertIn("panel_error=sv", added.url)

    def test_paste_and_errors(self):
        response = self.client.post(reverse("snpportal:upload"), {"kind": "sv", "sv_paste": "25:28,996,001-28,997,000 DEL mine\n9 23837001 23839000 DUP"})
        key = response.url.split("/")[-2]
        self.assertEqual((jobs.read(key)["input_kind"], jobs.read(key)["n_rows"]), ("sv", 2))
        bad = self.client.post(reverse("snpportal:upload"), {"kind": "sv", "sv_paste": "25 28996001"})
        self.assertEqual(bad.status_code, 400)
        page = bad.content.decode()
        self.assertIn("expected chrom:start-end", page)
        self.assertRegex(page, r'class="tab-pane active" id="pane-sv"')  # the error comes back on the SV tab
        example = self.client.post(reverse("snpportal:upload"), {"kind": "sv", "example": "svs_demo_SYNTHETIC"})
        job = jobs.read(example.url.split("/")[-2])
        self.assertEqual((job["input_kind"], job["state"], job["synthetic_input"]), ("sv", "done", True))
        self.assertIn("Example: SVs (synthetic)", self.client.get(example.url).content.decode())

    def test_known_svs(self):
        page = self.client.get(reverse("snpportal:known_loci"), {"tab": "local_adaptation"}).content.decode()
        self.assertIn("6 structural variants", page)
        self.assertIn("9:85,365,420-91,103,390", page)  # a span, not a position
        self.assertIn(">structural variant<", page)  # its evidence badge
        example = self.client.post(reverse("snpportal:upload"), {"kind": "sv", "example": "known_svs"})
        job = jobs.read(example.url.split("/")[-2])
        self.assertEqual((job["input_kind"], job["n_rows"], job["synthetic_input"]), ("sv", 1, False))  # chromosome 9: the fixture's
        table = self.client.get(example.url, {"tab": "table"}).content.decode()
        self.assertIn("inv_ssa09_chr9inv", table)
        self.assertIn("INV 5.74 Mb", table)
        self.assertIn("inside", table)  # the known locus is the SV itself

    def _rows(self):
        con = jobs.connect([jobs.folder(self.key)])
        return con.execute(f"SELECT id FROM read_parquet('{jobs.folder(self.key) / 'result.parquet'}')").fetchall()
