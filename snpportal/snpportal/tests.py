"""End to end on a release built from salmo-snpscore's fixture, with jobs run inline (SNPPORTAL_WORKERS=0):
upload/paste/example -> job -> overview, table, card, figure and downloads; job lifecycle; palette and templates."""
import json
import logging
import os
import re
import shutil
import tempfile
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from unittest import mock, skipUnless

import duckdb
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.http import QueryDict
from django.test import Client, SimpleTestCase, override_settings
from django.urls import reverse
from django.views.debug import ExceptionReporter

import snpscore

from . import jobs, palette, results

SNPSCORE = Path(__file__).resolve().parents[2] / "salmo-snpscore"
APP = Path(__file__).resolve().parent
FIXTURE = SNPSCORE / "tests" / "fixture"


class PaletteTest(SimpleTestCase):
    def test_text_contrast_is_aa(self):
        for fill, text in palette.TIERS.values():
            self.assertGreaterEqual(palette.contrast(fill, text), 4.5, fill)
        for scheme, colours in palette.STATE_PALETTES.items():  # both state palettes (R8)
            for name, fill in colours.items():
                self.assertGreaterEqual(palette.contrast(fill, palette.text_on(fill)), 4.5, (scheme, name))
        for text, background, _ in palette.STATUS.values():
            self.assertGreaterEqual(palette.contrast(text, background), 4.5, text)
        self.assertGreaterEqual(palette.contrast(palette.ACCENT, palette.WHITE), 4.5)
        self.assertGreaterEqual(palette.contrast(palette.SYNTHETIC[1], palette.SYNTHETIC[2]), 4.5)

    def test_state_palette_switch(self):
        from . import locus_svg
        try:
            self.assertEqual(palette.use_states("aquafaang"), "aquafaang")
            self.assertEqual(palette.STATES["Poised_enhancer_1"], ("#F9E700", "Poi"))
            self.assertIn(".st-Active_TSS{background:#BF2026", palette.css())
            self.assertIn('stroke="#6C757D"', locus_svg.chromatin_grid({"Brain_Immature_Female": "Quiescent"}))  # white: outlined
        finally:
            palette.use_states("portal")
        self.assertIn(".st-Active_TSS{background:#B2182B", palette.css())
        self.assertIn(".stp-aquafaang-Active_TSS{background:#BF2026", palette.css())

    def test_histogram_axis_is_whole_counts(self):
        from . import figures
        svg = figures.histogram([("0.00", 4000, "#000000", "", None, 8117.640888)], "MAF")
        self.assertIn(">10,000</text>", svg)
        self.assertNotIn("8,117.6", svg)

    def test_no_hard_coded_colours_in_templates_or_css(self):
        files = list((APP / "templates").rglob("*.html")) + [APP / "static" / "snpportal" / "portal.css"]
        for path in files:
            text = path.read_text()
            self.assertEqual(re.findall(r"(?<![&\w])#[0-9a-fA-F]{6}\b|rgba?\(", text), [], path.name)
            if path.suffix == ".html":
                self.assertNotIn("style=", text, path.name)
                self.assertFalse([x for x in text.splitlines() if "{#" in x and "#}" not in x], path.name)  # {# #} is one line


