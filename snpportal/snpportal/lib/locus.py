"""Everything a release knows about a genome window, for the locus browser and the evidence card, plus live signal
(bigWig) and ChromHMM segments (bigBed) on a fixed public tile grid, and one-position annotation for variant pages.
Coordinates are BED (0-based start, exclusive end), except the 1-based `pos` of SNPs and variants."""
from __future__ import annotations

import concurrent.futures
import csv
import hashlib
import json
import logging
import math
import re
import shutil
import tempfile
import time
from pathlib import Path

from snpscore import bbi
from snpscore.annotate import annotate, connect
from snpscore.formats import lit
from snpscore.score import CHROMATIN_CONDITIONS

MIN_WINDOW, MAX_WINDOW = 60, 2_000_000  # annotation lanes (60 bp: the browser's motif logos are readable from 150 bp)
MAX_SIGNAL = 500_000  # signal and ChromHMM rows are read only in windows up to this wide
CAPS = {"genes": 300, "peaks": 5000, "regbuild": 5000, "gerp": 5000, "variants": 5000}  # rows per lane; more = truncated
PUBLIC_SNPS = ("synchrosmolt_af", "axiom")  # point layers of public SNP sets besides public_af ('variants')
RUNGS = (10, 50, 200, 1000, 5000)  # signal tile grid: bases per bin
TILE_BINS = 200  # bins per signal tile
HMM_TILE = 250_000  # bases per ChromHMM tile
POSITION_PAD = 100_000  # annotate_position keeps at least this much of each layer either side (probe flanks etc.)
UNITS = {"": 1, "bp": 1, "kb": 1_000, "mb": 1_000_000}
REGION = re.compile(r"^\s*([\w.]+?)\s*[:\s]\s*([\d.,]+)\s*(bp|kb|mb)?\s*(?:(?:-|\.\.|–)\s*([\d.,]+)\s*(bp|kb|mb)?)?\s*$", re.I)

log = logging.getLogger(__name__)


def parse_region(text, release_dir=None):
    """(chrom, start, end) in BED coordinates from '25:28,980,000-29,010,000', 'ssa25:28.98-29.01Mb' or '25:28996360'
    (a 1-bp window). Chromosome aliases resolve through the release's alias.parquet. Raises ValueError."""
    m = REGION.match(text or "")
    if not m:
        raise ValueError("Write a region as chromosome:start-end, e.g. 25:28,980,000-29,010,000 or ssa25:28.98-29.01 Mb")
    chrom, a, unit_a, b, unit_b = m.groups()
    unit_a = (unit_a or unit_b or "").lower()
    try:
        start = round(float(a.replace(",", "")) * UNITS[unit_a])
        end = round(float(b.replace(",", "")) * UNITS[(unit_b or unit_a).lower()]) if b else start
    except ValueError:
        raise ValueError(f"'{text}' has a position that is not a number") from None
    start, end = min(start, end), max(start, end)
    if release_dir is not None:
        chrom = resolve_chrom(release_dir, chrom)
    return chrom, max(0, start - 1), max(end, 1)


def resolve_chrom(release_dir, name):
    """The release's name for a chromosome (aliases such as ssa25, chr25 or NC_059466.1 through alias.parquet);
    ValueError when the release doesn't know it."""
    release = Path(release_dir).resolve()
    sizes = json.loads((release / "manifest.json").read_text()).get("chrom_sizes") or {}
    if name in sizes:
        return name
    alias = release / "alias.parquet"
    if alias.exists():
        found = connect([release]).execute(f"SELECT chrom FROM read_parquet({lit(alias)}) WHERE alias = lower(?) LIMIT 1",
                                           [name]).fetchone()
        if found and (found[0] in sizes or not sizes):
            return found[0]
    if not sizes:
        return name
    raise ValueError(f"Unknown chromosome '{name}': use 1-29 (Ensembl/AQUA-FAANG names) or an alias such as ssa25")


