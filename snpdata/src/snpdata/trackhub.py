"""Signal track registry: the AQUA-FAANG trackhub bigWigs (BodyMap and DevMap trackDb.txt) and the per-condition
ChromHMM and robust ATAC peak bigBeds, written as tracks.yaml. Regenerate it with `snpdata tracks` (needs the
network); `snpdata build` copies it into the release, and the portal reads release/<v>/tracks.yaml."""
from __future__ import annotations

import argparse
import datetime
import re
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import yaml

from snpscore import bbi
from snpscore.score import CHROMATIN_CONDITIONS

HUB = "https://salmobase.org/datafiles/datasets/Aqua-Faang/trackhub/AtlanticSalmon/"
SOURCES = ("BodyMap", "DevMap")
CHROMHMM_LIST = "../../chromatin_states/chromhmm_salmon_files.txt"  # relative to HUB; its paths are relative to its parent
PEAKS_LIST = "../../robust_ATAC_peaks/salmon_files.txt"  # the same for the robust ATAC peaks
DEFAULT = Path("tracks.yaml")  # where `snpdata tracks` writes: next to layers.yaml, as the other commands assume
DEFAULTS = {  # PROVISIONAL (G to confirm): the signal rows a view shows before the user picks others
    "assay": "ATAC",
    "replicate": "R1",
    "max_rows": 8,
    # preset -> condition prefixes. Presets not listed here use their weights.yaml prefixes (see default_tracks).
    # 'all' = the first condition of each tissue in trackDb order (Gill gives ChIP rows only: see DISCARDED).
    "presets": {"all": ["Brain_Immature_Female", "Gill_Immature_Female", "Gonad_Immature_Female", "Liver_Immature_Female",
                        "Muscle_Immature_Female", "LateBlastulation"]},
}



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
    head = ("# Signal track registry, generated by `snpdata tracks` from the AQUA-FAANG trackhub; do not edit tracks\n"
            "# by hand. `defaults` is PROVISIONAL (G to confirm) and is kept when the file is regenerated.\n")
    Path(path).write_text(head + yaml.safe_dump(cfg, sort_keys=False, default_flow_style=None, width=4096))


def main(argv=None):
    p = argparse.ArgumentParser(prog="snpdata tracks", description="Regenerate tracks.yaml from the AQUA-FAANG trackhub")
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
