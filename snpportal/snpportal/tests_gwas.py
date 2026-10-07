"""GWAS summary statistics in the portal (P7.1-P7.4), offline, on a release built from salmo-snpscore's fixture and
the SYNTHETIC fixture-scale GWAS of prep/make_synthetic.py (generated into tmp and offered as the release's example).
ATAC rows of the regional plot come from SYNTHETIC bigWigs served by salmo-snpscore's tests/range_server.py."""
import logging
import os
import re
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock, skipUnless

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.urls import reverse

import snpscore
from snpscore import bbi

from . import association, jobs, locus_svg

SNPSCORE = Path(__file__).resolve().parents[2] / "salmo-snpscore"
FIXTURE = SNPSCORE / "tests" / "fixture"
STEM = "gwas_maturation_SYNTHETIC"


def key_of(url):
    return re.search(r"[0-9a-f]{8}-[0-9a-f-]{27}", url).group(0)


def svgs(html):
    """The page's inline figures (not nested)."""
    return re.findall(r"<svg .*?</svg>", html, re.S)


def figure_svg(html, name):
    """The whole SVG of figure card `name`, nested SVGs included."""
    part = html[html.index(f'id="fig-{name}"'):]
    part = part[:part.index("</figure>")]
    return part[part.index("<svg "):part.rindex("</svg>") + 6]