def clamp(start, end, size=None, low=MIN_WINDOW, high=None):
    """The window start-end widened to at least `low` bp (and narrowed to `high`) around its centre, inside 0-size."""
    width = max(low, end - start) if high is None else min(high, max(low, end - start))
    centre = (start + end) // 2
    start = max(0, centre - width // 2)
    if size:
        start = max(0, min(start, size - width))
    return start, start + width


def catalog(release_dir):
    """Rows of the release's known-loci catalogue (catalog/known_loci.tsv), each with `dois` from its source column."""
    path = Path(release_dir) / "catalog" / "known_loci.tsv"
    if not path.exists():
        return []
    with open(path, newline="") as f:
        rows = list(csv.DictReader((line for line in f if not line.startswith("#")), delimiter="\t"))
    for r in rows:
        r["dois"] = [d.strip() for d in (r.get("source") or "").split(";") if d.strip().startswith("10.")]
    return rows


def locus(release_dir, chrom, start, end, all_transcripts=False):
    """The release's lanes in chrom:start-end (at most MAX_WINDOW bp; lanes stop at CAPS rows, listed in 'truncated'):
    genes (one model each: the canonical transcript, else the longest; all transcripts, canonical first, with
    all_transcripts), peaks with their state per condition, regbuild, gerp, blacklist, lore, public variants
    (pos 1-based, with af/maf/dr2), the other public SNP sets (PUBLIC_SNPS, each under its layer name) and known
    loci. A lane whose file the release lacks is an empty list."""
    if end - start > MAX_WINDOW:
        raise ValueError(f"windows are at most {MAX_WINDOW:,} bp")
    release = Path(release_dir).resolve()
    manifest = json.loads((release / "manifest.json").read_text())
    con = connect([release])
    window = {"c": chrom, "s": start, "e": end}
    out = {"chrom": chrom, "start": start, "end": end, "size": (manifest.get("chrom_sizes") or {}).get(chrom),
           "truncated": [], "conditions": []}

    def rows(sql, params=window):
        rel = con.execute(sql, params)
        names = [d[0] for d in rel.description]
        return [dict(zip(names, r)) for r in rel.fetchall()]

    def lane(name, file=None, cap=100_000):
        path = release / f"{file or name}.parquet"
        if not path.exists():
            return []
        found = rows(f"""SELECT * EXCLUDE (chrom) FROM read_parquet({lit(path)})
                         WHERE chrom = $c AND start < $e AND "end" > $s ORDER BY start, "end" LIMIT {cap + 1}""")
        if len(found) > cap:
            out["truncated"].append(name)
        return found[:cap]

    peaks = lane("peaks", "chromatin", CAPS["peaks"])
    if (release / "chromatin.parquet").exists():
        names = [c for c, in con.execute(f"SELECT column_name FROM (DESCRIBE SELECT * FROM "
                                         f"read_parquet({lit(release / 'chromatin.parquet')}))").fetchall()]
        others = [c for c in names if c not in ("chrom", "start", "end", "summary")]
        out["conditions"] = [c for c in CHROMATIN_CONDITIONS if c in others] + [c for c in others if c not in CHROMATIN_CONDITIONS]
    out["peaks"] = [{"start": p["start"], "end": p["end"], "id": f"{chrom}:{p['start']}-{p['end']}", "summary": p.get("summary"),
                     "states": {c: p[c] for c in out["conditions"] if p.get(c)}} for p in peaks]
    for name in ("regbuild", "gerp", "blacklist", "lore"):
        out[name] = lane(name, cap=CAPS.get(name, 1000))
    out["variants"] = [dict(v, pos=v["end"]) for v in lane("variants", "public_af", CAPS["variants"])]
    for name in PUBLIC_SNPS:  # the other public SNP sets, each its own lane (af, maf, ...; axiom: probe)
        out[name] = [dict(v, pos=v["end"]) for v in lane(name, cap=CAPS["variants"])]
    out["motif"] = [dict(v, pos=v["end"]) for v in lane("motif", cap=CAPS["variants"]) if v.get("changed")]  # TF motif changes
    out["known"] = [r for r in catalog(release) if r.get("chrom") == chrom and r.get("pos", "").isdigit()
                    and start < int(r["pos"]) <= end]
    out["genes"] = _genes(release, rows, chrom, lane("genes", "gene", CAPS["genes"]), all_transcripts)
    con.close()
    return out


def _genes(release, rows, chrom, genes, all_transcripts):
    """Gene dicts with ortholog names, a display label and their transcript models ({transcript_id, canonical, start,
    end, parts [{start, end, part}]}, canonical first)."""
    if not genes:
        return []
    ids = [g["id"] for g in genes]
    orthologs = {}
    if (release / "gene_ortholog.parquet").exists():
        orthologs = {r["gene_id"]: r for r in rows(f"SELECT * FROM read_parquet({lit(release / 'gene_ortholog.parquet')}) "
                                                   "WHERE gene_id IN (SELECT unnest($ids))", {"ids": ids})}
    models = {}
    if (release / "transcripts.parquet").exists():
        one = "" if all_transcripts else "QUALIFY row_number() OVER (PARTITION BY gene_id ORDER BY canonical DESC, \"end\" - start DESC, transcript_id) = 1"
        for t in rows(f"""
                SELECT * FROM (SELECT gene_id, transcript_id, bool_or(coalesce(canonical, false)) AS canonical,
                                      min(start) AS start, max("end") AS "end",
                                      list({{'start': start, 'end': "end", 'part': part}} ORDER BY start) AS parts
                               FROM read_parquet({lit(release / 'transcripts.parquet')})
                               WHERE chrom = $c AND start < $e AND "end" > $s AND gene_id IN (SELECT unnest($ids))
                               GROUP BY ALL)
                {one} ORDER BY gene_id, canonical DESC, start""",
                      {"c": chrom, "s": min(g["start"] for g in genes), "e": max(g["end"] for g in genes), "ids": ids}):
            models.setdefault(t.pop("gene_id"), []).append(t)
    out = []
    for g in genes:
        o = orthologs.get(g["id"], {})
        out.append(dict(g, human=o.get("human"), zebrafish=o.get("zebrafish"), transcripts=models.get(g["id"], []),
                        label=gene_label(g.get("name"), o.get("human"), o.get("zebrafish"), g["id"])))
    return out


def gene_label(name, human=None, zebrafish=None, gene_id=""):
    """Ensembl name; for unnamed genes '~' + the human (else zebrafish) ortholog name (PROVISIONAL naming); else the id."""
    if name:
        return name
    ortholog = (human or zebrafish or "").split(",")[0]
    return f"~{ortholog}" if ortholog else gene_id


# ---- live signal and ChromHMM segments on a fixed tile grid ----

def rung(width, target=600):
    """Bases per bin for a window `width` bp wide: the RUNGS step giving closest to `target` bins."""
    return min(RUNGS, key=lambda r: abs(math.log(max(width, 1) / r / target)))


def _key(prefix, kind, url, *parts):
    """Cache key of a public tile: '<prefix>:<kind>:<first 16 hex of the track URL's sha1>:<chrom>[:<rung>]:<tile>'
    (signal tiles carry their rung; tile = index on the fixed grid), never a user's position. Which tiles are cached
    still shows which windows were viewed, so views of a user's SNPs pass a cache that stores nothing (the portal
    does for views opened from a job)."""
    return ":".join([prefix, kind, hashlib.sha1(url.encode()).hexdigest()[:16], *map(str, parts)])


def _get_many(cache, keys):
    if cache is None:
        return {}
    return cache.get_many(keys) if hasattr(cache, "get_many") else {k: cache[k] for k in keys if k in cache}


def _set_many(cache, values):
    if cache is not None and values:
        (cache.set_many if hasattr(cache, "set_many") else cache.update)(values)


def _many(fn, items, deadline):
    """fn(*item) for every item on snpscore.bbi's reader threads, like bbi.bins_many: a result per item, or None when it
    failed or missed the deadline (seconds); late tasks stop at their next request."""
    until = time.monotonic() + deadline

    def task(item):
        bbi._local.deadline = until
        try:
            return fn(*item)
        finally:
            bbi._local.deadline = None

    futures = [bbi._EXECUTOR.submit(task, item) for item in items]
    concurrent.futures.wait(futures, timeout=deadline)
    out = []
    for item, f in zip(items, futures):
        ok = f.done() and not f.cancelled() and f.exception() is None
        if not ok:
            log.warning("no data from %s: %r", item[0], f.exception() if f.done() and not f.cancelled() else "deadline passed")
            f.cancel()
        out.append(f.result() if ok else None)
    return out


def signal(tracks, chrom, start, end, cache=None, prefix="snpscore", deadline=4.0):
    """Mean signal of each track (tracks.yaml entries) across chrom:start-end, in bins of rung(end - start) bp aligned
    to a fixed grid of TILE_BINS-bin tiles. Tiles come from `cache` (anything with get_many/set_many, e.g. a Django
    cache, or a dict) or are read with one task per track; a track that fails or misses the deadline is None (shown as
    'signal unavailable', never filled in). Returns {start (of the first bin), rung, values: [list or None per track]}."""
    r = rung(end - start)
    size = r * TILE_BINS
    tiles = list(range(start // size, (end - 1) // size + 1))
    keys = {(t["url"], i): _key(prefix, "sig", t["url"], chrom, r, i) for t in tracks for i in tiles}
    have = _get_many(cache, list(keys.values()))
    todo = [(t["url"], [i for i in tiles if keys[(t["url"], i)] not in have]) for t in tracks]
    todo = [item for item in todo if item[1]]

    def read(url, wanted):  # one read per run of adjacent tiles (the same bins as tile by tile: they share the grid)
        f, out, runs = bbi.open_bbi(url), [], []
        for i in wanted:
            if runs and i == runs[-1][-1] + 1:
                runs[-1].append(i)
            else:
                runs.append([i])
        for run in runs:
            values = f.bins(chrom, run[0] * size, (run[-1] + 1) * size, TILE_BINS * len(run))
            out += [values[k * TILE_BINS:(k + 1) * TILE_BINS] for k in range(len(run))]
        return out

    fresh = {}
    for (url, wanted), got in zip(todo, _many(read, todo, deadline)):
        if got is not None:
            fresh.update({keys[(url, i)]: values for i, values in zip(wanted, got)})
    _set_many(cache, fresh)
    have.update(fresh)
    first = tiles[0] * size
    lo, hi = (start - first) // r, -(-(end - first) // r)
    values = []
    for t in tracks:
        parts = [have.get(keys[(t["url"], i)]) for i in tiles]
        values.append(None if any(p is None for p in parts) else [v for p in parts for v in p][lo:hi])
    return {"start": first + lo * r, "rung": r, "values": values}


def segments(tracks, chrom, start, end, cache=None, prefix="snpscore", deadline=4.0):
    """ChromHMM segments [(start, end, state)] of each bigBed track (tracks.yaml 'chromhmm' entries) overlapping
    chrom:start-end, read on a fixed grid of HMM_TILE-bp tiles (cached like signal()); None for a failed track.
    States are named as in the chromatin layer (spaces become underscores)."""
    tiles = list(range(start // HMM_TILE, (end - 1) // HMM_TILE + 1))
    keys = {(t["url"], i): _key(prefix, "hmm", t["url"], chrom, i) for t in tracks for i in tiles}
    have = _get_many(cache, list(keys.values()))
    todo = [(t["url"], [i for i in tiles if keys[(t["url"], i)] not in have]) for t in tracks]
    todo = [item for item in todo if item[1]]

    def read(url, wanted):
        f = bbi.open_bbi(url)
        return [[(s, e, rest.split("\t")[0].replace(" ", "_")) for s, e, rest in
                 f.entries(chrom, i * HMM_TILE, (i + 1) * HMM_TILE)] for i in wanted]

    fresh = {}
    for (url, wanted), got in zip(todo, _many(read, todo, deadline)):
        if got is not None:
            fresh.update({keys[(url, i)]: found for i, found in zip(wanted, got)})
    _set_many(cache, fresh)
    have.update(fresh)
    out = []
    for t in tracks:
        parts = [have.get(keys[(t["url"], i)]) for i in tiles]
        if any(p is None for p in parts):
            out.append(None)
            continue
        found = sorted({tuple(x) for p in parts for x in p if x[0] < end and x[1] > start})
        out.append(found)
    return out


# ---- one position, for variant pages ----

def annotate_position(release_dir, chrom, pos, ref=None, alt=None, trait="all", work_dir=None):
    """The annotated row (a dict, as `snpscore annotate` writes it) for one position, without a job: the release's
    layers are first cut to a window around it (max_distance, window or POSITION_PAD bp either side, whichever is
    widest) in a temporary folder under work_dir, so it takes a fraction of a second instead of seconds.
    Raises InputError (e.g. an unknown chromosome)."""
    release = Path(release_dir).resolve()
    manifest = json.loads((release / "manifest.json").read_text())
    with tempfile.TemporaryDirectory(dir=work_dir, prefix=".variant-") as tmp:
        mini = Path(tmp).resolve()
        con = connect([release], mini)
        for layer in manifest["layers"]:
            src = release / f"{layer['name']}.parquet"
            if not src.exists():
                continue
            if layer["type"] in ("interval", "nearest", "count", "point"):
                pad = max(int(layer.get("max_distance") or 0), int(layer.get("window") or 0), POSITION_PAD) + 1
                con.execute(f"""COPY (SELECT * FROM read_parquet({lit(src)}) WHERE chrom = {lit(chrom)}
                                      AND start < {int(pos) + pad} AND "end" > {int(pos) - 1 - pad})
                                TO {lit(mini / src.name)} (FORMAT parquet)""")
            elif layer["type"] == "gene":
                shutil.copy(src, mini)
            elif layer.get("format") == "gff3_transcripts":  # whole transcripts at the position: codons can span exons
                con.execute(f"""COPY (SELECT * FROM read_parquet({lit(src)}) WHERE transcript_id IN (
                                          SELECT transcript_id FROM read_parquet({lit(src)}) WHERE chrom = {lit(chrom)}
                                          AND start < {int(pos) + 2} AND "end" > {int(pos) - 3}))
                                TO {lit(mini / src.name)} (FORMAT parquet)""")
        con.close()
        for name in ("manifest.json", "alias.parquet", (manifest.get("catalog") or {}).get("file")):
            if name and (release / name).exists():
                (mini / name).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(release / name, mini / name)
        snps = mini / "position.tsv"
        snps.write_text(f"chrom\tpos\tref\talt\n{chrom}\t{int(pos)}\t{ref}\t{alt}\n" if ref and alt else f"chrom\tpos\n{chrom}\t{int(pos)}\n")
        out = annotate(snps, mini, mini / "position.parquet", trait=trait, threads=1)
        con = connect([mini])
        rel = con.execute(f"SELECT * FROM read_parquet({lit(out)})")
        row = dict(zip([d[0] for d in rel.description], rel.fetchone()))
        con.close()
        return row
