"""Jobs: every upload or candidate list becomes a folder results/<uuid>/ that a small thread pool annotates.

A job folder (0700, files 0600) holds:
- job.json: state (queued/running/done/failed), stage, timings and provenance, always written atomically
- input.<ext>: the list to score, deleted as soon as annotation ends
- result.parquet from snpscore.annotate, and tiers.parquet with the tiers of every preset, so switching presets
  never rescores
- summary.json, and validation.json / rejects.tsv when snpscore writes them
- weights.yaml and manifest.json copied from the release, so editing the release never changes an existing job
- GWAS jobs (input_kind 'gwas'): sumstats.parquet, gwas.json (QC) and gwas.parquet (statistics with alleles turned to
  Ssal_v3.1, keyed by the result's file_row_number), read by association.py

Log lines carry an event name, job_ref (a hash of the key), counts and timings: never SNPs or file names."""
from __future__ import annotations

import contextvars
import gc
import gzip
import hashlib
import inspect
import json
import logging
import os
import re
import shutil
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import duckdb
from django.conf import settings

import snpscore
from snpscore.annotate import user_message
from snpscore.formats import lit
from snpscore.pool import maf_bin_sql

log = logging.getLogger("snpportal")
STALE = 300  # seconds without a heartbeat before a queued or running job is given up (server restarted)
MAX_QUEUED = 10
TIER_COLUMNS = ("tier", "tier_score", "tier_evidence", "tier_terms")
PUBLIC_AF = "504-fish panel: mostly wild and farmed fish from Bertolotti et al. 2020 plus the 12 AQUA-FAANG fish"  # public_af (R1)

_lock = threading.RLock()
_queued, _running, _deleted = set(), set(), set()  # job keys; _deleted: 'Delete now' while running, removed when run() ends
_executor = None


class QueueFull(Exception):
    """Too many jobs are waiting; try again in a minute."""


class InputError(ValueError):
    """The input can't be scored; the message says why and how to fix it."""


class Deleted(Exception):
    """The job folder was deleted while the job ran."""


def setting(name, default):
    return getattr(settings, name, default)


_current = contextvars.ContextVar("snpportal_release", default=None)  # I17: the release of this request or job


def release():
    """The release folder a page or job reads: the job's own, the Design panel's own, or the one chosen on a local
    install (I17: set per request by `middleware`, per job by `run`), else settings.SNPSCORE_RELEASE."""
    return _current.get() or Path(settings.SNPSCORE_RELEASE).resolve()  # resolved: DuckDB's allowed_directories refuses symlinks


# ---- several releases (ROADMAP I17; local installs) ----

def installed():
    """{version: folder} of the releases this install holds: settings.SNPSCORE_RELEASE and every release under
    SNPPORTAL_RELEASES_DIR (salmo-snp's data folder releases/; on a server, the folder holding one release per species)."""
    base = Path(settings.SNPSCORE_RELEASE).resolve()
    out = {manifest(base).get("version") or base.name: base}
    where = setting("SNPPORTAL_RELEASES_DIR", None)
    if where:
        for m in sorted(Path(where).glob("*/manifest.json")):
            out.setdefault(manifest(m.parent).get("version") or m.parent.name, m.parent.resolve())
    return out


# ---- species (one release is for one species; the species bar picks which the pages read) ----

SALMON = {"key": "atlantic_salmon", "name": "Atlantic salmon", "latin": "Salmo salar", "prefix": "ssa",
          "example": {"region": "25:28985000-29010000", "label": "vgll3"}}  # releases from before manifest `species`
SPECIES_COOKIE = "snp_species"


def species(where=None):
    """The species of a release (default: the current one): {key, name, latin, prefix, example: {region, label}}."""
    own = manifest(where).get("species") or {}
    return {**SALMON, **own} if own.get("key", SALMON["key"]) == SALMON["key"] else {"prefix": "chr", **own}


def species_releases():
    """{species key: release folder} for the species bar: per species the default release (SNPSCORE_RELEASE) when it
    is that species', else the newest installed one (by build date, then version)."""
    out, found = {}, installed()
    default = next(iter(found.values()))
    for folder in [default] + sorted((f for f in found.values() if f != default),
                                     key=lambda f: (manifest(f).get("created") or "", f.name), reverse=True):
        out.setdefault(species(folder)["key"], folder)
    return out


def species_choices():
    """[{key, name, latin, current}] for the species bar; [] when the install holds one species only."""
    here = species()["key"]
    found = species_releases()
    return [{**species(folder), "current": key == here} for key, folder in found.items()] if len(found) > 1 else []


def _choice():
    return results_dir().parent / "release-in-use.json"


def chosen():
    """The release the user picked on the Releases page (a local install with several), or None for the default."""
    if not local():
        return None
    return installed().get(read_json(_choice()).get("version"))


def choose(version):
    """Use release `version` (installed) for new work; None: back to the default."""
    if version is None:
        _choice().unlink(missing_ok=True)
    elif version in installed():
        _write_json(_choice(), {"version": version, "chosen_utc": utc()})


def release_for(version):
    """The installed folder of release `version`, or None (not installed)."""
    return installed().get(version) if version else None


JOB_URL = re.compile(r"/results/([0-9a-f-]{36})/")


