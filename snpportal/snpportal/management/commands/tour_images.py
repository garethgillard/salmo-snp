"""python manage.py tour_images [--base URL] [--chrome PATH]: retake the guided tour's screenshots from a running portal.

Scores the example jobs the slides show through the Score form (known loci, the synthetic GWAS), then drives headless
Chrome over the DevTools protocol (a pipe, so no extra packages) in one fresh profile, so the Score page lists the results
it opened and the Design panel is its own: for each slide in explore.TOUR it POSTs the forms the slide needs first (e.g.
Add to panel), opens the page, clicks what the slide needs, crops to the slide's elements and saves
static/snpportal/tour/<slug>.webp, 1200 px wide. It also writes tour/tour.css, which places each numbered callout box over its image in %."""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, HTTPRedirectHandler, Request, build_opener

from django.core.management.base import BaseCommand, CommandError

from snpportal.explore import TOUR

OUT = Path(__file__).resolve().parents[2] / "static" / "snpportal" / "tour"
CHROMES = ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "google-chrome", "chromium", "chromium-browser")
WIDTH, MAX_RATIO, PAD, QUALITY = 1200, 0.68, 12, 82  # image width (px), tallest height/width, crop margin (CSS px), WebP quality
JOBS = {"snps": ("", "known_loci"), "gwas": ("gwas/", "gwas_maturation_SYNTHETIC")}
SUBMIT = """(async function (sel) {  // POST a button's form with the button's name=value, as a click would, staying on the page
  var b = document.querySelector(sel), data = new FormData(b.form);
  if (b.name) data.append(b.name, b.value);
  return (await fetch(b.form.action, {method: "POST", body: data, credentials: "same-origin"})).status;
})"""
FIND = """window.tourBox = function (spec) {  // [x, y, w, h] of an element, or of the union of a list; null if none is shown
  var find = function (sel) {
    if (sel.indexOf("text=") !== 0) return document.querySelector(sel);
    var walk = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT);
    while (walk.nextNode()) {
      var el = walk.currentNode;
      if (!el.children.length && el.textContent.trim() === sel.slice(5) && el.getClientRects().length) return el;
    }
  };
  var box = null;
  [].concat(spec).filter(function (s) { return s !== "row"; }).forEach(function (sel) {
    var el = find(sel), r = el && el.getBoundingClientRect();
    if (!r || !r.width) return;
    box = box ? [Math.min(box[0], r.left), Math.min(box[1], r.top), Math.max(box[2], r.right), Math.max(box[3], r.bottom)]
              : [r.left, r.top, r.right, r.bottom];
  });
  return box && [box[0], box[1], box[2] - box[0], box[3] - box[1]];
};"""


