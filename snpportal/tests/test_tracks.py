"""The signal track registry (tracks.yaml): the repo copy, its URL policy, picking rows and reading their signal from
SYNTHETIC bigWigs on a local range server. Offline, except the release/dev check (SNPSCORE_DEV=1)."""
import json
import os

import pytest
import yaml

from bbi_writer import synthetic_atac, synthetic_registry
from range_server import RangeServer
from snpportal.lib import tracks
from snpscore import WEIGHTS, bbi
from snpscore.score import CHROMATIN_CONDITIONS

from conftest import DATA

REGISTRY = DATA / "tracks.yaml"  # the repo copy that `snpdata build` copies into releases
CONDITIONS = ["Brain_Immature_Female", "Brain_Mature_Male", "Gonad_Mature_Male"]


def dev(test):
    """Marked 'dev' (pytest -m dev) and skipped unless SNPSCORE_DEV=1."""
    skip = pytest.mark.skipif(os.environ.get("SNPSCORE_DEV") != "1", reason="needs release/dev (SNPSCORE_DEV=1)")
    return pytest.mark.dev(skip(test))


@pytest.fixture(scope="module")
def folder(tmp_path_factory):
    d = tmp_path_factory.mktemp("tracks")
    for i, c in enumerate(CONDITIONS):
        synthetic_atac(d / f"ATAC_{c}_R1_SYNTHETIC.bw", seed=i)
    return d


@pytest.fixture
def remote(folder, monkeypatch):
    """A range server for the SYNTHETIC bigWigs, allowed by the URL policy, with cold caches."""
    monkeypatch.setattr(bbi, "ALLOWED_HOSTS", {"127.0.0.1"})
    monkeypatch.setattr(bbi, "ALLOWED_SCHEMES", ("http",))
    bbi.clear_caches()
    with RangeServer(folder, delay=3) as s:
        yield s


def check_registry(cfg):
    """P4.1 acceptance: 60 BodyMap ATAC bigWigs = 20 conditions x 3 replicates, Gill without ChromHMM states, and the
    bigWigs' chromatin conditions are the annotate chromatin_<condition> columns."""
    atac = [t for t in cfg["tracks"] if t["assay"] == "ATAC" and t["source"] == "BodyMap"]
    assert len(atac) == 60 and len({t["condition"] for t in atac}) == 20 and {t["replicate"] for t in atac} == {"R1", "R2", "R3"}
    assert {t["chromatin_condition"] for t in atac if t["tissue"] == "Gill"} == {None}
    assert {t["chromatin_condition"] for t in cfg["tracks"]} - {None} == {f"chromatin_{c}" for c in CHROMATIN_CONDITIONS}


def test_registry(tmp_path):
    cfg = tracks.load_tracks(REGISTRY)
    check_registry(cfg)
    hmm = cfg["chromhmm"]  # one ChromHMM bigBed per chromatin condition
    assert sorted(t["condition"] for t in hmm) == sorted(CHROMATIN_CONDITIONS) and {t["kind"] for t in hmm} == {"bigBed"}
    with pytest.raises(FileNotFoundError, match="snpdata build"):
        tracks.load_tracks(tmp_path)  # a release folder without tracks.yaml: no fallback to the repo copy
    presets = yaml.safe_load((WEIGHTS).read_text())["presets"]
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
    release = DATA / "release" / "dev"
    manifest = json.loads((release / "manifest.json").read_text())
    columns = next(layer["columns"] for layer in manifest["layers"] if layer["name"] == "chromatin")
    assert {f"chromatin_{c}" for c in columns if c not in ("summary", "id")} == {f"chromatin_{c}" for c in CHROMATIN_CONDITIONS}
    check_registry(tracks.load_tracks(release))
