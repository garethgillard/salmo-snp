"""The portal's health (ROADMAP P8.4, P8.5): /snp/health/ and the release system check, and no log line holding a
coordinate (a SYNTHETIC canary SNP scored, viewed and exported)."""
import logging
import shutil
import tempfile
from pathlib import Path
from unittest import skipUnless

from django.core.management import call_command
from django.core.management.base import SystemCheckError
from django.test import SimpleTestCase, override_settings
from django.urls import reverse

import snpdata

DATA = Path(__file__).resolve().parents[2] / "snpdata"
FIXTURE = DATA / "tests" / "fixture"
CANARY = "25 28123457 A G"  # a position nothing else in the fixture has


class Collect(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.lines = []

    def emit(self, record):
        self.lines.append(self.format(record))


@skipUnless(FIXTURE.exists(), "needs snpdata/ next to snpportal/")
class HealthTest(SimpleTestCase):
    def test_health_check_and_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            snpdata.build(DATA / "layers.yaml", FIXTURE, tmp / "release")
            with override_settings(SNPSCORE_RELEASE=str(tmp / "release"), SNPPORTAL_RESULTS_DIR=str(tmp / "results"), SNPPORTAL_WORKERS=0):
                h = self.client.get(reverse("snpportal:health")).json()
                self.assertEqual((h["status"], h["release"]["ok"], h["results"]["writable"]), ("ok", True, True))
                self.assertEqual(h["queue"]["queued"], 0)
                call_command("check")  # an intact release passes
                handler, root = Collect(), logging.getLogger()
                root.addHandler(handler)
                level = root.level
                root.setLevel(logging.DEBUG)
                try:
                    url = self.client.post(reverse("snpportal:upload"), {"paste": CANARY}).url.split("?")[0]
                    key = url.rstrip("/").split("/")[-1]
                    for tab in ("", "table", "export"):
                        self.client.get(url, {"tab": tab} if tab else {})
                    b"".join(self.client.get(reverse("snpportal:download", args=[key]), {"scope": "all", "format": "tsv"}).streaming_content)
                finally:
                    root.removeHandler(handler)
                    root.setLevel(level)
                self.assertTrue(handler.lines)  # the job logged something
                self.assertFalse([x for x in handler.lines if "28123457" in x or "28,123,457" in x])  # never the coordinate
                with open(tmp / "release" / "gene.parquet", "r+b") as f:  # a damaged release fails the check
                    f.seek(50)
                    b = f.read(1)
                    f.seek(50)
                    f.write(bytes([b[0] ^ 0xFF]))
                with self.assertRaises(SystemCheckError) as e:
                    call_command("check")
                self.assertIn("gene.parquet differs from SHA256SUMS", str(e.exception))
                shutil.rmtree(tmp / "release")
                self.assertEqual(self.client.get(reverse("snpportal:health")).status_code, 503)
