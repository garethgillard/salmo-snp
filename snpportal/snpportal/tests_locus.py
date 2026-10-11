"""Locus browser, evidence card and variant page on a release built from salmo-snpscore's fixture, offline: signal rows
come from SYNTHETIC bigWigs written at test time (salmo-snpscore tests/bbi_writer.py) and served by its
tests/range_server.py. With SNPSCORE_LIVE=1 one test reads the real salmobase bigWigs and prints timings."""
import logging
import os
import re
import shutil
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock, skipUnless

from django.template.loader import render_to_string
from django.test import SimpleTestCase, override_settings
from django.urls import reverse

import snpscore
from snpscore import bbi

from . import jobs, locus, palette

SNPSCORE = Path(__file__).resolve().parents[2] / "salmo-snpscore"
FIXTURE = SNPSCORE / "tests" / "fixture"
CONDITIONS = ["Brain_Immature_Female", "Brain_Mature_Male", "Gonad_Mature_Male", "Liver_Immature_Female"]
VGLL3 = "r=25:28,980,000-29,010,000"
SIGNAL_PATH = 'fill-opacity="0.85"'  # one per drawn signal row


class Tiles(dict):
    """A tile cache that keeps every key it was given."""

    def get_many(self, keys):
        return {k: self[k] for k in keys if k in self}

    def set_many(self, values):
        self.update(values)


def svg_of(html):
    """The first inline <svg> of a page."""
    return re.search(r"<svg .*?</svg>", html, re.S).group(0)


