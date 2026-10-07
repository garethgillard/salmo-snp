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

log = logging.getLogger("snpportal")
STALE = 300  # seconds without a heartbeat before a queued or running job is given up (server restarted)
MAX_QUEUED = 10
SNAPSHOT = ("weights.yaml", "manifest.json")
TIER_COLUMNS = ("tier", "tier_score", "tier_evidence", "tier_terms")
PUBLIC_AF = "504-fish panel: mostly wild and farmed fish from Bertolotti et al. 2020 plus the 12 AQUA-FAANG fish"  # public_af (R1)

_lock = threading.RLock()
_queued, _running = set(), set()
_executor = None


class QueueFull(Exception):
    """Too many jobs are waiting; try again in a minute."""


class InputError(ValueError):
    """The input can't be scored; the message says why and how to fix it."""


class Deleted(Exception):
    """The job folder was deleted while the job ran."""


def setting(name, default):
    return getattr(settings, name, default)


def release():
    return Path(settings.SNPSCORE_RELEASE).resolve()  # resolved: DuckDB's allowed_directories refuses symlinks


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
    snpscore has it."""
    if hasattr(snpscore, "connect"):
        return snpscore.connect(read_dirs=list(read), write_dir=write, **limits())
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
    return sha256(p) if kind == "sha256" else json.loads(p.read_text()) if kind == "json" else snpscore.load_weights(p.parent)


def _file(kind, path):
    path = Path(path)
    return _cached(kind, str(path), path.stat().st_mtime) if path.exists() else None


def manifest(where=None):
    """manifest.json of a job's snapshot folder, or of the current release ({} if missing)."""
    return _file("json", Path(where or release()) / "manifest.json") or {}


def weights(where=None):
    """weights.yaml of a job's snapshot folder, or of the current release (None if missing)."""
    return _file("weights", Path(where or release()) / "weights.yaml")


def release_info():
    """Version, assembly, build date, manifest sha256 and synthetic layers of the current release."""
    m = manifest()
    return {"version": m.get("version", "none"), "assembly": m.get("assembly", "Ssal_v3.1"), "created": m.get("created"),
            "sha256": _file("sha256", release() / "manifest.json"), "layers": m.get("layers", []),
            "synthetic": [layer["name"] for layer in m.get("layers", []) if layer.get("synthetic")]}


def release_changed(job):
    """True when the current release's manifest or weights differ from the job's snapshot."""
    return (job.get("manifest_sha256"), job.get("weights_sha256")) != (
        _file("sha256", release() / "manifest.json"), _file("sha256", release() / "weights.yaml"))


def presets(where=None):
    """[(value, label)] of the trait presets in weights.yaml."""
    w = weights(where)
    return [(p, p.replace("_", " ")) for p in w["presets"]] if w else []


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


def expires(key):
    """Unix time when cleanup() will delete the job."""
    return (folder(key) / "job.json").stat().st_mtime + 3600 * float(setting("SNPPORTAL_KEEP_HOURS", 24))


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


