"""snpscore.locus on the fixture release: the lanes of a window, regions, one-position annotation, and signal and
ChromHMM tiles read from SYNTHETIC bigWig and bigBed files written at test time and served by a local range server."""
import struct
import zlib
from pathlib import Path

import duckdb
import pytest

from bbi_writer import _rtree, synthetic_registry
from range_server import RangeServer
from snpscore import annotate, bbi, build, tracks
from snpscore import locus as sl

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixture"


@pytest.fixture(scope="module")
def release(tmp_path_factory):
    return build(ROOT / "layers.yaml", FIXTURE, tmp_path_factory.mktemp("release") / "test")


@pytest.fixture
def remote(monkeypatch):
    monkeypatch.setattr(bbi, "ALLOWED_HOSTS", {"127.0.0.1"})
    monkeypatch.setattr(bbi, "ALLOWED_SCHEMES", ("http",))
    bbi.clear_caches()


def write_bigbed(path, chrom_sizes, items):
    """SYNTHETIC test bigBed: items [(chrom, start, end, rest)] sorted, in one zlib block (no zoom levels)."""
    ids = {c: i for i, c in enumerate(chrom_sizes)}
    key = max(len(c) for c in chrom_sizes)
    tree = struct.pack("<IIIIQQ", 0x78CA8C91, len(ids), key, 8, len(ids), 0) + struct.pack("<BBH", 1, 0, len(ids))
    tree += b"".join(c.encode().ljust(key, b"\0") + struct.pack("<II", ids[c], n) for c, n in sorted(chrom_sizes.items()))
    raw = b"".join(struct.pack("<III", ids[c], s, e) + rest.encode() + b"\0" for c, s, e, rest in items)
    packed, data_offset = zlib.compress(raw), 64 + len(tree)
    index = _rtree([(items[0][0], items[0][1], items[-1][2], data_offset + 8, len(packed))], ids)
    header = struct.pack("<IHHQQQHHQQIQ", bbi.BIGBED, 4, 0, 64, data_offset, data_offset + 8 + len(packed), 9, 9, 0, 0, len(raw), 0)
    Path(path).write_bytes(header + tree + struct.pack("<Q", len(items)) + packed + index)


def test_lanes(release):
    d = sl.locus(release, "25", 28_979_999, 29_010_000)
    vgll3 = next(g for g in d["genes"] if g["id"] == "ENSSSAG00000053708")
    assert (vgll3["label"], vgll3["strand"], vgll3["human"]) == ("~VGLL3", "+", "VGLL3")  # unnamed in Ensembl 116
    t = vgll3["transcripts"]
    assert (len(t), t[0]["transcript_id"], t[0]["canonical"]) == (1, "ENSSSAT00000230965", True)
    assert any(p["part"] == "CDS" and p["start"] < 28996360 <= p["end"] for p in t[0]["parts"])
    assert len(d["conditions"]) == 21 and (d["conditions"][0], d["conditions"][-1]) == ("Brain_Immature_Female", "LateSomitogenesis")
    assert d["peaks"] and all(p["states"] and set(p["states"]) <= set(d["conditions"]) for p in d["peaks"])
    assert any(v["pos"] == 28996360 and v["maf"] == 0.33 for v in d["variants"])
    assert [k["id"] for k in d["known"]] == ["vgll3_Met54Thr", "vgll3_Asn323Lys"] and d["regbuild"]
    every = sl.locus(release, "25", 28_994_000, 28_999_000, all_transcripts=True)["genes"]
    assert [x["canonical"] for g in every for x in g["transcripts"]][:2] == [True, False]  # canonical first
    wide = sl.locus(release, "25", 28_880_000, 29_200_000)
    assert wide["gerp"] and wide["blacklist"] and sl.locus(release, "26", 19_100_000, 19_200_000)["lore"]
    with pytest.raises(ValueError):
        sl.locus(release, "25", 0, sl.MAX_WINDOW + 1)


