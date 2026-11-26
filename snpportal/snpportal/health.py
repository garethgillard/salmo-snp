"""The portal's health (ROADMAP P8.4, P8.5), without content: a Django system check (`manage.py check`, and every
runserver or `salmo-snp serve` start) that re-hashes the release against its SHA256SUMS, and /snp/health/ for
monitoring (the salmobase container's HEALTHCHECK): release, results folder, job queue, pool and genome; the
track hosts only with ?tracks=1, as that asks them over the network."""
from __future__ import annotations

import os
import shutil
import tempfile
import time
import urllib.request

import duckdb
from django.core import checks
from django.http import JsonResponse

from . import jobs
from .lib import export as snp_export
from .lib import predict

_TRACKS = {}  # host -> (checked, reachable): track hosts asked at most every 5 minutes


@checks.register()
def release_check(app_configs=None, **kwargs):
    """Errors for a damaged release (snpscore verify), a results folder that can't be written and a DuckDB older than 2;
    a warning when no release is set up (as in the test suite, whose tests set their own)."""
    from snpscore.release import verify
    out, release = rules_check(), jobs.release()
    if not (release / "manifest.json").exists():
        return out + [checks.Warning(f"No release at {release}", hint="Set SNPSCORE_RELEASE, or run `salmo-snp download`.",
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


def rules(path=None):
    """The rules in use (or the file `path`), checked by snpscore and for the portal's own blocks: RulesError names
    each mistake and the file."""
    import snpscore
    w = snpscore.load_weights(path, check=False)  # a YAML mistake, or an own file that is gone, raises here
    problems = snpscore.check_weights(w) + snp_export.check_rules(w) if w is not None else []  # every mistake at once
    if problems:
        raise snpscore.RulesError(f"The tier rules in {path or snpscore.score.rules_file()} can't be used:\n  "
                                  + "\n  ".join(problems))
    return w


def rules_check():
    """An error (the portal won't start) for tier rules with a mistake: the shipped weights.yaml, or the own copy
    SNPSCORE_WEIGHTS names (a local install's in its data folder, salmo-snp rules)."""
    import snpscore
    try:
        rules()
    except snpscore.RulesError as e:
        return [checks.Error(str(e), hint="Correct the file (`salmo-snp rules` checks it again), or remove your own copy to "
                             "use the shipped rules.", id="snpportal.E004")]
    return []


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
    from snpscore.pool import stale
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
           "pool_fits": not stale(release),  # false: built for other weights or another snpscore (or missing)
           "species": {k: jobs.manifest(f).get("version") for k, f in jobs.species_releases().items()},
           "genome": "none" if not where else "remote" if where.startswith("http") else "local",
           # the card's Predict button: the models of this assembly, and whether their packages are installed here
           "predict": {"models": [x["name"] for x in predict.models(m.get("assembly", ""))], "packages": not predict.missing_packages()}}
    if request.GET.get("tracks") == "1" and (release / "tracks.yaml").exists():
        import yaml
        registry = yaml.safe_load((release / "tracks.yaml").read_text()) or {}
        out["tracks"] = dict(_reachable(str(x)) for x in (registry.get("hosts") or [])[:5])
        if os.environ.get("SNPSCORE_SALMOBASE"):  # on the salmobase server: the track files it reads from its own disk
            from snpscore import bbi

            from .lib import tracks
            urls = [t["url"] for k in tracks.KEYS for t in tracks.load_tracks(release).get(k, [])]
            out["tracks"]["read from the disk"] = f"{sum(bbi.local(u) != u for u in urls)} of {len(urls)}"
    response = JsonResponse(out, status=200 if out["status"] == "ok" else 503)
    response["Cache-Control"] = "no-store"
    return response
