"""Your tracks (/snp/tracks/): a user's own BED files, shown in the locus browser above the release's tracks and
offered as a Table filter ('inside my track'). They are never scored: no tier, Overview or card changes (G,
2026-11-15). A track is a folder named by an unguessable id, holding track.parquet (chrom, start, end in BED
coordinates on the release's chromosome names, name, score, strand, rgb, max_end; sorted) and track.json (name,
assembly, n, ...); the uploaded file is deleted once converted. On the user's own computer (SNPPORTAL_LOCAL) tracks
live in the data folder's tracks/ and stay until deleted; on a server each is a track-<id> folder among the results,
listed for the browser that uploaded it (a cookie) and removed with the results after SNPPORTAL_KEEP_HOURS.
A track belongs to the assembly it was uploaded for: only that assembly's pages show it."""
from __future__ import annotations

import gzip
import os
import shutil
import time
import uuid
import zlib
from html import escape
from pathlib import Path

from django.http import Http404, HttpResponseNotAllowed
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.datastructures import MultiValueDict
from django.utils.safestring import mark_safe
from django.views.decorators.csrf import csrf_exempt, csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from snpscore.annotate import parquet_columns
from snpscore.formats import lit

from . import jobs, palette
from .views import PrivateReports, UploadToResults, private

COOKIE = "snpportal_mytracks"  # this browser's track ids on a server, newest first
SUFFIXES = (".bed.gz", ".bed", ".txt.gz", ".txt")
# PROVISIONAL limits (snpportal/AGENTS.md): G agreed 50 MB and a million intervals (2026-11-15); the rest are Claude's
MAX_MB, MAX_ROWS, MAX_TRACKS, NAME = 50, 1_000_000, 20, 80
MAX_UNPACKED_MB = 500  # a gzipped file, unpacked (a million BED lines with names is about 100 MB)
DRAWN, LANES = 5000, 4  # intervals drawn per track in a window, and the lanes overlapping ones are packed into
ERRORS = {
    "file": "Choose a BED file (.bed, .bed.gz or .txt): chromosome, start and end, then optionally a name, score, strand and colour.",
    "large": "The file is larger than {mb:g} MB.",
    "unpacked": "Unpacked, the file is larger than {unpacked:g} MB.",
    "rows": "The file has more than {rows:,} intervals.",
    "empty": "No interval in the file is on a chromosome of {assembly}: check the chromosome names and the assembly.",
    "many": "You have {tracks} tracks already: delete one first.",
    "read": "The file could not be read as BED: chromosome, start and end, separated by tabs or spaces.",
    "encoding": "The file is not UTF-8 text (Excel's 'Text (Tab delimited)' on Windows is not): save it as UTF-8 and try again.",
}


# ---- where tracks are kept ----

def root():
    """A local install's tracks folder: SNPPORTAL_MYTRACKS_DIR, else tracks/ next to the results folder."""
    return Path(jobs.setting("SNPPORTAL_MYTRACKS_DIR", jobs.results_dir().parent / "tracks"))


def folder(track_id):
    """The folder of an existing track, or None (not an id, gone, or expired). The id is the only way in."""
    try:
        name = str(uuid.UUID(str(track_id)))
    except ValueError:
        return None
    d = root() / name if jobs.local() else jobs.results_dir() / f"track-{name}"
    try:
        fresh = jobs.keep_seconds() is None or time.time() - (d / "created").stat().st_mtime < jobs.keep_seconds()
    except FileNotFoundError:
        return None
    return d if fresh and (d / "track.json").is_file() and (d / "track.parquet").is_file() else None


def meta(d):
    return {**jobs.read_json(d / "track.json"), "path": d / "track.parquet"}


def _ids(request):
    """The track ids this browser added (a server's signed cookie: an id alone, as in a shared Table link, only filters)."""
    cookie = request.get_signed_cookie(COOKIE, default="", salt=COOKIE) if hasattr(request, "get_signed_cookie") else ""
    return [i for i in cookie.split(",") if i][:MAX_TRACKS]


