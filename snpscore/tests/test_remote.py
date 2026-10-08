"""Remote reader (bbi, fasta) against a local range server with SYNTHETIC bigWigs written at test time, and the
track registry. Offline, except the timings test (SNPSCORE_LIVE=1) and the release/dev check (SNPSCORE_DEV=1)."""
import gc
import json
import os
import shutil
import threading
import time
from pathlib import Path

import pytest
import yaml

from bbi_writer import synthetic_atac, synthetic_registry
from range_server import RangeServer
from snpscore import bbi, tracks
from snpscore.fasta import Fasta

ROOT = Path(__file__).resolve().parent.parent
GENOME = "Salmo_salar.Ssal_v3.1.dna_sm.toplevel.fa.gz"
CONDITIONS = ["Brain_Immature_Female", "Brain_Mature_Male", "Gonad_Mature_Male"]
NAME = "ATAC_Brain_Immature_Female_R1_SYNTHETIC.bw"
REGISTRY = ROOT / "tracks.yaml"  # the repo copy that `snpscore build` copies into releases


def live(test):
    """Marked 'live' (pytest -m live) and skipped unless SNPSCORE_LIVE=1."""
    skip = pytest.mark.skipif(os.environ.get("SNPSCORE_LIVE") != "1", reason="needs salmobase (SNPSCORE_LIVE=1)")
    return pytest.mark.live(skip(test))


def dev(test):
    """Marked 'dev' (pytest -m dev) and skipped unless SNPSCORE_DEV=1."""
    skip = pytest.mark.skipif(os.environ.get("SNPSCORE_DEV") != "1", reason="needs release/dev (SNPSCORE_DEV=1)")
    return pytest.mark.dev(skip(test))


@pytest.fixture(scope="module")
def folder(tmp_path_factory):
    d = tmp_path_factory.mktemp("tracks")
    items = {c: synthetic_atac(d / f"ATAC_{c}_R1_SYNTHETIC.bw", seed=i) for i, c in enumerate(CONDITIONS)}
    for ext in ("", ".fai", ".gzi"):
        shutil.copy(ROOT / "tests" / "fixture" / (GENOME + ext), d)
    return d, items


@pytest.fixture(scope="module")
def server(folder):
    with RangeServer(folder[0], delay=3) as s:
        yield s


@pytest.fixture
def remote(server, monkeypatch):
    """The range server, allowed by the URL policy, with cold caches and an empty request log."""
    monkeypatch.setattr(bbi, "ALLOWED_HOSTS", {"127.0.0.1"})
    monkeypatch.setattr(bbi, "ALLOWED_SCHEMES", ("http",))
    bbi.clear_caches()
    server.requests.clear()
    server.connections = 0
    return server


def test_read_back(folder, remote):
    items = folder[1]["Brain_Immature_Female"]
    for f in (bbi.BBIFile(folder[0] / NAME), bbi.open_bbi(remote.url + NAME)):
        assert f.values("25", 0, 10 ** 9) == [(s, e, v) for _, s, e, v in items]  # raw level, exactly
        assert f.values("25", 28_960_003, 28_960_011) == [(s, e, v) for _, s, e, v in items if s < 28_960_011 and e > 28_960_003]
        # 100 bins of 1000 bp come from the 1000 bp zoom level, one record per bin (items are 2 bp)
        means = [sum(v for _, s, _, v in items[i * 500:(i + 1) * 500]) / 500 for i in range(100)]
        assert f.bins("25", 28_950_000, 29_050_000, 100) == pytest.approx(means, rel=1e-6)
        assert f.bins("21", 0, 1000, 4) == [None] * 4 and f.bins("ssa25", 0, 1000, 4) == [None] * 4
        for start, end, n in ((0, 1000, 0), (1000, 1000, 4)):
            with pytest.raises(ValueError):
                f.bins("25", start, end, n)


def test_request_counts(folder, remote):
    local = bbi.BBIFile(folder[0] / NAME)
    f = bbi.open_bbi(remote.url + NAME)
    block = 28_950_000 + 185 * 512  # data blocks hold 256 items of 2 bp; this one is past bbi.HEAD
    f.bins("25", block + 50, block + 450, 40)
    assert len(remote.requests) <= 3 and remote.connections == 1  # header, R-tree root, one data block; kept alive
    n = len(remote.requests)
    f.bins("25", block + 100, block + 300, 20)  # same data block
    assert bbi.open_bbi(remote.url + NAME) is f and len(remote.requests) == n
    f.bins("25", 28_950_000, 29_050_000, 50)  # 2 kb per bin: zoom level only, no raw data block
    wide = remote.requests[n:]
    assert wide and not any(local.data_offset <= start < local.index_offset for _, start, _ in wide)


def test_connections_closed_with_thread(remote):
    """A connection made by a thread that has ended (a Django request, an inline job) is closed, not leaked."""
    for _ in range(5):
        t = threading.Thread(target=bbi.read_all, args=(remote.url + GENOME + ".fai",))
        t.start()
        t.join()
    gc.collect()
    until = time.monotonic() + remote.delay + 2  # the server sees a close a moment later (after a slow-mode sleep)
    while remote.open and time.monotonic() < until:
        time.sleep(0.01)
    assert remote.connections == 5 and remote.open == 0


