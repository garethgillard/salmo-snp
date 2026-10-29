"""Read sequence from a bgzipped FASTA with .fai and .gzi indexes (local path or allowlisted https URL), standard library
only. salmobase serves Ssal_v3.1 this way, so probe flanks can be read without downloading the 738 MB genome.
Remote reads go through bbi.Source (kept-alive connections, shared byte cache)."""
from __future__ import annotations

import bisect
import struct
import zlib

from .bbi import Source, cached, read_all


class Fasta:
    def __init__(self, location):
        location = str(location)
        self.src = Source(location)
        self.index = {}  # chrom -> (length, offset of first base, bases per line, bytes per line)
        for line in read_all(location + ".fai").decode().splitlines():
            name, length, offset, line_bases, line_bytes = line.split("\t")[:5]
            self.index[name] = (int(length), int(offset), int(line_bases), int(line_bytes))
        gzi = read_all(location + ".gzi")
        pairs = [(0, 0)] + [struct.unpack_from("<QQ", gzi, 8 + 16 * i) for i in range(struct.unpack_from("<Q", gzi)[0])]
        self.compressed = [c for c, _ in pairs]  # where each BGZF block starts in the .gz file
        self.uncompressed = [u for _, u in pairs]  # and in the uncompressed FASTA text
        self.blocks = {}

    def _block(self, i, need=None):
        """Uncompressed block i, or at least its first `need` bytes. A block ends where the next one starts; each is one
        gzip member of at most 64 KiB, decompressed only as far as asked (and at least doubled when it grows): a SNP's
        window needs ~71 bytes. Safe when threads share this Fasta (open_fasta): a stored decompressor is copied before
        it continues, and another thread may clear self.blocks at any time."""
        d, data, tail = self.blocks.get(i) or (None, b"", b"")
        if d is None:
            size = self.compressed[i + 1] - self.compressed[i] if i + 1 < len(self.compressed) else 65536
            d, tail = zlib.decompressobj(31), self.src.read(self.compressed[i], size)
        if (need is None or len(data) < need) and not d.eof:
            d = d.copy()
            data += d.decompress(tail, 0 if need is None else max(need - len(data), len(data), 4096))  # 0: all
            if len(self.blocks) > 256:
                self.blocks.clear()
            self.blocks[i] = (d, data, d.unconsumed_tail)
        return data

    def _text(self, start, end):
        first = bisect.bisect_right(self.uncompressed, start) - 1
        last = bisect.bisect_right(self.uncompressed, end - 1) - 1
        data = b"".join(self._block(i, end - self.uncompressed[i] if i == last else None) for i in range(first, last + 1))
        return data[start - self.uncompressed[first]:end - self.uncompressed[first]]

    def fetch(self, chrom, start, end):
        """Sequence of chrom:start-end (BED coordinates), soft-masked (lowercase = repeat), clipped to the chromosome."""
        length, offset, line_bases, line_bytes = self.index[chrom]
        start, end = max(0, start), min(end, length)
        if end <= start:
            return ""
        at = lambda pos: offset + pos // line_bases * line_bytes + pos % line_bases
        return self._text(at(start), at(end - 1) + 1).decode().replace("\n", "").replace("\r", "")


def open_fasta(location):
    """The process-wide Fasta for a location (indexes read once)."""
    return cached(Fasta, location)
