"""Explore without an upload (P5.1-P5.4) on a release built from salmo-snpscore's fixture: the search resolver and
suggestions, gene pages with candidates (with and without a pool), candidate jobs from genes and intervals, the
known-loci page, and the data, methods, help and run-locally pages generated from the release."""
import logging
import os
import re
import shutil
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import skipUnless

from django.test import SimpleTestCase, override_settings
from django.urls import reverse

import snpscore

from . import explore, jobs, palette, search

SNPSCORE = Path(__file__).resolve().parents[2] / "salmo-snpscore"
FIXTURE = SNPSCORE / "tests" / "fixture"
VGLL3, VGLL3_CHR21 = "ENSSSAG00000053708", "ENSSSAG00000099564"


@skipUnless(FIXTURE.exists(), "needs the salmo-snpscore repo next to this one")
class ExploreTest(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tmp = tempfile.TemporaryDirectory()
        cls.release = Path(cls.tmp.name).resolve() / "release"
        if os.environ.get("SNPPORTAL_TEST_RELEASE"):
            shutil.copytree(os.environ["SNPPORTAL_TEST_RELEASE"], cls.release)
        else:
            snpscore.build(SNPSCORE / "layers.yaml", FIXTURE, cls.release)
        shutil.rmtree(cls.release / "pool", ignore_errors=True)  # the pool is tested on a copy below
        cls.override = override_settings(SNPSCORE_RELEASE=str(cls.release), SNPPORTAL_RESULTS_DIR=str(Path(cls.tmp.name) / "results"),
                                          SNPPORTAL_WORKERS=0)
        cls.override.enable()
        logging.disable(logging.WARNING)  # job log lines

    @classmethod
    def tearDownClass(cls):
        logging.disable(logging.NOTSET)
        cls.override.disable()
        cls.tmp.cleanup()
        super().tearDownClass()

    def copy(self):
        """A copy of the test release to change, used with override_settings(SNPSCORE_RELEASE=...)."""
        folder = Path(tempfile.mkdtemp(dir=self.tmp.name)).resolve() / "release"
        shutil.copytree(self.release, folder)
        return folder

    def search(self, q):
        return self.client.get(reverse("snpportal:search"), {"q": q})

    def public_sites(self, release, windows):
        """Rows of public_af.parquet inside 1-based windows, counted independently of explore.py."""
        where = " OR ".join(f"(chrom = '{c}' AND \"end\" BETWEEN {a} AND {b})" for c, a, b in windows)
        return jobs.connect([release]).execute(f"SELECT count(*) FROM read_parquet('{release / 'public_af.parquet'}') WHERE {where}").fetchone()[0]

    def test_search_resolver(self):
        page = self.search("vgll3")  # the chr25 maturation copy (catalogue) and Ensembl's chr21 'vgll3'
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, reverse("snpportal:gene", args=[VGLL3]))
        self.assertContains(page, reverse("snpportal:gene", args=[VGLL3_CHR21]))
        self.assertLess(page.content.decode().index(VGLL3), page.content.decode().index(VGLL3_CHR21))  # catalogue copy first
        both = self.client.get(reverse("snpportal:suggest"), {"q": "VGLL3"})  # human ortholog symbol: both salmon copies
        self.assertContains(both, VGLL3)
        self.assertContains(both, VGLL3_CHR21)
        for q in ("ssa25:28,990,000-29,000,000", "chr25:28.99-29.0Mb", "NC_059466.1:28990000-29000000", "25:29,000,000-28,990,000"):
            response = self.search(q)
            self.assertEqual(response.status_code, 302, q)
            self.assertIn("r=25%3A28990000-29000000", response.url, q)
            self.assertIn("chrom=25&start=28990000&end=29000000", response.url, q)
        for q in ("25:28996360", "NC_059466.1:28996360", "ssa25 28996360"):
            self.assertEqual(self.search(q).url, reverse("snpportal:variant", args=["25-28996360"]), q)
        self.assertEqual(self.search(VGLL3.lower()).url, reverse("snpportal:gene", args=[VGLL3]))
        self.assertContains(self.search("zzzz"), "Nothing matches")
        self.assertEqual(search.region("chrUn:12"), None)

        # R6: rs IDs (the catalogue's, else EVA release 9 through snpscore.rsid) and NCBI LOC symbols
        self.assertEqual(self.search("rs3108342415").url, reverse("snpportal:variant", args=["9-23839717-C-T"]))
        self.assertEqual(self.search("RS863231655").url, reverse("snpportal:variant", args=["26-15391479-C-G"]))
        self.assertContains(self.search("rs1"), "EVA release 9")
        self.assertContains(self.client.get(reverse("snpportal:suggest"), {"q": "rs863239503"}), "ICSASG_v2 9:25,753,517")
        for q in ("ICSASG_v2 25:28656101", "v2 ssa25:28,656,101", "CM003303.1:28656101"):  # ICSASG_v2 via the rs table
            self.assertEqual(self.search(q).url, reverse("snpportal:variant", args=["25-28996360-C-T"]), q)
        self.assertContains(self.search("ICSASG_v2 25:1"), "No EVA release 9 rs ID sits at this")
        self.assertIsNone(search.v2_position("25:28656101"))  # without the prefix a position is Ssal_v3.1
        self.assertEqual(self.search("LOC100195380").url, reverse("snpportal:gene", args=["ENSSSAG00000106352"]))
        self.assertContains(self.search("LOC999"), "LOC symbols are found only")

        many = self.client.get(reverse("snpportal:suggest"), {"q": "cadherin"})  # descriptions
        self.assertLessEqual(many.content.decode().count("<li"), 10)
        self.assertGreater(many.content.decode().count("<li"), 1)
        self.assertIn("resolve;dur=", many["Server-Timing"])
        self.assertEqual(len(search.resolve("c", limit=10)), 10)

    def test_landing_and_known_loci(self):
        landing = self.client.get(reverse("snpportal:landing"))
        self.assertContains(landing, "chromatin conditions")
        self.assertContains(landing, "<b>21</b>", html=False)
        self.assertContains(landing, reverse("snpportal:known_loci"))
        self.assertContains(landing, 'id="known-loci"')
        self.assertContains(landing, 'class="sp-card sp-hero"')  # the vgll3 thumbnail
        self.assertContains(landing, "#trait-pd_resistance")
        self.assertContains(landing, f'action="{reverse("snpportal:candidates")}"')
        page = self.client.get(reverse("snpportal:known_loci"))
        self.assertContains(page, "https://doi.org/10.1038/nature16062")
        self.assertContains(page, '>effect allele T</span>', html=False)  # vgll3 Met54Thr effect allele
        self.assertContains(page, reverse("snpportal:gene", args=[VGLL3_CHR21]))  # the ohnolog caveat
        self.assertContains(page, "unnamed in Ensembl 116")
        for trait in ("age_at_maturity", "pd_resistance", "flesh_colour", "sex_determination"):  # R3: grouped by trait
            self.assertContains(page, f'id="trait-{trait}"')
        self.assertContains(page, 'sp-ev sp-ev-missense" title="missense (candidate causal)"')
        self.assertContains(page, ">suggestive</span>")  # sea lice rows
        self.assertContains(page, f'{reverse("snpportal:search")}?q=rs863754587')
        self.assertContains(page, "https://salmobase.org/genes/id/ENSSSAG00000053708?assembly=Ssal_v3.1")

        release = self.copy()  # a QTL interval row is PROVISIONAL
        path = release / "catalog" / "known_loci.tsv"
        lines = path.read_text().splitlines()
        header = lines[0].split("\t") + ["type", "start", "end"]
        row = {"chrom": "26", "id": "SYNTHETIC_qtl", "locus": "SYNTHETIC test interval", "trait": "age_at_maturity",
               "evidence": "qtl", "type": "qtl_interval", "start": "14500000", "end": "15000000"}
        lines = ["\t".join(header)] + [line + "\t\t\t" for line in lines[1:]] + ["\t".join(row.get(h, "") for h in header)]
        path.write_text("\n".join(lines) + "\n")
        with override_settings(SNPSCORE_RELEASE=str(release)):
            page = self.client.get(reverse("snpportal:known_loci")).content.decode()
        row = page[page.index("SYNTHETIC test interval"):]
        self.assertIn("PROVISIONAL", row[:600])
        self.assertIn("r=26%3A14500000-15000000", row)

    def test_gene_page(self):
        url = reverse("snpportal:gene", args=[VGLL3])
        page = self.client.get(url)
        self.assertContains(page, "<h1>vgll3", html=False)  # catalogue name; unnamed in Ensembl
        self.assertContains(page, "VGLL3")
        self.assertContains(page, 'id="fig-expression"')
        self.assertContains(page, reverse("snpportal:variant", args=["25-28996360"]))  # vgll3 Met54Thr is a public site
        self.assertEqual(page.content.decode().count('class="text-nowrap" title='), 21)  # 21 condition columns
        self.assertContains(page, 'id="ohnolog"')
        self.assertContains(page, "hx-get=\"" + reverse("snpportal:locus_svg"))
        self.assertContains(page, "Score these")
        svg = self.client.get(url, {"download": "expression.svg"})
        self.assertEqual(ET.fromstring(svg.content).get("role"), "img")
        self.assertNotIn(b"var(--", svg.content)

        tsv = self.client.get(url, {"download": "candidates.tsv", "trait": "maturation"}).content.decode().splitlines()
        comments = [line for line in tsv if line.startswith("#")]
        self.assertIn("PROVISIONAL", "\n".join(comments))
        self.assertTrue(tsv[len(comments)].startswith("chrom\tpos\t"))
        window = ("25", 28995075 - explore.FLANK, 28999268 + explore.FLANK)
        self.assertEqual(len(tsv) - len(comments) - 1, self.public_sites(self.release, [window]))
        plain = self.client.get(url, {"download": "candidates.tsv", "plain": "1"}).content.decode()
        self.assertTrue(plain.startswith("chrom\t"))
        tiers = [int(line.split("\t")[plain.splitlines()[0].split("\t").index("tier")]) for line in plain.splitlines()[1:]]
        self.assertEqual(tiers, sorted(tiers))  # sorted by tier by default
        self.assertEqual(self.client.get(url, {"sort": "maf", "flank": "10000", "trait": "nope"}).status_code, 200)
        self.assertEqual(self.client.get(reverse("snpportal:gene", args=["ENSSSAG0"])).status_code, 404)

    def test_candidate_jobs(self):
        text = f"{VGLL3}\n26:14.5-15Mb"
        response = self.client.post(reverse("snpportal:candidates"), {"targets": text, "flank": "50000", "trait": "maturation"})
        self.assertEqual(response.status_code, 302)
        self.assertIn("trait=maturation", response.url)
        job = jobs.read(response.url.split("/")[-2])
        windows = [("25", 28995075 - 50000, 28999268 + 50000), ("26", 14_500_000, 15_000_000)]
        self.assertEqual((job["state"], job["input_kind"]), ("done", "from_rows"))
        self.assertEqual(job["n_rows"], self.public_sites(self.release, windows))
        self.assertEqual(self.client.get(response.url).status_code, 200)  # 'Score these' lands on a results page
        for targets, message in [("vgll3", "matches 2 genes"), ("nosuchgene", "is not a gene id"), ("", "at least one")]:
            self.assertContains(self.client.post(reverse("snpportal:candidates"), {"targets": targets}), message, status_code=400)
        self.assertEqual(self.client.get(reverse("snpportal:candidates")).status_code, 405)

    @skipUnless(hasattr(snpscore, "build_pool") or (SNPSCORE / "src" / "snpscore" / "pool.py").exists(), "needs snpscore.pool")
    def test_pool_gives_the_same_candidates(self):
        from snpscore.pool import build_pool
        window = [("25", 28995075 - explore.FLANK, 28999268 + explore.FLANK)]
        fresh = explore.candidates(window, "maturation")
        release = self.copy()
        build_pool(release, FIXTURE / "ALL_chrome_phased_filtered_HWE_1e6_biSNPs_MAF_0.01.sites.vcf.gz", threads=2, memory_limit="1GB")
        with override_settings(SNPSCORE_RELEASE=str(release)):
            pooled = explore.candidates(window, "maturation")
            page = self.client.get(reverse("snpportal:gene", args=[VGLL3]))
        self.assertEqual((fresh[2], pooled[2]), ("annotated now", "pool"))
        pick = lambda rows: [(r["pos"], r["ref"], r["alt"], r["tier"], r["tier_evidence"]) for r in rows]
        self.assertEqual(pick(fresh[0]), pick(pooled[0]))
        self.assertNotContains(page, "annotated now")
        self.assertContains(page, "504-fish reference panel (release pool)")

    def test_about_pages(self):
        data = self.client.get(reverse("snpportal:about_data"))
        for layer in jobs.manifest()["layers"]:
            self.assertContains(data, f'id="layer-{layer["name"]}"')
            self.assertContains(data, layer["sha256"][:12])
        self.assertContains(data, "Population scope")
        self.assertContains(data, "Bertolotti et al. 2020")  # public_af's population (R1)
        self.assertContains(data, 'id="cite"')  # R8: citation block and ENA projects
        self.assertContains(data, "https://doi.org/10.64898/2025.12.18.695160")
        self.assertContains(data, "https://www.ebi.ac.uk/ena/browser/view/PRJEB47409")
        self.assertContains(data, "rsid.parquet")

        help_page = self.client.get(reverse("snpportal:help")).content.decode()
        for anchor in ("state-Active_TSS", "term-active", "tiers", "format-plink", "format-illumina", "header-aliases", "privacy", "liftover"):
            self.assertIn(f'id="{anchor}"', help_page)
        self.assertIn("mapinfo", help_page)
        self.assertIn('class="sp-state stp-aquafaang-Active_TSS"', help_page)  # the two state palettes side by side
        self.assertIn('id="format-rsid"', help_page)  # rs-only uploads (R6)
        self.assertIn("unknown_rsid", help_page)
        self.assertIn("ssa25", help_page)
        methods = self.client.get(reverse("snpportal:methods")).content.decode()
        for anchor in re.findall(r'help/#([\w-]+)"', methods):  # every glossary link from the methods page resolves
            self.assertIn(f'id="{anchor}"', help_page, anchor)
        self.assertIn("Methods text for a paper", methods)

        release = self.copy()  # editing weights.yaml changes the tables; extra blocks are shown and badged
        weights = release / "weights.yaml"
        text = weights.read_text().replace("active: 3", "active: 7").replace("provisional: [", "provisional: [assay, ")
        weights.write_text(text + "\nassay:\n  gc: [0.3, 0.7]\n  max_homopolymer: 6\n")
        (release / "benchmark.tsv").write_text("# SYNTHETIC test data written by tests_explore (seed 0): not real results\n"
                                               "feature\tpositives\tcontrols\tshare_pos\tshare_ctrl\tenrichment\n"
                                               "chromatin\t6\t60\t0.5\t0.1\t5.0\nregion\t6\t60\t0.0\t0.2\t0.0\n")
        with override_settings(SNPSCORE_RELEASE=str(release)):
            edited = self.client.get(reverse("snpportal:methods")).content.decode()
            svg = self.client.get(reverse("snpportal:methods"), {"download": "benchmark.svg"})
            local = self.client.get(reverse("snpportal:run_locally"), {"trait": "maturation"})
        self.assertIn('<td class="sp-num">7</td>', edited)
        self.assertIn("Assay settings", edited)
        self.assertIn("0.3, 0.7", edited)
        section = edited[edited.index('id="block-assay"'):]
        self.assertIn("PROVISIONAL", section[:400])
        self.assertIn("smoke test only", edited)
        self.assertEqual(ET.fromstring(svg.content).get("role"), "img")
        self.assertContains(local, "--trait maturation")
        self.assertContains(local, jobs.release_info()["sha256"])


    def test_viewer_palette_cookie(self):  # R8: the footer toggle picks the state palette per viewer
        help_url = reverse("snpportal:help")
        try:
            page = self.client.get(help_url)
            self.assertContains(page, ".st-Active_TSS{background:#B2182B")
            self.assertContains(page, f'{reverse("snpportal:state_palette")}?name=aquafaang')
            switch = self.client.get(reverse("snpportal:state_palette"), {"name": "aquafaang"}, HTTP_REFERER=f"http://testserver{help_url}")
            self.assertEqual(switch.url, f"http://testserver{help_url}")
            self.assertEqual(switch.cookies[palette.COOKIE].value, "aquafaang")
            page = self.client.get(help_url)  # the client sends the cookie back
            self.assertContains(page, ".st-Active_TSS{background:#BF2026")
            self.assertContains(page, '<strong aria-current="true">AQUA-FAANG itemRgb</strong>')
            only = set(palette.STATE_PALETTES["aquafaang"].values()) - set(palette.STATE_PALETTES["portal"].values()) - {"#FFFFFF"}
            self.assertTrue(any(colour in explore.hero() for colour in only))  # figures too
            away = self.client.get(reverse("snpportal:state_palette"), {"name": "nope"}, HTTP_REFERER="https://elsewhere.example/")
            self.assertEqual(away.url, reverse("snpportal:landing"))  # other sites' referers are not followed
            self.assertNotIn(palette.COOKIE + "=nope", str(away.cookies))
            self.client.cookies.pop(palette.COOKIE)
            self.assertContains(self.client.get(help_url), ".st-Active_TSS{background:#B2182B")
        finally:
            palette.choose(None)  # the test client runs requests in this thread

    async def test_viewer_palette_cookie_asgi(self):  # the same cookie under ASGI (request_started carries the scope)
        self.async_client.cookies[palette.COOKIE] = "aquafaang"
        try:
            self.assertContains(await self.async_client.get(reverse("snpportal:help")), ".st-Active_TSS{background:#BF2026")
        finally:
            palette.choose(None)


@skipUnless(os.environ.get("SNPSCORE_DEV") and (SNPSCORE / "release" / "dev").exists(), "SNPSCORE_DEV=1 with release/dev")
class ExploreDevTest(SimpleTestCase):
    def test_timings(self):
        """P5.1: suggest/ timings on release/dev (reported, not asserted), and the gene page."""
        with override_settings(SNPSCORE_RELEASE=str((SNPSCORE / "release" / "dev").resolve())):
            times = {}
            for q in ("vgll3", "VGLL3", "six", "cadherin", "ENSSSAG0000005", "25:28996360"):
                self.client.get(reverse("snpportal:suggest"), {"q": q})
                t = time.time()
                response = self.client.get(reverse("snpportal:suggest"), {"q": q})
                times[q] = round(1000 * (time.time() - t))
                self.assertLessEqual(response.content.decode().count("<li"), 10)
            t = time.time()
            self.assertEqual(self.client.get(reverse("snpportal:gene", args=[VGLL3])).status_code, 200)
            print(f"\nsuggest ms {times}; gene page {time.time() - t:.2f} s")