def test_regions(release):
    same = sl.parse_region("25:28,980,000-29,010,000", release)
    assert same == sl.parse_region("ssa25:28.98-29.01Mb", release) == sl.parse_region("chr25 28980 kb - 29010 kb", release)
    assert same == ("25", 28_979_999, 29_010_000)
    assert sl.parse_region("25:28996360", release) == ("25", 28_996_359, 28_996_360)
    assert sl.parse_region("NC_059466.1:100-200", release)[0] == "25"  # RefSeq accession through alias.parquet
    for bad in ("ssa99:1-100", "25:abc", "vgll3"):
        with pytest.raises(ValueError):
            sl.parse_region(bad, release)
    assert sl.clamp(1000, 1001) == (900, 1100) and sl.clamp(0, 10, 5000) == (0, 200) and sl.clamp(4990, 5000, 5000) == (4800, 5000)


def test_annotate_position_matches_annotate(release, tmp_path):
    sites = [("25", 28996360, "C", "T"), ("1", 110987765, "G", "A"), ("9", 24240012, "C", "G"), ("21", 32279275, "C", "T"),
             ("26", 14268589, "C", "G"), ("26", 19138923, None, None)]
    snps = tmp_path / "sites.tsv"
    snps.write_text("chrom\tpos\tref\talt\n" + "".join(f"{c}\t{p}\t{r or ''}\t{a or ''}\n" for c, p, r, a in sites))
    rel = duckdb.sql(f"SELECT * FROM read_parquet('{annotate(snps, release, tmp_path / 'all.parquet', trait='maturation')}')")
    full = [dict(zip(rel.columns, row)) for row in rel.fetchall()]
    for (chrom, pos, ref, alt), expected in zip(sites, full):
        got = sl.annotate_position(release, chrom, pos, ref, alt, "maturation", work_dir=tmp_path)
        if ref is None:  # the table above has empty allele columns, which annotate reads as missing alleles
            expected = {k: v for k, v in expected.items() if k in got}
        assert got == expected, (chrom, pos)
    assert [p.name for p in tmp_path.iterdir() if p.name.startswith(".variant-")] == []


def test_signal_tiles(tmp_path, remote):
    conditions = ["Brain_Immature_Female", "Gonad_Mature_Male"]
    with RangeServer(tmp_path, delay=2.0) as server:
        cfg = tracks.load_tracks(synthetic_registry(tmp_path, server.url, conditions, slow=["Gonad_Mature_Male"]))
        fast, slow = cfg["tracks"]
        cache = {}
        out = sl.signal([fast, slow], "25", 28_990_000, 29_000_000, cache, "t", deadline=1.0)
        assert out["rung"] == 10 and out["values"][1] is None  # the slow track misses the deadline: no signal, never made up
        values = out["values"][0]
        assert len(values) == 1000 and values == bbi.open_bbi(fast["url"]).bins("25", out["start"], out["start"] + 10_000, 1000)
        assert all(k.startswith("t:sig:") and k.split(":")[3:5] == ["25", "10"] for k in cache)  # grid tiles, not positions
        before = len(server.requests)
        again = sl.signal([fast], "25", 28_990_500, 28_999_500, cache, "t")
        assert len(server.requests) == before and again["values"][0] == values[50:950]  # all from the tile cache


def test_segments(tmp_path, remote):
    states = [("25", 28_900_000, 28_995_000, "Quiescent"), ("25", 28_995_000, 29_002_000, "Active TSS"),
              ("25", 29_002_000, 29_100_000, "Accessible chromatin")]  # the middle one crosses a HMM_TILE boundary
    write_bigbed(tmp_path / "AtlanticSalmon_Brain_Immature_Female.SYNTHETIC.bb", {"25": 54_385_492},
                 [(c, s, e, f"{name}\t0\t.\t{s}\t{e}\t0,0,0") for c, s, e, name in states])
    with RangeServer(tmp_path) as server:
        track = {"url": server.url + "AtlanticSalmon_Brain_Immature_Female.SYNTHETIC.bb"}
        missing = {"url": server.url + "missing.bb"}
        found = sl.segments([track, missing], "25", 28_990_000, 29_010_000, {}, deadline=2.0)
    assert found == [[(28_900_000, 28_995_000, "Quiescent"), (28_995_000, 29_002_000, "Active_TSS"),
                      (29_002_000, 29_100_000, "Accessible_chromatin")], None]
