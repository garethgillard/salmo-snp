"""Signal track registry: the AQUA-FAANG trackhub bigWigs (BodyMap and DevMap trackDb.txt) and the per-condition
ChromHMM and robust ATAC peak bigBeds as tracks.yaml, plus picking tracks for a view and reading their signal with bbi.bins_many.
URLs come only from tracks.yaml, never from requests, and every one must pass bbi.check_url.
Regenerate the repo copy with `snpscore tracks` (needs the network); `snpscore build` copies it into the release,
and the portal reads release/<v>/tracks.yaml."""
from __future__ import annotations

import argparse
import datetime
import functools
import re
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import yaml

from . import bbi

HUB = "https://salmobase.org/datafiles/datasets/Aqua-Faang/trackhub/AtlanticSalmon/"
SOURCES = ("BodyMap", "DevMap")
CHROMHMM_LIST = "../../chromatin_states/chromhmm_salmon_files.txt"  # relative to HUB; its paths are relative to its parent
PEAKS_LIST = "../../robust_ATAC_peaks/salmon_files.txt"  # the same for the robust ATAC peaks
DEFAULT = Path("tracks.yaml")  # where `snpscore tracks` writes: next to layers.yaml, as the other commands assume
# The 21 conditions with ChromHMM states in AtlanticSalmon_unified_peaks.bed (annotate columns chromatin_<condition>).
# Gill (ATAC and ChIP only), Sperm (ChIP only) and the RNA-only embryo stages have none.
CHROMATIN_CONDITIONS = tuple(f"{t}_{m}_{s}" for t in ("Brain", "Gonad", "Liver", "Muscle")
                             for m in ("Immature", "Mature") for s in ("Female", "Male")) + (
    "LateBlastulation", "MidGastrulation", "EarlySomitogenesis", "MidSomitogenesis", "LateSomitogenesis")
DEFAULTS = {  # PROVISIONAL (G to confirm): the signal rows a view shows before the user picks others
    "assay": "ATAC",
    "replicate": "R1",
    "max_rows": 8,
    # preset -> condition prefixes. Presets not listed here use their weights.yaml prefixes (see default_tracks).
    # 'all' = the first condition of each tissue in trackDb order (Gill gives ChIP rows only: see DISCARDED).
    "presets": {"all": ["Brain_Immature_Female", "Gill_Immature_Female", "Gonad_Immature_Female", "Liver_Immature_Female",
                        "Muscle_Immature_Female", "LateBlastulation"]},
}


DISCARDED = {("ATAC", "Gill")}  # (assay, tissue) that AQUA-FAANG discarded (RESEARCH.md section 6): never selected


def _condition(cond):
    """Fields of a file-name condition: [tissue, maturity, sex] (BodyMap) or [stage] (DevMap)."""
    tissue, maturity, sex, stage = cond + [None] if len(cond) == 3 else ["Embryo", None, None, cond[0]]
    condition = "_".join(cond)
    return {"tissue": tissue, "sex": sex, "maturity": maturity, "stage": stage, "condition": condition,
            "chromatin_condition": f"chromatin_{condition}" if condition in CHROMATIN_CONDITIONS else None}


def parse_trackdb(text, base, source):
    """bigWig tracks of one trackDb.txt; bigDataUrl paths are relative to `base` (the trackDb folder).
    File names look like AtlanticSalmon_<assay>_<tissue>_<maturity>_<sex>_R1[.forward].bigWig (BodyMap)
    or AtlanticSalmon_<assay>_<stage>_R1....bigWig (DevMap)."""
    tracks = []
    for stanza in re.split(r"\n\s*\n", text):
        f = dict((line.strip().split(" ", 1) + [""])[:2] for line in stanza.splitlines() if line.strip() and not line.startswith("#"))
        if f.get("type", "").split(" ")[0] != "bigWig" or "bigDataUrl" not in f:
            continue
        name = f["bigDataUrl"].rsplit("/", 1)[-1]
        stem, *ext = name.split(".")
        _, assay, *cond, rep = stem.split("_")
        if not stem.startswith("AtlanticSalmon_") or len(cond) not in (1, 3) or not re.fullmatch(r"R\d+", rep):
            raise ValueError(f"unexpected trackhub file name {name}")
        assay = assay.replace("ChIP-", "").replace("input", "Input")
        strand = "+" if "forward" in ext else "-" if "reverse" in ext else None  # nf-core/rnaseq .forward/.reverse
        fields = _condition(cond)
        tracks.append({
            "id": "_".join([assay, fields["condition"], rep] + (["forward" if strand == "+" else "reverse"] if strand else [])),
            "source": source, "assay": assay, **fields,
            "replicate": rep, "strand": strand, "kind": "bigWig", "url": urljoin(base, f["bigDataUrl"]),
        })
    return tracks


