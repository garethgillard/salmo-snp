"""Guided tour (an illustrated slide show) and the printable report (P3.5), on a release built from salmo-snpscore's
fixture; example jobs run inline."""
import logging
import os
import re
import shutil
import tempfile
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from unittest import skipUnless

from django.test import SimpleTestCase, override_settings
from django.urls import reverse

import snpscore

from . import explore, jobs, views

SNPSCORE = Path(__file__).resolve().parents[2] / "salmo-snpscore"
FIXTURE = SNPSCORE / "tests" / "fixture"
TOUR_DIR = Path(__file__).resolve().parent / "static" / "snpportal" / "tour"


class Page(HTMLParser):
    """Links (<a href>) of a page, and its POST forms as (action, {hidden fields})."""

    def __init__(self, html):
        super().__init__()
        self.links, self.forms = [], []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "a" and a.get("href"):
            self.links.append(a["href"])
        if tag == "form" and a.get("method") == "post":
            self.forms.append((a["action"], {}))
        if tag == "input" and a.get("type") == "hidden" and self.forms and a["name"] != "csrfmiddlewaretoken":
            self.forms[-1][1][a["name"]] = a["value"]


def kpis(html):
    return re.findall(r'class="sp-kpi[^"]*"(?: href="[^"]*")?>\s*<b>([^<]*)</b>', html)


def card_rows(html, key):
    return list(dict.fromkeys(re.findall(rf"/snp/results/{key}/snp/(\d+)/", html)))


def shown(html):
    """Title of the one slide shown (the others are hidden)."""
    visible = [m for m in re.findall(r'<article class="sp-slide"[^>]*>', html) if " hidden" not in m]
    assert len(visible) == 1, visible
    n = re.search(r'aria-labelledby="slide-(\d+)"', visible[0]).group(1)
    return re.search(rf'<h2 id="slide-{n}"[^>]*>([^<]*)</h2>', html).group(1)


