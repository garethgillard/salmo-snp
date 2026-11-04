"""Saved design projects (projects.py, ROADMAP I7) on a local install: save the Design panel as versions, compare two,
download one, export and import a project, open a version in the Design panel; and no projects on a server."""
import io
import logging
import tempfile
from pathlib import Path
from unittest import skipUnless

from django.test import SimpleTestCase, override_settings
from django.urls import reverse

import snpdata

SNPSCORE = Path(__file__).resolve().parents[2] / "snpscore"
DATA = SNPSCORE.parent / "snpdata"
FIXTURE = DATA / "tests" / "fixture"


@skipUnless(FIXTURE.exists(), "needs snpdata/ next to snpportal/")
class ProjectsTest(SimpleTestCase):
    def test_versions_diff_export_import_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            snpdata.build(DATA / "layers.yaml", FIXTURE, tmp / "release")
            with override_settings(SNPSCORE_RELEASE=str(tmp / "release"), SNPPORTAL_RESULTS_DIR=str(tmp / "results"),
                                   SNPPORTAL_PROJECTS_DIR=str(tmp / "projects"), SNPPORTAL_WORKERS=0, SNPPORTAL_LOCAL=True):
                logging.disable(logging.WARNING)
                try:
                    self.flow(tmp)
                finally:
                    logging.disable(logging.NOTSET)

    def flow(self, tmp):
        paste = "25 28996360 C T\n25 28998410 C G\n26 15000000\n"
        url = self.client.post(reverse("snpportal:upload"), {"paste": paste}).url.split("?")[0]
        key = url.rstrip("/").split("/")[-1]
        self.client.post(reverse("snpportal:panel_add", args=[key]))
        save = reverse("snpportal:panel_save")
        self.assertEqual(self.client.post(save, {"name": "Smolt chip 2027", "note": "first draft"}).status_code, 302)
        self.client.post(reverse("snpportal:panel_change"), {"drop": "25:28998410:C:G"})
        self.client.post(save, {"name": "Smolt chip 2027", "note": "without Asn323Lys"})
        page = self.client.get(reverse("snpportal:projects"), {"project": "Smolt-chip-2027", "a": 1, "b": 2}).content.decode()
        self.assertIn("first draft", page)
        self.assertIn("without Asn323Lys", page)
        self.assertIn("0 SNPs added, 1 removed", page)
        self.assertIn("25:28,998,410", page)  # the SNP dropped by hand, listed as removed
        tsv = b"".join(self.client.get(reverse("snpportal:project_download", args=["Smolt-chip-2027", 2])).streaming_content).decode()
        self.assertTrue(tsv.startswith("#"))  # provenance lines
        self.assertIn("28996360", tsv)
        self.assertNotIn("28998410", tsv)
        zipped = b"".join(self.client.get(reverse("snpportal:project_export", args=["Smolt-chip-2027"])).streaming_content)
        f = io.BytesIO(zipped)
        f.name = "project.zip"
        self.client.post(reverse("snpportal:project_import"), {"project": f})
        self.assertTrue((tmp / "projects" / "Smolt-chip-2027-2" / "v2" / "panel.parquet").exists())
        bad = io.BytesIO(b"not a zip")
        bad.name = "x.zip"
        self.assertIn("not a project", self.client.post(reverse("snpportal:project_import"), {"project": bad}, follow=True).content.decode())
        self.client.post(reverse("snpportal:project_open", args=["Smolt-chip-2027", 1]))
        panel = self.client.get(reverse("snpportal:design_panel")).content.decode()
        self.assertIn("Smolt chip 2027, version 1", panel)  # the version is the working panel's one source
        self.assertIn("<strong>3</strong> SNPs in the panel", panel)  # version 1: all three, the dropped one too
        self.assertEqual(self.client.get(reverse("snpportal:projects"), {"project": "../etc"}).status_code, 200)  # ignored
        with override_settings(SNPPORTAL_LOCAL=False):
            self.assertEqual(self.client.get(reverse("snpportal:projects")).status_code, 404)  # a server keeps no projects
