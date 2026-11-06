"""The portal's health (ROADMAP P8.4, P8.5), without content: a Django system check (`manage.py check`, and every
runserver or `salmo-snp serve` start) that re-hashes the release against its SHA256SUMS, and /snp/health/ for
monitoring (the salmobase container's HEALTHCHECK): release, results folder, job queue, pool and genome; the
track hosts only with ?tracks=1, as that asks them over the network."""
from __future__ import annotations

import shutil
import tempfile
import time
import urllib.request

import duckdb
from django.core import checks
from django.http import JsonResponse

from . import jobs

_TRACKS = {}  # host -> (checked, reachable): track hosts asked at most every 5 minutes


@checks.register()
def release_check(app_configs=None, **kwargs):
    """Errors for a damaged release (snpscore verify), a results folder that can't be written and a DuckDB older than 2;
    a warning when no release is set up (as in the test suite, whose tests set their own)."""
    from snpscore.release import verify
    out, release = [], jobs.release()
    if not (release / "manifest.json").exists():
        return [checks.Warning(f"No release at {release}", hint="Set SNPSCORE_RELEASE, or run `salmo-snp download`.",
                               id="snpportal.W001")]
    for problem in verify(release):
        cls = checks.Warning if problem.startswith("no SHA256SUMS") else checks.Error
        out.append(cls(f"Release {release.name}: {problem}", id="snpportal.W002" if cls is checks.Warning else "snpportal.E001"))
    try:
        with tempfile.NamedTemporaryFile(dir=jobs.results_dir()):
            pass
    except OSError as e:
        out.append(checks.Error(f"The results folder can't be written ({type(e).__name__})", id="snpportal.E002"))
    if int(duckdb.__version__.split(".")[0]) < 2:
        out.append(checks.Error(f"DuckDB {duckdb.__version__}: the portal needs DuckDB 2", id="snpportal.E003"))
    return out


def _reachable(url):
    host = url.split("/")[2] if "://" in url else url
    checked, ok = _TRACKS.get(host, (0, None))
    if time.time() - checked > 300:
        try:
            with urllib.request.urlopen(urllib.request.Request(f"https://{host}/", method="HEAD"), timeout=3):
                ok = True
        except Exception as e:  # any answer at all (even 403 or 404) means the host and its TLS work
            ok = getattr(e, "code", None) is not None
        _TRACKS[host] = (time.time(), ok)
    return host, ok


def health(request):
    """/snp/health/: JSON, 200 when the portal can score, else 503. Counts and states only: never a SNP or a file name."""
    from snpscore.annotate import genome_location
    from snpscore.release import check
    release = jobs.release()
    m = jobs.manifest()
    problems = check(release)
    results = jobs.results_dir()
    free = shutil.disk_usage(results).free
    try:
        with tempfile.NamedTemporaryFile(dir=results):
            writable = True
    except OSError:
        writable = False
    where = genome_location(m) or ""
    out = {"status": "ok" if not problems and writable else "error",
           "release": {"version": m.get("version"), "assembly": m.get("assembly"), "ok": not problems},
           "results": {"writable": writable, "free_gb": round(free / 1e9, 1), "local": jobs.local()},
           "queue": {"queued": len(jobs._queued), "running": len(jobs._running), "max_queued": jobs.MAX_QUEUED},
           "pool": (release / "pool" / "pool.parquet").exists(),
           "genome": "none" if not where else "remote" if where.startswith("http") else "local"}
    if request.GET.get("tracks") == "1" and (release / "tracks.yaml").exists():
        import yaml
        hosts = (yaml.safe_load((release / "tracks.yaml").read_text()) or {}).get("hosts") or []
        out["tracks"] = dict(_reachable(str(x)) for x in hosts[:5])
    response = JsonResponse(out, status=200 if out["status"] == "ok" else 503)
    response["Cache-Control"] = "no-store"
    return response