@skipUnless(FIXTURE.exists(), "needs the salmo-snpscore repo next to this one")
class TourTest(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name).resolve()
        cls.release = root / "release"
        if os.environ.get("SNPPORTAL_TEST_RELEASE"):
            shutil.copytree(os.environ["SNPPORTAL_TEST_RELEASE"], cls.release)
        else:
            snpscore.build(SNPSCORE / "layers.yaml", FIXTURE, cls.release)
        cls.override = override_settings(SNPSCORE_RELEASE=str(cls.release), SNPPORTAL_RESULTS_DIR=str(root / "results"),
                                          SNPPORTAL_WORKERS=0)
        cls.override.enable()
        logging.disable(logging.WARNING)  # job log lines

    @classmethod
    def tearDownClass(cls):
        logging.disable(logging.NOTSET)
        cls.override.disable()
        cls.tmp.cleanup()
        super().tearDownClass()

    def example(self, **fields):
        """Score the known-loci example as the Score page and the tour's 'Try it' do; returns (key, redirect URL)."""
        response = self.client.post(reverse("snpportal:upload"), {"example": "known_loci", "trait": "maturation", **fields})
        self.assertEqual(response.status_code, 302)
        return re.search(r"[0-9a-f-]{36}", response.url).group(0), response.url

    def test_slides_images_and_navigation(self):
        tour, n = reverse("snpportal:tour"), len(explore.TOUR)
        first = self.client.get(tour)
        html = first.content.decode()
        self.assertEqual(html.count('aria-roledescription="slide"'), n)  # every slide is in the page, one shown
        self.assertEqual(shown(html), explore.TOUR[0]["title"])
        self.assertContains(first, f"Slide 1 of {n}")
        self.assertContains(first, 'aria-disabled="true" data-tour-prev')
        self.assertContains(first, 'href="?slide=2" data-tour-next')
        css = (TOUR_DIR / "tour.css").read_text()
        for s in explore.TOUR:  # short text, and a screenshot with a placed box per callout
            self.assertLessEqual(len(s["title"].split()), 6, s["title"])
            self.assertLessEqual(len(s["text"].split()), 40, s["slug"])
            self.assertLessEqual(len(re.findall(r"[.?!](\s|$)", s["text"])), 2, s["slug"])
            self.assertContains(first, s["title"])
            self.assertContains(first, f'/static/snpportal/tour/{s["slug"]}.webp')
            self.assertTrue((TOUR_DIR / f'{s["slug"]}.webp').exists(), s["slug"])
            for i in range(1, len(s["callouts"]) + 1):
                self.assertIn(f'#tour-{s["slug"]}-{i} {{', css)
        self.assertLess(sum(p.stat().st_size for p in TOUR_DIR.glob("*.webp")), 1.5 * 2 ** 20)

        third = self.client.get(tour, {"slide": 3}).content.decode()  # ?slide=N without JavaScript
        self.assertEqual(shown(third), explore.TOUR[2]["title"])
        self.assertIn('href="?slide=2" data-tour-prev', third)
        self.assertIn('href="?slide=4" data-tour-next', third)
        last = self.client.get(tour, {"slide": n}).content.decode()
        self.assertEqual(shown(last), explore.TOUR[-1]["title"])
        self.assertIn(f'href="{reverse("snpportal:upload")}" data-tour-next', last)  # 'Start scoring'
        self.assertIn("Start scoring</a>", last)
        for bad in ("0", "99", "x"):
            self.assertEqual(shown(self.client.get(tour, {"slide": bad}).content.decode()), explore.TOUR[0]["title"])

        menu = re.search(r'<details class="sp-menu">.*?</details>', self.client.get(reverse("snpportal:landing")).content.decode(), re.S)
        self.assertIn(f'href="{tour}">Guided tour</a>', menu.group(0))  # in the Help menu
        self.assertContains(self.client.get(reverse("snpportal:landing")), f'href="{tour}"')  # 'Take the tour'

        page = Page(html)  # 'Try it': real pages, or the Score page's example buttons
        for link in page.links:  # (the locus browser asks salmobase for live signal: tests_locus covers it offline)
            if link.startswith("/snp/") and not link.startswith((tour, reverse("snpportal:locus"))):
                self.assertEqual(self.client.get(link).status_code, 200, link)
        examples = views.examples()
        for action, fields in page.forms:
            self.assertIn(action, (reverse("snpportal:upload"), reverse("snpportal:gwas_score")))
            self.assertIn(fields["example"], examples)
        table = next(f for _, f in page.forms if f.get("tab") == "table")
        key, url = self.example(**table)
        self.assertIn("tab=table", url)
        self.assertIn("trait=maturation", url)
        self.assertEqual(jobs.read(key)["state"], "done")

    def test_report_matches_overview_and_table(self):
        rows = explore.public_rows([("25", 28_945_075, 29_049_268)])  # public variants within 50 kb of vgll3: over 20
        key = jobs.create_from_rows(rows, "Public variants near vgll3", "maturation")
        results, report = reverse("snpportal:results", args=[key]), reverse("snpportal:report", args=[key])
        overview = self.client.get(results, {"trait": "maturation"})
        self.assertContains(overview, f"{report}?trait=maturation")  # the results header links the report
        page = self.client.get(report, {"trait": "maturation"})
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page["Cache-Control"], "no-store, private")
        html = page.content.decode()
        self.assertTrue(kpis(html))
        self.assertEqual(kpis(html), kpis(overview.content.decode()))  # the same 4 tiles
        for name in ("tiers", "ideogram"):  # two figures
            self.assertIn(f'id="fig-{name}"', html)
        for svg in re.findall(r"<svg .*?</svg>", html, re.S):
            ET.fromstring(svg)
        table = self.client.get(results, {"trait": "maturation", "tab": "table"}).content.decode()
        drawers = list(dict.fromkeys(re.findall(r"snp=(\d+)", table)))  # the table's rows, in order
        self.assertEqual(card_rows(html, key), drawers[:20])
        self.assertEqual(len(card_rows(html, key)), 20)
        self.assertEqual(card_rows(overview.content.decode(), key), drawers[:10])  # the Overview's top 10, in the same order
        self.assertIn("SNPs were annotated with snpscore", html)
        self.assertIn(jobs.read(key)["manifest_sha256"][:12], html)  # provenance, 12-character hashes
        self.assertNotIn(jobs.read(key)["manifest_sha256"], html)
        self.assertIn("rules are provisional", html)
        self.assertNotIn("DOI to add", html)

        filtered = self.client.get(report, {"trait": "maturation", "known": "1"}).content.decode()  # filters as the table
        known = self.client.get(results, {"trait": "maturation", "tab": "table", "known": "1"}).content.decode()
        self.assertEqual(card_rows(filtered, key), list(dict.fromkeys(re.findall(r"snp=(\d+)", known)))[:20])
        self.assertIn("known=1", filtered)
        self.assertEqual(self.client.get(reverse("snpportal:report", args=["00000000-0000-0000-0000-000000000000"])).status_code, 404)
