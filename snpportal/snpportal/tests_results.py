"""Overview dashboard (P3.2) and results table (P3.3) on a job scored from snpscore's fixture, run inline
(SNPPORTAL_WORKERS=0): summary.json, every panel whose columns exist, figure downloads, bin -> table links, the
filter whitelist, sorting, paging, the column chooser, column gating and the empty state."""
import gzip
import html
import json
import logging
import os
import re
import shutil
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock, skipUnless

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.urls import reverse

import snpdata
import snpscore

from . import figures, jobs, palette, results

SNPSCORE = Path(__file__).resolve().parents[2] / "snpscore"
DATA = SNPSCORE.parent / "snpdata"  # layers.yaml, the fixture, prep/, the catalogue, data/ and release/
FIXTURE = DATA / "tests" / "fixture"
SVG = re.compile(r'<svg (?!class="sp-i").*?</svg>', re.S)  # figures, not the icons


def svgs(html):
    """Every inline SVG of a page, parsed (fails on invalid XML)."""
    return [ET.fromstring(s) for s in SVG.findall(html)]


@skipUnless(FIXTURE.exists(), "needs snpscore/ next to snpportal/")
class ResultsTest(SimpleTestCase):
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

    def test_chromatin_filter_leaves_the_tiers(self):
        total, brain = self.summary["n_rows"], self.count("?tissue=Brain")
        self.assertTrue(0 < brain < total)  # in a robust ATAC peak in a brain condition
        self.assertLessEqual(self.count("?tissue=Brain&act=active"), brain)  # in an active state there: fewer
        self.assertLessEqual(self.count("?tissue=Brain&maturity=Mature&sex=Female"), brain)
        self.assertEqual(self.count("?trait=Brain.Mature.Female"), total)  # an older link's trait: ignored
        page = self.client.get(self.url + "?tab=table&tissue=Brain").content.decode()
        self.assertIn("Chromatin: in a peak in brain", page)
        self.assertNotIn("Chromatin: in a peak in brain", self.client.get(self.url + "?tab=overview").content.decode())  # whole list
        self.assertFalse(list(self.d.glob("tiers_*")))  # never scored for other conditions
        self.client.get(self.url + "?tab=table")  # back to the whole list, for the other tests
        if "tier_terms" not in self.columns:  # several evidence terms: SNPs with any of them
            terms = jobs.connect([self.d]).execute(
                f"SELECT count(*) FROM '{self.d / 'tiers.parquet'}' WHERE list_has_any(list_transform(tier_terms__all, lambda x: x.term), "
                "['coding', 'utr'])").fetchone()[0]
            page = self.client.get(self.url + "?tab=table&term=coding&term=utr").content.decode()
            self.assertIn("Evidence: CDS (protein change or unknown), UTR", page)
            self.assertIn(f"of {terms:,} shown" if terms > 50 else f"&ndash;{terms} of {terms} shown", page)

    def test_selector_column(self):
        page = self.client.get(self.url + "?tab=table").content.decode()
        rows = re.findall(r'href="\?[^"]*exclude=(\d+)"', page)  # every row starts +
        self.assertEqual(page.count('class="sp-tick"'), page.count("<tr data-card"))  # a Keep box on every row
        self.assertNotIn('id="dd-pick"', page)  # nothing taken out: no options yet
        out = self.client.get(self.url + f"?tab=table&exclude={rows[0]}&exclude={rows[1]}").content.decode()  # the last wins
        self.client.get(self.url + f"?tab=table&exclude={rows[0]}")
        page = self.client.get(self.url + "?tab=table").content.decode()
        n = self.summary["n_rows"]
        self.assertIn("2 left out", page)
        self.assertIn(f"Add your Table selection ({n - 2:,} SNPs)", self.client.get(self.url + "?tab=export").content.decode())  # the
        # selection (Export's Add to Design panel) leaves the unticked rows out
        self.assertEqual(page.count('class=" sp-out"'), 0)  # out of the table too, unless asked
        self.assertEqual(self.client.get(self.url + "?tab=table&picked=all").content.decode().count('class=" sp-out"'), 2)  # all: dimmed
        self.assertIn('id="dd-pick"', page)
        only = self.client.get(self.url + "?tab=table&picked=out").content.decode()
        self.assertEqual(only.count("<tr data-card"), 2)
        self.assertEqual(page.count("<tr data-card"), min(n - 2, 50))  # + only, the default
        got = self.client.get(reverse("snpportal:download", args=[self.key]), {"plain": "1"})
        tsv = b"".join(got.streaming_content) if got.streaming else got.content
        self.assertEqual(len(tsv.decode().splitlines()) - 1, n - 2)  # downloads take the + rows
        self.client.get(self.url + f"?tab=table&include={rows[0]}")
        self.assertIn("1 left out", self.client.get(self.url + "?tab=table").content.decode())
        reset = self.client.get(self.url + "?tab=table&include_all=1").content.decode()
        self.assertNotIn("left out", reset)
        self.assertFalse(results.unselected(self.d))

    def test_summary_holds_every_panel(self):
        s, n = self.summary, self.summary["n_rows"]
        self.assertEqual(s["version"], jobs.SUMMARY_VERSION)
        for preset in jobs.weights(self.d)["presets"]:
            self.assertEqual(sum(s["tiers"][preset].values()), n)
            self.assertEqual(sum(sum(b[2:]) for b in s["bins"][preset]), n)
            self.assertEqual(sum(sum(t.values()) for t in s["region_tiers"][preset].values()), n)
            self.assertEqual(sum(sum(t.values()) for t in s["chrom_tiers"][preset].values()), n)
        self.assertEqual(len(s["conditions"]), 27)
        self.assertEqual(sum(s["maf"]["bins"]) + s["maf"]["missing"], n)
        self.assertEqual(s["counts"]["known"], self.direct("known_locus IS NOT NULL"))
        if "assay_status" in self.columns:
            self.assertEqual(sum(s["assay"].values()), n)

    def test_overview_renders_every_panel_and_parses(self):
        page = self.client.get(self.url + "?trait=maturation").content.decode()
        expected = ["summary", "ideogram", "conditions", "regions", "terms", "maf"]
        for name in expected:
            self.assertIn(f'id="fig-{name}"', page)
        more = page[page.index('<span class="sp-fold-title">More charts</span>'):]  # analyst charts closed, after the two open ones
        self.assertIn("Evidence behind the scores", more[:400])  # the fold names what it holds
        self.assertTrue(all(f'id="fig-{name}"' in more for name in ("conditions", "regions", "terms", "maf")))
        self.assertNotIn('id="top-h"', page)  # an overview of the whole list: the SNPs themselves are on the Table tab
        summary = page[page.index('id="fig-summary"'):page.index('id="fig-ideogram"')]  # key numbers and how the SNPs split
        self.assertIn(f'font-size="28" font-weight="600">{self.summary["n_rows"]:,}</text><text x="0.0" y="50.0" text-anchor="start" '
                      'font-size="13" class="sp-ph">SNPs scored', summary)
        rows = re.findall(r'font-size="13" font-weight="600" class="sp-ph">([^<]*)</text>', summary)
        self.assertEqual(rows, ["Score", "Gene region", "Near a known locus"] + ["Assay check"] * ("assay_status" in self.columns))
        self.assertNotIn("for all conditions", summary)  # tiers always count them all: no qualifier
        self.assertIn('href="?tab=table&amp;trait=all&amp;tier=1"', summary)  # every part lists its SNPs, Active in reset
        self.assertNotIn("PROVISIONAL", re.sub(r"<svg .*?</svg>", "", page, flags=re.S))  # no badges
        self.assertNotIn('class="sp-caveat', page)  # no prototype line on the pages
        self.assertEqual('id="qc" open' in page, results.qc_problem(jobs.read_json(self.d / "validation.json")))  # one QC line
        found = svgs(page)
        self.assertGreaterEqual(len(found), len(expected))
        for root in found:
            self.assertEqual(root.get("role"), "img")
            self.assertTrue(root.find("{http://www.w3.org/2000/svg}title").text)
        self.assertNotIn("var(--", "".join(SVG.findall(page)))
        self.assertIn("?tab=table&amp;trait=all&amp;tier=1", page)  # tier bar -> table, Active in reset

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
                   "?gene=ppm1", "?min_maf=0.2", "?max_maf=0.1", "?known=1", "?term=constrained", "?min_score=3",
                   "?hide_blacklist=1", "?hide_lore=1", "?hide_ambiguous=1", "?hide_flank=1"]
        if "assay_status" in self.columns:
            queries += ["?assay=pass", "?assay=ok"]
            self.assertLessEqual(self.count("?assay=ok_nolore"), self.count("?assay=ok"))
            self.assertLessEqual(self.count("?assay=pass"), self.count("?assay=ok"))
        for query in queries:
            self.assertLess(self.count(query), total, query)
            self.assertGreater(self.count(query), 0, query)
        for query in ("?bogus=1", "?tier=9", "?region=nowhere", "?chrom=1%27%20OR%201=1", "?min_maf=abc", "?min_maf=nan",
                      f"?active={cond}", "?active=summary", "?term=nope", "?hide_lore=", "?known=2"):  # no single-condition filter
            self.assertEqual(self.count(query), total, query)
        self.assertEqual(self.count("?gene=it's"), 0)  # quoted, not SQL

    def test_your_tracks(self):
        """A BED file becomes a track: listed for this browser only, drawn first in the locus browser in its own colours
        with names as hover text, a Table filter that changes no tier, and gone when deleted. Never scored."""
        from . import mytracks
        bed = (b'track name="x"\nchrom\tstart\tend\tname\n'
               b"ssa25\t28990000\t28999000\tmy <region> A\t7\t+\t0\t0\t255,0,0\n"   # overlapping intervals: their union is
               b"chr25\t28991000\t28992000\tinside A\n25\t28998000\t29000000\ttail\t.\t.\t0\t0\t0\n"  # 28990000-29000000
               b"25\t28990000\t28990500\tsame start\n25 28999500 28999600 split on spaces\n"
               b"scaffold_1\t5\t9\tnot a chromosome\n25\t9\t3\tbackwards\n")
        add = lambda content, file="regions_SYNTHETIC.bed", **more: self.client.post(  # noqa: E731
            reverse("snpportal:track_add"), {"file": SimpleUploadedFile(file, content), **more})
        self.assertNotIn('id="g-tracks"', self.client.get(f"{reverse('snpportal:locus')}?r=25:28,980,000-29,010,000").content.decode())
        for content, name, code in ((bed, "regions.vcf", "file"), (b"hello\n", "x_SYNTHETIC.bed", "empty"), (b"\x00\xff" * 9, "x_SYNTHETIC.bed", "encoding"),
                                    (b"\x1f\x8b" + b"not gzip" * 9, "x_SYNTHETIC.bed.gz", "read"), (gzip.compress(bed)[:40], "x_SYNTHETIC.bed.gz", "read")):
            self.assertIn(f"error={code}", add(content, name).url, code)
        with override_settings(SNPPORTAL_MAX_TRACK_UNPACKED_MB=len(bed) * 3 / 2 ** 20):  # a small file that unpacks large
            self.assertIn("error=unpacked", add(gzip.compress(bed * 4), "x_SYNTHETIC.bed.gz").url)
        with override_settings(SNPPORTAL_MAX_TRACK_ROWS=2):
            self.assertIn("error=rows", add(bed).url)
        self.assertIn("error=large", self.client.post(reverse("snpportal:track_add"), CONTENT_LENGTH=str(60 * 2 ** 20)).url)
        self.assertEqual([p.name for p in jobs.results_dir().iterdir() if p.name.startswith((".", "track-"))], [])  # nothing left behind
        track = add(bed, name="Mine").url.split("added=")[1]
        d = mytracks.folder(track)
        self.assertEqual(sorted(p.name for p in d.iterdir()), ["created", "track.json", "track.parquet"])  # the upload is not kept
        self.assertEqual((oct(d.stat().st_mode)[-3:], oct((d / "track.parquet").stat().st_mode)[-3:]), ("700", "600"))
        self.assertEqual({k: mytracks.meta(d)[k] for k in ("name", "n", "dropped", "colours", "assembly")},
                         {"name": "Mine", "n": 5, "dropped": 2, "colours": 1, "assembly": "Ssal_v3.1"})
        con = jobs.connect([d])  # intervals sharing a start share max_end, which the filter's ASOF join relies on
        self.assertEqual(con.execute(f"SELECT DISTINCT max_end FROM '{d / 'track.parquet'}' WHERE start = 28990000").fetchall(), [(28999000,)])
        page = self.client.get(reverse("snpportal:tracks"))
        self.assertEqual(page["Cache-Control"], "no-store, private")
        self.assertIn("Mine", page.content.decode())
        browser = self.client.get(f"{reverse('snpportal:locus')}?r=25:28,980,000-29,010,000").content.decode()
        self.assertLess(browser.index('id="g-tracks"'), browser.index('id="g-genes"'))  # near the top
        self.assertIn('fill="#FF0000"', browser)  # the file's colour; the others share the palette's
        self.assertIn(f'fill="{palette.USER_TRACK}"', browser)
        self.assertIn("<title>my &lt;region&gt; A · 25:28,990,001-28,999,000 · + strand · score 7</title>", browser)
        other = self.client_class()  # another browser: no track listed or drawn, though the id still filters (as a job key does)
        self.assertNotIn("Mine", other.get(reverse("snpportal:tracks")).content.decode())
        self.assertNotIn('id="g-tracks"', other.get(f"{reverse('snpportal:locus')}?r=25:28,980,000-29,010,000").content.decode())
        self.assertEqual(other.post(reverse("snpportal:track_change", args=[track]), {"action": "delete"}).status_code, 404)
        other.cookies[mytracks.COOKIE] = track  # the id alone (a shared link) is not the signed cookie
        self.assertNotIn("Mine", other.get(reverse("snpportal:tracks")).content.decode())
        self.assertEqual(other.post(reverse("snpportal:track_change", args=[track]), {"action": "delete"}).status_code, 404)
        inside = self.count("?chrom=25&start=28990000&end=29000000")
        self.assertEqual(self.count(f"?track={track}"), 0)  # a server: the id works only on jobs its owner filtered with it,
        other.get(f"{self.url}?tab=table&track={track}")      # so it can't map a track with a list of one's own
        self.assertEqual(self.count(f"?track={track}"), 0)
        self.client.get(f"{self.url}?tab=table&track={track}")  # the owner filters this job: from now on its links do
        self.assertEqual(self.count(f"?track={track}"), inside)
        self.assertEqual(self.count(f"?track={track}&tier=1"), self.count("?chrom=25&start=28990000&end=29000000&tier=1"))
        for bad in ("nope", "../../etc"):
            self.assertEqual(self.count(f"?track={bad}"), self.summary["n_rows"], bad)
        self.assertEqual(self.count(f"?track={uuid.uuid4()}"), 0)  # an id whose track is gone keeps nothing
        table = self.client.get(f"{self.url}?tab=table&track={track}").content.decode()
        self.assertIn("Inside my track: Mine", table)
        self.assertIn(f'<option value="{track}" selected>Mine</option>', table)
        self.assertIn(f'value="{track}" selected>Mine</option>', other.get(f"{self.url}?tab=table&track={track}").content.decode())  # a shared link
        self.assertNotIn(track, self.client.get(f"{reverse('snpportal:report', args=[self.key])}?track={track}").content.decode().split("Filters:")[1][:200])
        self.assertNotIn("Inside my track", self.client.get(f"{self.url}?tab=overview&track={track}").content.decode())  # the Table only
        self.assertEqual(json.loads((self.d / "summary.json").read_text()), self.summary)  # no tier or count changed
        tsv = self.client.get(f"{reverse('snpportal:download', args=[self.key])}?track={track}")
        tsv = b"".join(tsv.streaming_content).decode()
        self.assertEqual(sum(1 for line in tsv.splitlines() if line and not line.startswith(("#", "chrom"))), inside)
        self.client.post(reverse("snpportal:track_change", args=[track]), {"action": "hide"})
        self.assertNotIn('id="g-tracks"', self.client.get(f"{reverse('snpportal:locus')}?r=25:28,980,000-29,010,000").content.decode())
        self.client.post(reverse("snpportal:track_change", args=[track]), {"action": "delete"})
        self.assertIsNone(mytracks.folder(track))
        self.assertEqual(self.count(f"?track={track}"), 0)  # a deleted track: no SNP, rather than every SNP
        self.assertIn("Inside my track: no longer available", self.client.get(f"{self.url}?tab=table&track={track}").content.decode())
        with override_settings(SNPPORTAL_LOCAL=True, SNPPORTAL_MYTRACKS_DIR=str(Path(self.tmp.name) / "mytracks")):  # a local install
            local = add(bed, name="Here").url.split("added=")[1]
            self.assertIn("Here", self.client_class().get(reverse("snpportal:tracks")).content.decode())  # every track, no cookie
            self.assertEqual(self.count(f"?track={local}"), inside)  # on any job of its assembly
            self.client.post(reverse("snpportal:track_change", args=[local]), {"action": "delete"})
            self.assertEqual(list((Path(self.tmp.name) / "mytracks").iterdir()), [])
        with mock.patch.object(jobs, "wording", return_value=[(re.compile(r"\bssa(?=\d)"), "omy")]):  # a trout page
            self.assertEqual(html.unescape(mytracks.asis("ssa25 & <x>")), "ssa25 & <x>")
            self.assertNotIn("ssa", mytracks.asis("ssa25"))

    def test_table_page_sort_columns_and_barcode(self):
        page = self.client.get(self.url + "?tab=table&size=100").content.decode()
        rows = page.count("<tr data-card")
        self.assertEqual(rows, 100)
        self.assertEqual(page.count('class="sp-bc"'), rows)  # a barcode on every row
        barcode = re.search(r'<span class="sp-bc".*?</span></span>', page, re.S).group(0)
        self.assertEqual(barcode.count("<i "), 27)
        self.assertNotIn(' in"', barcode)  # tiers count all conditions: none is underlined
        headers = re.findall(r'<th scope="col"[^>]*><span class="sp-th">(?:<a [^>]*>|<span [^>]*>)([^<&]+)', page)
        self.assertEqual([h.strip() for h in headers], ["Keep"] + [results.COLUMNS[k][0] for k in results.DEFAULT_COLUMNS
                                                                if k != "size"])  # the selector, then 9 (Size: SV jobs only)
        self.assertIn('aria-sort="descending"', page)  # the score, the default: highest first
        head = page[page.index("<thead"):page.index("</thead>")]  # each filter on its column; the others above the table
        self.assertTrue(all(f'id="dd-{d}"' in head for d in ("tier", "region", "gene", "active", "assay")))  # active: Chromatin
        few = self.client.get(self.url + "?tab=table&cols=1&col=tier").content.decode()
        self.assertNotIn('id="dd-region"', few)  # Region hidden: no filter for it (Columns shows it)
        self.assertRegex(few, r'href="\?tab=table[^"]*" hx-boost="true">Default</a>')  # back to the default columns
        self.assertNotIn(">Default</a>", page)  # already the default
        filtered = self.client.get(self.url + "?tab=table&cols=1&col=tier&region=intron").content.decode()
        self.assertIn('id="dd-region"', filtered[filtered.index("<thead"):filtered.index("</thead>")])  # filtered: it shows
        self.assertNotIn('id="drawer"', page)  # the evidence drawer opens only on a click
        row = re.search(r'href="\?[^"]*snp=(\d+)"', page).group(1)
        drawer = self.client.get(self.url + f"?tab=table&snp={row}").content.decode()
        self.assertIn('id="drawer"', drawer)
        self.assertIn('id="card-body"', drawer)  # the full card
        self.assertRegex(drawer[drawer.index('id="drawer"'):], r'class="sp-badge sp-tier-\d" title="Score \d+, band ')  # the score, coloured
        self.assertIn('aria-current="true">100</a>', page)  # rows per page, under the table
        region = page[page.index('id="dd-region"'):]
        self.assertIn('<summary class="sp-colf" title="Filter Gene region"', region[:200])  # no region filter: a plain funnel
        both = self.client.get(self.url + "?tab=table&region=coding&region=UTR").content.decode()  # ticked: any of them
        self.assertIn('<summary class="sp-colf on" title="Filter Gene region: protein-changing, synonymous, coding (effect unknown), splice site or region, 5′ UTR, 3′ UTR"', both)
        self.assertEqual(int(re.search(r"of ([\d,]+) shown", both).group(1).replace(",", "")),
                         self.direct("region_class IN ('CDS', 'splice_region') OR region_class LIKE '%UTR'"))
        chip = r'class="sp-badge sp-tier-(\d) sp-band( sp-band-off)?"[^>]*>[^<:]+: ([\d,]+)'  # a chip per score band, on or off
        tiers = re.findall(chip, both)
        self.assertEqual(sum(int(n.replace(",", "")) for _, _, n in tiers), int(re.search(r"of ([\d,]+) shown", both).group(1).replace(",", "")))
        one = self.client.get(self.url + "?tab=table&region=coding&region=UTR&tier=1").content.decode()
        self.assertEqual({t for t, off, _ in re.findall(chip, one) if not off}, {"1"})  # the others greyed, a click away

        by_maf = self.client.get(self.url + "?tab=table&sort=maf&desc=1").content.decode()
        first = float(re.search(r'<td class="sp-num">(0\.\d\d)</td>', by_maf).group(1))
        top = jobs.connect([self.d]).execute(f"SELECT max(public_af_maf) FROM '{self.d / 'result.parquet'}'").fetchone()[0]
        self.assertEqual(first, round(top, 2))
        last = self.client.get(self.url + "?tab=table&page=99999").content.decode()
        self.assertIn(f"Page {-(-self.summary['n_rows'] // results.PAGE_SIZE):,} of", last)

        chosen = self.client.get(self.url + "?tab=table&cols=1&col=gerp&col=bogus&col=score").content.decode()
        self.assertIn(">GERP</a>", chosen)
        self.assertIn(">Score &#9660;</a>", chosen)  # the default sort: highest score first, so a down arrow
        self.assertNotIn("sort=tier", chosen)
        self.assertIn("col=gerp", chosen)  # kept in the sort and page links
        layers = self.client.get(self.url + "?tab=table&cols=1&col=id&col=pike&col=summit&sort=summit").content.decode()  # 2026-11-24
        self.assertIn(">Pike</a>", layers)
        self.assertIn("<td>yes</td>", layers)
        self.assertRegex(layers, r'title="Nearest ATAC summit inside a robust peak: signal [\d.]+ \(fold enrichment\) in [^"]+">'
                                 r'(at the summit|\d+ bp) · top \d+%</td>')

    def test_empty_state_names_the_most_restrictive_filter(self):
        page = self.client.get(self.url + "?tab=table&region=coding&tier=4").content.decode()  # coding is never tier 4
        self.assertIn("No SNPs match these filters", page)
        self.assertIn("most restrictive one is <strong>Gene region: protein-changing, synonymous, coding (effect unknown), splice site or region</strong>", page)
        self.assertIn("Remove &ldquo;Gene region: protein-changing, synonymous, coding (effect unknown), splice site or region&rdquo;", page)

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
        self.assertEqual(figures.share_label(49_839, 50_000), ">99%")  # nor the rest as 100%: the shares add up
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
        self.assertEqual([g for g, _ in groups], ["Brain", "Gonad", "Liver", "Muscle", "Gill", "HeadKidney", "Embryo"])
        self.assertEqual([label for label, _ in groups[0][1]], ["Imm F", "Imm M", "Mat F", "Mat M"])
        mark = figures.hbars([{"label": "x", "segments": [(3, "#08519C", "t", None)]}], "T", synthetic=True)
        self.assertIn("SYNTHETIC", mark)
        ET.fromstring(mark)


    def test_predict_on_demand(self):
        """The card's button for a sequence model (G, 2026-11-25): offered for a SNP of an assembly that has a model;
        its address names the job's row and never the position; the result replaces the button. The model itself is
        lib.predict's (tests/test_predict.py): a stand-in here."""
        from . import predict
        from .lib import predict as lp
        chrom, pos, ref, alt = jobs.connect([self.d]).execute(
            f"SELECT chrom, pos, ref, alt FROM read_parquet('{self.d / 'result.parquet'}', file_row_number=true) WHERE file_row_number = 0").fetchall()[0]
        card_url = reverse("snpportal:card", args=[self.key, 0])
        url = reverse("snpportal:predict_job", args=[self.key, 0, "chrombpnet_gill"])
        self.assertNotIn(str(pos), url)
        with mock.patch.object(lp, "missing_packages", lambda: []):
            card = self.client.get(card_url, HTTP_HX_REQUEST="true").content.decode()
        self.assertIn("Predict with ChromBPNet Gill", card)
        self.assertIn(f'hx-get="{url}"', card)
        self.assertIn('hx-select="unset"', card)  # the Table's drawer inherits the results page's hx-select
        with mock.patch.object(lp, "missing_packages", lambda: ["onnxruntime"]):  # the base install: no button, but how to get one
            card = self.client.get(card_url, HTTP_HX_REQUEST="true").content.decode()
        self.assertNotIn("Predict with ChromBPNet Gill", card)
        self.assertIn("needs onnxruntime in this install: pip install numpy onnxruntime", card)
        canned = {"model": "Gill", "version": "v1", "fold": 2, "chrom": chrom, "pos": pos, "ref": ref, "alt": alt, "other_strand": False,
                  "ref_counts": 43.25, "alt_counts": 37.35, "effect": -0.21179, "score": 0.21179, "percentile": 0.9922, "jsd": 0.0574,
                  "jsd_percentile": 0.99967, "active_allele_quantile": 0.1, "ref_profile": [0.04] * 1000, "alt_profile": [0.03] * 1000}
        asked = []

        def stand_in(model, folder, sequence, chrom, pos, ref, alt, threads=1):
            asked.append((model["name"], Path(folder).parts[-2:], chrom, pos, ref, alt))
            return canned
        predict._CACHE.clear()
        with mock.patch.object(lp, "predict", stand_in):
            page = self.client.get(url, HTTP_HX_REQUEST="true").content.decode()
            again = self.client.get(url, HTTP_HX_REQUEST="true").content.decode()  # from this process's memory
        self.assertEqual(asked, [("chrombpnet_gill", ("chrombpnet_gill", "v1"), chrom, pos, ref, alt)])
        self.assertEqual(page, again)
        for text in (f"the alt allele {alt} is predicted", f"<strong>less accessible</strong> than {ref}", "log2 fold change -0.21",
                     "43.2 &rarr; 37.4 predicted Tn5 cuts in the 1,000 bp", "99.2% of 100,000 random public SNPs (top 1%)",
                     "&gt;99.9% of them", "on this server for this SNP alone"):
            self.assertIn(text, page)
        self.assertEqual(len(svgs(page)), 1)  # the two predicted profiles, a valid SVG
        self.assertIn(palette.EFFECTS["down"], page)
        predict._CACHE.clear()
        with mock.patch.object(lp, "predict", mock.Mock(side_effect=lp.Unavailable("The model's files could not be fetched from salmobase.org: offline"))):
            page = self.client.get(url, HTTP_HX_REQUEST="true").content.decode()
        self.assertIn("ChromBPNet Gill: The model&#x27;s files could not be fetched from salmobase.org: offline", page)
        self.assertEqual(self.client.get(reverse("snpportal:predict_job", args=[self.key, 0, "nomodel"])).status_code, 404)
        self.assertEqual(self.client.get(reverse("snpportal:predict_job", args=[self.key, 10 ** 7, "chrombpnet_gill"])).status_code, 404)
        with mock.patch.object(lp, "predict", stand_in):  # a variant page's SNP has its own address; alleles are needed
            self.assertEqual(self.client.get(reverse("snpportal:predict_variant", args=[f"{chrom}-{pos}-{ref}-{alt}", "chrombpnet_gill"])).status_code, 200)
            self.assertEqual(self.client.get(reverse("snpportal:predict_variant", args=[f"{chrom}-{pos}", "chrombpnet_gill"])).status_code, 404)


