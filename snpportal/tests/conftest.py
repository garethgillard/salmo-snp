"""pytest tests of the portal's plain-Python modules (snpportal.lib), run from snpportal/: python -m pytest tests.
They share snpscore's test helpers (a range server, a bigWig writer) and build releases from snpdata's fixture."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # snpportal/
DATA = ROOT.parent / "snpdata"
sys.path[:0] = [str(ROOT), str(ROOT.parent / "snpscore" / "tests")]


def pytest_configure(config):
    config.addinivalue_line("markers", "dev: needs the genome-wide release/dev (run with SNPSCORE_DEV=1)")