def create(src, suffix, input_kind="snps", preset="all", label="", input_format=None, synthetic=False, move=True):
    """Make a job from the input file `src` (moved into the job folder, or copied if move=False) and queue it.
    Returns the key. Raises QueueFull before creating anything when MAX_QUEUED jobs are already waiting."""
    if executor() is not None and len(_queued) >= MAX_QUEUED:
        raise QueueFull()
    key = uuid.uuid4()
    d = folder(key)
    d.mkdir(mode=0o700)
    for name in SNAPSHOT:
        if (release() / name).exists():
            shutil.copyfile(release() / name, d / name)
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
        "error_code": None, "error": None,
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
    inline); never raises: failures end in state 'failed' with an error_code and a message for the user."""
    key = str(key)
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
        _running.discard(key)
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
    w = snpscore.load_weights(d)
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

SUMMARY_VERSION = 3  # 3: molQTL count and assay reasons
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
    tiers = d / "tiers.parquet"
    stored = [c for c, in con.execute(f"SELECT column_name FROM (DESCRIBE SELECT * FROM read_parquet('{tiers}'))").fetchall()] if tiers.exists() else []
    presets = [p for p in (w or {}).get("presets", {}) if f"tier__{p}" in stored]
    if presets:
        for key in ("region_tiers", "chrom_tiers", "bins", "terms"):
            s[key] = {}
        con.execute(f"CREATE TEMP TABLE s AS SELECT r.chrom, (r.pos - 1) // 1000000 AS bin, {region_sql(columns)} AS region, "
                    + ", ".join(f"t.{ident('tier__' + p)}" for p in presets)
                    + f" FROM r JOIN read_parquet('{tiers}') t USING (file_row_number)")
        for p in presets:
            t = ident("tier__" + p)
            rows = con.execute(f"SELECT GROUPING(region, chrom, bin), region, chrom, bin, {t}, count(*) FROM s GROUP BY GROUPING SETS "
                               f"(({t}), (region, {t}), (chrom, {t}), (chrom, bin, {t})) ORDER BY TRY_CAST(chrom AS INTEGER), chrom, bin, {t}").fetchall()
            bins = {}
            s["tiers"][p], s["region_tiers"][p], s["chrom_tiers"][p] = {}, {}, {}
            for g, region, chrom, b, tier, k in rows:  # GROUPING bits: region, chrom, bin (1 = summed over)
                if g == 7:
                    s["tiers"][p][str(tier)] = k
                elif g == 3:
                    if region:  # NULL without a region_class column
                        s["region_tiers"][p].setdefault(region, {})[str(tier)] = k
                elif g == 5:
                    s["chrom_tiers"][p].setdefault(chrom, {})[str(tier)] = k
                else:
                    bins.setdefault((chrom, b), [chrom, b, 0, 0, 0, 0])[1 + min(max(tier, 1), 4)] = k
            s["bins"][p] = list(bins.values())
            if f"tier_terms__{p}" in stored:  # group by the list of terms first: few distinct lists, then unnest
                s["terms"][p] = {}
                for term, tier, k in con.execute(
                        f"SELECT term, tier, sum(k)::BIGINT FROM (SELECT unnest(terms) AS term, tier, k FROM ("
                        f"SELECT list_transform({ident('tier_terms__' + p)}, x -> x.term) AS terms, {t} AS tier, count(*) AS k "
                        f"FROM read_parquet('{tiers}') GROUP BY ALL)) GROUP BY ALL ORDER BY ALL").fetchall():
                    s["terms"][p].setdefault(term, {})[str(tier)] = k

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
        hist = dict(con.execute(f"SELECT least(floor(m / {MAF_BIN}), {round(0.5 / MAF_BIN) - 1})::INTEGER, count(*) "
                                f"FROM (SELECT {maf} AS m FROM r) GROUP BY 1").fetchall())
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


def refresh_summary(d):
    """Rebuild a job's summary.json (one made before SUMMARY_VERSION) and return it."""
    con = connect([d], d)
    con.execute(f"CREATE VIEW r AS SELECT * FROM read_parquet('{d / 'result.parquet'}', file_row_number=true)")
    columns = [c for c, in con.execute("SELECT column_name FROM (DESCRIBE r)").fetchall()]
    s = summarise(con, d, columns, snpscore.load_weights(d))
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
    """Delete a job folder now (the 'Delete now' button). A running job notices and stops writing."""
    _queued.discard(str(key))
    shutil.rmtree(folder(key), ignore_errors=True)
    log.info("job_deleted_by_user job_ref=%s", job_ref(key))


def cleanup():
    """Delete job folders whose job.json is older than SNPPORTAL_KEEP_HOURS (default 24), and stray upload files.
    Safe to run concurrently: anything already gone is skipped. Returns the number of entries removed."""
    cutoff = time.time() - 3600 * float(setting("SNPPORTAL_KEEP_HOURS", 24))
    removed = 0
    for p in results_dir().iterdir():
        try:
            age = (p / "job.json").stat().st_mtime if (p / "job.json").exists() else p.stat().st_mtime
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
        f"preset {trait}; filters: {', '.join(f'{k}={v}' for k, v in (filters or {}).items()) or 'none'}",
        "tier rules PROVISIONAL (prototype weights, under review)",
    ]
    if job.get("synthetic_input") or job.get("synthetic_layers"):
        lines.append("SYNTHETIC: built from synthetic test data, not real results")
    lines.append(f"equivalent command: snpscore annotate <your list> --release <release {job.get('release')}> --trait {trait}")
    return ["# " + line for line in lines]