def mine(request, assembly=None):
    """This user's tracks, newest first: every track of a local install, else those this browser uploaded. With
    `assembly`, only that assembly's."""
    if jobs.local():
        ids = [d.name for d in root().iterdir()] if root().is_dir() else []
    else:
        ids = _ids(request)
    found = [meta(d) for d in map(folder, ids) if d]
    if jobs.local():  # newest first ('created' never changes; added_utc is to the minute)
        found.sort(key=lambda m: (m["path"].parent / "created").stat().st_mtime, reverse=True)
    return [m for m in found if assembly is None or m.get("assembly") == assembly]


def keep(response, ids):
    """Remember this browser's tracks (a server only: a local install lists its folder)."""
    if not jobs.local():
        response.set_signed_cookie(COOKIE, ",".join(ids[:MAX_TRACKS]), salt=COOKIE,
                                   max_age=int(jobs.keep_seconds() or jobs.FOREVER), httponly=True, samesite="Lax",
                                   path=jobs.cookie_path())
    return response


def usable(m, d):
    """Why track `m` may not filter the job in folder `d`, or None when it may. It must be on the job's assembly; and
    on a server, the job must be one its owner filtered with it (allow): the id then works in that job's links, as
    the job's key does, but pasting it into another job's Table can't map the track with a list of one's own."""
    if not jobs.local() and (d is None or Path(d).name not in m.get("jobs", [])):
        return "no longer available"  # as for a deleted track: says nothing of whether it exists
    if m.get("assembly") != jobs.manifest(d).get("assembly", "Ssal_v3.1"):
        return "on another assembly"
    return None


def allow(request, d):
    """On a server, when the browser that owns the track in ?track= opens the job in folder `d` with it, let the track
    filter that job from then on (usable). A local install needs nothing."""
    track = folder(request.GET.get("track", "")) if not jobs.local() and request.GET.get("track") else None
    if track is None or track.name.removeprefix("track-") not in _ids(request):
        return
    m = jobs.read_json(track / "track.json")
    if Path(d).name not in m.get("jobs", []):
        jobs._write_json(track / "track.json", {**m, "jobs": [*m.get("jobs", []), Path(d).name]})


def read_dirs(request):
    """The folder of the track a request's ?track= names, as a list (empty when none): what a sandboxed connection
    must be allowed to read for the Table's filter."""
    d = folder(request.GET.get("track", "")) if request.GET.get("track") else None
    return [d] if d else []


def asis(text, guard=None):
    """User text (a track's or an interval's name) escaped for HTML or SVG and, on another species' pages, written as
    character references, so that jobs.wording() (which turns the pages' salmon wording into the release's) leaves it
    as the user wrote it. `guard`: whether wording applies, when the caller already knows."""
    guard = bool(jobs.wording()) if guard is None else guard
    if not guard:
        return mark_safe(escape(str(text)))
    return mark_safe("".join(f"&#{ord(c)};" if c.isascii() and c.isalnum() else escape(c) for c in str(text)))


# ---- reading a BED file ----

def unpacked(src, limit):
    """Check a gzipped file whole before it is read: ValueError('unpacked') past `limit` bytes unpacked (a small file
    can unpack to gigabytes), ValueError('read') when it is damaged or cut short."""
    total = 0
    try:
        with gzip.open(src, "rb") as f:
            while chunk := f.read(1 << 20):
                total += len(chunk)
                if total > limit:
                    raise ValueError("unpacked")
    except (OSError, EOFError, zlib.error):
        raise ValueError("read") from None


