"""GWAS summary statistics in the portal (P7.1-P7.4), offline, on a release built from salmo-snpscore's fixture and
the SYNTHETIC fixture-scale GWAS of prep/make_synthetic.py (generated into tmp and offered as the release's example).
ATAC rows of the regional plot come from SYNTHETIC bigWigs served by salmo-snpscore's tests/range_server.py."""
import io
import logging
import os
import re
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile
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

    def test_score_page_gwas_tab_and_example(self):
        html = self.client.get(reverse("snpportal:upload")).content.decode()
        box = html[html.index('id="try-it"'):html.index('id="privacy"')]  # the examples under the tabs
        self.assertEqual(re.findall(r'name="example" value="(\w+)"', box), ["known_loci", "chip_demo_SYNTHETIC", STEM])
        form = box[box.rindex("<form", 0, box.index(f'value="{STEM}"')):]  # the GWAS example's form
        self.assertTrue(form.startswith(f'<form method="post" action="{reverse("snpportal:gwas_score")}">'))
        self.assertIn('name="trait" value="all"', form)  # the example opens with all conditions
        self.assertIn("synthetic, maturation", form)
        self.assertEqual(html.count(f'value="{STEM}"'), 1)  # not offered as a SNP-list example too
        gwas = self.client.get(reverse("snpportal:upload"), {"input": "gwas"})  # the GWAS tab, also without JavaScript
        self.assertContains(gwas, 'class="tab-pane active" id="pane-gwas" role="tabpanel" aria-labelledby="tab-gwas" '
                                  f'method="post" action="{reverse("snpportal:gwas_score")}"')
        self.assertRedirects(self.client.get(reverse("snpportal:gwas_score")), reverse("snpportal:upload") + "?input=gwas",
                             fetch_redirect_response=False)
        error = self.client.post(reverse("snpportal:gwas_score"), {})  # errors re-show Score on the GWAS tab
        self.assertContains(error, "Choose a summary-statistics file", status_code=400)
        self.assertContains(error, 'class="nav-link active" id="tab-gwas"', status_code=400)
        self.assertContains(error, 'class="tab-pane active" id="pane-gwas"', status_code=400)
        self.assertContains(error, f'id="pane-file" role="tabpanel" aria-labelledby="tab-file" method="post" '
                                   f'action="{reverse("snpportal:upload")}"', status_code=400)  # not this page's URL

    def test_example_job_and_association_page(self):
        job = jobs.read(self.key)
        self.assertEqual((job["state"], job["input_kind"], job["synthetic_input"]), ("done", "gwas", True))
        response = self.client.get(self.page)
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        top = html[:html.index('id="fig-manhattan"')]  # answer first: one QC line above the Manhattan plot
        self.assertNotIn("Prototype: tiers rank", html)  # no prototype line on the pages
        self.assertNotIn("SYNTHETIC data", html)  # synthetic is said once, in the results title
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
        self.assertIn("sig=1e-10&amp;locus=1", changed)  # links keep the settings, so a regional plot opens the same locus
        self.assertIn("sig=1e-10&amp;tab=table", changed)  # and so do the tabs
        self.assertTrue(list((jobs.folder(self.key) / "loci").glob("*.json")))  # loci and fine-mapping cached per settings
        self.assertRegex(html, rf'{reverse("snpportal:results", args=[self.key])}\?trait=[^"&]*&amp;tab=export')  # the Export link
        self.assertNotIn("format=loci", html)
        results = self.client.get(reverse("snpportal:results", args=[self.key]))  # GWAS jobs open on Association
        self.assertTrue(results.url.startswith(reverse("snpportal:association", args=[self.key])))

    def test_trait_sd_check_and_methods_text(self):
        """The trait SD defaults to the one se, N and af imply (as snpscore gwas); one far from it is flagged in the QC
        line, and the report's references and the bundle's methods.txt carry the fine-mapping (Wakefield 2009)."""
        est = jobs.read_json(jobs.folder(self.key) / "gwas.json")["trait_sd_estimate"]
        html = self.client.get(self.page).content.decode()
        self.assertIn(f'name="trait_sd" value="{est:g}"', html)
        self.assertNotIn("PIPs unreliable", html)
        far = self.client.get(self.page + "&trait_sd=20").content.decode()
        self.assertIn(f"trait SD 20 but se, N and af imply {est:.3g}: PIPs unreliable", far)
        self.assertIn('<details class="sp-more mb-2" open><summary>', far)  # a problem opens the QC details
        report = self.client.get(reverse("snpportal:report", args=[self.key]), {"trait": "maturation"}).content.decode()
        self.assertIn("Wakefield", report)
        bundle = self.client.get(reverse("snpportal:download", args=[self.key]), {"trait": "maturation", "format": "bundle", "trait_sd": "20"})
        methods = zipfile.ZipFile(io.BytesIO(b"".join(bundle.streaming_content))).read("methods.txt").decode()
        self.assertIn("Wakefield", methods)
        self.assertIn("trait SD 20 (given)", methods)
        shown = self.client.get(reverse("snpportal:download", args=[self.key]), {"trait": "maturation", "format": "bundle", "trait_sd": f"{est:g}"})
        methods = zipfile.ZipFile(io.BytesIO(b"".join(shown.streaming_content))).read("methods.txt").decode()
        self.assertIn(f"trait SD {est:g} (estimated from se, N and allele frequency)", methods)  # the form's default, resubmitted

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
        credible = html[html.index('id="credible"'):]
        self.assertIn(causal, credible)  # the credible-set SNPs under both priors, linked to their cards
        card = re.search(rf'href="(/snp/results/{self.key}/snp/\d+/\?trait=[^"]*)">{re.escape(causal)}<', credible).group(1)
        card = self.client.get(card, follow=True).content.decode()  # the card opens in the Table's drawer
        card = card[card.index('id="drawer"'):]
        self.assertRegex(card, r'class="sp-fact" title="GWAS p value">p ')  # the card's GWAS chips, the PIP's with its qualifier
        self.assertIn("one causal variant per locus, no LD", card)
        self.assertIn(">PIP ", card)
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