@skipUnless(FIXTURE.exists(), "needs the salmo-snpscore repo next to this one")
class LocusTest(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        sys.path.insert(0, str(SNPSCORE / "tests"))
        from bbi_writer import synthetic_registry
        from range_server import RangeServer
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name).resolve()
        cls.release = root / "release"
        if os.environ.get("SNPPORTAL_TEST_RELEASE"):
            shutil.copytree(os.environ["SNPPORTAL_TEST_RELEASE"], cls.release)
        else:
            snpscore.build(SNPSCORE / "layers.yaml", FIXTURE, cls.release)
        (root / "tracks").mkdir()
        cls.patches = [mock.patch.object(bbi, "ALLOWED_HOSTS", {"127.0.0.1"}), mock.patch.object(bbi, "ALLOWED_SCHEMES", ("http",))]
        [p.start() for p in cls.patches]
        cls.server = RangeServer(root / "tracks", delay=2.0)
        registry = synthetic_registry(root / "tracks", cls.server.url, CONDITIONS, slow=["Gonad_Mature_Male"])
        cls.override = override_settings(SNPSCORE_RELEASE=str(cls.release), SNPPORTAL_RESULTS_DIR=str(root / "results"),
                                          SNPPORTAL_WORKERS=0, SNPPORTAL_TRACKS=str(registry), SNPPORTAL_SIGNAL_DEADLINE=1.0)
        cls.override.enable()
        logging.disable(logging.WARNING)  # job log lines and 'no data from <slow track>'

    @classmethod
    def tearDownClass(cls):
        logging.disable(logging.NOTSET)
        cls.override.disable()
        cls.server.close()
        [p.stop() for p in cls.patches]
        cls.tmp.cleanup()
        super().tearDownClass()

    def setUp(self):
        self.tiles = Tiles()
        patch = mock.patch.object(locus, "tile_cache", return_value=self.tiles)
        patch.start()
        self.addCleanup(patch.stop)

    def get(self, url, **headers):
        response = self.client.get(url, **headers)
        self.assertEqual(response.status_code, 200, url)
        return response.content.decode()

    def test_locus_page_groups(self):
        page = self.get(f"{reverse('snpportal:locus')}?{VGLL3}")
        for group in ("genes", "peaks", "hmm", "assays", "other"):  # track groups, closed by default
            self.assertIn(f'class="sp-grp" id="g-{group}"' if group != "assays" else 'class="sp-grp sp-sec" id="g-assays"', page)
        self.assertIn(palette.CENTRE, page)  # the centre position on the ruler
        self.assertIn("ENSSSAG00000053708", page)  # the vgll3 gene model, black, with its Ss4R duplicate linked
        self.assertRegex(page, r">(← )?vgll3( →)?</text>")
        self.assertIn("duplicate chr21:33.00 Mb", page)
        self.assertIn("Ss4R block, duplicated on chr21", page)  # the chromosome: the block around the window
        self.assertIn("504-fish panel: MAF 0.48, alt AF 0.48", page)  # public variant at vgll3 Met54Thr (R1)
        self.assertIn("AQUA-FAANG 12 fish: alt AF 0.67, DR2 1.00", page)
        self.assertIn("vgll3_Met54Thr", page)
        self.assertNotIn("g-bgee", page)  # no Bgee expression on the locus browser
        self.assertIn("conditions with the peak", page)  # regulatory elements: the unified robust peaks
        self.assertIn("inside robust peaks", page)  # no ChromHMM in this registry: states in peaks
        self.assertIn('class="st-Active_TSS"', page)  # the state legend, in its group
        self.assertNotIn("Display options", page)
        self.assertNotIn('name="trait"', page)  # no trait on the locus browser
        self.assertIn(f'hx-get="{reverse("snpportal:locus_assay")}?', page)  # assays load when their section opens
        self.assertIn('hx-push-url="/snp/locus/?r=25%3A', page)
        self.assertIn("https://salmobase.org/jbrowse/?assembly=Ssal_v3.1&amp;loc=25:28980000..29010000", page)
        self.assertIn('class="sp-grp open" id="g-peaks"', self.get(f"{reverse('snpportal:locus')}?{VGLL3}&open=peaks,nonsense"))

        wide = self.get(f"{reverse('snpportal:locus')}?r=25:28.88-29.2Mb")
        self.assertIn("GERP constrained element", wide)
        self.assertIn("molQTL lead (nf-RASQUAL, 12 fish): Brain ca 25:28963213-28965045", wide)  # the molQTL lane (R4)
        self.assertIn("AQUA-FAANG blacklist", wide)
        self.assertIn("LORe region", self.get(f"{reverse('snpportal:locus')}?r=26:19.1-19.2Mb"))
        self.assertIn('value="25:28,980,000-29,010,000"', self.get(f"{reverse('snpportal:locus')}?r=ssa25:28.98-29.01Mb"))  # aliases, Mb
        self.assertIn("wider than 2 Mb", self.get(f"{reverse('snpportal:locus')}?r=25:20-29Mb"))
        self.assertIn("Unknown chromosome", self.get(f"{reverse('snpportal:locus')}?r=ssa99:1-100"))
        self.assertIn('value="25:28,985,000-29,010,000"', self.get(reverse("snpportal:locus")))  # opens at vgll3

    def test_assay_group(self):
        url = f"{reverse('snpportal:locus_assay')}?{VGLL3}&assay=ATAC"
        with self.settings(SNPPORTAL_ASSAY_DEADLINE=1.0):  # the slow Gonad track misses it
            group = self.get(url)
            retried = self.get(url + "&retry=1")
        self.assertIn('id="g-ATAC"', group)
        self.assertIn("&amp;retry=1", group)  # it fetches itself once more
        self.assertIn("1 of 4 files did not load in time", retried)
        self.assertNotIn("data-retry", retried)  # but only once
        self.assertIn("Brain Imm F", group)
        self.assertEqual(group.count("<polygon"), 2 + 3)  # Brain and Liver stacked (Gonad missed it), three conditions read
        self.assertIn("1 of 4 files did not load in time", group)
        self.assertIn('class="sp-grp open" id="g-ATAC"', self.get(url + "&open=ATAC"))
        self.assertEqual(self.client.get(f"{reverse('snpportal:locus_assay')}?{VGLL3}&assay=nope").status_code, 400)

    def test_fragment_download_and_moves(self):
        url = f"{reverse('snpportal:locus_svg')}?{VGLL3}"
        fragment = self.get(url, HTTP_HX_REQUEST="true", HTTP_HX_TARGET="locus-view")
        self.assertIn('id="locus-view"', fragment)
        self.assertNotIn("sp-nav", fragment)  # only the swapped part
        moved = re.findall(r'hx-get="/snp/locus/svg/\?([^"]+)"', fragment)
        self.assertEqual(len(moved), 4)  # zoom out, zoom in, left, right
        self.assertTrue(all(m.startswith("r=25%3A") for m in moved))
        response = self.client.get(url + "&download=1")
        self.assertIn("attachment", response["Content-Disposition"])
        root = ET.fromstring(response.content.decode())  # standalone and valid XML
        self.assertIn("manifest sha256", root.find("{http://www.w3.org/2000/svg}desc").text)
        self.assertNotIn("<a href", response.content.decode())  # no links in a downloaded file

    def test_tiles_cached_and_never_keyed_by_user_positions(self):
        bbi.clear_caches()
        self.server.requests.clear()
        url = f"{reverse('snpportal:locus_svg')}?{VGLL3}"  # preset 'all': two fast synthetic tracks
        first = self.get(url)
        self.assertEqual(first.count(SIGNAL_PATH), 2)
        self.assertTrue(self.server.requests)
        n = len(self.server.requests)
        self.assertEqual(self.get(url), first)
        self.assertEqual(len(self.server.requests), n)  # the same view again: no range requests at all

        positions = [28996360, 28998410, 28990123]
        key = jobs.create_from_rows([("25", p, f"snp{i}", "C", "T") for i, p in enumerate(positions)], "Test rows")
        page = self.get(f"{reverse('snpportal:locus')}?{VGLL3}&key={key}&trait=maturation")
        self.assertIn(f"/snp/results/{key}/snp/0/", page)  # lollipops open the card
        self.assertTrue(self.tiles)
        for k in self.tiles:
            self.assertFalse(any(str(p) in k or f"{p:,}" in k for p in positions), k)
            self.assertNotIn(str(key), k)
        self.assertEqual(self.client.get(f"{reverse('snpportal:locus')}?key=00000000-0000-0000-0000-000000000000").status_code, 404)
        centred = self.get(f"{reverse('snpportal:locus')}?key={key}&row=1")  # opened from a card: no coordinates in the URL
        self.assertIn('value="25:28,993,410-29,003,409"', centred)
        self.assertIn(">28,998,410</text>", centred)  # the centre: the SNP, in red on the ruler
        bare = Path(self.tmp.name) / "bare.tsv"  # a list with no id, ref or alt column (e.g. a chip of chrom, pos)
        bare.write_text("chrom\tpos\n25\t28996360\n")
        key = jobs.create(bare, ".tsv", label="Positions only")
        self.assertIn(f"/snp/results/{key}/snp/0/", self.get(f"{reverse('snpportal:locus')}?key={key}&row=0"))

    def test_card_and_variant_page(self):
        key = jobs.create_from_rows([("25", 28996360, "vgll3_Met54Thr", "C", "T"), ("26", 19138923, "bco1l", "A", "G"),
                                     ("25", 28964518, "mq", None, None)], "Card rows")
        page = self.get(reverse("snpportal:results", args=[key]) + "?tab=table&trait=brain&snp=0")  # the card, in the drawer
        self.assertIn("sp-caveat", page)  # the page's one caveat line
        card = page[page.index('id="drawer"'):]
        d = jobs.folder(key)
        scores = dict(jobs.connect([d]).execute(f"SELECT file_row_number, tier_score__brain FROM read_parquet('{d / 'tiers.parquet'}')").fetchall())
        score, line = re.search(r">score (\d+)</span>", card).group(1), re.search(r'class="mb-2 sp-terms">(.*?)</p>', card, re.S).group(1)
        self.assertEqual(sum(int(w) for w in re.findall(r"\+(\d+)", line)), scores[0])  # the tier line sums to tier_score
        self.assertEqual(int(score), scores[0])
        self.assertIn('class="sp-fact" title="Known locus vgll3_Met54Thr', card)  # the key facts
        mini = svg_of(card[card.index("Locus &plusmn;20 kb"):])  # the mini locus browser, inline: the SNP +- the minimum spacing
        self.assertIn("<title>Mini locus browser</title>", mini)
        self.assertIn(">Your SNPs</text>", mini)  # the list's SNPs in the window, linked to their cards
        self.assertIn(f'href="/snp/results/{key}/snp/0/', mini)
        self.assertIn('<g opacity="0.3">', mini)  # no peak in Brain: out of the selection, so faded
        self.assertIn(">GERP</text>", mini)
        self.assertIn(f'href="/snp/locus/?key={key}&amp;row=0&amp;trait=Brain"', card)  # its button to the locus browser
        self.assertIn("exclude=0", card[:card.index('id="card-body"')])  # the +/− switch
        self.assertNotIn("data-next", card)  # no peak in Brain: not in the table, so no Previous/Next
        every = self.get(reverse("snpportal:results", args=[key]) + "?tab=table&snp=0")
        self.assertIn(" of 3</span>", every)  # its place in the table, and the rows either side
        self.assertTrue("data-next" in every or "data-prev" in every)
        out = self.get(reverse("snpportal:results", args=[key]) + "?tab=table&snp=0&exclude=0")
        self.assertIn("&minus; Not selected", out)  # taken out, it stays in the table while its card is open
        self.assertIn('class="sp-selected sp-out"', out)
        self.assertIn("include=0", out[out.index('id="drawer"'):])
        self.get(reverse("snpportal:results", args=[key]) + "?tab=table&include=0")
        self.assertIn("Missense p.Thr46Met (ENSSSAT00000230965; published as Met54Thr) +3", line)
        self.assertIn("No AQUA-FAANG peak in the 21 conditions sampled", card)  # one line instead of an empty grid
        self.assertNotIn("Chromatin state per condition", card)
        self.assertIn("Expression of the nearest gene (not necessarily the target)</summary>", card)  # closed
        self.assertIn('aria-label="Published association"', card)
        self.assertIn("effect allele T (alt) = early maturation (1SW)", card)  # said once, matched to the SNP's alleles
        self.assertIn('href="https://doi.org/10.1038/nature16062"', card)
        self.assertIn("Nearby: ", card)  # vgll3_Asn323Lys, 2 kb away
        self.assertNotIn("molQTL", card)  # not a lead SNP: no section
        self.assertIn("https://salmobase.org/genes/id/ENSSSAG00000053708?assembly=Ssal_v3.1", card)
        self.assertIn("VGLL3", card)
        self.assertIn('data-copy="25-28996360-C-T"', card)
        self.assertEqual(card.count("<h2"), 1)  # the drawer's heading is the only title
        mq = self.get(reverse("snpportal:results", args=[key]) + "?tab=table&trait=brain&snp=2")
        self.assertIn("caQTL (chromatin accessibility)", mq)  # the molQTL section (R4): the peak shown 1-based
        self.assertIn("25:28,963,214-28,965,045", mq)
        self.assertIn("no direction implied", mq)
        grid = svg_of(mq[mq.index("Chromatin state per condition"):])
        self.assertIn("Chromatin state per condition", grid)  # a peak somewhere: the grid
        self.assertEqual(grid.count('rx="3" fill="none"'), 4)  # the 4 Brain conditions of the trait are outlined
        swap = self.get(reverse("snpportal:card", args=[key, 2]) + "?trait=all", HTTP_HX_REQUEST="true", HTTP_HX_TARGET="card-body")
        self.assertNotIn("sp-nav", swap)  # a trait change swaps only the card
        self.assertIn('id="card-body"', swap)
        table = self.get(reverse("snpportal:results", args=[key]) + "?tab=table&molqtl=1")
        self.assertIn("1&ndash;1 of 1 shown", table)
        columns = [c[0] for c in jobs.connect([d]).execute(f"DESCRIBE SELECT * FROM read_parquet('{d / 'result.parquet'}')").fetchall()]
        self.assertEqual("Assay: " in card, "assay_status" in columns)  # only with assay columns
        bare = locus.evidence({"chrom": "25", "pos": 1, "tier": 4, "tier_score": 0, "tier_terms": []}, jobs.weights(), "all")
        self.assertEqual((bare.get("assay"), bare.get("grid"), bare.get("gene"), bare["terms"]), (None, None, None, None))
        two = locus.evidence({"chrom": "25", "pos": 1, "tier": 1, "tier_score": 6, "tier_evidence": "active: Brain; CDS",
                              "tier_terms": [{"term": "active", "weight": 3}, {"term": "coding", "weight": 3}]}, jobs.weights(), "all")
        self.assertEqual(two["terms"], [("active: Brain", 3), ("CDS (amino-acid effect not computed)", 3)])
        other = locus.evidence({"chrom": "25", "pos": 1, "ref": "C", "alt": "T", "public_af": False, "public_af_alleles": "other",
                                "public_af_maf": None}, jobs.weights(), "all")  # the panel has another variant here: no MAF
        self.assertTrue(other["maf"]["other"])
        self.assertIn(("Public variant (504-fish panel)", "a different variant at this position"), other["details"])
        self.assertIn("a different variant at this position", render_to_string("snpportal/card.html", {"ev": other}))
        why = svg_of(two["why"])  # the score bars only when two or more terms count
        self.assertEqual(sum(int(w) for w in re.findall(r": \+(\d+)</title>", why)), 6)
        ET.fromstring(mini)
        self.assertEqual(locus.flank_parts("ACGYT[A/G]NNA"), [("ACG", ""), ("Y", "var"), ("T", ""), ("[A/G]", "snp"), ("NN", "n"), ("A", "")])

        variant = self.get(reverse("snpportal:variant", args=["25-28996360-C-T"]))
        self.assertIn("vgll3_Met54Thr", variant)  # no upload: annotated on the fly
        self.assertIn("sp-tier-", variant)
        self.assertIn("conditions sampled", variant)
        self.assertIn("<title>Mini locus browser</title>", variant)
        self.assertIn("Open in the locus browser", variant)
        self.assertIn("25:28996360", self.get(reverse("snpportal:variant", args=["ssa25-28996360"])))
        self.assertEqual(self.client.get(reverse("snpportal:variant", args=["ssa99-1"])).status_code, 404)
        self.assertFalse([p for p in (Path(self.tmp.name) / "results").iterdir() if p.name.startswith(".")])


@skipUnless(os.environ.get("SNPSCORE_LIVE") == "1", "reads salmobase.org (SNPSCORE_LIVE=1; set SNPSCORE_CA_FILE)")
class LiveLocusTest(SimpleTestCase):
    def test_live_atac_rows(self):
        """P4.3b: the maturation preset at vgll3 renders 8 real Brain/Gonad ATAC rows; cold and warm timings printed."""
        dev = SNPSCORE / "release" / "dev"
        with override_settings(**({"SNPSCORE_RELEASE": str(dev)} if dev.exists() else {})), \
                mock.patch.object(locus, "tile_cache", return_value=Tiles()):
            bbi.clear_caches()
            url = f"{reverse('snpportal:locus_assay')}?region=25:28,990,000-29,000,000&assay=ATAC"
            t = time.time()
            cold = self.client.get(url).content.decode()
            t_cold, t = time.time() - t, time.time()
            self.client.get(url)
            t_warm = time.time() - t
            self.assertGreaterEqual(cold.count("<polygon"), 25)  # 25 conditions, means of 3 replicates
            self.assertNotIn("did not load", cold)
            print(f"\nlive locus: cold {t_cold:.2f} s ({bbi.STATS['requests']} requests), warm {t_warm:.2f} s")