def parse_bigbeds(text, base, assay="ChromHMM"):
    """One bigBed per condition from a salmobase file list, paths relative to `base`: ChromHMM segmentations
    (chromhmm_salmon_files.txt: chromatin_states/AtlanticSalmon/<BodyMap|DevMap>/AtlanticSalmon_<condition>.bb) or,
    with assay 'Peaks', the robust ATAC peaks (robust_ATAC_peaks/salmon_files.txt: .../AtlanticSalmon_ATAC_<condition>.bb).
    Either way the bigBed name field is the ChromHMM state (e.g. 'Accessible chromatin'), read by locus.segments()."""
    prefix = "AtlanticSalmon_ATAC_" if assay == "Peaks" else "AtlanticSalmon_"
    out = []
    for line in text.split():
        *_, source, name = line.split("/")
        cond = name[len(prefix):-len(".bb")].split("_")
        if not (name.startswith(prefix) and name.endswith(".bb") and len(cond) in (1, 3)):
            raise ValueError(f"unexpected {assay} file name {name}")
        fields = _condition(cond)
        out.append({"id": f"{assay}_{fields['condition']}", "source": source, "assay": assay, **fields,
                    "replicate": None, "strand": None, "kind": "bigBed", "url": urljoin(base, line)})
    return out


def from_trackhub(hub=HUB, defaults=None):
    """The tracks.yaml content, read from the trackhub's BodyMap and DevMap trackDb.txt and the ChromHMM and robust
    ATAC peak file lists."""
    hub = hub.rstrip("/") + "/"
    tracks = []
    for source in SOURCES:
        base = f"{hub}{source}/"
        tracks += parse_trackdb(bbi.read_all(base + "trackDb.txt").decode(), base, source)
    beds = {}
    for key, listing, assay in (("chromhmm", CHROMHMM_LIST, "ChromHMM"), ("peaks", PEAKS_LIST, "Peaks")):
        listing = urljoin(hub, listing)
        beds[key] = parse_bigbeds(bbi.read_all(listing).decode(), urljoin(listing, "../"), assay)
    every = tracks + beds["chromhmm"] + beds["peaks"]
    ids = [t["id"] for t in every]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate track ids")
    return {"version": 1, "generated": datetime.date.today().isoformat(), "hub": hub,
            "hosts": sorted({urlsplit(t["url"]).hostname for t in every}), "defaults": defaults or DEFAULTS,
            "tracks": tracks, **beds}


def write_tracks(cfg, path):
    head = ("# Signal track registry, generated by `python -m snpscore.tracks` from the AQUA-FAANG trackhub; do not edit tracks\n"
            "# by hand. `defaults` is PROVISIONAL (G to confirm) and is kept when the file is regenerated.\n")
    Path(path).write_text(head + yaml.safe_dump(cfg, sort_keys=False, default_flow_style=None, width=4096))


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
    `snpscore build` copies there) or a file. There is no fallback to the repo's copy, so a release always shows the
    tracks it was built with. Raises FileNotFoundError when it is missing, ValueError on a URL that is not allowed."""
    path = Path(path)
    if path.is_dir():
        path = path / "tracks.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"track registry {path} not found: `snpscore build` copies tracks.yaml (next to "
                                "layers.yaml) into the release; rebuild it, or run `snpscore tracks` first")
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


def main(argv=None):
    p = argparse.ArgumentParser(prog="snpscore tracks", description="Regenerate tracks.yaml from the AQUA-FAANG trackhub")
    p.add_argument("-o", "--out", default=str(DEFAULT), help="default: tracks.yaml (run it next to layers.yaml)")
    p.add_argument("--hub", default=HUB)
    args = p.parse_args(argv)
    old = (yaml.safe_load(Path(args.out).read_text()) or {}) if Path(args.out).exists() else {}
    cfg = from_trackhub(args.hub, old.get("defaults"))
    write_tracks(cfg, args.out)
    counts = {}
    for t in cfg["tracks"]:
        counts[(t["source"], t["assay"])] = counts.get((t["source"], t["assay"]), 0) + 1
    print(f"{args.out}: {len(cfg['tracks'])} bigWigs; " + ", ".join(f"{s} {a} {n}" for (s, a), n in counts.items())
          + f"; {len(cfg['chromhmm'])} ChromHMM and {len(cfg['peaks'])} peak bigBeds")


if __name__ == "__main__":
    main()
