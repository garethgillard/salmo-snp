"""Guided tour (P5.11) and printable report (P3.5) on a release built from salmo-snpscore's fixture, offline: the
tour's signal rows point at a closed local port (so they come back hatched) and its example job runs inline."""
import logging
import os
import re
import shutil
import socket
import sys
import tempfile
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from unittest import mock, skipUnless

from django.test import SimpleTestCase, override_settings
from django.urls import reverse

import snpscore
from snpscore import bbi

from . import explore, jobs

SNPSCORE = Path(__file__).resolve().parents[2] / "salmo-snpscore"
FIXTURE = SNPSCORE / "tests" / "fixture"


class Links(HTMLParser):
    """Link targets of a page, in order: hrefs of <a> and hx-get of any element."""

    def __init__(self, html):
        super().__init__()
        self.links = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self.links += [a[k] for k in ("href", "hx-get") if a.get(k) and (k == "hx-get" or tag == "a")]


def kpis(html):
    return re.findall(r'class="sp-kpi[^"]*"(?: href="[^"]*")?>\s*<b>([^<]*)</b>', html)


def card_rows(html, key):
    return list(dict.fromkeys(re.findall(rf"/snp/results/{key}/snp/(\d+)/", html)))


@skipUnless(FIXTURE.exists(), "needs the salmo-snpscore repo next to this one")
class TourTest(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        sys.path.insert(0, str(SNPSCORE / "tests"))
        from bbi_writer import synthetic_registry
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name).resolve()
        cls.release = root / "release"
        if os.environ.get("SNPPORTAL_TEST_RELEASE"):
            shutil.copytree(os.environ["SNPPORTAL_TEST_RELEASE"], cls.release)
        else:
            snpscore.build(SNPSCORE / "layers.yaml", FIXTURE, cls.release)
        with socket.socket() as s:  # a local port nobody listens on: salmobase 'does not answer'
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        (root / "tracks").mkdir()
        registry = synthetic_registry(root / "tracks", f"http://127.0.0.1:{port}/", ["Brain_Mature_Male", "Gonad_Mature_Male"])
        cls.patches = [mock.patch.object(bbi, "ALLOWED_HOSTS", {"127.0.0.1"}), mock.patch.object(bbi, "ALLOWED_SCHEMES", ("http",))]
        [p.start() for p in cls.patches]
        cls.override = override_settings(SNPSCORE_RELEASE=str(cls.release), SNPPORTAL_RESULTS_DIR=str(root / "results"),
                                          SNPPORTAL_WORKERS=0, SNPPORTAL_TRACKS=str(registry), SNPPORTAL_SIGNAL_DEADLINE=1.0)
        cls.override.enable()
        logging.disable(logging.WARNING)  # job log lines and 'no data from <track>'

    @classmethod
    def tearDownClass(cls):
        logging.disable(logging.NOTSET)
        cls.override.disable()
        [p.stop() for p in cls.patches]
        cls.tmp.cleanup()
        super().tearDownClass()

    def steps(self, response):
        tour = reverse("snpportal:tour") + "?step="
        return list(dict.fromkeys(u for u in Links(response.content.decode()).links if u.startswith(tour)))

    def example(self):
        """Score the tour's example (step 4); returns (key, redirect URL)."""
        response = self.client.post(reverse("snpportal:tour") + "?step=4&trait=maturation")
        self.assertEqual(response.status_code, 302)
        self.assertIn("step=5", response.url)
        return re.search(r"key=([0-9a-f-]{36})", response.url).group(1), response.url

    def test_tour_steps_example_job_and_links(self):
        first = self.client.get(reverse("snpportal:tour"))
        self.assertContains(first, "Step 1 of 8")
        self.assertContains(first, "ENSSSAG00000099564")  # the chr21 namesake of vgll3 (the caveat)
        self.assertEqual(first["Cache-Control"], "no-store, private")
        steps = self.steps(first)
        self.assertEqual(len(steps), 8)
        for i, url in enumerate(steps, 1):
            page = self.client.get(url)
            self.assertContains(page, f"Step {i} of 8")
            if i in (5, 6, 7):  # no example job yet: these offer to score it
                self.assertContains(page, "Score the example")

        key, url = self.example()
        job = jobs.read(key)
        self.assertEqual((job["state"], job["preset"]), ("done", "maturation"))
        n = len([r for r in explore.catalogue() if (r.get("pos") or "").isdecimal()])  # the demo is the catalogue
        self.assertTrue(job["label"].startswith(f"Tour example: {n} known loci + "), job["label"])
        overview = self.client.get(url)
        self.assertContains(overview, "SNPs scored")
        self.assertContains(overview, 'id="fig-tiers"')
        self.assertContains(overview, f'href="/snp/results/{key}/?tab=table')  # figure and KPI links point at the results
        steps = self.steps(overview)
        self.assertEqual(len(steps), 8)
        self.assertTrue(all(f"key={key}" in u for u in steps))

        followed = set()
        for url in steps:  # every step, and every portal page or live figure it links (downloads aside)
            page = self.client.get(url)
            self.assertEqual(page.status_code, 200, url)
            for link in Links(page.content.decode()).links:
                if link.startswith("/snp/") and "/download/" not in link and not link.startswith(reverse("snpportal:tour")) \
                        and link not in followed:
                    followed.add(link)
                    self.assertIn(self.client.get(link).status_code, (200, 302), link)
        self.assertTrue(any("tab=panel" in x for x in followed) and any("&known=1" in x for x in followed))
        self.assertTrue(any(x.startswith(reverse("snpportal:report", args=[key])) for x in followed))

        locus_svg = next(x for x in followed if x.startswith(reverse("snpportal:locus_svg")))
        self.assertIn("trait=maturation", locus_svg)
        svg = self.client.get(locus_svg).content.decode()
        ET.fromstring(svg)
        self.assertIn("signal unavailable", svg)  # offline: hatched rows, never synthesised signal
        variant = next(x for x in followed if x.startswith(reverse("snpportal:variant", args=["25-28996360-C-T"])))
        self.assertContains(self.client.get(variant, HTTP_HX_REQUEST="true"), 'id="card-body"')

    def test_report_matches_overview_and_table(self):
        key, _ = self.example()
        results, report = reverse("snpportal:results", args=[key]), reverse("snpportal:report", args=[key])
        overview = self.client.get(results, {"trait": "maturation"})
        self.assertContains(overview, f"{report}?trait=maturation")  # the results header links the report
        page = self.client.get(report, {"trait": "maturation"})
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page["Cache-Control"], "no-store, private")
        html = page.content.decode()
        self.assertTrue(kpis(html))
        self.assertEqual(kpis(html), kpis(overview.content.decode()))
        for name in ("ideogram", "regions", "conditions"):
            self.assertEqual(f'id="fig-{name}"' in html, f'id="fig-{name}"' in overview.content.decode(), name)
        for svg in re.findall(r"<svg .*?</svg>", html, re.S):
            ET.fromstring(svg)
        table = self.client.get(results, {"trait": "maturation", "tab": "table"}).content.decode()
        self.assertEqual(card_rows(html, key), card_rows(table, key)[:20])
        self.assertEqual(len(card_rows(html, key)), 20)
        self.assertIn("SNPs were annotated with snpscore", html)  # snpscore.export.methods_text
        self.assertIn(jobs.read(key)["manifest_sha256"], html)  # provenance
        self.assertIn("PROVISIONAL", html)

        filtered = self.client.get(report, {"trait": "maturation", "known": "1"}).content.decode()  # filters as the table
        known = self.client.get(results, {"trait": "maturation", "tab": "table", "known": "1"}).content.decode()
        self.assertEqual(card_rows(filtered, key), card_rows(known, key)[:20])
        self.assertIn("known=1", filtered)
        self.assertEqual(self.client.get(reverse("snpportal:report", args=["00000000-0000-0000-0000-000000000000"])).status_code, 404)