def convert(src, d):
    """Write d/track.parquet from the BED file `src`: lines of chromosome, start, end and optionally name, score,
    strand, (thickStart, thickEnd,) itemRgb. A line with a tab is split on tabs (so names may hold spaces), others on
    runs of spaces. Comment, 'track' and 'browser' lines are skipped, and a first line whose start is not a number
    and whose chromosome is not one is a header. Chromosome names go through the release's aliases (ssa25, chr25,
    accessions); intervals on other names, or without 0 <= start < end, are left out and counted. max_end is the
    largest end of the chromosome's intervals starting at or before each start (ties share it): the Table's filter
    finds the last start before a SNP and compares its max_end. Returns {n, dropped, colours}; raises
    ValueError('rows' | 'unpacked' | 'empty' | 'encoding' | 'read')."""
    release, cap = jobs.release(), int(jobs.setting("SNPPORTAL_MAX_TRACK_ROWS", MAX_ROWS))
    with open(src, "rb") as f:
        gz = f.read(2) == b"\x1f\x8b"
    if gz:
        unpacked(src, float(jobs.setting("SNPPORTAL_MAX_TRACK_UNPACKED_MB", MAX_UNPACKED_MB)) * 2 ** 20)
    split = "list_slice(CASE WHEN contains(line, chr(9)) THEN string_split(line, chr(9)) ELSE string_split_regex(trim(line), '\\s+') END, 1, 9)"
    known = list(jobs.manifest().get("chrom_sizes") or {})
    con = jobs.connect([Path(src).parent, release, d], d)
    try:
        con.execute(f"""CREATE TEMP TABLE raw AS SELECT {split} AS f FROM read_csv({lit(src)}, header=false,
            columns={{'line': 'VARCHAR'}}, delim='\x01', quote='', escape='', auto_detect=false,
            compression={lit('gzip' if gz else 'none')})
            WHERE trim(line) <> '' AND NOT regexp_matches(line, '^(#|track\\s|browser\\s)') LIMIT {cap + 2}""")
        alias = release / "alias.parquet"
        warned = " AND a.warning IS NULL" if alias.exists() and "warning" in parquet_columns(con, alias) else ""
        join = f"LEFT JOIN read_parquet({lit(alias)}) a ON a.alias = lower(trim(r.f[1])){warned}" if alias.exists() else ""  # not an older sequence's (HG993277.1)
        chrom = "coalesce(a.chrom, trim(r.f[1]))" if join else "trim(r.f[1])"
        rgb = "regexp_extract(trim(r.f[9]), '^(\\d{1,3}),(\\d{1,3}),(\\d{1,3})$', ['r', 'g', 'b'])"
        con.execute(f"""CREATE TEMP TABLE t AS SELECT r.rowid AS i, {chrom} AS chrom, try_cast(trim(r.f[2]) AS BIGINT) AS start,
                try_cast(trim(r.f[3]) AS BIGINT) AS "end", nullif(nullif(trim(r.f[4]), ''), '.')[:200] AS name,
                try_cast(trim(r.f[5]) AS DOUBLE) AS score, CASE WHEN trim(r.f[6]) IN ('+', '-') THEN trim(r.f[6]) END AS strand,
                {rgb} AS c
            FROM raw r {join}""")
        total, header = con.execute("""SELECT count(*), count(*) FILTER (WHERE i = (SELECT min(i) FROM t) AND start IS NULL
                                              AND chrom NOT IN (SELECT unnest(?::VARCHAR[]))) FROM t""", [known]).fetchall()[0]
        total -= header
        if total > cap:
            raise ValueError("rows")
        con.execute("""CREATE TEMP TABLE kept AS SELECT chrom, start, "end", name, score, strand,
                CASE WHEN r <= 255 AND g <= 255 AND b <= 255 AND r + g + b > 0  -- 0 or 0,0,0: no colour of its own
                     THEN printf('#%02X%02X%02X', r, g, b) END AS rgb
            FROM (SELECT *, try_cast(c.r AS INT) AS r, try_cast(c.g AS INT) AS g, try_cast(c.b AS INT) AS b FROM t)
            WHERE chrom IN (SELECT unnest(?::VARCHAR[])) AND start >= 0 AND "end" > start""", [known])
        n, colours = con.execute("SELECT count(*), count(rgb) FROM kept").fetchall()[0]
        if not n:
            raise ValueError("empty")
        new = d / ".track.parquet"
        con.execute(f"""COPY (SELECT *, max("end") OVER (PARTITION BY chrom ORDER BY start
                                                         RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS max_end
                             FROM kept ORDER BY chrom, start, "end") TO {lit(new)} (FORMAT parquet)""")
    except ValueError:
        raise
    except Exception as e:  # DuckDB could not read it (its message may quote the file: withheld)
        raise ValueError("encoding" if "not utf-8 encoded" in str(e).lower() else "read") from None
    finally:
        con.close()
    os.chmod(new, 0o600)
    os.replace(new, d / "track.parquet")
    return {"n": n, "dropped": total - n, "colours": colours}


