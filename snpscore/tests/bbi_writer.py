"""Test-only bigWig writer, standard library only: header, one chromosome-tree leaf, zlib-compressed bedGraph blocks
indexed by one R-tree leaf, and one zoom level (with its own R-tree leaf). Enough for snpscore.bbi to read back.
synthetic_atac() writes a SYNTHETIC ATAC-like track (Gaussian peaks plus noise) for offline tests."""
from __future__ import annotations

import math
import random
import struct
import zlib
from pathlib import Path

BIGWIG = 0x888FFC26
FIXTURE_PEAKS = Path(__file__).resolve().parents[2] / "snpdata" / "tests" / "fixture" / "AtlanticSalmon_unified_peaks.bed"


def _rtree(blocks, chrom_ids):
    """R-tree index with a single leaf: blocks are (chrom, start, end, offset, size)."""
    head = struct.pack("<IIQIIIIQII", 0x2468ACE0, max(256, len(blocks)), len(blocks), chrom_ids[blocks[0][0]],
                       blocks[0][1], chrom_ids[blocks[-1][0]], blocks[-1][2], 0, 1, 0)
    leaf = struct.pack("<BBH", 1, 0, len(blocks))
    for chrom, s, e, off, size in blocks:
        leaf += struct.pack("<IIIIQQ", chrom_ids[chrom], s, chrom_ids[chrom], e, off, size)
    return head + leaf


def _zoom_records(items, reduction):
    """Summary records (chrom, start, end, bases, min, max, sum, sum of squares) per `reduction` bases."""
    out = {}
    for chrom, s, e, v in items:
        while s < e:
            w = s // reduction
            cut = min(e, (w + 1) * reduction)
            r = out.setdefault((chrom, w), [chrom, s, cut, 0, v, v, 0.0, 0.0])
            r[2], r[3], r[4], r[5] = cut, r[3] + cut - s, min(r[4], v), max(r[5], v)
            r[6] += v * (cut - s)
            r[7] += v * v * (cut - s)
            s = cut
    return list(out.values())


def write_bigwig(path, chrom_sizes, items, reduction=1000, per_block=256):
    """Write items [(chrom, start, end, value)], sorted as chrom_sizes then start and not overlapping, as a bigWig."""
    chrom_ids = {c: i for i, c in enumerate(chrom_sizes)}
    key_size = max(len(c) for c in chrom_sizes)
    zoom = _zoom_records(items, reduction)
    covered = sum(e - s for _, s, e, _ in items)
    total = struct.pack("<Qdddd", covered, min(v for *_, v in items), max(v for *_, v in items),
                        sum(v * (e - s) for _, s, e, v in items), sum(v * v * (e - s) for _, s, e, v in items))
    chrom_tree = struct.pack("<IIIIQQ", 0x78CA8C91, len(chrom_sizes), key_size, 8, len(chrom_sizes), 0)
    chrom_tree += struct.pack("<BBH", 1, 0, len(chrom_sizes))
    for c, size in sorted(chrom_sizes.items()):  # keys sorted, as in a B+ tree
        chrom_tree += c.encode().ljust(key_size, b"\0") + struct.pack("<II", chrom_ids[c], size)

    def chunks(rows):  # blocks of at most per_block rows, never across chromosomes
        block = []
        for row in rows:
            if block and (len(block) == per_block or row[0] != block[0][0]):
                yield block
                block = []
            block.append(row)
        yield block

    data_offset = 64 + 24 + 40 + len(chrom_tree)
    out, blocks, biggest = bytearray(struct.pack("<Q", 0)), [], 0
    for block in chunks(items):
        raw = struct.pack("<IIIIIBBH", chrom_ids[block[0][0]], block[0][1], block[-1][2], 0, 0, 1, 0, len(block))
        raw += b"".join(struct.pack("<IIf", s, e, v) for _, s, e, v in block)
        packed, biggest = zlib.compress(raw), max(biggest, len(raw))
        blocks.append((block[0][0], block[0][1], block[-1][2], data_offset + len(out), len(packed)))
        out += packed
    struct.pack_into("<Q", out, 0, len(blocks))
    index_offset = data_offset + len(out)
    out += _rtree(blocks, chrom_ids)
    zoom_data = data_offset + len(out)
    out += struct.pack("<I", len(zoom))
    zoom_blocks = []
    for block in chunks(zoom):
        raw = b"".join(struct.pack("<IIIIffff", chrom_ids[c], *r) for c, *r in block)
        packed, biggest = zlib.compress(raw), max(biggest, len(raw))
        zoom_blocks.append((block[0][0], block[0][1], block[-1][2], data_offset + len(out), len(packed)))
        out += packed
    zoom_index = data_offset + len(out)
    out += _rtree(zoom_blocks, chrom_ids)
    header = struct.pack("<IHHQQQHHQQIQ", BIGWIG, 4, 1, 128, data_offset, index_offset, 0, 0, 0, 88, biggest, 0)
    header += struct.pack("<IIQQ", reduction, 0, zoom_data, zoom_index)
    Path(path).write_bytes(header + total + chrom_tree + bytes(out))
    return {"data_offset": data_offset, "index_offset": index_offset, "zoom_index": zoom_index, "size": Path(path).stat().st_size}