@skipUnless(os.environ.get("SNPSCORE_DEV") and (DATA / "release" / "dev").exists()
            and (DATA / "data" / "demo" / "public_50k.vcf").exists(), "SNPSCORE_DEV=1 with release/dev and data/demo")
class DevTimingTest(SimpleTestCase):
    def test_public_50k_overview_and_sorted_table(self):
        """P3.2/P3.3: warm render times for the 50K public demo list on release/dev (reported, not gated)."""
        with tempfile.TemporaryDirectory() as tmp, override_settings(
                SNPSCORE_RELEASE=str(DATA / "release" / "dev"), SNPPORTAL_RESULTS_DIR=tmp, SNPPORTAL_WORKERS=0):
            t0 = time.time()
            with open(DATA / "data" / "demo" / "public_50k.vcf", "rb") as f:
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


@skipUnless(FIXTURE.exists(), "needs snpscore/ next to snpportal/")
class VariantScoreTest(SimpleTestCase):  # I15: a SYNTHETIC per-variant score layer in the Table, the card and the browser
    def test_scores_everywhere(self):
        import importlib
        from unittest import mock
        b = importlib.import_module("snpdata.build")
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            lines = [x.split("\t")[:5] for x in (FIXTURE / "snps.vcf").read_text().splitlines() if not x.startswith("#")]
            scored, unscored = lines[:2], lines[2]
            scores = tmp / "variant_scores_SYNTHETIC.tsv"
            scores.write_text("chrom\tpos\tref\talt\tscore\teffect\n" + "".join(  # effect: signed, of the alt allele
                f"{c}\t{p}\t{r}\t{a}\t{s}\t{e}\n" for (c, p, _, r, a), s, e in zip(scored, (0.25, 0.75), (0.25, -0.75))))
            layer = {"name": "synscore", "type": "point", "format": "variant_scores", "file": str(scores),
                     "label": "SynScore", "description": "SYNTHETIC test scores", "direction": ["more open", "less open"]}
            load = b.load_yaml
            with mock.patch.object(b, "load_yaml", lambda p: (lambda c: {**c, "layers": c["layers"] + [layer]}
                                                              if "layers" in c else c)(load(p))):
                snpdata.build(DATA / "layers.yaml", FIXTURE, tmp / "release")
            with override_settings(SNPSCORE_RELEASE=str(tmp / "release"), SNPPORTAL_RESULTS_DIR=str(tmp / "results"),
                                   SNPPORTAL_WORKERS=0):
                logging.disable(logging.WARNING)
                try:
                    paste = "\n".join(f"{c} {p} {r} {a}" for c, p, _, r, a in scored + [unscored])
                    url = self.client.post(reverse("snpportal:upload"), {"paste": paste}).url.split("?")[0]
                    table = self.client.get(url, {"tab": "table", "cols": "1", "col": ["tier", "scores"]}).content.decode()
                    self.assertIn("Scores", table)
                    self.assertIn("SynScore ↓ 0.75 · top 1%", table)  # the higher of the two: percentile 1; its alt allele lowers it
                    self.assertIn("The alt allele is predicted less open (effect -0.75). Higher than 100.0% of the variants scored", table)
                    self.assertIn("SynScore not scored", table)  # outside the scored set
                    key = url.rstrip("/").split("/")[-1]
                    card = self.client.get(reverse("snpportal:card", args=[key, 0]), follow=True).content.decode()
                    self.assertIn("SynScore ↑ 0.25", card)  # the card in the Table's drawer: one key fact per score
                    c, p = scored[0][0], int(scored[0][1])
                    browser = self.client.get(reverse("snpportal:locus"), {"r": f"{c}:{p - 5000}-{p + 5000}"}).content.decode()
                    self.assertIn("Predicted allele effects", browser)  # the browser's group of score rows
                    self.assertIn("SynScore 0.25 (", browser)  # a tick's title
                    self.assertIn("the alt allele is predicted more open (effect +0.25)", browser)
                    self.assertIn(f'fill="{palette.EFFECTS["up"]}"', browser)  # up and red: the alt allele raises the prediction
                    self.assertIn("ChromBPNet Gill", browser)  # the release's own layer has a row too
                finally:
                    logging.disable(logging.NOTSET)