def for_request(request):
    """The release a request reads (I17): a job's pages read the job's own release (job.json), the Design panel its
    own (panel.json), a saved project version its own (meta.json); other pages the release of the species chosen on
    the species bar (a cookie), which on a local install is the one picked on the Releases page when that is the same
    species'. None: the default."""
    if len(installed()) < 2:
        return None
    m = JOB_URL.search(request.path)
    if m:
        try:
            own = release_for(read_json(folder(m.group(1)) / "job.json").get("release"))
        except ValueError:
            own = None
        if own:
            return own
    if "/panel/" in request.path:
        from . import panel
        d = panel._folder(request)
        own = release_for(read_json(d / "panel.json").get("release")) if d else None
        if own:
            return own
    m = re.search(r"/projects/([^/]+)/(\d+)/", request.path)
    if m:
        try:
            from . import projects
            own = release_for(read_json(projects.root() / m.group(1) / f"v{int(m.group(2))}" / "meta.json").get("release"))
        except (OSError, ValueError):
            own = None
        if own:
            return own
    picked, wanted = chosen(), request.COOKIES.get(SPECIES_COOKIE)
    by_species = species_releases()
    if wanted in by_species and not (picked and species(picked)["key"] == wanted):
        return by_species[wanted]
    return picked


def wording(where=None):
    """[(pattern, replacement)] that turn the pages' Atlantic salmon wording into that of another species' release:
    the assembly and the older one, the number of chromatin conditions, the chromosome names, the species' names and
    the release's own pairs (layers.yaml species.wording, e.g. the samples and the public SNP set). The pages are
    written for salmon, the first species; this is the one place that says what differs. [] for a salmon release."""
    m, sp = manifest(where), species(where)
    if sp["key"] == SALMON["key"]:
        return []
    chromatin = next((layer for layer in m.get("layers", []) if layer["name"] == "chromatin"), {})
    n = sum(1 for c in chromatin.get("columns", []) if c not in ("summary", "id"))
    older = (m.get("rsid") or {}).get("older") or "an older assembly"
    span = str(m.get("chromosomes", "")).split(" (")[0]
    latin, prefix = sp.get("latin", ""), sp.get("prefix", "chr")
    pairs = [(re.escape(a), b) for a, b in sp.get("wording") or []]
    pairs += [(r"Ssal_v3\.1", m.get("assembly", "")), (r"ICSASG_v2", older), (r"Salmo_salar", latin.replace(" ", "_")),
              (r"Salmo salar", latin), (r"(?<!>)Atlantic salmon", sp["name"].lower()), (r"\bssa(?=\d)", prefix), (r"\bSsa(?=\d+p|&lt;chromosome|<chromosome)", prefix.capitalize()),
              (r"(?<=[Cc]hromosomes )1[-–]29", span), (r"\b1[-–]29(?= \(Ensembl)", span)]
    if n:
        pairs.append((r"\b21(?=\s+(?:chromatin\s+|sample\s+|AQUA-FAANG\s+)?(?:conditions|tissues and stages))", str(n)))
    return [(re.compile(a), b) for a, b in pairs]


def middleware(get_response):
    """settings.MIDDLEWARE 'snpportal.jobs.middleware': each request reads its own release (for_request), and a page
    of another species than salmon gets that release's wording (wording)."""
    def with_release(request):
        token = _current.set(for_request(request))
        try:
            response = get_response(request)
            kind = response.get("Content-Type", "")
            if not response.streaming and kind.startswith(("text/html", "image/svg")) and not request.path.endswith("/releases/"):
                pairs = wording()
                if pairs:
                    text = response.content.decode(response.charset or "utf-8")
                    for pattern, replacement in pairs:
                        text = pattern.sub(lambda _m, r=replacement: r, text)
                    response.content = text.encode(response.charset or "utf-8")
            return response
        finally:
            _current.reset(token)
    return with_release


def results_dir():
    d = Path(setting("SNPPORTAL_RESULTS_DIR", Path(tempfile.gettempdir()) / "snpportal"))
    if not d.is_dir():
        d.mkdir(mode=0o700, parents=True, exist_ok=True)
    if d.stat().st_mode & 0o077:  # e.g. made by an older version: only the server's user may list results
        d.chmod(0o700)
    return d.resolve()


def folder(key):
    return results_dir() / str(uuid.UUID(str(key)))


def job_ref(key):
    """Short hash of a job key for log lines (the key itself is the private link to the results)."""
    return hashlib.sha256(str(key).encode()).hexdigest()[:8]