def fixture_peaks(chrom, start, end):
    """Centres of the fixture's robust ATAC peaks in chrom:start-end."""
    out = []
    for line in FIXTURE_PEAKS.read_text().splitlines():
        c, s, e = line.split("\t")[:3]
        if c == chrom and start <= int(s) and int(e) <= end:
            out.append((int(s) + int(e)) // 2)
    return out


def synthetic_atac(path, seed=42, chrom="25", start=28_950_000, end=29_050_000, peaks=None, step=2):
    """SYNTHETIC ATAC-like bigWig over chrom:start-end: Gaussian peaks (default: the fixture robust peaks) plus noise,
    one value per `step` bp, in multiples of 1/16 so float32 stores them exactly. Returns the items written."""
    rng = random.Random(seed)
    peaks = fixture_peaks(chrom, start, end) if peaks is None else peaks
    heights = [rng.uniform(5, 40) for _ in peaks]
    items = []
    for s in range(start, end, step):
        v = sum(h * math.exp(-((s - p) / 150) ** 2) for p, h in zip(peaks, heights) if abs(s - p) < 1500) + rng.uniform(0, 1.5)
        items.append((chrom, s, s + step, round(v * 16) / 16))
    write_bigwig(path, {"21": 59_819_933, chrom: 54_385_492 if chrom == "25" else end}, items)
    return items


def synthetic_registry(folder, base_url, conditions, replicates=("R1",), slow=(), seed=42):
    """SYNTHETIC ATAC bigWigs for conditions x replicates in `folder`, and folder/tracks_SYNTHETIC.yaml listing them at
    base_url (a RangeServer url on that folder). Tracks of conditions in `slow` use the server's slow mode.
    Returns the yaml path, for snpportal.lib.tracks.load_tracks (allow the server's host and http in snpscore.bbi first)."""
    import yaml
    from snpdata.trackhub import DEFAULTS, parse_trackdb

    names = [f"AtlanticSalmon_ATAC_{c}_{r}.SYNTHETIC.bigWig" for c in conditions for r in replicates]
    for i, name in enumerate(names):
        synthetic_atac(Path(folder) / name, seed=seed + i)
    tracks = parse_trackdb("\n\n".join(f"bigDataUrl {n}\ntype bigWig" for n in names), base_url, "SYNTHETIC")
    for t in tracks:
        if t["condition"] in slow:
            t["url"] = base_url + "slow/" + t["url"][len(base_url):]
    path = Path(folder) / "tracks_SYNTHETIC.yaml"
    path.write_text("# SYNTHETIC test data generated by tests/bbi_writer.py (seed %d): not real results\n" % seed
                    + yaml.safe_dump({"version": 1, "hosts": ["127.0.0.1"], "defaults": DEFAULTS, "tracks": tracks}, sort_keys=False))
    return path
