"""Overview dashboard (P3.2) and results table (P3.3) on a job scored from salmo-snpscore's fixture, run inline
(SNPPORTAL_WORKERS=0): summary.json, every panel whose columns exist, figure downloads, bin -> table links, the
filter whitelist, sorting, paging, the column chooser, column gating and the empty state."""
import json
import logging
import os
import re
import shutil
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import skipUnless

from django.test import RequestFactory, SimpleTestCase, override_settings
from django.urls import reverse

import snpscore

from . import figures, jobs, results

SNPSCORE = Path(__file__).resolve().parents[2] / "salmo-snpscore"
FIXTURE = SNPSCORE / "tests" / "fixture"
SVG = re.compile(r"<svg .*?</svg>", re.S)


def svgs(html):
    """Every inline SVG of a page, parsed (fails on invalid XML)."""
    return [ET.fromstring(s) for s in SVG.findall(html)]


@skipUnless(FIXTURE.exists(), "needs the salmo-snpscore repo next to this one")
class ResultsTest(SimpleTestCase):
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
        logging.disable(logging.WARNING)  # job log lines
        cls.release = release
        with open(FIXTURE / "snps.vcf", "rb") as f:
            cls.url = cls.client_class().post(reverse("snpportal:upload"), {"snps": f}).url.split("?")[0]
        cls.key = cls.url.split("/")[-2]
        cls.d = jobs.folder(cls.key)
        cls.summary = json.loads((cls.d / "summary.json").read_text())
        con = jobs.connect([cls.d])
        cls.columns = [c for c, in con.execute(f"SELECT column_name FROM (DESCRIBE SELECT * FROM '{cls.d / 'result.parquet'}')").fetchall()]

    @classmethod
    def tearDownClass(cls):
        logging.disable(logging.NOTSET)
        cls.override.disable()
        cls.tmp.cleanup()
        super().tearDownClass()

    def count(self, query):
        """SNPs matching the table filters in `query`, through the same view the table uses."""
        con, _, where, _ = results.open_result(RequestFactory().get("/" + query), self.key)
        return con.execute(f"SELECT count(*) FROM v {where}").fetchone()[0]

    def direct(self, sql):
        return jobs.connect([self.d]).execute(f"SELECT count(*) FROM '{self.d / 'result.parquet'}' WHERE {sql}").fetchone()[0]

    def test_active_in_sets_the_tiers(self):
        same = self.client.get(self.url + "?tab=table&active_set=1&tissue=Gonad&tissue=Brain").content.decode()
        self.assertIn("Tiers for <strong>maturation: Brain, Gonad</strong>", same)  # the preset with these conditions: stored tiers
        self.assertFalse(list(self.d.glob("tiers_*")))
        own = self.client.get(self.url + "?tab=overview&trait=Brain.Mature.Female").content.decode()
        self.assertIn("Tiers for <strong>brain (mature females)</strong>", own)
        self.assertTrue((self.d / "tiers_Brain.Mature.Female.parquet").exists())  # scored once, kept with the job
        parts = json.loads((self.d / "summary_Brain.Mature.Female.json").read_text())
        self.assertEqual(sum(parts["tiers"]["Brain.Mature.Female"].values()), self.summary["n_rows"])
        if "tier_terms" not in self.columns:  # several evidence terms: SNPs with any of them
            terms = jobs.connect([self.d]).execute(
                f"SELECT count(*) FROM '{self.d / 'tiers.parquet'}' WHERE list_has_any(list_transform(tier_terms__maturation, x -> x.term), "
                "['coding', 'utr'])").fetchone()[0]
            page = self.client.get(self.url + "?tab=table&trait=maturation&term=coding&term=utr").content.decode()
            self.assertIn("Evidence: CDS (protein change or unknown), UTR", page)
            self.assertIn(f"of {terms:,} shown" if terms > 50 else f"&ndash;{terms} of {terms} shown", page)

    def test_summary_holds_every_panel(self):
        s, n = self.summary, self.summary["n_rows"]
        self.assertEqual(s["version"], jobs.SUMMARY_VERSION)
        for preset in jobs.weights(self.d)["presets"]:
            self.assertEqual(sum(s["tiers"][preset].values()), n)
            self.assertEqual(sum(sum(b[2:]) for b in s["bins"][preset]), n)
            self.assertEqual(sum(sum(t.values()) for t in s["region_tiers"][preset].values()), n)
            self.assertEqual(sum(sum(t.values()) for t in s["chrom_tiers"][preset].values()), n)
        self.assertEqual(len(s["conditions"]), 21)
        self.assertEqual(sum(s["maf"]["bins"]) + s["maf"]["missing"], n)
        self.assertEqual(s["counts"]["known"], self.direct("known_locus IS NOT NULL"))
        if "assay_status" in self.columns:
            self.assertEqual(sum(s["assay"].values()), n)

    def test_overview_renders_every_panel_and_parses(self):
        page = self.client.get(self.url + "?trait=maturation").content.decode()
        expected = ["summary", "ideogram", "conditions", "regions", "terms", "maf"]
        for name in expected:
            self.assertIn(f'id="fig-{name}"', page)
        more = page[page.index("More charts (4)"):]  # analyst charts closed, after the two open ones side by side
        self.assertTrue(all(f'id="fig-{name}"' in more for name in ("conditions", "regions", "terms", "maf")))
        self.assertNotIn('id="top-h"', page)  # an overview of the whole list: the SNPs themselves are on the Table tab
        summary = page[page.index('id="fig-summary"'):page.index('id="fig-ideogram"')]  # key numbers and how the SNPs split
        self.assertIn(f'font-size="28" font-weight="700">{self.summary["n_rows"]:,}</text><text x="0.0" y="46.0" text-anchor="start" '
                      'font-size="12.5">SNPs scored', summary)
        rows = re.findall(r'font-size="12.5" font-weight="600">([^<]*)</text>', summary)
        self.assertEqual(rows, ["Tier for maturation", "Gene region", "Near a known locus"] + ["Assay check"] * ("assay_status" in self.columns))
        self.assertIn('href="?tab=table&amp;trait=maturation&amp;tier=1-2"', summary)  # every part lists its SNPs
        self.assertNotIn("PROVISIONAL", re.sub(r"<svg .*?</svg>", "", page, flags=re.S))  # no badges: one caveat line
        self.assertEqual(page.count('class="sp-caveat'), 1)  # one caveat line
        self.assertEqual('id="qc" open' in page, results.qc_problem(jobs.read_json(self.d / "validation.json")))  # one QC line
        found = svgs(page)
        self.assertGreaterEqual(len(found), len(expected))
        for root in found:
            self.assertEqual(root.get("role"), "img")
            self.assertTrue(root.find("{http://www.w3.org/2000/svg}title").text)
        self.assertNotIn("var(--", "".join(SVG.findall(page)))
        self.assertIn("?tab=table&amp;trait=maturation&amp;tier=1", page)  # tier bar -> table

    def test_figure_downloads(self):
        n = self.summary["n_rows"]
        for name in results.FIGURES:
            if name == "assay" and "assay_status" not in self.columns:
                continue
            url = reverse("snpportal:figure", args=[self.key, name]) + "?trait=liver"
            svg = self.client.get(url)
            self.assertEqual(svg["Content-Type"], "image/svg+xml", name)
            root = ET.fromstring(svg.content)
            desc = root.find("{http://www.w3.org/2000/svg}desc").text
            self.assertIn("PROVISIONAL", desc)
            self.assertIn(jobs.read(self.key)["manifest_sha256"], desc)
            self.assertNotIn(b"<a ", svg.content)  # downloads carry no links back to the page
            tsv = self.client.get(url + "&format=tsv&plain=1").content.decode().splitlines()
            self.assertGreater(len(tsv), 1, name)
            self.assertFalse(tsv[0].startswith("#"))
        tiers = self.client.get(reverse("snpportal:figure", args=[self.key, "ideogram"]) + "?format=tsv&plain=1").content.decode()
        self.assertEqual(sum(int(line.split("\t")[3]) for line in tiers.splitlines()[1:]), n)
        self.assertEqual(self.client.get(reverse("snpportal:figure", args=[self.key, "nosuch"])).status_code, 404)

    def test_ideogram_bin_filters_the_table(self):
        chrom, b, *n = next(x for x in self.summary["bins"]["all"] if x[0] == "25")
        start, end = b * 1_000_000, (b + 1) * 1_000_000
        overview = self.client.get(self.url).content.decode()
        self.assertIn(f"chrom=25&amp;start={start}&amp;end={end}", overview)
        page = self.client.get(f"{self.url}?tab=table&chrom=25&start={start}&end={end}")
        expected = self.direct(f"chrom = '25' AND pos > {start} AND pos <= {end}")
        self.assertEqual(expected, sum(n))
        self.assertContains(page, f"of {expected:,} shown")
        self.assertContains(page, f"25:{start:,}–{end:,}")  # the chip

    def test_every_filter_changes_the_count_and_others_are_ignored(self):
        total = self.summary["n_rows"]
        cond = next(c for c, k in self.summary["conditions"].items() if 0 < k < total)
        queries = ["?tier=1", "?max_tier=2", "?region=coding", "?chrom=25", "?chrom=25&start=28990000&end=29000000",
                   "?gene=ppm1", "?min_maf=0.2", "?max_maf=0.1", "?known=1", f"?active={cond}", "?term=constrained",
                   "?hide_blacklist=1", "?hide_lore=1", "?hide_ambiguous=1", "?hide_flank=1"]
        if "assay_status" in self.columns:
            queries += ["?assay=pass", "?assay=ok"]
            self.assertLessEqual(self.count("?assay=ok_nolore"), self.count("?assay=ok"))
            self.assertLessEqual(self.count("?assay=pass"), self.count("?assay=ok"))
        for query in queries:
            self.assertLess(self.count(query), total, query)
            self.assertGreater(self.count(query), 0, query)
        for query in ("?bogus=1", "?tier=9", "?region=nowhere", "?chrom=1%27%20OR%201=1", "?min_maf=abc", "?min_maf=nan",
                      "?active=summary", "?active=id", "?term=nope", "?hide_lore=", "?known=2"):
            self.assertEqual(self.count(query), total, query)
        self.assertEqual(self.count("?gene=it's"), 0)  # quoted, not SQL

    def test_table_page_sort_columns_and_barcode(self):
        page = self.client.get(self.url + "?tab=table&size=25&trait=brain").content.decode()
        rows = page.count("<tr data-card>")
        self.assertEqual(rows, 25)
        self.assertEqual(page.count('class="sp-bc"'), rows)  # a barcode on every row
        barcode = re.search(r'<span class="sp-bc".*?</span></span>', page, re.S).group(0)
        self.assertEqual(barcode.count("<i "), 21)
        self.assertEqual(len(re.findall(r'class="st-\w+ in"|class=" in"', barcode)), 4)  # the brain conditions are underlined
        headers = re.findall(r'<th scope="col" title="[^"]*"[^>]*>(?:<a [^>]*>)?([^<&]+)', page)
        self.assertEqual([h.strip() for h in headers if h.strip() != "Position"],
                         [results.COLUMNS[k][0] for k in results.DEFAULT_COLUMNS])  # 9 default columns
        self.assertIn('aria-sort="ascending"', page)  # tier, the default
        self.assertNotIn('id="drawer"', page)  # the evidence drawer opens only on a click
        row = re.search(r'href="\?[^"]*snp=(\d+)"', page).group(1)
        drawer = self.client.get(self.url + f"?tab=table&trait=brain&snp={row}").content.decode()
        self.assertIn('id="drawer"', drawer)
        self.assertIn('id="card-body"', drawer)  # the full card
        self.assertIn("Tier ", drawer[drawer.index('id="drawer"'):])
        self.assertIn('<input type="radio" name="size" value="25" checked>', page)  # Rows: 25, under More
        self.assertIn('<details class="sp-dd" id="dd-region">', page)  # no region filter: the Region pill is plain
        both = self.client.get(self.url + "?tab=table&region=coding&region=UTR").content.decode()  # ticked: any of them
        self.assertIn('<details class="sp-dd on" id="dd-region">', both)
        self.assertIn("Region <b>coding (CDS, splice), UTR</b>", both)
        self.assertEqual(int(re.search(r"of ([\d,]+) shown", both).group(1).replace(",", "")),
                         self.direct("region_class IN ('CDS', 'splice_region') OR region_class LIKE '%UTR'"))
        tiers = re.findall(r'<a(?: class="off")? href="[^"]*"[^>]*><span class="sp-badge sp-tier-(\d)">Tier \d: ([\d,]+)', both)
        self.assertEqual(sum(int(n.replace(",", "")) for _, n in tiers), int(re.search(r"of ([\d,]+) shown", both).group(1).replace(",", "")))

        by_maf = self.client.get(self.url + "?tab=table&sort=maf&desc=1").content.decode()
        first = float(re.search(r'<td class="sp-num">(0\.\d\d)</td>', by_maf).group(1))
        top = jobs.connect([self.d]).execute(f"SELECT max(public_af_maf) FROM '{self.d / 'result.parquet'}'").fetchone()[0]
        self.assertEqual(first, round(top, 2))
        last = self.client.get(self.url + "?tab=table&page=99999").content.decode()
        self.assertIn(f"Page {-(-self.summary['n_rows'] // results.PAGE_SIZE):,} of", last)

        chosen = self.client.get(self.url + "?tab=table&cols=1&col=gerp&col=bogus&col=score").content.decode()
        self.assertIn(">GERP</a>", chosen)
        self.assertIn(">Score</a>", chosen)
        self.assertNotIn("sort=tier", chosen)
        self.assertIn("col=gerp", chosen)  # kept in the sort and page links

    def test_empty_state_names_the_most_restrictive_filter(self):
        page = self.client.get(self.url + "?tab=table&region=coding&tier=4").content.decode()  # coding is never tier 4
        self.assertIn("No SNPs match these filters", page)
        self.assertIn("most restrictive one is <strong>Region: coding (CDS, splice)</strong>", page)
        self.assertIn("Remove &ldquo;Region: coding (CDS, splice)&rdquo;", page)

    def test_panels_and_filters_need_their_columns(self):
        """A job whose result lacks the assay, AF and known-locus columns (e.g. an older release): no KPI, panel,
        filter or column for them, nothing errors, and the old summary.json is rebuilt."""
        key = "00000000-0000-4000-8000-0000000000aa"
        d = jobs.folder(key)
        shutil.copytree(self.d, d)
        drop = [c for c in self.columns if c.startswith(("assay_", "public_af", "known_"))]
        con = jobs.connect([d], d)
        con.execute(f"COPY (SELECT * EXCLUDE ({', '.join(drop)}) FROM '{d / 'result.parquet'}') TO '{d / 'slim.parquet'}' (FORMAT parquet)")
        os.replace(d / "slim.parquet", d / "result.parquet")
        (d / "summary.json").write_text(json.dumps({"n_rows": self.summary["n_rows"], "tiers": self.summary["tiers"]}))
        url = reverse("snpportal:results", args=[key])
        overview = self.client.get(url).content.decode()
        for gone in ('id="fig-assay"', 'id="fig-maf"', "assay pass", "MAF ≥ 0.05", "near a known locus"):
            self.assertNotIn(gone, overview)
        self.assertIn('id="fig-ideogram"', overview)  # rebuilt from the result
        self.assertEqual(jobs.read_json(d / "summary.json")["version"], jobs.SUMMARY_VERSION)
        table = self.client.get(url + "?tab=table&assay=pass&min_maf=0.1&known=1&sort=maf").content.decode()
        self.assertIn(f"Showing 1&ndash;50 of {self.summary['n_rows']:,} SNPs", table)
        for gone in ('name="assay"', 'name="min_maf"', 'name="known"', ">MAF<"):
            self.assertNotIn(gone, table)

    def test_background_markers(self):
        """With the release's pool/background.json (as snpscore pool writes it), the heatmap prints folds and the
        region and MAF bars get background ticks."""
        pool = self.release / "pool"
        pool.mkdir(exist_ok=True)
        (pool / "background.json").write_text(json.dumps({  # SYNTHETIC test data written by tests_results.py: not real results
            "n_sites": 1000, "active_by_condition": {c: 0.01 for c in self.summary["conditions"]},
            "region_class": {"CDS": {"n": 20, "share": 0.02}, "intron": {"n": 500, "share": 0.5}, "intergenic": {"n": 480, "share": 0.48}},
            "maf_histogram": {f"{i / 20:.2f}-{(i + 1) / 20:.2f}": {"n": 100, "share": 0.1} for i in range(10)}}))
        try:
            page = self.client.get(self.url).content.decode()
            self.assertIn("× the public background", page)
            self.assertIn("Public background: 2.0% of SNPs", page)
            self.assertIn("public background 10.0%", page)
            tsv = self.client.get(reverse("snpportal:figure", args=[self.key, "conditions"]) + "?format=tsv&plain=1").content.decode()
            self.assertIn("\t0.01000\t", tsv)
        finally:
            shutil.rmtree(pool)

    def test_helpers(self):
        self.assertEqual(results.gene_label(None, "ENSSSAG1", "VGLL3,VGLL3B"), "~VGLL3")
        self.assertEqual(results.gene_label(None, "ENSSSAG00000053708", "VGLL3"), "vgll3")  # the catalogue's name, as on gene pages
        self.assertEqual(figures.share_label(161, 50_000), "<1%")  # a few hundred tier-1 SNPs never read as 0%
        self.assertEqual(results.evidence_text("active: Brain,EarlySomitogenesis; molQTL lead: Brain",
                                               [{"term": "active", "weight": 3}, {"term": "molqtl", "weight": 0}]), "active: Brain, E somit.")
        self.assertEqual(results.reasons_text("repeat 1.0; GC 0.72"), "repeat (soft-masked) flanks (100%); GC content out of range (72%)")
        self.assertEqual(results.gene_label("vgll3a", "ENSSSAG1", "VGLL3"), "vgll3a")
        self.assertEqual(results.gene_label(None, "ENSSSAG1", None), "ENSSSAG1")
        self.assertEqual(results.pct(1, 20000), "<0.1%")
        published = {k: results.published_as(k, h) for k, h in (("vgll3_Met54Thr", "p.Thr46Met"), ("cdh1_S167P", "p.Pro167Ser"),
                                                                  ("gig1like3_G78D", "p.Gly78Asp"), ("akap11_Val214Met", "p.Met214Val"))}
        self.assertEqual(published, {"vgll3_Met54Thr": "Met54Thr", "cdh1_S167P": "S167P", "gig1like3_G78D": None,
                                     "akap11_Val214Met": "Val214Met"})  # residue or direction differs, 1- or 3-letter
        at = {"coding_hgvsp": "p.Thr46Met", "known_locus": "vgll3_Met54Thr", "known_locus_dist": 0}.get
        self.assertEqual(results.with_published("active: Brain; missense p.Thr46Met", at),
                         "active: Brain; missense p.Thr46Met (published Met54Thr)")  # tables say it too, not only the card
        near = {"coding_hgvsp": "p.Thr46Met", "known_locus": "vgll3_Met54Thr", "known_locus_dist": 120}.get
        self.assertEqual(results.with_published("missense p.Thr46Met", near), "missense p.Thr46Met")
        groups = results.condition_groups(results.conditions_of(["chromatin_" + c for c in self.summary["conditions"]]))
        self.assertEqual([g for g, _ in groups], ["Brain", "Gonad", "Liver", "Muscle", "Embryo"])
        self.assertEqual([label for label, _ in groups[0][1]], ["Imm F", "Imm M", "Mat F", "Mat M"])
        mark = figures.hbars([{"label": "x", "segments": [(3, "#08519C", "t", None)]}], "T", synthetic=True)
        self.assertIn("SYNTHETIC", mark)
        ET.fromstring(mark)


