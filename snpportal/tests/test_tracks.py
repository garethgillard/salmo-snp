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


GILL = ["Gill_Immature_Female", "Gill_Immature_Male", "Gill_Mature_Male"]  # gill ATAC-seq of 2026 (no usable Mature Female)
IMMUNOMAP = ["HeadKidney_invivo_pbs", "HeadKidney_invivo_polyIC", "HeadKidney_invivo_vibrio"]


def check_registry(cfg):
    """P4.1 acceptance: 54 BodyMap ATAC bigWigs = 16 conditions x 3 replicates and the 6 gill libraries AQUA-FAANG used
    (UNUSED drops the rest), the ImmunoMap's 3 treatments x 6 fish, ChromHMM states for the 21 scored conditions plus
    gill and the ImmunoMap, and the bigWigs' chromatin conditions are the annotate chromatin_<condition> columns."""
    atac = [t for t in cfg["tracks"] if t["assay"] == "ATAC" and t["source"] == "BodyMap"]
    assert len(atac) == 54 and len({t["condition"] for t in atac}) == 19 and {t["replicate"] for t in atac} == {"R1", "R2", "R3"}
    assert {t["id"] for t in atac if t["tissue"] == "Gill"} == {"ATAC_Gill_Immature_Female_R2", "ATAC_Gill_Immature_Female_R3",
        "ATAC_Gill_Immature_Male_R1", "ATAC_Gill_Immature_Male_R2", "ATAC_Gill_Immature_Male_R3", "ATAC_Gill_Mature_Male_R3"}
    assert {t["chromatin_condition"] for t in atac if t["tissue"] == "Gill"} == {None}
    assert {t["chromatin_condition"] for t in cfg["tracks"]} - {None} == {f"chromatin_{c}" for c in CHROMATIN_CONDITIONS}
    immuno = [t for t in cfg["tracks"] if t["source"] == "ImmunoMap" and t["assay"] == "ATAC"]
    assert len(immuno) == 18 and sorted({t["condition"] for t in immuno}) == IMMUNOMAP and {t["tissue"] for t in immuno} == {"HeadKidney"}
    for key in ("chromhmm", "peaks"):  # one bigBed per condition with states
        assert sorted(t["condition"] for t in cfg[key]) == sorted([*CHROMATIN_CONDITIONS, *GILL, *IMMUNOMAP])
        assert {t["kind"] for t in cfg[key]} == {"bigBed"}


def test_registry(tmp_path):
    cfg = tracks.load_tracks(REGISTRY)
    check_registry(cfg)
    with pytest.raises(FileNotFoundError, match="snpdata build"):
        tracks.load_tracks(tmp_path)  # a release folder without tracks.yaml: no fallback to the repo copy
    presets = yaml.safe_load((WEIGHTS).read_text())["presets"]
    rows = tracks.default_tracks(cfg, "maturation", presets)
    assert len(rows) == 8 and all(t["replicate"] == "R1" and t["tissue"] in ("Brain", "Gonad") for t in rows)
    # 'all': one row per tissue and an embryo stage; gill only for ChIP, as its ATAC R1 (Immature Female) is unused
    assert {t["tissue"] for t in tracks.default_tracks(cfg, "all", presets)} == {"Brain", "Gonad", "Liver", "Muscle", "Embryo"}
    assert "Gill" in {t["tissue"] for t in tracks.select(cfg, "H3K27ac", cfg["defaults"]["presets"]["all"])}
    assert [t["id"] for t in tracks.select(cfg, "ATAC", ["Gill"])] == ["ATAC_Gill_Immature_Male_R1"]
    assert not tracks.select(cfg, "H3K4me1", ["Gill_Immature_Female"], "R2")  # the mixed library (AQUA-FAANG note 3)


def test_added(tmp_path):
    """A release registry made before the 2026 gill and ImmunoMap tracks gets them from tracks_added.yaml (same hub);
    another hub's (rainbow trout) gets nothing."""
    new = yaml.safe_load(REGISTRY.read_text())
    late = lambda t: t["source"] == "ImmunoMap" or (t["assay"] in ("ChromHMM", "Peaks") and t["tissue"] == "Gill")
    old = {**new, **{k: [t for t in new[k] if not late(t)] for k in ("tracks", "chromhmm", "peaks")}}
    (tmp_path / "old").mkdir()
    (tmp_path / "old" / "tracks.yaml").write_text(yaml.safe_dump(old))
    cfg = tracks.load_tracks(tmp_path / "old")
    check_registry(cfg)
    want = tracks.load_tracks(REGISTRY)
    assert [{t["id"] for t in cfg[k]} for k in tracks.KEYS] == [{t["id"] for t in want[k]} for k in tracks.KEYS]
    trout = yaml.safe_load((DATA / "rainbow_trout" / "tracks.yaml").read_text())
    got = tracks.load_tracks(DATA / "rainbow_trout" / "tracks.yaml")
    assert len(got["tracks"]) == len(trout["tracks"]) and not any(t["source"] == "ImmunoMap" for t in got["tracks"])


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