@skipUnless(FIXTURE.exists(), "needs the salmo-snpscore repo next to this one")
class PortalTest(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tmp = tempfile.TemporaryDirectory()
        cls.release = Path(cls.tmp.name) / "release"
        if os.environ.get("SNPPORTAL_TEST_RELEASE"):  # reuse a release already built from the fixture (a copy)
            shutil.copytree(os.environ["SNPPORTAL_TEST_RELEASE"], cls.release)
        else:
            snpscore.build(SNPSCORE / "layers.yaml", FIXTURE, cls.release)
        demo = Path(cls.release) / "demo"
        if not demo.exists():  # releases from before the demo/ folder: add the known loci as an example
            demo.mkdir()
            shutil.copy(SNPSCORE / "benchmark" / "known_loci.tsv", demo / "known_loci.tsv")
        cls.results = Path(cls.tmp.name) / "results"
        cls.override = override_settings(SNPSCORE_RELEASE=str(cls.release), SNPPORTAL_RESULTS_DIR=str(cls.results),
                                          SNPPORTAL_WORKERS=0)
        cls.override.enable()
        logging.disable(logging.WARNING)  # job log lines

    @classmethod
    def tearDownClass(cls):
        logging.disable(logging.NOTSET)
        cls.override.disable()
        cls.tmp.cleanup()
        super().tearDownClass()

    def upload(self, trait="all", path=FIXTURE / "snps.vcf"):
        with open(path, "rb") as f:
            return self.client.post(reverse("snpportal:upload"), {"snps": f, "trait": trait})

    def paste(self, text):
        return self.client.post(reverse("snpportal:upload"), {"paste": text})

    def key(self, response):
        return response.url.split("/")[-2]

    def leftovers(self):
        return [p.name for p in self.results.iterdir() if p.name.startswith(".")]

    def test_upload_job_tabs_card_download(self):
        response = self.upload(trait="liver")
        self.assertEqual(response.status_code, 302)
        self.assertNotIn("trait=", response.url)  # a posted trait is ignored: tiers always count all conditions
        key, url = self.key(response), response.url.split("?")[0]
        folder = self.results / key
        job = json.loads((folder / "job.json").read_text())
        self.assertEqual((job["state"], job["preset"]), ("done", "all"))
        n = job["n_rows"]
        self.assertGreater(n, 1000)
        self.assertTrue(all(job[k] for k in ("manifest_sha256", "weights_sha256", "input_sha256", "created_utc")))
        self.assertFalse(list(folder.glob("input*")))  # the upload is gone once scored
        self.assertTrue({"result.parquet", "tiers.parquet", "summary.json", "weights.yaml", "manifest.json"} <= {p.name for p in folder.iterdir()})
        self.assertEqual(folder.stat().st_mode & 0o777, 0o700)
        self.assertTrue(all(p.stat().st_mode & 0o777 == 0o600 for p in folder.iterdir()))

        overview = self.client.get(response.url)
        self.assertContains(overview, "SNPs scored")
        self.assertContains(overview, 'id="fig-summary"')
        self.assertEqual(overview["Cache-Control"], "no-store, private")
        self.assertEqual(overview["Referrer-Policy"], "same-origin")
        self.assertContains(overview, 'hx-select-oob="#sp-actions"')  # Download in the header follows preset switches
        self.assertContains(overview, 'id="sp-actions"')

        self.assertContains(self.client.get(url + "?tab=panel"), "Panel designer")
        page = self.client.get(url + "?tab=table&sort=pos&desc=1&page=2")
        self.assertContains(page, f"Page 2 of {-(-n // results.PAGE_SIZE)}")
        for html in (overview, page):  # htmx would swap nothing into #results for a boosted file or other-page link
            self.assertEqual(boosted_links(html.content.decode()), {"?"})
        self.assertEqual(self.client.get(url + "?tab=table&page=²").status_code, 200)
        self.assertContains(page, "Tier 1:")
        filtered = self.client.get(url + "?tab=table&trait=maturation&max_tier=2&hide_lore=1")
        self.assertContains(filtered, "shown")
        form = filtered.content.decode().split('id="tf"')[1].split("</form>")[0]
        self.assertIn('name="tissue"', form)  # the Chromatin filter: it filters after scoring
        self.assertNotIn('name="active_set"', form)
        self.assertIn('name="tier" value="1" checked', form)  # max_tier=2 (older links): tiers 1 and 2 ticked
        self.assertIn('name="tier" value="2" checked', form)
        self.assertIn('name="hide_lore" value="1" checked', form)

        card = self.client.get(reverse("snpportal:card", args=[key, 0]) + "?trait=brain", HTTP_HX_REQUEST="true")
        self.assertTrue("Chromatin state per condition" in card.content.decode() or "conditions sampled" in card.content.decode())
        self.assertNotContains(card, 'id="card-trait"')  # a job's card follows the Table's Active in
        self.assertContains(card, 'rel="noreferrer noopener"')
        self.assertEqual(card["Cache-Control"], "no-store, private")
        page = self.client.get(reverse("snpportal:card", args=[key, 0]) + "?trait=brain")  # no page of its own: the Table's drawer
        self.assertEqual(page.status_code, 302)
        self.assertTrue(page["Location"].endswith("?tab=table&trait=brain&snp=0"))
        d = jobs.folder(key)  # resolved, as DuckDB's sandbox wants
        in_peak = jobs.connect([d]).execute(f"SELECT file_row_number FROM read_parquet('{d / 'result.parquet'}', file_row_number=true) "
                                            "WHERE chromatin_id IS NOT NULL LIMIT 1").fetchone()
        peak = self.client.get(reverse("snpportal:card", args=[key, in_peak[0]]), HTTP_HX_REQUEST="true")
        self.assertNotContains(peak, 'title="Embryo id')  # the peak id is not a condition
        self.assertContains(peak, "Chromatin state per condition")  # a peak: the grid
        self.assertNotContains(peak, "chromatin_id")  # internal columns are not listed ('Your columns' are the upload's)
        missing = self.client.get(reverse("snpportal:card", args=[uuid.uuid4(), 0]))
        self.assertEqual((missing.status_code, missing["Cache-Control"], missing["Referrer-Policy"]),
                         (404, "no-store, private", "same-origin"))

        everything = b"".join(self.client.get(url + "download/").streaming_content).decode().splitlines()
        comments = [line for line in everything if line.startswith("#")]
        self.assertIn(job["manifest_sha256"], "\n".join(comments))
        self.assertIn(job["weights_sha256"], "\n".join(comments))
        self.assertIn("PROVISIONAL", "\n".join(comments))
        header = everything[len(comments)]
        self.assertIn("chromatin_Brain_Immature_Female", header)
        self.assertIn("tier_evidence", header)
        some = b"".join(self.client.get(url + "download/?max_tier=2").streaming_content).decode().splitlines()
        self.assertLess(len(some), len(everything))
        plain = b"".join(self.client.get(url + "download/?plain=1").streaming_content).decode()
        self.assertTrue(plain.startswith("id\t") or plain.startswith("chrom\t"))
        self.assertFalse([p for p in folder.iterdir() if p.name.startswith(".")])  # no export left behind

        svg = self.client.get(reverse("snpportal:figure", args=[key, "summary"]) + "?trait=liver")
        text = svg.content.decode()
        self.assertNotIn("var(--", text)
        self.assertIn("PROVISIONAL", text)
        root = ET.fromstring(text)
        self.assertEqual(root.get("role"), "img")
        tsv = self.client.get(reverse("snpportal:figure", args=[key, "summary"]) + "?format=tsv&plain=1").content.decode()
        self.assertEqual(sum(int(line.split("\t")[2]) for line in tsv.splitlines()[1:] if line.startswith("Tier for ")), n)

    def test_switching_preset_never_rescores_and_card_reads_one_row(self):
        url = self.upload().url
        with mock.patch.object(snpscore, "scored", side_effect=AssertionError("rescored")) as scored:
            self.assertContains(self.client.get(url + "?tab=table&trait=liver"), "Page 1 of")
            self.client.get(url + "?tab=overview&trait=brain")
            self.client.get(reverse("snpportal:card", args=[url.split("/")[-2], 3]) + "?trait=gonad")
            scored.assert_not_called()
        self.assertIn("WHERE file_row_number = ?", results.CARD_SQL)

    def test_paste_and_rows_jobs(self):
        lines = "\n".join(f"25 {28990000 + 1000 * i}" for i in range(10))
        response = self.paste(lines)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(jobs.read(self.key(response))["n_rows"], 10)
        self.assertContains(self.paste("25 abc"), "Line 1", status_code=400)
        self.assertContains(self.paste("25 ²"), "Line 1", status_code=400)
        rs = self.key(self.paste("rs863754587\n25 28998410"))  # rs IDs are placed through EVA release 9
        self.assertEqual(jobs.read(rs)["n_rows"], 2)

        key = jobs.create_from_rows([("25", 28996360, "vgll3_Met54Thr", "C", "T"), ("26", 19138923, "bco1l", "A", None)], "Test rows")
        job = jobs.read(key)
        self.assertEqual((job["state"], job["n_rows"], job["input_kind"]), ("done", 2, "from_rows"))
        table = self.client.get(reverse("snpportal:results", args=[key]) + "?tab=table")
        self.assertContains(table, "vgll3_Met54Thr")

    def test_examples_run_end_to_end(self):
        page = self.client.get(reverse("snpportal:upload")).content.decode()
        tabs = re.findall(r'role="tab"[^>]*>([^<]+)</a>', page)
        self.assertEqual(tabs, ["Upload SNPs", "Paste positions", "Genes or regions", "GWAS"])
        self.assertIn('name="example" value="known_loci" title="Known loci: ', page)  # the examples under the tabs
        self.assertRegex(page, r'value="chip_demo_SYNTHETIC" title="SNP chip: synthetic, [\d,]+ SNPs">SNP chip <small>synthetic</small>')
        chip =self.client.post(reverse("snpportal:upload"), {"example": "chip_demo_SYNTHETIC"})
        job = jobs.read(self.key(chip))
        self.assertEqual((job["state"], job["label"], job["synthetic_input"]), ("done", "Example: SNP chip (synthetic)", True))
        page = self.client.get(chip.url).content.decode()  # synthetic: said once, in the title
        self.assertIn("(synthetic)", page[page.index("<h1>"):page.index("</h1>")])
        self.assertNotIn("SYNTHETIC data", page)  # no badge (figures keep it in their <desc>, for downloads)
        response = self.client.post(reverse("snpportal:upload"), {"example": "known_loci"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(jobs.read(self.key(response))["state"], "done")
        self.assertTrue((Path(self.release) / "demo" / "known_loci.tsv").exists())  # copied, not moved
        folder = self.results / self.key(response)
        if (folder / "validation.json").exists():  # snpscore writes a validation report and the rejected rows
            self.assertContains(self.client.get(response.url), "Upload QC")
        if (folder / "rejects.tsv").exists():
            rejects = self.client.get(reverse("snpportal:download", args=[self.key(response)]) + "?format=rejects")
            self.assertIn(b"reason", b"".join(rejects.streaming_content))
        self.assertContains(self.client.post(reverse("snpportal:upload"), {"example": "../manifest"}), "not part", status_code=400)

    def test_limits(self):
        before = set(os.listdir(self.results)) if self.results.exists() else set()
        with open(FIXTURE / "snps.vcf", "rb") as f:
            big = self.client.post(reverse("snpportal:upload"), {"snps": f}, CONTENT_LENGTH=str(400 * 2 ** 20))
        self.assertEqual(big.status_code, 413)
        self.assertEqual(set(os.listdir(self.results)) if self.results.exists() else set(), before)
        with override_settings(SNPPORTAL_MAX_SNPS=100):
            response = self.upload()
        job = jobs.read(self.key(response))
        self.assertEqual(job["state"], "failed")
        self.assertIn("more than 100 SNPs", job["error"])
        self.assertContains(self.client.get(response.url), "more than 100 SNPs")
        self.assertFalse(list((self.results / self.key(response)).glob("input*")))
        self.assertTrue(all(p.stat().st_mode & 0o777 == 0o600 for p in (self.results / self.key(response)).iterdir()))
        self.assertEqual(self.leftovers(), [])
        with open(SNPSCORE / "layers.yaml", "rb") as f:
            self.assertContains(self.client.post(reverse("snpportal:upload"), {"snps": f}), "This file type", status_code=400)
        self.assertEqual(self.leftovers(), [])

    def test_queue_limit_and_stale_jobs(self):
        class Stub:  # an executor that never runs anything, so jobs stay queued
            def submit(self, *args):
                pass
        with override_settings(SNPPORTAL_WORKERS=1), mock.patch.object(jobs, "_executor", Stub()):
            try:
                codes = [self.paste("25 28996360").status_code for _ in range(11)]
            finally:
                queued = list(jobs._queued)
                jobs._queued.clear()
        self.assertEqual(codes, [302] * 10 + [503])
        stale = queued[0]
        jobs.update(stale, heartbeat=time.time() - 360)
        page = self.client.get(reverse("snpportal:results", args=[stale]))
        self.assertContains(page, "server restarted")
        self.assertEqual(jobs.read(stale)["state"], "failed")
        fresh = self.client.get(reverse("snpportal:results", args=[queued[1]]))
        self.assertContains(fresh, 'hx-trigger="every 1s"')
        self.assertIn("HX-Refresh", self.client.get(reverse("snpportal:status", args=[stale])))

    def test_delete_and_cleanup(self):
        url = self.paste("25 28996360").url
        key = url.split("/")[-2]
        self.assertEqual(self.client.post(reverse("snpportal:delete", args=[key])).status_code, 302)
        self.assertFalse((self.results / key).exists())
        gone = self.client.get(url)
        self.assertContains(gone, "expired or were deleted", status_code=404)
        self.assertContains(gone, reverse("snpportal:upload"), status_code=404)
        running = self.key(self.paste("25 28996360"))  # 'Delete now' while a worker runs: its DuckDB spills into the folder,
        jobs._running.add(running)  # so only job.json goes at once (the page says deleted) ...
        jobs.delete(running)
        self.assertEqual(((self.results / running).exists(), jobs.read(running)), (True, None))
        jobs.run(running)  # ... and the worker removes the folder when it ends
        self.assertFalse((self.results / running).exists())

        old = self.key(self.paste("25 28996360"))
        os.utime(self.results / old / "job.json", (0, 0))
        stray = self.results / ".upload-old"
        stray.write_text("x")
        os.utime(stray, (0, 0))
        threads = [threading.Thread(target=jobs.cleanup) for _ in range(2)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        call_command("snpportal_cleanup", stdout=open(os.devnull, "w"))
        self.assertFalse((self.results / old).exists())
        self.assertFalse(stray.exists())

    def test_release_edit_keeps_job_tiers_and_shows_banner(self):
        key = self.key(self.upload())
        before = jobs.read_json(self.results / key / "summary.json")["tiers"]
        weights = Path(self.release) / "weights.yaml"
        original = weights.read_text()
        try:
            weights.write_text(original.replace("active: 3", "active: 0"))
            page = self.client.get(reverse("snpportal:results", args=[key]) + "?tab=table")
            self.assertContains(page, "The release has changed since")
            tiers = dict((t, n) for t, n in results.open_result(mock.Mock(GET=QueryDict()), key)[0].execute(
                "SELECT tier, count(*) FROM v GROUP BY 1").fetchall())
            self.assertEqual({str(t): n for t, n in tiers.items()}, before["all"])
        finally:
            weights.write_text(original)

    def test_score_page_lists_this_browsers_results(self):
        a = jobs.create_from_rows([("25", 28996360, "vgll3", "C", "T")], "First list")
        b = jobs.create_from_rows([("26", 19138923, "bco1l", "A", "G")], "Second list")
        for key in (a, b):
            self.client.get(reverse("snpportal:results", args=[key]))  # opening results adds them to the list
        page = self.client.get(reverse("snpportal:upload")).content.decode()
        self.assertLess(page.index("Second list"), page.index("First list"))  # newest first
        self.assertIn("1 SNPs", page)
        self.assertIn('class="sp-mine-current"', page)
        response = self.client.post(reverse("snpportal:delete", args=[b]), {"next": "score"})
        self.assertEqual(response["Location"], reverse("snpportal:upload"))  # back to the Score page
        page = self.client.get(reverse("snpportal:upload")).content.decode()
        self.assertNotIn("Second list", page)
        self.assertIn("First list", page)
        self.assertIsNone(jobs.read(b))

    def test_pages_render(self):
        for name in ("landing", "upload", "locus", "about_data", "methods", "help", "run_locally", "tour", "search"):
            response = self.client.get(reverse(f"snpportal:{name}"))
            self.assertContains(response, 'class="sp-nav"', msg_prefix=name)
        self.assertContains(self.client.get(reverse("snpportal:about_data")), "chromatin")
        self.assertContains(self.client.get(reverse("snpportal:variant", args=["25-28996360-C-T"])), 'data-copy="25-28996360-C-T"')
        self.assertEqual(self.client.get(reverse("snpportal:search") + "?q=25:28996360").status_code, 302)
        locus = self.client.get(reverse("snpportal:search") + "?q=ssa25:28,990,000-29,000,000")
        self.assertIn("chrom=25&start=28990000&end=29000000", locus.url)
        backwards = self.client.get(reverse("snpportal:search") + "?q=25:29,000,000-28,990,000")
        self.assertIn("chrom=25&start=28990000&end=29000000", backwards.url)
        gene = snpscore_gene()
        self.assertContains(self.client.get(reverse("snpportal:gene", args=[gene])), gene)
        self.assertContains(self.client.get(reverse("snpportal:suggest") + "?q=" + gene), gene)
        self.assertEqual(self.client.get(reverse("snpportal:locus_svg")).status_code, 200)

    def test_error_reports_hold_no_snps(self):
        client = Client(raise_request_exception=False)
        with mock.patch.object(jobs, "create", side_effect=RuntimeError("boom")):
            pasted = client.post(reverse("snpportal:upload"), {"paste": "25 28996360 PRIVATEREF T"})
            uploaded = client.post(reverse("snpportal:upload"), {"snps": SimpleUploadedFile("PRIVATENAME.vcf", b"x")})
        key = self.key(self.paste("25 28996360"))
        with mock.patch.object(results, "table", side_effect=duckdb.ConversionException("PRIVATEVALUE")):
            query = client.get(reverse("snpportal:results", args=[key]) + "?tab=table")
        for response in (pasted, uploaded, query):
            self.assertEqual(response.status_code, 500)
            report = ExceptionReporter(response.wsgi_request, *response.exc_info).get_traceback_text()
            self.assertNotIn("PRIVATE", report)
        self.assertEqual(self.leftovers(), [])

    def test_alias_warning_in_upload_qc(self):  # R7: HG993277.1 is read as chromosome 18, with a warning
        response = self.client.post(reverse("snpportal:upload"), {"snps": SimpleUploadedFile(
            "SYNTHETIC_alias.tsv", b"chrom\tpos\nHG993277.1\t1000\nHG993285.2\t19138923\n25\t28996360\n")})
        overview = self.client.get(response.url)
        self.assertContains(overview, "Chromosome name HG993277.1 (read as 18")
        self.assertContains(overview, "older chromosome 18 sequence")
        self.assertContains(overview, "chromosome name warning")  # the upload-warnings KPI
        self.assertContains(overview, "HG993285.2 → 26")  # .2 GenBank versions are accepted

    def test_qc_in_words(self):
        items = dict(results.qc({"format": "vcf", "rows_read": 3, "rejected": {"unknown_rsid": 1}, "columns_dropped": [],
                                 "ref_check_sampled": False, "ref_check": {"ok": 2}, "rsid": {"placed": 2, "unknown": 1},
                                 "assembly": {"verdict": "ok", "checked": 2, "mismatch_or_flip_share": 0.0}})[0])
        self.assertEqual(items["File format"], "VCF")
        self.assertEqual(items["Rows rejected"], "1 rs IDs not in EVA release 9")
        self.assertEqual(items["Reference alleles"], "2 match the Ssal_v3.1 reference")
        self.assertIn("2 by their Ssal_v3.1 rs position", items["Placed by rs ID (EVA release 9)"])
        self.assertTrue(items["Assembly check"].startswith("Ssal_v3.1 confirmed"))
        self.assertNotIn("Columns not kept", items)  # empty: left out
        clean = {"rows_read": 3, "snps_kept": 3, "rejected": {}, "assembly": {"verdict": "ok"}, "ref_check": {"ok": 3}}
        self.assertEqual(results.qc_line(clean), "3 rows read · 3 scored · 0 rejected · Ssal_v3.1 confirmed")
        self.assertFalse(results.qc_problem(clean))  # the one-line QC stays closed
        for problem in ({"snps_kept": 2}, {"rejected": {"bad_pos": 1}}, {"indels": 1}, {"rsid": {"moved_from_icsasg_v2": 1}},
                        {"alias_warnings": [{"from": "x"}]}, {"assembly": {"verdict": "warning"}}, {"ref_check": {"ok": 2, "mismatch": 1}}):
            self.assertTrue(results.qc_problem({**clean, **problem}), problem)  # ... and opens by itself on any problem

    def test_qc_warning_is_snpscores_verdict(self):
        counts = {"ok": 85, "mismatch": 15, "not_snp": 100}
        self.assertEqual(results.qc({"ref_check": counts, "assembly": {"verdict": "warning", "message": "15% ..."}})[1], "15% ...")
        self.assertIsNone(results.qc({"ref_check": counts, "assembly": {"verdict": "ok"}})[1])


@skipUnless(os.environ.get("SNPSCORE_DEV") and (SNPSCORE / "release" / "dev").exists(), "SNPSCORE_DEV=1 with release/dev")
class DevLoadTest(SimpleTestCase):
    def test_public_vcf_scores_in_the_background(self):
        """P1.3: the 1.6M-site public VCF: the POST returns at once and the job finishes on the pool; then the heavy
        pages (a deep sort, the panel, a whole-list export) at the 2 GB DuckDB limit (timings printed)."""
        with tempfile.TemporaryDirectory() as tmp, override_settings(
                SNPSCORE_RELEASE=str(SNPSCORE / "release" / "dev"), SNPPORTAL_RESULTS_DIR=tmp, SNPPORTAL_WORKERS=1):
            t0 = time.time()
            with open(SNPSCORE / "data" / "raw" / "12_samples_genotype_filtered_on_504.vcf.gz", "rb") as f:
                response = self.client.post(reverse("snpportal:upload"), {"snps": f})
            posted = time.time() - t0
            self.assertEqual(response.status_code, 302)
            self.assertLess(posted, 30)
            key = response.url.split("/")[-2]
            while jobs.status(key)["state"] in ("queued", "running") and time.time() - t0 < 1800:
                time.sleep(2)
            job, finished = jobs.status(key), time.time() - t0
            self.assertEqual(job["state"], "done", job.get("error"))
            pages = {}
            for tab in ("overview", "table"):
                self.client.get(f"{response.url}?tab={tab}&trait=liver")
                t = time.time()
                self.assertEqual(self.client.get(f"{response.url}?tab={tab}&trait=liver").status_code, 200)
                pages[tab] = round(time.time() - t, 3)
            download = reverse("snpportal:download", args=[key])
            for name, url in (("table by gene, last page", f"{response.url}?tab=table&trait=liver&sort=gene&page=999999"),
                              ("panel (designed)", f"{response.url}?tab=panel&trait=liver"),
                              ("TSV of all SNPs", f"{download}?trait=liver&scope=all&format=tsv")):
                t = time.time()
                page = self.client.get(url)
                self.assertEqual(page.status_code, 200, name)
                for _ in page.streaming_content if page.streaming else ():  # stream it, as a browser would
                    pass
                pages[name] = round(time.time() - t, 3)
            print(f"\ndev load: {job['n_rows']:,} SNPs; POST {posted:.1f} s; job {finished:.0f} s; "
                  f"stages {job['timings']}; warm pages {pages}")


class _Boosted(HTMLParser):
    """Collects the hrefs of links that htmx boosts (an hx-boost="true" ancestor and no closer "false")."""
    VOID = {"input", "br", "img", "meta", "link", "hr", "source", "wbr"}

    def __init__(self):
        super().__init__()
        self.stack, self.hrefs = [], set()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        boost = attrs.get("hx-boost", self.stack[-1][1] if self.stack else "false")
        if tag == "a" and boost == "true" and "href" in attrs:
            self.hrefs.add(attrs["href"][:1])
        if tag not in self.VOID:
            self.stack.append((tag, boost))

    def handle_endtag(self, tag):
        if any(t == tag for t, _ in self.stack):  # an unmatched end tag (e.g. an implied </p>) must not empty the stack
            while self.stack.pop()[0] != tag:
                pass


def boosted_links(html):
    """First characters of the boosted links' hrefs: {'?'} when they all stay on this page."""
    parser = _Boosted()
    parser.feed(html)
    return parser.hrefs


def snpscore_gene():
    """Some gene id from the fixture release's gene layer."""
    return jobs.connect([jobs.release()]).execute(f"SELECT id FROM read_parquet('{jobs.release() / 'gene.parquet'}') LIMIT 1").fetchone()[0]