def create(upload, name, assembly):
    """A new track from an uploaded file (moved in, converted, deleted): its id. ValueError as convert()."""
    track_id = str(uuid.uuid4())
    parent = root() if jobs.local() else jobs.results_dir()
    parent.mkdir(parents=True, exist_ok=True)
    d = parent / (track_id if jobs.local() else f"track-{track_id}")
    d.mkdir(mode=0o700)
    src = d / "upload"
    try:
        os.replace(upload.path, src)
        os.chmod(src, 0o600)
        (d / "created").touch(mode=0o600)  # never changes: cleanup counts the hours from it
        found = convert(src, d)
        src.unlink()
        jobs._write_json(d / "track.json", {
            "id": track_id, "name": name[:NAME], "assembly": assembly, "release": jobs.manifest().get("version"),
            "added_utc": jobs.utc(), "shown": True, **found})
    except BaseException:
        shutil.rmtree(d, ignore_errors=True)
        raise
    return track_id


# ---- the locus browser's group ----

def rows(m, chrom, start, end, shown=None):
    """A track's intervals overlapping chrom:start-end (BED), at most DRAWN + 1: those in the `shown` window (start,
    end) first, an even sample of them when there are more, then the margins' nearest the window first, so the cap is
    spent where the user looks and next to it. The first DRAWN by start; one more means some were left out."""
    a, b = shown or (start, end)
    con = jobs.connect([m["path"].parent])
    try:
        cur = con.execute(f"""SELECT start, "end", name, score, strand, rgb FROM read_parquet({lit(m['path'])})
                              WHERE chrom = ? AND start < ? AND "end" > ?
                              ORDER BY ("end" <= ? OR start >= ?), greatest(? - "end", start - ?, 0), hash(start, "end")
                              LIMIT {DRAWN + 1}""", [chrom, end, start, a, b, a, b])
        found = cur.fetchall()
    finally:
        con.close()
    return sorted(found[:DRAWN], key=lambda r: (r[0], r[1])) + found[DRAWN:]  # drawn by start; one more: cut


def draw(m, ax, chrom, found, width):
    """(height, SVG body) of one track's row: its intervals as boxes in the BED's own colour, else the tracks' colour,
    packed into at most LANES lanes where they overlap (the last lane takes the rest); hover: name, position, strand
    and score. `width`: the track column's, for the lines that span the margins."""
    lanes, body, guard = [], [], bool(jobs.wording())  # lanes: each one's last end, in bp
    for a, e, name, score, strand, rgb in found[:DRAWN]:
        x0, x1 = ax.x(a), ax.x(e)
        lane = next((i for i, right in enumerate(lanes) if right <= a), None)  # overlapping intervals go below
        if lane is None:
            lane = len(lanes) if len(lanes) < LANES else LANES - 1
            lanes[len(lanes):] = [0] * (lane + 1 - len(lanes))
        lanes[lane] = max(lanes[lane], e)
        fill = rgb or palette.USER_TRACK
        score = None if score is None else repr(score).removesuffix(".0")  # every digit the file has
        tip = " · ".join(x for x in (asis(name, guard) if name else "", f"{chrom}:{a + 1:,}-{e:,}",
                                     f"{strand} strand" if strand else "", f"score {score}" if score else "") if x)
        edge = f' stroke="{palette.edge(fill)}" stroke-width="0.5"' if palette.edge(fill) else ""
        body.append(f'<rect x="{x0:.1f}" y="{2 + lane * 11}" width="{max(1.5, x1 - x0):.1f}" height="9" fill="{fill}"{edge}>'
                    f'<title>{tip}</title></rect>')
    h = 4 + 11 * max(1, len(lanes))
    line = f'<line x1="{-width}" x2="{2 * width}" y1="{h - 0.5}" y2="{h - 0.5}" stroke="{palette.GREY[300]}"/>'
    return h, line + "".join(body)