class Chrome:
    """Headless Chrome on --remote-debugging-pipe: DevTools messages on fds 3 (to Chrome) and 4 (from Chrome)."""

    def __init__(self, binary):
        to_r, to_w = os.pipe()
        from_r, from_w = os.pipe()
        os.set_inheritable(to_r, True)  # when a pipe end already is fd 3 or 4, dup2 onto itself keeps it close-on-exec
        os.set_inheritable(from_w, True)
        self.profile = tempfile.mkdtemp(prefix="tour-chrome-")

        def fds():
            os.dup2(to_r, 3)
            os.dup2(from_w, 4)
        self.proc = subprocess.Popen([binary, "--headless=new", "--remote-debugging-pipe", "--hide-scrollbars", "--no-first-run",
                                      "--no-default-browser-check", "--force-color-profile=srgb", f"--user-data-dir={self.profile}",
                                      "about:blank"], preexec_fn=fds, close_fds=False,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.close(to_r)
        os.close(from_w)
        self.out, self.inp, self.buf, self.n = os.fdopen(to_w, "wb"), from_r, b"", 0
        target = self.send("Target.createTarget", url="about:blank")["targetId"]
        self.session = self.send("Target.attachToTarget", targetId=target, flatten=True)["sessionId"]

    def send(self, method, page=False, **params):
        self.n += 1
        msg = {"id": self.n, "method": method, "params": params, **({"sessionId": self.session} if page else {})}
        self.out.write(json.dumps(msg).encode() + b"\0")
        self.out.flush()
        while True:  # skip events until our reply
            while b"\0" not in self.buf:
                chunk = os.read(self.inp, 1 << 20)
                if not chunk:
                    raise CommandError("Chrome closed the DevTools pipe")
                self.buf += chunk
            raw, self.buf = self.buf.split(b"\0", 1)
            reply = json.loads(raw)
            if reply.get("id") == self.n:
                if "error" in reply:
                    raise CommandError(f"{method}: {reply['error'].get('message')}")
                return reply["result"]

    def js(self, expression):
        result = self.send("Runtime.evaluate", True, expression=expression, returnByValue=True, awaitPromise=True)
        if "exceptionDetails" in result:
            raise CommandError(f"JavaScript error: {result['exceptionDetails'].get('text')} in {expression[:80]}")
        return result["result"].get("value")

    def size(self, width, height):
        self.send("Emulation.setDeviceMetricsOverride", True, width=width, height=height, deviceScaleFactor=1, mobile=False)

    def wait(self, condition, timeout=30):
        end = time.time() + timeout
        while not self.js(condition):
            if time.time() > end:
                raise CommandError(f"Timed out waiting for {condition}")
            time.sleep(0.2)

    def open(self, url):
        self.send("Page.navigate", True, url=url)
        time.sleep(0.3)
        self.wait("document.readyState === 'complete' && !document.querySelector('.htmx-request')", 60)
        self.js(FIND)

    def close(self):
        try:
            self.send("Browser.close")
            self.proc.wait(10)
        finally:
            shutil.rmtree(self.profile, ignore_errors=True)


def score_example(base, path, example):
    """Score a release example through the portal's own form; returns the job key once it has finished."""
    class Stay(HTTPRedirectHandler):
        def redirect_request(self, *args):
            return None
    jar = CookieJar()
    web = build_opener(HTTPCookieProcessor(jar), Stay)
    web.open(base).read()  # the Score page, for the CSRF cookie
    token = next((c.value for c in jar if c.name == "csrftoken"), "")
    data = urlencode({"example": example}).encode()
    try:
        web.open(Request(base + path, data=data, headers={"X-CSRFToken": token, "Referer": base}))
        raise CommandError(f"Scoring the example {example} did not start a job (is it in this release?)")
    except HTTPError as e:
        if e.code != 302:
            raise CommandError(f"Scoring the example {example}: HTTP {e.code}")
        key = re.search(r"[0-9a-f-]{36}", e.headers["Location"]).group(0)
    for _ in range(600):  # the status panel sends HX-Refresh once the job has ended
        response = web.open(f"{base}results/{key}/status/")
        if response.headers.get("HX-Refresh"):
            if "failed" in response.read().decode().lower():
                raise CommandError(f"The example {example} failed to score")
            return key
        time.sleep(0.5)
    raise CommandError(f"The example {example} is still scoring after 5 minutes")


class Command(BaseCommand):
    help = "Retake the guided tour's screenshots (static/snpportal/tour/) from a running portal with headless Chrome."

    def add_arguments(self, parser):
        parser.add_argument("--base", default="http://localhost:8000/snp/", help="the running portal's landing page URL")
        parser.add_argument("--chrome", default=os.environ.get("CHROME"), help="Chrome or Chromium binary")

    def handle(self, *args, **options):
        base = options["base"].rstrip("/") + "/"
        binary = options["chrome"] or next((c for c in CHROMES if shutil.which(c) or Path(c).exists()), None)
        if not binary:
            raise CommandError("Chrome not found: pass --chrome or set CHROME")
        need = {name for s in TOUR for name in JOBS if "{" + name + "}" in json.dumps(s["shot"])}
        keys = {name: score_example(base, *JOBS[name]) for name in sorted(need)}
        OUT.mkdir(parents=True, exist_ok=True)
        css = ["/* Written by `python manage.py tour_images` with the images: each slide's numbered callout boxes, in % of its image. */"]
        chrome = Chrome(binary)
        try:
            for s in TOUR:
                css += self.shoot(chrome, base, s, keys)
        finally:
            chrome.close()
        (OUT / "tour.css").write_text("\n".join(css) + "\n")
        for stale in set(OUT.glob("*.webp")) - {OUT / f"{s['slug']}.webp" for s in TOUR}:
            stale.unlink()
        sizes = {s["slug"]: (OUT / f"{s['slug']}.webp").stat().st_size for s in TOUR}
        self.stdout.write(f"Wrote {len(sizes)} images, {sum(sizes.values()) / 1024:.0f} KB in all, and tour.css to {OUT}")

    def shoot(self, chrome, base, slide, keys):
        """Screenshot one slide's page; returns its tour.css rules."""
        shot, slug = slide["shot"], slide["slug"]
        chrome.size(shot["width"], 900)
        for path, button in shot.get("before", []):
            chrome.open(base + path.format(**keys))
            status = chrome.js(f"{SUBMIT}({json.dumps(button)})")
            if status != 200:
                raise CommandError(f"{slug}: POSTing {button} on {path} gave HTTP {status}")
        chrome.open(base + shot["path"].format(**keys))
        if shot.get("click"):
            chrome.js(f"document.querySelector({json.dumps(shot['click'])}).click()")
            chrome.wait(f"!!document.querySelector({json.dumps(shot['wait'])})")
            chrome.wait("!document.querySelector('.htmx-request')")
        height = chrome.js("document.documentElement.scrollHeight")
        chrome.size(shot["width"], min(int(height), 4000))  # the whole page in the viewport, so boxes are page coordinates
        time.sleep(0.5)
        chrome.js("window.scrollTo(0, 0)")
        crop = chrome.js(f"tourBox({json.dumps(shot['crop'])})")
        if not crop:
            raise CommandError(f"{slug}: nothing to crop")
        x, y = max(0, crop[0] - PAD), max(0, crop[1] - PAD)
        w = min(shot["width"] - x, crop[2] + 2 * PAD)
        h = min(crop[3] + 2 * PAD, w * MAX_RATIO)
        scale = WIDTH / w
        image = chrome.send("Page.captureScreenshot", True, format="webp", quality=QUALITY,
                            clip={"x": x, "y": y, "width": w, "height": h, "scale": scale})
        (OUT / f"{slug}.webp").write_bytes(base64.b64decode(image["data"]))
        rules = [f"#tour-{slug} img {{ aspect-ratio: {WIDTH} / {round(h * scale)}; }}"]
        for i, (label, target) in enumerate(slide["callouts"], 1):
            box = chrome.js(f"tourBox({json.dumps(target)})")
            if not box:
                raise CommandError(f"{slug}: callout {i} ({label}) points at nothing")
            grow = [max(4, (26 - side) / 2) for side in box[2:]]  # 4 px around, and at least 26 px across
            bx, by, bw, bh = box[0] - grow[0], box[1] - grow[1], box[2] + 2 * grow[0], box[3] + 2 * grow[1]
            if isinstance(target, list) and target[0] == "row":
                bx, bw = x + 4, w - 8
            left, top = max(bx, x), max(by, y)
            right, bottom = min(bx + bw, x + w), min(by + bh, y + h)
            if right - left < 4 or bottom - top < 4:
                raise CommandError(f"{slug}: callout {i} ({label}) is outside the crop")
            rules.append(f"#tour-{slug}-{i} {{ left: {100 * (left - x) / w:.2f}%; top: {100 * (top - y) / h:.2f}%; "
                         f"width: {100 * (right - left) / w:.2f}%; height: {100 * (bottom - top) / h:.2f}%; }}")
        self.stdout.write(f"{slug}: {round(w)}x{round(h)} CSS px -> {WIDTH}x{round(h * scale)}, "
                          f"{(OUT / f'{slug}.webp').stat().st_size / 1024:.0f} KB")
        return rules