def test_slot_wait_respects_deadline(remote):
    """With every connection slot to the host busy, a task gives up at its deadline instead of blocking its worker."""
    slots = bbi._SLOTS["127.0.0.1"]
    for _ in range(bbi.MAX_PER_HOST):
        slots.acquire()
    try:
        t = time.monotonic()
        with pytest.raises(TimeoutError):
            bbi._bins_task(remote.url + NAME, "25", 0, 1000, 4, time.monotonic() + 0.3)
        assert time.monotonic() - t < 1
    finally:
        for _ in range(bbi.MAX_PER_HOST):
            slots.release()
    assert remote.requests == []


def test_fault_modes(remote):
    with pytest.raises(bbi.RemoteError, match="206"):
        bbi.BBIFile(remote.url + "no-range/" + NAME)
    urls = [remote.url + f"ATAC_{c}_R1_SYNTHETIC.bw" for c in CONDITIONS[:2]]
    urls.append(remote.url + f"slow/ATAC_{CONDITIONS[2]}_R1_SYNTHETIC.bw")
    t = time.monotonic()
    out = bbi.bins_many(urls, "25", 28_990_000, 29_000_000, 20, deadline=1.0)
    assert time.monotonic() - t < 2.0
    assert out[0] and out[1] and out[0] != out[1] and out[2] is None


@pytest.mark.parametrize("url", ["http://salmobase.org/x.bw", "https://example.org/x.bw", "ftp://ftp.ensembl.org/x.bw",
                                 "https://user@salmobase.org/x.bw", "https://:x@salmobase.org/x.bw",
                                 "https://salmobase.org.example.org/x.bw", "https://salmobase.org:22/x.bw",
                                 "https://salmobase.org:x/x.bw"])
def test_url_policy(url):
    for read in (bbi.BBIFile, bbi.read_all, Fasta):
        with pytest.raises(ValueError, match="only https"):
            read(url)
    assert bbi.bins_many([url], "25", 0, 10, 1) == [None]
    bbi.check_url("https://salmobase.org:443/x.bw")


def test_remote_fasta(folder, remote):
    local, far = Fasta(folder[0] / GENOME), Fasta(remote.url + GENOME)
    assert far.fetch("25", 28_996_300, 28_996_420) == local.fetch("25", 28_996_300, 28_996_420)
    assert len(local.fetch("25", 28_996_300, 28_996_420)) == 120


TRACKDB = """track ATAC_bigWig
superTrack off
shortLabel bigWig

track ATAC_bigWig_AtlanticSalmon_ATAC_Gill_Mature_Male_R2_mLb_clN_bigWig
bigDataUrl ATAC/bigWig/AtlanticSalmon_ATAC_Gill_Mature_Male_R2.mLb.clN.bigWig
type bigWig
parent ATAC_bigWig


track RNA_bigWig_x
bigDataUrl RNA/bigWig/AtlanticSalmon_RNA_Liver_Immature_Female_R3.reverse.bigWig
type bigWig

track ChIP_bigWig_x
bigDataUrl ChIP/bigWig/AtlanticSalmon_ChIP-input_MidGastrulation_R1.bigWig
type bigWig

track ATAC_bam_x
bigDataUrl ATAC/bam/AtlanticSalmon_ATAC_Brain_Immature_Female_R1.mLb.clN.sorted.bam
type bam
"""
CHROMHMM = """chromatin_states/AtlanticSalmon/BodyMap/AtlanticSalmon_Brain_Immature_Female.bb
chromatin_states/AtlanticSalmon/DevMap/AtlanticSalmon_LateBlastulation.bb
"""


def test_parse_trackdb():
    gill, rna, chip = tracks.parse_trackdb(TRACKDB, tracks.HUB + "BodyMap/", "BodyMap")
    assert gill["id"] == "ATAC_Gill_Mature_Male_R2" and gill["chromatin_condition"] is None
    assert (gill["tissue"], gill["maturity"], gill["sex"], gill["replicate"]) == ("Gill", "Mature", "Male", "R2")
    assert gill["url"] == tracks.HUB + "BodyMap/ATAC/bigWig/AtlanticSalmon_ATAC_Gill_Mature_Male_R2.mLb.clN.bigWig"
    assert rna["strand"] == "-" and rna["chromatin_condition"] == "chromatin_Liver_Immature_Female"
    assert (chip["assay"], chip["tissue"], chip["stage"], chip["chromatin_condition"]) == (
        "Input", "Embryo", "MidGastrulation", "chromatin_MidGastrulation")
    brain, blast = tracks.parse_bigbeds(CHROMHMM, "https://salmobase.org/datafiles/datasets/Aqua-Faang/")
    assert (brain["id"], brain["source"], brain["kind"], brain["chromatin_condition"]) == (
        "ChromHMM_Brain_Immature_Female", "BodyMap", "bigBed", "chromatin_Brain_Immature_Female")
    assert (blast["tissue"], blast["stage"]) == ("Embryo", "LateBlastulation")
    assert blast["url"] == "https://salmobase.org/datafiles/datasets/Aqua-Faang/" + CHROMHMM.split()[1]