@skipUnless(os.environ.get("SNPSCORE_DEV") and (SNPSCORE / "release" / "dev").exists()
            and (SNPSCORE / "data" / "demo" / "public_50k.vcf").exists(), "SNPSCORE_DEV=1 with release/dev and data/demo")
class DevTimingTest(SimpleTestCase):
    def test_public_50k_overview_and_sorted_table(self):
        """P3.2/P3.3: warm render times for the 50K public demo list on release/dev (reported, not gated)."""
        with tempfile.TemporaryDirectory() as tmp, override_settings(
                SNPSCORE_RELEASE=str(SNPSCORE / "release" / "dev"), SNPPORTAL_RESULTS_DIR=tmp, SNPPORTAL_WORKERS=0):
            t0 = time.time()
            with open(SNPSCORE / "data" / "demo" / "public_50k.vcf", "rb") as f:
                url = self.client.post(reverse("snpportal:upload"), {"snps": f}).url.split("?")[0]
            scored = time.time() - t0
            timings = {}
            for name, query in (("overview", "?trait=liver"), ("table", "?tab=table&trait=liver"),
                                ("table sorted by position, page 500", "?tab=table&trait=liver&sort=position&desc=1&page=500"),
                                ("table filtered", "?tab=table&trait=liver&region=coding&min_maf=0.05&hide_lore=1&sort=maf")):
                self.client.get(url + query)
                t = time.time()
                self.assertEqual(self.client.get(url + query).status_code, 200)
                timings[name] = round(time.time() - t, 3)
            print(f"\npublic_50k: scored in {scored:.1f} s; warm pages (s): {timings}")
