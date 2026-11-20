"""Reading the signal track registry (tracks.yaml, written by `snpdata tracks` and copied into each release): load it,
pick tracks for a view and read their signal with bbi.bins_many. URLs come only from tracks.yaml and tracks_added.yaml,
never from requests, and every one must pass bbi.check_url."""
from __future__ import annotations

import functools
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from snpscore import bbi

# AQUA-FAANG tracks published after a release's registry was made (`snpdata tracks --added-since`): added to a release
# registry of the same hub that lacks them, so they show without a new release (the 2026 salmon gill and ImmunoMap data).
ADDED = Path(__file__).with_name("tracks_added.yaml")
KEYS = ("tracks", "chromhmm", "peaks")
# hub -> libraries the AQUA-FAANG README (salmobase, November 2026) says weren't used: left out of the registry. Salmon
# gill ATAC-seq (re-made in 2026): replicates were chosen by quality (Immature Female R2, R3; Immature Male R1-R3;
# Mature Male R3; Mature Female none). Its gill H3K4me1 Immature Female R2 is mixed with a gonad H3K4me3 (note 3).
UNUSED = {"https://salmobase.org/datafiles/datasets/Aqua-Faang/trackhub/AtlanticSalmon/": {
    "ATAC_Gill_Immature_Female_R1", "ATAC_Gill_Mature_Female_R1", "ATAC_Gill_Mature_Female_R2", "ATAC_Gill_Mature_Female_R3",
    "ATAC_Gill_Mature_Male_R1", "ATAC_Gill_Mature_Male_R2", "H3K4me1_Gill_Immature_Female_R2"}}


def _read(path):
    return yaml.load(Path(path).read_text(), Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader)) or {}


@functools.lru_cache(maxsize=8)
def _load(path, mtime, added=ADDED):
    cfg = _read(path)
    extra = _read(added) if Path(added).is_file() else {}
    if extra.get("hub") and extra["hub"] == cfg.get("hub"):
        have = {t["id"] for k in KEYS for t in cfg.get(k, [])}
        cfg.update({k: cfg.get(k, []) + [t for t in extra.get(k, []) if t["id"] not in have] for k in KEYS})
        cfg["hosts"] = sorted(set(cfg.get("hosts", [])) | set(extra.get("hosts", [])))
    unused = UNUSED.get(cfg.get("hub"), set())
    for k in KEYS:
        cfg[k] = [t for t in cfg.get(k, []) if t["id"] not in unused]
    for t in cfg["tracks"] + cfg["chromhmm"] + cfg["peaks"]:
        bbi.check_url(t["url"])
        if urlsplit(t["url"]).hostname not in cfg.get("hosts", []):
            raise ValueError(f"{t['url']}: host not in the hosts of {path}")
    return cfg


def load_tracks(path):
    """tracks.yaml as a dict (shared; don't modify it) from a release folder (release/<v>/tracks.yaml, which
    `snpdata build` copies there) or a file, with the ADDED tracks of its hub and without the UNUSED libraries. There is
    no fallback to the repo's copy, so a release shows the tracks it was built with and those added since. Raises
    FileNotFoundError when it is missing, ValueError on a URL that is not allowed."""
    path = Path(path)
    if path.is_dir():
        path = path / "tracks.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"track registry {path} not found: `snpdata build` copies tracks.yaml (next to "
                                "layers.yaml) into the release; rebuild it, or run `snpdata tracks` first")
    return _load(str(path.resolve()), path.stat().st_mtime_ns)


def select(tracks, assay="ATAC", conditions=None, replicate="R1", limit=8):
    """Tracks of one assay and replicate whose condition starts with one of `conditions` (None = all), in the order
    of `conditions`, then registry order; at most `limit`. `tracks` is the tracks.yaml dict (load_tracks: without the
    UNUSED libraries) or its track list."""
    tracks = tracks["tracks"] if isinstance(tracks, dict) else tracks
    prefixes = list(conditions) if conditions else [""]
    rank = lambda t: next((i for i, p in enumerate(prefixes) if t["condition"].startswith(p)), None)
    chosen = [t for t in tracks if t["assay"] == assay
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