def check_registry(cfg):
    """P4.1 acceptance: 60 BodyMap ATAC bigWigs = 20 conditions x 3 replicates, Gill without ChromHMM states, and the
    bigWigs' chromatin conditions are the annotate chromatin_<condition> columns."""
    atac = [t for t in cfg["tracks"] if t["assay"] == "ATAC" and t["source"] == "BodyMap"]
    assert len(atac) == 60 and len({t["condition"] for t in atac}) == 20 and {t["replicate"] for t in atac} == {"R1", "R2", "R3"}
    assert {t["chromatin_condition"] for t in atac if t["tissue"] == "Gill"} == {None}
    assert {t["chromatin_condition"] for t in cfg["tracks"]} - {None} == {f"chromatin_{c}" for c in tracks.CHROMATIN_CONDITIONS}


def test_registry(tmp_path):
    cfg = tracks.load_tracks(REGISTRY)
    check_registry(cfg)
    hmm = cfg["chromhmm"]  # one ChromHMM bigBed per chromatin condition
    assert sorted(t["condition"] for t in hmm) == sorted(tracks.CHROMATIN_CONDITIONS) and {t["kind"] for t in hmm} == {"bigBed"}
    with pytest.raises(FileNotFoundError, match="snpscore build"):
        tracks.load_tracks(tmp_path)  # a release folder without tracks.yaml: no fallback to the repo copy
    presets = yaml.safe_load((ROOT / "weights.yaml").read_text())["presets"]
    rows = tracks.default_tracks(cfg, "maturation", presets)
    assert len(rows) == 8 and all(t["replicate"] == "R1" and t["tissue"] in ("Brain", "Gonad") for t in rows)
    # 'all': one row per tissue and an embryo stage; gill only for ChIP, as AQUA-FAANG discarded gill ATAC
    assert {t["tissue"] for t in tracks.default_tracks(cfg, "all", presets)} == {"Brain", "Gonad", "Liver", "Muscle", "Embryo"}
    assert "Gill" in {t["tissue"] for t in tracks.select(cfg, "H3K27ac", cfg["defaults"]["presets"]["all"])}
    assert not tracks.select(cfg, "ATAC", ["Gill"])


def test_registry_policy(tmp_path, remote):
    path = tmp_path / "tracks.yaml"
    path.write_text(yaml.safe_dump({"hosts": ["127.0.0.1"], "tracks": [{"id": "x", "url": "https://example.org/x.bw"}]}))
    with pytest.raises(ValueError):
        tracks.load_tracks(path)
    path = synthetic_registry(remote.root, remote.url, CONDITIONS, slow=CONDITIONS[2:])
    rows = tracks.select(tracks.load_tracks(path), conditions=["Brain", "Gonad"])
    assert [t["id"] for t in rows] == [f"ATAC_{c}_R1" for c in CONDITIONS]
    out = tracks.signal(rows, "25", 28_990_000, 29_000_000, 10, deadline=1.0)
    assert [len(r["bins"] or []) for r in out] == [10, 10, 0]


@dev
def test_registry_matches_release():
    release = ROOT / "release" / "dev"
    manifest = json.loads((release / "manifest.json").read_text())
    columns = next(layer["columns"] for layer in manifest["layers"] if layer["name"] == "chromatin")
    assert {f"chromatin_{c}" for c in columns if c not in ("summary", "id")} == {f"chromatin_{c}" for c in tracks.CHROMATIN_CONDITIONS}
    check_registry(tracks.load_tracks(release))


@live
def test_live_timings(capsys):
    """Cold and warm timings and request counts for 1 and 8 salmobase ATAC bigWigs (reported, not a gate)."""
    rows = tracks.default_tracks(tracks.load_tracks(REGISTRY), "maturation", {"maturation": ["Brain", "Gonad"]})
    urls = [t["url"] for t in rows]
    lines = []

    def run(label, us, start, end):
        n, t = bbi.STATS["requests"], time.monotonic()
        out = bbi.bins_many(us, "25", start, end, 600, deadline=30)
        lines.append(f"{len(us)} track(s) {label:28} {time.monotonic() - t:6.2f} s {bbi.STATS['requests'] - n:4} requests")
        assert all(b and any(v is not None for v in b) for b in out)

    for us in (urls[:1], urls):
        bbi.clear_caches()
        run("cold open + 20 kb", us, 28_980_000, 29_000_000)
        run("warm 20 kb", us, 28_980_000, 29_000_000)
        run("open, cold 2 Mb", us, 28_000_000, 30_000_000)
        run("warm 2 Mb", us, 28_000_000, 30_000_000)
        bbi.clear_caches()
        run("cold open + 2 Mb", us, 28_000_000, 30_000_000)
    with capsys.disabled():
        print("\n" + "\n".join(lines))
