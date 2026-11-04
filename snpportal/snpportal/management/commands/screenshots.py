"""python manage.py screenshots PAGE [PAGE ...] [--base URL] [--out DIR] [--width PX] [--viewport]: PNG screenshots of a
running portal's pages, for reviewing a change (cloud sessions send them to the chat; AGENTS.md "Cloud sessions").

PAGE is a path under the portal (`/snp/`, `/snp/locus/?r=25:28980000-29020000`) or a full URL. Each page is opened in
headless Chrome (tour_images' DevTools pipe, so no extra packages), waited for until htmx has settled, and saved as
<out>/<n>-<page>.png: the whole page (or only the window with --viewport), at 2x for sharp text. Prints each file with
the page's height and whether htmx and Bootstrap loaded (a CDN or SRI failure shows here as 'no')."""
from __future__ import annotations

import base64
import re
import shutil
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from .tour_images import CHROMES, Chrome


class Command(BaseCommand):
    help = "Screenshots of a running portal's pages (headless Chrome), for reviewing a change"

    def add_arguments(self, parser):
        parser.add_argument("pages", nargs="+", help="paths under the portal (/snp/...) or full URLs")
        parser.add_argument("--base", default="http://127.0.0.1:8000", help="the running portal (default: salmo-snp serve's)")
        parser.add_argument("--out", default="screenshots", help="folder for the PNGs (made if missing)")
        parser.add_argument("--width", type=int, default=1440, help="window width in CSS px (default 1440)")
        parser.add_argument("--viewport", action="store_true", help="only the first screen (900 px high), not the whole page")
        parser.add_argument("--chrome", default=None, help="Chrome or Chromium binary (default: the first one found)")

    def handle(self, *args, **opts):
        binary = opts["chrome"] or next((c for c in CHROMES if shutil.which(c) or Path(c).exists()), None)
        if not binary:
            raise CommandError("No Chrome found: give --chrome")
        out = Path(opts["out"])
        out.mkdir(parents=True, exist_ok=True)
        chrome = Chrome(binary)
        try:
            for n, page in enumerate(opts["pages"], 1):
                url = page if "://" in page else opts["base"].rstrip("/") + "/" + page.lstrip("/")
                chrome.size(opts["width"], 900)
                chrome.open(url)
                height = 900 if opts["viewport"] else int(chrome.js("document.documentElement.scrollHeight"))
                chrome.send("Emulation.setDeviceMetricsOverride", True, width=opts["width"], height=min(height, 16000),
                            deviceScaleFactor=2, mobile=False)
                png = chrome.send("Page.captureScreenshot", True, format="png", captureBeyondViewport=True)["data"]
                name = re.sub(r"[^A-Za-z0-9]+", "-", page.split("://")[-1].replace("/snp/", "/")).strip("-")[:60] or "home"
                path = out / f"{n:02d}-{name}.png"
                path.write_bytes(base64.b64decode(png))
                libs = chrome.js("[typeof htmx !== 'undefined', typeof bootstrap !== 'undefined']")
                self.stdout.write(f"{path}  {opts['width']}x{height}  htmx {'yes' if libs[0] else 'no'}, "
                                  f"bootstrap {'yes' if libs[1] else 'no'}")
        finally:
            chrome.close()