def utc(t=None):
    return datetime.fromtimestamp(time.time() if t is None else t, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def limits():
    return {"threads": int(setting("SNPPORTAL_DUCKDB_THREADS", 2)), "memory_limit": str(setting("SNPPORTAL_DUCKDB_MEMORY", "2GB"))}


def connect(read=(), write=None):
    """DuckDB connection for portal queries that may read files only under `read` (and write under `write`), with
    SNPPORTAL_DUCKDB_THREADS (2) and SNPPORTAL_DUCKDB_MEMORY (2GB). Uses snpscore.connect() (the sandbox) when this
    snpscore has it. Every connection, also a read-only one (a sort or export of a 1.6M-row result needs more than
    2GB), spills into results/.spill-<uuid>, which DuckDB makes when needed and removes on close: never into the job
    folder, which 'Delete now' or cleanup() may remove while a request runs."""
    if hasattr(snpscore, "connect"):
        spill = results_dir() / f".spill-{uuid.uuid4().hex}"
        return snpscore.connect(read_dirs=[*read, *([write] if write else [])], write_dir=spill, **limits())
    return duckdb.connect(config=limits())


# ---- release files, cached by path and mtime ----

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@lru_cache(maxsize=64)
def _cached(kind, path, mtime):
    p = Path(path)
    if kind == "weights":
        w = snpscore.load_weights(p)
        if w and "presets" in w:
            w["presets"] = Presets(w["presets"])
        return w
    return sha256(p) if kind == "sha256" else json.loads(p.read_text())


def _file(kind, path):
    path = Path(path)
    return _cached(kind, str(path), path.stat().st_mtime) if path.exists() else None


def manifest(where=None):
    """manifest.json of a job's snapshot folder, or of the current release ({} if missing)."""
    return _file("json", Path(where or release()) / "manifest.json") or {}


def weights(where=None):
    """weights.yaml of a job's snapshot folder, or snpscore's current one (None if missing); its presets also take
    Active-in keys (Presets)."""
    return _file("weights", Path(where) / "weights.yaml" if where else snpscore.score.WEIGHTS)


def score_layers(where=None):
    """[(name, label)] of the per-variant score layers (layers.yaml format variant_scores, ROADMAP I15) of a job's
    snapshot or the current release; the label is the layer's `label`, else its name."""
    return [(layer["name"], layer.get("label") or layer["name"]) for layer in manifest(where).get("layers", [])
            if layer.get("format") == "variant_scores"]


def release_info():
    """Version, assembly, build date, manifest sha256 and synthetic layers of the current release."""
    m = manifest()
    return {"version": m.get("version", "none"), "assembly": m.get("assembly", "Ssal_v3.1"), "created": m.get("created"),
            "sha256": _file("sha256", release() / "manifest.json"), "layers": m.get("layers", []),
            "known_loci": (release() / "catalog" / "known_loci.tsv").exists(),
            "synthetic": [layer["name"] for layer in m.get("layers", []) if layer.get("synthetic")]}


def release_changed(job):
    """True when the current release's manifest or snpscore's weights differ from the job's snapshot."""
    return (job.get("manifest_sha256"), job.get("weights_sha256")) != (
        _file("sha256", release() / "manifest.json"), _file("sha256", snpscore.score.WEIGHTS))


def presets(where=None):
    """[(value, label)] of the condition sets a page's Conditions menu offers: all conditions, then one per tissue
    (each has stored tiers). Never a phenotype: the portal names sample conditions only."""
    return [("all", trait_label("all"))] + [(t, trait_label(t)) for t in TISSUES] if weights(where) else []


def trait_label(trait):
    """The conditions tiers count, as people read them: 'all conditions', 'brain + gonad (mature females)'. A
    weights.yaml preset name (older links, job.json) reads as its tissues."""
    sel = selection(trait if trait == "all" or selection(trait) else _as_key(trait))
    if sel and trait != "all":
        tissues, maturity, sex = sel
        who = " ".join(x.lower() for x in (maturity, sex and f"{sex}s") if x)
        return " + ".join(t.lower() for t in tissues) + (f" ({who})" if who else "")
    return "all conditions"


def _as_key(name, presets=None):
    """The Active-in key of a weights.yaml preset name ('maturation' -> 'Brain+Gonad'), 'all' for 'all' or unknown."""
    if name == "all":
        return "all"
    try:
        presets = presets if presets is not None else (weights() or {}).get("presets") or {}
    except OSError:  # no release configured
        presets = {}
    if not dict.__contains__(presets, name):
        return "all"
    tissues = selection_of(name, presets)[0]
    return "all" if len(tissues) == len(TISSUES) else selection_key(tissues)


# ---- traits: the conditions tiers score against. A weights.yaml preset, or the Table's Active-in selection of
# tissues, maturity and sex, written as a key: tissues joined by '+', then optionally '.Immature' or '.Mature' and
# '.Female' or '.Male' ('Brain+Gonad.Mature.Female'). URLs carry ?trait=; a key with the same conditions as a named
# preset becomes that preset, whose tiers are stored; other keys are scored once per job (trait_tiers). ----

TISSUES = ("Brain", "Gonad", "Liver", "Muscle", "Embryo")  # Embryo: the 5 DevMap stages (no maturity or sex)
MATURITIES, SEXES = ("Immature", "Mature"), ("Female", "Male")
STAGES = ("LateBlastulation", "MidGastrulation", "EarlySomitogenesis", "MidSomitogenesis", "LateSomitogenesis")
CONDITIONS = tuple(f"{t}_{m}_{s}" for t in TISSUES[:-1] for m in MATURITIES for s in SEXES) + STAGES


def selection(key):
    """(tissues, maturity, sex) of an Active-in key (None = both), or None when `key` is not one. A typed URL's '+'
    arrives as a space: either joins tissues."""
    head, *rest = str(key or "").replace(" ", "+").split(".")
    tissues = head.split("+")
    maturity, sex = next((x for x in rest if x in MATURITIES), None), next((x for x in rest if x in SEXES), None)
    if not head or not set(tissues) <= set(TISSUES) or len(set(tissues)) < len(tissues) \
            or len(rest) != (maturity is not None) + (sex is not None):
        return None
    return [t for t in TISSUES if t in tissues], maturity, sex


def selection_key(tissues, maturity=None, sex=None):
    """The Active-in key of a selection; no tissue means all of them."""
    tissues = [t for t in TISSUES if t in tissues] or list(TISSUES)
    return "+".join(tissues) + "".join(f".{x}" for x in (maturity, sex) if x in MATURITIES + SEXES)


def selection_prefixes(key):
    """An Active-in key's condition prefixes, as weights.yaml presets list them; None when `key` is not one."""
    sel = selection(key)
    if sel is None:
        return None
    tissues, maturity, sex = sel
    out = []
    for t in tissues:
        if t == "Embryo":
            out += STAGES
        elif sex:
            out += [f"{t}_{m}_{sex}" for m in ([maturity] if maturity else MATURITIES)]
        else:
            out.append(f"{t}_{maturity}" if maturity else t)
    return out


class Presets(dict):
    """weights.yaml presets that also take Active-in keys (as their condition prefixes, so snpscore scores them like
    any preset); iterating gives only the named presets."""

    def __contains__(self, key):
        return dict.__contains__(self, key) or selection(key) is not None

    def __missing__(self, key):
        prefixes = selection_prefixes(key)
        if prefixes is None:
            raise KeyError(key)
        return prefixes

    def get(self, key, default=None):
        return self[key] if key in self else default


def conditions_in(prefixes):
    return {c for c in CONDITIONS if not prefixes or c.startswith(tuple(prefixes))}


def canonical(trait, presets):
    """`trait` as URLs carry it: an Active-in key in one spelling ('Brain+Gonad', tissues in order), or 'all'. A preset
    name of older links becomes the key of its tissues."""
    if trait == "all" or trait not in presets:
        return "all"
    key = selection_key(*selection(trait)) if selection(trait) else _as_key(trait, presets)
    return "all" if key == "all" or conditions_in(presets[key]) == set(CONDITIONS) else key


def cli_trait(trait):
    """snpscore's --trait for these conditions: 'all' or a single tissue's preset; None for any other set."""
    w = weights() or {}
    name = stored_preset(canonical(trait, w["presets"]), w["presets"]) if w.get("presets") else None
    return name if name and (name == "all" or name.capitalize() in TISSUES) else None


def stored_preset(trait, presets):
    """The weights.yaml preset whose stored tiers (tiers.parquet, summary.json, the pool) are those of the Active-in
    key `trait`: the same conditions, single tissues first; None when no preset has them."""
    if trait == "all":
        return "all" if dict.__contains__(presets, "all") else None
    wanted = conditions_in(presets[trait])
    names = sorted(presets, key=lambda p: p.capitalize() not in TISSUES)
    return next((p for p in names if conditions_in(presets[p]) == wanted), None)


def selection_of(trait, presets):
    """(tissues, maturity, sex) of `trait`; a named preset covers whole tissues."""
    sel = selection(trait)
    if sel:
        return sel
    conditions = conditions_in(presets.get(trait, []))
    return [t for t in TISSUES if conditions & conditions_in(selection_prefixes(t))], None, None


def trait_tiers(d, w, trait):
    """(file, suffix) holding a job's tier columns (<column>__<suffix>): tiers.parquet under the stored preset with the
    conditions of `trait` (always 'all' in the portal). (None, None) for jobs made before tiers.parquet."""
    if not (d / "tiers.parquet").exists():
        return None, None
    return d / "tiers.parquet", stored_preset(trait, w["presets"]) or "all"


# ---- job.json ----

def _write_json(path, data):
    """Write JSON atomically (temp file + os.replace), mode 0600."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=1, default=str)
    os.replace(tmp, path)


def read(key):
    try:
        return json.loads((folder(key) / "job.json").read_text())
    except (FileNotFoundError, ValueError):
        return None


def update(key, **changes):
    """Merge changes into job.json; returns the job, or None if it has been deleted."""
    with _lock:
        job = read(key)
        if job is None:
            return None
        job.update(changes)
        try:
            _write_json(folder(key) / "job.json", job)
        except FileNotFoundError:
            return None
        return job


def status(key):
    """job.json, or None if expired or deleted. A queued or running job without a heartbeat for STALE seconds
    (the server restarted) is marked failed."""
    job = read(key)
    if job and job["state"] in ("queued", "running") and time.time() - job["heartbeat"] > STALE:
        job = update(key, state="failed", error_code="stale",
                     error="The server restarted while this list was being scored. Please upload it again.")
        log.warning("job_stale job_ref=%s", job_ref(key))
    return job


FOREVER = 10 * 365 * 86400  # cookie lifetime on a local install, where results and panels stay until deleted


def local():
    """True when the portal runs on the user's own computer (salmo-snp serve sets SNPPORTAL_LOCAL): nothing expires and
    nothing is shared, and the pages say so."""
    return bool(setting("SNPPORTAL_LOCAL", False))


def keep_seconds():
    """How long results and Design panels are kept: SNPPORTAL_KEEP_HOURS (24), or None (until deleted) when local()."""
    return None if local() else 3600 * float(setting("SNPPORTAL_KEEP_HOURS", 24))


def expires(key):
    """Unix time when cleanup() will delete the job, or None when it is kept until deleted (local())."""
    keep = keep_seconds()
    return None if keep is None else (folder(key) / "job.json").stat().st_mtime + keep


# ---- creating and running jobs ----

def executor():
    """The module-level pool (SNPPORTAL_WORKERS threads, default 1), or None to run jobs inline (WORKERS = 0)."""
    global _executor
    workers = int(setting("SNPPORTAL_WORKERS", 1))
    if workers <= 0:
        return None
    with _lock:
        if _executor is None:
            _executor = ThreadPoolExecutor(workers, thread_name_prefix="snpportal-job")
            threading.Thread(target=_beat, name="snpportal-heartbeat", daemon=True).start()
    return _executor


def _beat():
    """Keep the heartbeat of this process's queued and running jobs fresh, so status() can spot lost ones."""
    while True:
        time.sleep(30)
        for key in list(_queued | _running):
            update(key, heartbeat=time.time())


def position_choices():
    """[(value, label)] of the assemblies an upload's positions may be on, for this release: its own ('' ), each
    assembly its liftover tables convert from (I19: icsasg_v2, fsalsal1) and, with flank keys, any other one placed by
    flank sequence (I18: 'flank')."""
    from snpscore.annotate import conversions
    m = manifest()
    own = m.get("assembly", "Ssal_v3.1")
    out = [("", f"{own} (as is)")] + [(k, f"{v['label']} (converted to {own})") for k, v in conversions(m).items()
                                      if (release() / v["file"]).exists()]
    if (release() / "flank_keys.parquet").exists():
        out.append(("flank", "another assembly (placed by flank sequence)"))
    return out


def create(src, suffix, input_kind="snps", preset="all", label="", input_format=None, synthetic=False, move=True,
           positions=None):
    """Make a job from the input file `src` (moved into the job folder, or copied if move=False) and queue it.
    `positions` (a position_choices value): the input's positions are on another assembly. Returns the key. Raises QueueFull before
    creating anything when MAX_QUEUED jobs are already waiting."""
    if executor() is not None and len(_queued) >= MAX_QUEUED:
        raise QueueFull()
    key = uuid.uuid4()
    d = folder(key)
    d.mkdir(mode=0o700)
    for kept in (release() / "manifest.json", snpscore.score.WEIGHTS):  # the job keeps the data and rules it was scored with
        if kept.exists():
            shutil.copyfile(kept, d / kept.name)
    (os.replace if move else shutil.copyfile)(src, d / f"input{suffix}")
    lock_down(d)
    now = time.time()
    snapshot = manifest(d)
    _write_json(d / "job.json", {
        "state": "queued", "stage": "queued", "n_rows": None, "label": label, "preset": preset,
        "input_kind": input_kind, "input_format": input_format or suffix.lstrip(".").replace(".gz", ""),
        "input_suffix": suffix, "input_sha256": sha256(d / f"input{suffix}"),
        "synthetic_input": bool(synthetic), "synthetic_layers": [x["name"] for x in snapshot.get("layers", []) if x.get("synthetic")],
        "release": snapshot.get("version"), "assembly": snapshot.get("assembly", "Ssal_v3.1"),
        "manifest_sha256": sha256(d / "manifest.json") if (d / "manifest.json").exists() else None,
        "weights_sha256": sha256(d / "weights.yaml") if (d / "weights.yaml").exists() else None,
        "snpscore_version": _version("snpscore"), "duckdb_version": duckdb.__version__,
        "created": now, "created_utc": utc(now), "started": None, "heartbeat": now, "timings": {},
        "error_code": None, "error": None, **({"positions": positions} if positions and positions in dict(position_choices()) else {}),
    })
    log.info("job_created job_ref=%s kind=%s", job_ref(key), input_kind)
    submit(key)
    return key


def submit(key):
    """Queue a created job on the pool, or run it now when SNPPORTAL_WORKERS = 0."""
    pool = executor()
    if pool is None:
        run(key)
    else:
        _queued.add(str(key))
        pool.submit(run, key)


def run(key):
    """Annotate a job's input, precompute tiers for every preset and write summary.json. Runs on the pool (or
    inline), reading the release the job was created with (I17); never raises: failures end in state 'failed' with
    an error_code and a message for the user."""
    try:
        own = release_for(read_json(folder(key) / "job.json").get("release"))
    except ValueError:
        own = None
    token = _current.set(own or _current.get())
    try:
        _run(key)
    finally:
        _current.reset(token)


def _run(key):
    key = str(key)
    with _lock:
        _queued.discard(key)
        _running.add(key)
    d, t0 = folder(key), time.time()
    current, timings = {"stage": "reading", "t": t0}, {}

    def progress(stage):  # also passed to snpscore.annotate, which reports stage names only
        now = time.time()
        timings[current["stage"]] = round(now - current["t"], 2)
        current.update(stage=stage, t=now)
        if update(key, stage=stage, heartbeat=now, timings=timings) is None:
            raise Deleted()

    try:
        job = update(key, state="running", stage="reading", started=t0, heartbeat=t0)
        if job is None:
            return
        src = d / f"input{job['input_suffix']}"
        gwas = job.get("input_kind") == "gwas"
        if gwas:  # GWAS summary statistics (P7.1): sumstats.parquet + gwas.json; annotate gets their positions and alleles
            from snpscore import gwas as sumstats
            src = sumstats.prepare(src, release(), d, max_snps=int(setting("SNPPORTAL_MAX_SNPS", 3_000_000)), **limits())
        _annotate(src, d, progress)
        src.unlink(missing_ok=True)
        progress("tiers")
        n = precompute(d)
        validation, extra = read_json(d / "validation.json"), {}
        if gwas:  # gwas.parquet: the statistics with alleles turned to Ssal_v3.1, joined to the result's rows
            progress("association")
            validation = sumstats.attach(d, **limits())
            extra["synthetic_input"] = bool(job.get("synthetic_input") or validation.get("synthetic"))
        progress("done")
        fmt = validation.get("input_format") or validation.get("format") or job["input_format"]
        update(key, state="done", n_rows=n, input_format=fmt, timings=timings, **extra)
        log.info("job_done job_ref=%s n_rows=%s seconds=%.1f", job_ref(key), n, time.time() - t0)
    except Deleted:
        log.info("job_deleted job_ref=%s", job_ref(key))
    except (InputError, snpscore.InputError, duckdb.Error) as e:  # snpscore's messages say what is wrong and the fix;
        error = user_message(e) if isinstance(e, duckdb.Error) else str(e)[:2000]  # DuckDB's may quote paths or rows
        update(key, state="failed", error_code="invalid_input", error=error)
        log.info("job_failed job_ref=%s error_code=invalid_input exception=%s", job_ref(key), type(e).__name__)
    except Exception as e:  # noqa: BLE001 - a worker must never die; the message may hold content, so log the type only
        update(key, state="failed", error_code="internal",
               error="Something went wrong while scoring this list. Please try again, or contact us if it keeps happening.")
        log.error("job_failed job_ref=%s error_code=internal exception=%s", job_ref(key), type(e).__name__)
    finally:
        with _lock:
            _running.discard(key)
            deleted = key in _deleted
            _deleted.discard(key)
        if deleted:  # 'Delete now' came while this ran: its DuckDB connections (spilling into d) are closed by now
            gc.collect()
            shutil.rmtree(d, ignore_errors=True)
        else:
            for p in d.glob("input*"):
                p.unlink(missing_ok=True)
            try:
                lock_down(d)  # also after a failure: validation.json and rejects.tsv hold the user's rows
            except FileNotFoundError:  # deleted meanwhile
                pass


def _annotate(src, d, progress):
    """snpscore.annotate into result.parquet, passing progress=, max_snps= and the DuckDB limits when this snpscore
    supports them (else the portal counts rows itself); its <stem>.validation.json and <stem>.rejects.tsv (when
    written) become validation.json and rejects.tsv."""
    params = inspect.signature(snpscore.annotate).parameters
    cap = int(setting("SNPPORTAL_MAX_SNPS", 3_000_000))
    kwargs = {k: v for k, v in [("progress", progress), ("max_snps", cap), *limits().items()] if k in params}
    positions = read_json(d / "job.json").get("positions")  # I18, I19: positions on another assembly
    if positions == "flank":
        kwargs["place_by_flank"] = True
    elif positions:
        kwargs["lift_from"] = positions
    if "max_snps" not in params:
        check_rows(src, cap)
    try:
        snpscore.annotate(src, release(), d / "result.parquet", **kwargs)
    finally:
        for name in ("validation.json", "rejects.tsv"):
            if (d / f"result.{name}").exists():
                os.replace(d / f"result.{name}", d / name)


def precompute(d):
    """tiers.parquet: file_row_number plus tier__<preset>, tier_score__<preset>, tier_evidence__<preset> (and
    tier_terms__<preset>) for every named preset in the job's weights.yaml; and summary.json. Returns the row count."""
    con = connect([d], d)
    con.execute(f"CREATE VIEW r AS SELECT * FROM read_parquet('{d / 'result.parquet'}', file_row_number=true)")
    columns = [c for c, in con.execute("SELECT column_name FROM (DESCRIBE r)").fetchall()]
    n = con.execute("SELECT count(*) FROM r").fetchone()[0]
    w = snpscore.load_weights(d / "weights.yaml")
    if w and w.get("presets"):
        # A chain of projections, one per preset, each renaming its tier columns to <column>__<preset>: one streaming
        # pass with no joins, so 1.6M SNPs fit the 2 GB DuckDB limit. scored() replaces any tier columns it is given.
        view, cols, stored, picked = "r", columns, [], None
        for i, preset in enumerate(w["presets"]):
            sql = scored_sql(view, w, cols, preset, d)
            if picked is None:  # the tier columns this snpscore adds
                picked = [c for c, in con.execute(f"SELECT column_name FROM (DESCRIBE ({sql}))").fetchall() if c in TIER_COLUMNS]
            renamed = [f"{c}__{preset}" for c in picked]
            con.execute(f"CREATE VIEW c{i} AS SELECT * EXCLUDE ({', '.join(picked)}), "
                        + ", ".join(f"{c} AS {ident(r)}" for c, r in zip(picked, renamed)) + f" FROM ({sql})")
            view, cols, stored = f"c{i}", [c for c in cols if c not in TIER_COLUMNS] + renamed, stored + renamed
        con.execute(f"COPY (SELECT file_row_number, {', '.join(map(ident, stored))} FROM {view}) "
                    f"TO '{d / 'tiers.parquet'}' (FORMAT parquet)")
    _write_json(d / "summary.json", summarise(con, d, columns, w))
    return n


# ---- summary.json: everything the Overview tab shows, so it never scans the result ----

SUMMARY_VERSION = 4  # 3: molQTL count and assay reasons; 4: MAF bins with the Table filter's edges
REGION_GROUPS = {  # region filter / figure group -> SQL condition on region_class (the rest is 'other')
    "coding": "region_class IN ('CDS', 'splice_region')", "UTR": "region_class LIKE '%UTR'",
    "exon": "region_class = 'exon'", "intron": "region_class = 'intron'", "intergenic": "region_class IS NULL"}
MAF_BIN = 0.05  # histogram bin width; MAF >= 0.05 is the 'common' KPI


def region_sql(columns):
    """SQL giving a SNP's REGION_GROUPS key (NULL without region_class)."""
    if "region_class" not in columns:
        return "NULL"
    return "CASE " + " ".join(f"WHEN {cond} THEN '{g}'" for g, cond in REGION_GROUPS.items()) + " ELSE 'other' END"


def maf_sql(columns):
    """(SQL for a SNP's minor allele frequency, its source): the user's maf or af column, else the public AF layer."""
    for name, source in (("maf", "yours"), ("af", "yours"), ("public_af_maf", "public")):
        if name in columns:
            x = f"TRY_CAST({ident(name)} AS DOUBLE)"
            return f"least({x}, 1 - {x})", source
    return None, None


def summarise(con, d, columns, w):
    """summary.json for a job: n_rows, and per preset: tier counts, region group x tier, chromosome x tier, 1 Mb bins
    ([chrom, bin, n tier 1..4], bin = (pos - 1) // 1e6) and evidence term x tier. Preset-free: SNPs active per
    condition, MAF histogram, assay status and reasons ({reason: {status: n}}, with leading and trailing numbers
    stripped: 'GC 0.72' counts as 'GC'), known loci and molQTL leads. Needs view `r` (result.parquet with
    file_row_number) and tiers.parquet."""
    n = con.execute("SELECT count(*) FROM r").fetchone()[0]
    s = {"version": SUMMARY_VERSION, "n_rows": n, "tiers": {}}
    if (d / "tiers.parquet").exists() and (w or {}).get("presets"):
        parts = _trait_parts(con, d / "tiers.parquet", list(w["presets"]), columns)
        if parts["tiers"]:
            s.update(parts)

    # One pass over the result for the per-condition activity, known loci and molQTL leads.
    counts = []  # (summary key, name, SQL condition)
    conditions = [c[len("chromatin_"):] for c in columns if c.startswith("chromatin_") and c not in snpscore.score.NOT_CONDITIONS]
    if w and conditions:
        active = ", ".join(lit(x) for x in w.get("active_states", [])) or "NULL"
        counts += [("conditions", c, f"{ident('chromatin_' + c)} IN ({active})") for c in conditions]
        s["active_states"] = list(w.get("active_states", []))
    if "known_locus" in columns:
        counts.append(("counts", "known", "known_locus IS NOT NULL"))
    if "molqtl" in columns:
        counts.append(("counts", "molqtl", "coalesce(molqtl, false)"))
    if counts:
        values = con.execute("SELECT " + ", ".join(f"count(*) FILTER (WHERE {cond})" for _, _, cond in counts) + " FROM r").fetchone()
        for (key, name, _), k in zip(counts, values):
            s.setdefault(key, {})[name] = k
    maf, source = maf_sql(columns)
    if maf:
        # the pool's bins (snpscore.pool.maf_bin_sql): each holds exactly the rows its bar's Table filter (m >= 0.15) keeps
        hist = dict(con.execute(f"SELECT {maf_bin_sql('m')}, count(*) FROM (SELECT {maf} AS m FROM r) GROUP BY 1").fetchall())
        s["maf"] = {"source": source, "width": MAF_BIN, "missing": hist.pop(None, 0),
                    "bins": [hist.get(i, 0) for i in range(round(0.5 / MAF_BIN))]}
    if "assay_status" in columns:
        s["assay"] = dict(con.execute("SELECT coalesce(assay_status, 'not_checked'), count(*) FROM r GROUP BY 1 ORDER BY 1").fetchall())
    if "assay_reasons" in columns and "assay_status" in columns:
        s["assay_reasons"] = {}
        for reason, status, k in con.execute("""
                SELECT trim(regexp_replace(regexp_replace(x, '^[0-9]+ ', ''), '( +[0-9.+-]+)+$', '')), status, count(*) FROM (
                    SELECT unnest(string_split(assay_reasons, '; ')) AS x, coalesce(assay_status, 'not_checked') AS status
                    FROM r WHERE assay_reasons IS NOT NULL AND coalesce(assay_status, '') <> 'pass') GROUP BY ALL ORDER BY ALL""").fetchall():
            s["assay_reasons"].setdefault(reason, {})[status] = k
    return s


def _trait_parts(con, tiers, names, columns):
    """summary.json's per-trait parts for the traits `names` whose tier columns (<column>__<name>) the `tiers` file
    has: tier counts, region group x tier, chromosome x tier, 1 Mb bins ([chrom, bin, n tier 1..4], bin = (pos - 1)
    // 1e6) and evidence term x tier. Needs view `r`."""
    out = {k: {} for k in ("tiers", "region_tiers", "chrom_tiers", "bins", "terms")}
    stored = [c for c, in con.execute(f"SELECT column_name FROM (DESCRIBE SELECT * FROM read_parquet('{tiers}'))").fetchall()]
    names = [p for p in names if f"tier__{p}" in stored]
    if not names:
        return out
    con.execute(f"CREATE OR REPLACE TEMP TABLE s AS SELECT r.chrom, (r.pos - 1) // 1000000 AS bin, {region_sql(columns)} AS region, "
                + ", ".join(f"t.{ident('tier__' + p)}" for p in names)
                + f" FROM r JOIN read_parquet('{tiers}') t USING (file_row_number)")
    for p in names:
        t = ident("tier__" + p)
        rows = con.execute(f"SELECT GROUPING(region, chrom, bin), region, chrom, bin, {t}, count(*) FROM s GROUP BY GROUPING SETS "
                           f"(({t}), (region, {t}), (chrom, {t}), (chrom, bin, {t})) ORDER BY TRY_CAST(chrom AS INTEGER), chrom, bin, {t}").fetchall()
        bins = {}
        out["tiers"][p], out["region_tiers"][p], out["chrom_tiers"][p] = {}, {}, {}
        for g, region, chrom, b, tier, k in rows:  # GROUPING bits: region, chrom, bin (1 = summed over)
            if g == 7:
                out["tiers"][p][str(tier)] = k
            elif g == 3:
                if region:  # NULL without a region_class column
                    out["region_tiers"][p].setdefault(region, {})[str(tier)] = k
            elif g == 5:
                out["chrom_tiers"][p].setdefault(chrom, {})[str(tier)] = k
            else:
                bins.setdefault((chrom, b), [chrom, b, 0, 0, 0, 0])[1 + min(max(tier, 1), 4)] = k
        out["bins"][p] = list(bins.values())
        if f"tier_terms__{p}" in stored:  # group by the list of terms first: few distinct lists, then unnest
            out["terms"][p] = {}
            for term, tier, k in con.execute(
                    f"SELECT term, tier, sum(k)::BIGINT FROM (SELECT unnest(terms) AS term, tier, k FROM ("
                    f"SELECT list_transform({ident('tier_terms__' + p)}, lambda x: x.term) AS terms, {t} AS tier, count(*) AS k "
                    f"FROM read_parquet('{tiers}') GROUP BY ALL)) GROUP BY ALL ORDER BY ALL").fetchall():
                out["terms"][p].setdefault(term, {})[str(tier)] = k
    return out


def refresh_summary(d):
    """Rebuild a job's summary.json (one made before SUMMARY_VERSION) and return it."""
    con = connect([d], d)
    con.execute(f"CREATE VIEW r AS SELECT * FROM read_parquet('{d / 'result.parquet'}', file_row_number=true)")
    columns = [c for c, in con.execute("SELECT column_name FROM (DESCRIBE r)").fetchall()]
    s = summarise(con, d, columns, snpscore.load_weights(d / "weights.yaml"))
    _write_json(d / "summary.json", s)
    return s


def scored_sql(table, w, columns, preset, d):
    """snpscore.scored() for a job, telling it the snapshot's synthetic layers (which never count) when it can."""
    synthetic = [x["name"] for x in manifest(d).get("layers", []) if x.get("synthetic")]
    if "synthetic" in inspect.signature(snpscore.scored).parameters:
        return snpscore.scored(table, w, columns, preset, synthetic=synthetic)
    return snpscore.scored(table, w, columns, preset)


def ident(name):
    """Quote a column name for DuckDB SQL."""
    return '"' + str(name).replace('"', '""') + '"'


def check_rows(path, cap):
    """Raise InputError when the file has more than `cap` data lines. Counts lines on the decompressed stream in
    bounded reads, so a huge or gzip-bomb file stops at the cap instead of filling memory or disk."""
    with open(path, "rb") as f:
        gz = f.read(2) == b"\x1f\x8b"
    n = 0
    with (gzip.open if gz else open)(path, "rb") as f:
        for line in iter(lambda: f.readline(1 << 20), b""):
            if not line.startswith(b"#") and line.strip():
                n += 1
                if n > cap + 1:  # + 1 for a header line
                    raise InputError(f"This list has more than {cap:,} SNPs, the most the portal scores at once. "
                                     "Split it into smaller files, or run snpscore on your own computer (see 'Run it locally').")


def read_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (FileNotFoundError, ValueError):
        return {}


def lock_down(d):
    """Folder 0700, files 0600: results are readable only by the server's user."""
    d.chmod(0o700)
    for p in d.iterdir():
        p.chmod(0o600)


def _version(package):
    try:
        from importlib.metadata import version
        return version(package)
    except Exception:  # noqa: BLE001 - not installed as a distribution
        return None


def create_from_rows(rows, label, preset="all", kind="from_rows", input_format="rows", synthetic=False):
    """Make a job from rows of (chrom, pos, id, ref, alt), e.g. a gene or interval candidate list. Returns the key."""
    fd, tmp = tempfile.mkstemp(dir=results_dir(), prefix=".rows-", suffix=".tsv")
    try:
        with os.fdopen(fd, "w") as f:
            f.write("chrom\tpos\tid\tref\talt\n")
            for row in rows:
                f.write("\t".join("" if v is None else str(v).replace("\t", " ") for v in row) + "\n")
        return create(Path(tmp), ".tsv", kind, preset, label, input_format, synthetic)
    finally:
        Path(tmp).unlink(missing_ok=True)


def parse_paste(text, limit):
    """Rows (chrom, pos, None, ref, alt) from pasted 'chrom pos [ref alt]' lines (spaces, tabs, commas or ':'), or
    (None, None, rs ID, None, None) from a line starting with an rs ID (snpscore places it through EVA release 9)."""
    rows = []
    for number, line in enumerate(text.splitlines(), 1):
        fields = [f for f in re.split(r"[\s,;:]+", line.strip()) if f]
        if not fields or fields[0].startswith("#") or fields[0].lower() in ("chrom", "chr", "chromosome", "#chrom"):
            continue
        rs = re.fullmatch(r"rs\d{1,12}", fields[0], re.I)
        if not rs and (len(fields) < 2 or not fields[1].isdecimal()):  # not isdigit(): it accepts '²', which int() refuses
            raise InputError(f"Line {number}: expected a chromosome and a whole-number position, e.g. '25 28996360 C T', "
                             "or an rs ID.")
        if len(rows) == limit:
            raise InputError(f"Paste at most {limit:,} lines, or upload the list as a file.")
        ref, alt = (fields[2:4] + [None, None])[:2]
        rows.append((None, None, fields[0], None, None) if rs else (fields[0], int(fields[1]), None, ref, alt))
    if not rows:
        raise InputError("Paste at least one line with a chromosome and a position, e.g. '25 28996360 C T'.")
    return rows


# ---- lifecycle ----

def delete(key):
    """Delete a job now (the 'Delete now' button). A running job's folder is DuckDB's spill folder, so it only loses
    job.json (its pages say deleted, and it stops at its next stage); run() removes the folder when it ends."""
    key = str(key)
    with _lock:
        _queued.discard(key)
        running = key in _running
        if running:
            _deleted.add(key)
    if running:
        (folder(key) / "job.json").unlink(missing_ok=True)
    else:
        shutil.rmtree(folder(key), ignore_errors=True)
    log.info("job_deleted_by_user job_ref=%s", job_ref(key))


def cleanup():
    """Delete job folders whose job.json is older than SNPPORTAL_KEEP_HOURS (default 24), Design panel folders whose
    'created' marker is, and stray upload files; nothing on a local install. Safe to run concurrently: anything already
    gone is skipped. Returns the number of entries removed."""
    if keep_seconds() is None:
        return 0
    cutoff = time.time() - keep_seconds()
    removed = 0
    for p in results_dir().iterdir():
        try:
            mark = next((p / m for m in ("created", "job.json") if (p / m).exists()), p)  # a panel's age: from its start
            age = mark.stat().st_mtime
            if age >= cutoff:
                continue
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            else:
                p.unlink()
            removed += 1
        except FileNotFoundError:
            continue
    if removed:
        log.info("cleanup removed=%d", removed)
    return removed


def provenance(job, trait=None, filters=None):
    """'#' header lines for exports and figure captions: release, hashes, preset, filters, PROVISIONAL rules,
    SYNTHETIC inputs and the equivalent snpscore command. Never includes SNPs or file names."""
    trait = trait or job.get("preset") or "all"
    lines = [
        f"salmobase functional SNP portal, exported {utc()}",
        f"release {job.get('release')} ({job.get('assembly', 'Ssal_v3.1')}); manifest sha256 {job.get('manifest_sha256')}; "
        f"weights sha256 {job.get('weights_sha256')}",
        f"snpscore {job.get('snpscore_version')}; duckdb {job.get('duckdb_version')}; job created {job.get('created_utc')}",
        f"conditions {trait_label(trait)}; filters: {', '.join(f'{k}={v}' for k, v in (filters or {}).items()) or 'none'}",
        "tier rules PROVISIONAL (prototype weights, under review)",
    ]
    if job.get("synthetic_input") or job.get("synthetic_layers"):
        lines.append("SYNTHETIC: built from synthetic test data, not real results")
    cli = cli_trait(trait)
    lines.append(f"equivalent command: snpscore annotate <your list> --release <release {job.get('release')}> --trait "
                 + (cli or f"all (the portal scored tiers for {trait_label(trait)}, which snpscore has no name for)"))
    return ["# " + line for line in lines]