@skipUnless(FIXTURE.exists(), "needs the salmo-snpscore repo next to this one")
class GwasTest(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        for folder in ("tests", "prep"):
            sys.path.insert(0, str(SNPSCORE / folder))
        import make_synthetic
        from bbi_writer import synthetic_registry
        from range_server import RangeServer
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name).resolve()
        cls.release = root / "release"
        if os.environ.get("SNPPORTAL_TEST_RELEASE"):
            shutil.copytree(os.environ["SNPPORTAL_TEST_RELEASE"], cls.release)
        else:
            snpscore.build(SNPSCORE / "layers.yaml", FIXTURE, cls.release)
        cls.synthetic = root / "synthetic"
        make_synthetic.gwas(FIXTURE / "12_samples_genotype_filtered_on_504.vcf.gz", cls.synthetic, "fixture")
        (cls.release / "demo").mkdir(exist_ok=True)
        shutil.copy(cls.synthetic / f"{STEM}.tsv", cls.release / "demo")  # the Score page's GWAS example
        lines = (cls.synthetic / f"{STEM}_truth.tsv").read_text().splitlines()
        cls.lambda_gc = float(next(x for x in lines if x.startswith("# lambda_gc")).split()[2])
        rows = [x.split("\t") for x in lines if x and not x.startswith("#")]
        cls.truth = {r[0]: dict(zip(rows[0], r)) for r in rows[1:]}
        (root / "tracks").mkdir()
        cls.patches = [mock.patch.object(bbi, "ALLOWED_HOSTS", {"127.0.0.1"}), mock.patch.object(bbi, "ALLOWED_SCHEMES", ("http",))]
        [p.start() for p in cls.patches]
        cls.server = RangeServer(root / "tracks", delay=2.0)
        registry = synthetic_registry(root / "tracks", cls.server.url, ["Brain_Immature_Female", "Gonad_Mature_Male"])
        cls.override = override_settings(SNPSCORE_RELEASE=str(cls.release), SNPPORTAL_RESULTS_DIR=str(root / "results"),
                                          SNPPORTAL_WORKERS=0, SNPPORTAL_TRACKS=str(registry), SNPPORTAL_SIGNAL_DEADLINE=2.0)
        cls.override.enable()
        logging.disable(logging.WARNING)
        response = cls.client_class().post(reverse("snpportal:gwas_score"), {"example": STEM, "trait": "maturation"})
        cls.key = key_of(response.url)
        cls.page = response.url

    @classmethod
    def tearDownClass(cls):
        logging.disable(logging.NOTSET)
        cls.override.disable()
        cls.server.close()
        [p.stop() for p in cls.patches]
        cls.tmp.cleanup()
        super().tearDownClass()

    def test_score_page_offers_the_synthetic_example(self):
        html = self.client.get(reverse("snpportal:upload")).content.decode()
        section = html[html.index('id="gwas"'):]
        section = section[:section.index("</details>")]  # the closed 'Have GWAS summary statistics?' section
        self.assertIn(f'value="{STEM}"', section)
        self.assertIn("(synthetic)", section)
        self.assertIn('name="trait" value="maturation"', section)  # the example opens with trait=maturation
        self.assertEqual(html.count(f'value="{STEM}"'), 1)  # not offered as a SNP-list example too
        error = self.client.post(reverse("snpportal:gwas_score"), {})  # errors re-show Score with the GWAS section open
        self.assertContains(error, 'id="gwas" open', status_code=400)

    def test_example_job_and_association_page(self):
        job = jobs.read(self.key)
        self.assertEqual((job["state"], job["input_kind"], job["synthetic_input"]), ("done", "gwas", True))
        response = self.client.get(self.page)
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        top = html[:html.index('id="fig-manhattan"')]  # answer first: one caveat line (SYNTHETIC on this job), one QC line
        self.assertIn("SYNTHETIC data", top[top.index("sp-caveat"):])
        self.assertEqual(html.count("SYNTHETIC data"), 1)  # one line, no badges
        report = jobs.read_json(jobs.folder(self.key) / "gwas.json")
        self.assertLess(abs(report["lambda_gc"] - self.lambda_gc), 0.01)
        self.assertIn(f"{report['rows_read']:,} rows read, all kept · beta/se on all · λGC {report['lambda_gc']:.2f}", top)
        self.assertIn(f"{report['lambda_gc']}", html)  # in the closed QC details
        self.assertIn('<details class="sp-more mb-2"><summary>', top)  # closed: nothing went wrong
        figures = svgs(html)
        self.assertEqual(len(figures), 3)
        for svg in figures:
            root = ET.fromstring(svg)
            self.assertEqual(root.get("role"), "img")
            self.assertIn("SYNTHETIC", svg)  # watermark
        self.assertIn(self.truth["a_vgll3"]["id"], html)
        loci = html[html.index('id="loci-h"'):html.index("</table>")]
        self.assertIn("Top SNP by PIP", loci)
        self.assertNotIn("Best functional candidate", loci)
        self.assertLess(html.index('id="fig-manhattan"'), html.index('id="loci-h"'))
        self.assertLess(html.index('id="loci-h"'), html.index('id="fig-pip"'))
        self.assertIn('<details class="sp-more mt-3"><summary>QQ plot</summary>', html)  # closed
        self.assertIn('<details class="sp-more"><summary>Fine-mapping settings</summary>', html)  # closed at the defaults
        changed = self.client.get(self.page + "&sig=1e-10").content.decode()
        self.assertIn('<details class="sp-more" open><summary>Fine-mapping settings (1 changed)</summary>', changed)
        self.assertIn(f'{reverse("snpportal:results", args=[self.key])}?trait=maturation&amp;tab=export', html)  # one Export link
        self.assertNotIn("format=loci", html)
        results = self.client.get(reverse("snpportal:results", args=[self.key]))  # GWAS jobs open on Association
        self.assertTrue(results.url.startswith(reverse("snpportal:association", args=[self.key])))

    def test_figures_loci_and_lambda(self):
        base = reverse("snpportal:association_figure", args=[self.key, "manhattan"])
        svg = self.client.get(f"{base}?trait=maturation").content
        self.assertLess(len(svg), 1_000_000)
        self.assertNotIn(b"<a ", svg)  # downloads carry no links
        ET.fromstring(svg)
        loci = self.client.get(f"{reverse('snpportal:association_download', args=[self.key])}?trait=maturation&format=loci").content.decode()
        self.assertIn("# SYNTHETIC", loci)
        rows = [x.split("\t") for x in loci.splitlines() if not x.startswith("#")]
        rows = [dict(zip(rows[0], r)) for r in rows[1:]]
        significant = sorted(r["chrom"] for r in rows if r["significant"] == "True")
        self.assertEqual(significant, sorted(t["chrom"] for t in self.truth.values()))  # four planted loci, separate
        qq = self.client.get(f"{reverse('snpportal:association_figure', args=[self.key, 'qq'])}?trait=maturation&format=tsv").content.decode()
        self.assertIn("tier 1", qq)
        bed = self.client.get(f"{reverse('snpportal:association_download', args=[self.key])}?format=bed").content.decode()
        self.assertEqual(len([x for x in bed.splitlines() if not x.startswith("#")]), len(rows))
        fm = self.client.get(f"{reverse('snpportal:association_download', args=[self.key])}?trait=maturation&format=finemap").content.decode()
        self.assertIn("pip_functional", fm)
        # settings come from whitelisted parameters: a stricter threshold leaves only the vgll3 locus significant
        strict = self.client.get(f"{reverse('snpportal:association_download', args=[self.key])}?format=loci&sig=1e-20&sugg=1e-20").content.decode()
        self.assertEqual(len([x for x in strict.splitlines() if x and not x.startswith(("#", "locus"))]), 1)
        self.assertEqual(self.client.get(f"{reverse('snpportal:association_download', args=[self.key])}?format=nope").status_code, 404)

    def test_regional_plot_over_the_locus_lanes(self):
        url = reverse("snpportal:association_region", args=[self.key])
        html = self.client.get(f"{url}?trait=maturation&locus=1").content.decode()
        svg = figure_svg(html, "region")
        ET.fromstring(svg)
        causal = self.truth["a_vgll3"]["id"]
        mark = re.search(r'<(circle|path) [^>]*stroke-width="1.8"[^>]*><title>' + re.escape(causal) + r"[^<]*credible set", svg)
        self.assertIsNotNone(mark)  # the planted causal SNP, outlined as a credible-set member
        self.assertLess(svg.index(causal), svg.index(">Genes</text>"))  # the association lane on top
        self.assertNotIn('fill-opacity="0.85"', svg)  # no ATAC rows: they stay in the locus browser
        self.assertNotIn(">Public variants</text>", svg)
        self.assertIn("No LD used: colours are tiers, not r²", svg)
        self.assertIn("SYNTHETIC data", html[:html.index('id="fig-region"')])  # the job's caveat line
        credible = html[html.index('id="credible"'):]
        self.assertIn(causal, credible)  # the credible-set SNPs under both priors, linked to their cards
        card = re.search(rf'href="(/snp/results/{self.key}/snp/\d+/\?trait=maturation)">{re.escape(causal)}<', credible).group(1)
        card = self.client.get(card).content.decode()
        self.assertIn("GWAS: p ", card)  # the card's GWAS line, with its qualifier
        self.assertIn("(one causal variant, no LD)", card)
        download = self.client.get(f"{url}?trait=maturation&locus=1&download=1")
        self.assertIn("attachment", download["Content-Disposition"])
        self.assertNotIn(b"<a ", download.content)
        ET.fromstring(download.content)

    def test_uploads_are_detected(self):
        for name, fmt in ((f"{STEM}.fastGWA", "GCTA-fastGWA"), (f"{STEM}.glm.linear", "PLINK2 .glm")):
            data = (self.synthetic / name).read_bytes()
            response = self.client.post(reverse("snpportal:gwas_score"), {"sumstats": SimpleUploadedFile(name, data), "trait": "all"})
            key = key_of(response.url)
            job = jobs.read(key)
            self.assertEqual((job["state"], job["input_format"]), ("done", fmt))
            self.assertTrue(job["synthetic_input"])  # from the file's first line
            self.assertIn(fmt, self.client.get(response.url).content.decode())
        bad = self.client.post(reverse("snpportal:gwas_score"), {"sumstats": SimpleUploadedFile("x.vcf", b"#CHROM\tPOS\n")})
        self.assertEqual(bad.status_code, 400)
        no_p = self.client.post(reverse("snpportal:gwas_score"), {"sumstats": SimpleUploadedFile("x_SYNTHETIC.tsv", b"chrom\tpos\n25\t28996360\n")})
        job = jobs.read(key_of(no_p.url))
        self.assertEqual((job["state"], job["error_code"]), ("failed", "invalid_input"))
        self.assertIn("p-value", job["error"])

    def test_lane_in_the_locus_figure(self):
        request = RequestFactory().get("/", {"trait": "maturation"})
        a = self.truth["a_vgll3"]
        lane = association.browser_lane(request, self.key, "25", int(a["pos"]) - 20000, int(a["pos"]) + 20000)
        causal = next(p for p in lane["points"] if p["pos"] == int(a["pos"]))
        self.assertTrue(causal["cs"] and causal["kind"] == "coding" and causal["tier"] <= 2)
        svg = self.client.get(reverse("snpportal:locus_svg"), {"key": self.key, "trait": "maturation",
                                                               "r": f"25:{int(a['pos']) - 20000}-{int(a['pos']) + 20000}"}).content.decode()
        self.assertLess(svg.index("Association"), svg.index("Genes"))  # the locus browser draws the job's GWAS lane
        snp_job = key_of(self.client.post(reverse("snpportal:upload"), {"paste": "25 28996360 C T"}).url)
        self.assertIsNone(association.browser_lane(request, snp_job, "25", 28990000, 29000000))
        self.assertEqual(self.client.get(reverse("snpportal:association", args=[snp_job])).status_code, 404)
        data = {"chrom": "25", "start": 28990000, "end": 29000000, "size": 50_000_000, "conditions": []}
        lane = {"points": [{"pos": 28996360, "neglog10p": 30.0, "tier": 2, "kind": "lead", "cs": True, "title": "lead SNP", "url": "/x"},
                           {"pos": 28995000, "neglog10p": 3.0, "tier": 4, "kind": "", "cs": False, "title": "other"}], "significant": 7.3}
        svg = locus_svg.locus(data, title="t", gwas=lane)
        ET.fromstring(svg)
        self.assertLess(svg.index("Association"), svg.index("Genes"))
        self.assertIn('href="/x"', svg)
