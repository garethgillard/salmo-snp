"""Reading the signal track registry (tracks.yaml, written by `snpdata tracks` and copied into each release): load it,
pick tracks for a view and read their signal with bbi.bins_many. URLs come only from tracks.yaml, never from requests,
and every one must pass bbi.check_url."""
from __future__ import annotations

import functools
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from snpscore import bbi

DISCARDED = {("ATAC", "Gill")}  # (assay, tissue) that AQUA-FAANG discarded (docs/RESEARCH.md section 6): never selected



@functools.lru_cache(maxsize=8)
def _load(path, mtime):
    cfg = yaml.load(Path(path).read_text(), Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader)) or {}
    for t in cfg.get("tracks", []) + cfg.get("chromhmm", []) + cfg.get("peaks", []):
        bbi.check_url(t["url"])
        if urlsplit(t["url"]).hostname not in cfg.get("hosts", []):
            raise ValueError(f"{t['url']}: host not in the hosts of {path}")
    return cfg


def load_tracks(path):
    """tracks.yaml as a dict (shared; don't modify it) from a release folder (release/<v>/tracks.yaml, which
    `snpdata build` copies there) or a file. There is no fallback to the repo's copy, so a release always shows the
    tracks it was built with. Raises FileNotFoundError when it is missing, ValueError on a URL that is not allowed."""
    path = Path(path)
    if path.is_dir():
        path = path / "tracks.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"track registry {path} not found: `snpdata build` copies tracks.yaml (next to "
                                "layers.yaml) into the release; rebuild it, or run `snpdata tracks` first")
    return _load(str(path.resolve()), path.stat().st_mtime_ns)


def select(tracks, assay="ATAC", conditions=None, replicate="R1", limit=8):
    """Tracks of one assay and replicate whose condition starts with one of `conditions` (None = all), in the order
    of `conditions`, then registry order; at most `limit`. `tracks` is the tracks.yaml dict or its track list. DISCARDED
    assays (gill ATAC) are never selected."""
    tracks = tracks["tracks"] if isinstance(tracks, dict) else tracks
    prefixes = list(conditions) if conditions else [""]
    rank = lambda t: next((i for i, p in enumerate(prefixes) if t["condition"].startswith(p)), None)
    chosen = [t for t in tracks if t["assay"] == assay and (assay, t.get("tissue")) not in DISCARDED
              and (replicate is None or t["replicate"] == replicate) and rank(t) is not None]
    return sorted(chosen, key=rank)[:limit]


def default_tracks(cfg, preset="all", presets=None):
    """PROVISIONAL default rows for a trait preset: defaults.presets[preset] if tracks.yaml lists it, else `presets`
    (the weights.yaml presets: name -> condition prefixes)[preset]."""
    d = cfg["defaults"]
    conditions = d.get("presets", {}).get(preset)
    if conditions is None:
        conditions = (presets or {}).get(preset)
    return select(cfg, d["assay"], conditions, d["replicate"], d["max_rows"])


def signal(selected, chrom, start, end, n, deadline=4.0):
    """[{track, bins}] for the selected tracks: n mean values across chrom:start-end (BED coordinates), or None for a
    track that failed or missed the deadline (seconds)."""
    bins = bbi.bins_many([t["url"] for t in selected], chrom, start, end, n, deadline)
    return [{"track": t, "bins": b} for t, b in zip(selected, bins)]