# ---- the page ----

def _error(code, assembly):
    text = ERRORS.get(code or "", "")
    return text.format(mb=float(jobs.setting("SNPPORTAL_MAX_TRACK_MB", MAX_MB)), assembly=assembly, tracks=MAX_TRACKS,
                       unpacked=float(jobs.setting("SNPPORTAL_MAX_TRACK_UNPACKED_MB", MAX_UNPACKED_MB)),
                       rows=int(jobs.setting("SNPPORTAL_MAX_TRACK_ROWS", MAX_ROWS)))


@private
def page(request):
    """/snp/tracks/: this user's tracks and the form that adds one."""
    assembly = jobs.manifest().get("assembly", "Ssal_v3.1")
    tracks = mine(request)
    for m in tracks:
        m["here"] = m.get("assembly") == assembly
    added = next((m for m in tracks if m.get("id") == request.GET.get("added")), None)
    return render(request, "snpportal/tracks.html", {
        "nav": "explore", "title": "Your tracks", "tracks": tracks, "assembly": assembly, "added": added,
        "error": _error(request.GET.get("error"), assembly), "local": jobs.local(), "keep_hours": jobs.keep_text(),
        "max_mb": float(jobs.setting("SNPPORTAL_MAX_TRACK_MB", MAX_MB)), "max_rows": int(jobs.setting("SNPPORTAL_MAX_TRACK_ROWS", MAX_ROWS)),
        "max_unpacked": float(jobs.setting("SNPPORTAL_MAX_TRACK_UNPACKED_MB", MAX_UNPACKED_MB))})


def _back(code=None, **more):
    query = "&".join(f"{k}={v}" for k, v in {"error": code, **more}.items() if v)
    return redirect(reverse("snpportal:tracks") + (f"?{query}" if query else ""))


@csrf_exempt  # so the upload handler can be set before the body is read; _add checks the CSRF token
def add(request):
    """POST a BED file (and a name): a new track, then back to the page."""
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    try:
        length = int(request.META.get("CONTENT_LENGTH") or 0)
    except ValueError:
        length = 0
    if length > float(jobs.setting("SNPPORTAL_MAX_TRACK_MB", MAX_MB)) * 2 ** 20:  # before Django reads the body
        return _back("large")
    request.exception_reporter_filter = PrivateReports()
    handler = UploadToResults(request)
    request.upload_handlers = [handler]
    try:
        return _add(request)
    except Exception:
        request._files = MultiValueDict()  # keep uploaded file names out of the error report
        raise
    finally:
        handler.discard()


@csrf_protect
@sensitive_post_parameters()
@private
def _add(request):
    upload = request.FILES.get("file")
    lower = (upload.name or "").lower() if upload else ""
    suffix = next((s for s in SUFFIXES if lower.endswith(s)), None)
    if not upload or suffix is None:
        return _back("file")
    if len(mine(request)) >= MAX_TRACKS:
        return _back("many")
    name = (request.POST.get("name") or "").strip() or upload.name[:-len(suffix)] or "Track"
    try:
        track_id = create(upload, name, jobs.manifest().get("assembly", "Ssal_v3.1"))
    except ValueError as e:
        return _back(str(e))
    return keep(_back(added=track_id), [track_id] + _ids(request))


@private
def change(request, track_id):
    """POST action=delete | show | hide for one of this user's tracks."""
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    d = folder(track_id)
    if d is None or (not jobs.local() and str(track_id) not in _ids(request)):
        raise Http404("No such track")
    action = request.POST.get("action")
    if action == "delete":
        shutil.rmtree(d, ignore_errors=True)
        return keep(_back(), [i for i in _ids(request) if i != str(track_id)])
    if action in ("show", "hide"):
        jobs._write_json(d / "track.json", {**jobs.read_json(d / "track.json"), "shown": action == "show"})
    return _back()
