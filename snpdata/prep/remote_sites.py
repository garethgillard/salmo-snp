"""remote_sites.py <url of a bgzipped VCF> <target sites.vcf.gz> [part MB] [workers]: what `snpdata fetch` does for a
`sites_only` source with count_gt and snps_only (AC, AN and NS counted from the genotypes, SNPs only, genotypes never
written), but over parallel byte ranges: each part is fetched (retried), processed in memory and kept when done, so a
killed run continues where it stopped. For files too large for one stream (the 55 GB trout cohort at about 1.3 MB/s
per connection from ENA); `snpdata fetch` then finds the target and skips it. The species-data workflow uses it."""
import gzip
import os
import struct
import sys
import time
import urllib.request
import zlib
from concurrent.futures import ProcessPoolExecutor

from snpdata.build import gt_counts

url, target = sys.argv[1], sys.argv[2]
STEP = (int(sys.argv[3]) if len(sys.argv) > 3 else 48) << 20
WORKERS = int(sys.argv[4]) if len(sys.argv) > 4 else 8
TAIL = 1 << 20  # read past a part's end: the block that finishes its last line
MAGIC = b"\x1f\x8b\x08\x04"


def fetch(start, end):
    """Bytes [start, end) of the URL."""
    while True:
        try:
            r = urllib.request.urlopen(urllib.request.Request(url, headers={"Range": f"bytes={start}-{end - 1}"}), timeout=90)
            data = r.read()
            if len(data) == end - start:
                return data
        except Exception:
            pass
        time.sleep(3)


def total():
    while True:
        try:
            r = urllib.request.urlopen(urllib.request.Request(url, headers={"Range": "bytes=0-0"}), timeout=60)
            return int(r.headers["Content-Range"].split("/")[1])
        except Exception:
            time.sleep(3)


def first_block(buf):
    """Offset of the first BGZF block start in buf (checked by following its size to the next block)."""
    i = 0
    while True:
        i = buf.find(MAGIC, i)
        if i < 0:
            raise SystemExit("no BGZF block found")
        if buf[i + 12:i + 14] == b"BC":
            n = struct.unpack("<H", buf[i + 16:i + 18])[0] + 1
            if buf[i + n:i + n + 4] == MAGIC:
                return i
        i += 1


def blocks(buf, at):
    pos = at
    while pos + 18 <= len(buf):
        n = struct.unpack("<H", buf[pos + 16:pos + 18])[0] + 1
        if pos + n > len(buf):
            return
        yield pos, zlib.decompress(buf[pos + 18:pos + n - 8], -15)
        pos += n


def part(k, start, end, size):
    """Lines that begin in blocks at [start, end), nominal offsets: the real cuts are the first block at or after each."""
    out_path = f"{target}.part{k:04d}"
    if os.path.exists(out_path):
        return k
    last = end >= size
    buf = fetch(start, min(size, end + TAIL))
    begin = 0 if start == 0 else first_block(buf)
    stop = len(buf) if last else (end - start) + first_block(buf[end - start:])
    kept, rest, first, done = [], b"", k > 0, False
    for pos, data in blocks(buf, begin):
        past = pos >= stop
        if first:
            cut = data.find(b"\n")
            if cut < 0:
                continue
            data, first = data[cut + 1:], False
        if past:
            cut = data.find(b"\n")
            if cut < 0:
                rest += data
                continue
            lines, rest, done = [rest + data[:cut]], b"", True
        else:
            lines = (rest + data).split(b"\n")
            rest = lines.pop()
        for line in lines:
            if not line or line.startswith(b"#"):
                continue
            fld = line.split(b"\t", 9)
            if not (len(fld[3]) == 1 and len(fld[4]) == 1) or len(fld) < 10:
                continue
            c = gt_counts(fld[8], fld[9])
            fld[7] = b"AC=%d;AN=%d;NS=%d" % (c[b"AC"], c[b"AN"], c[b"NS"])
            kept.append(b"\t".join(fld[:8]) + b"\n")
        if done:
            break
    if not (done or (last and not rest)):
        raise SystemExit(f"part {k}: its last line does not end within the tail read")
    with gzip.open(out_path + ".tmp", "wb", compresslevel=6) as out:
        out.write(b"".join(kept))
    os.rename(out_path + ".tmp", out_path)
    return k


if __name__ == "__main__":
    size = total()
    starts = list(range(0, size, STEP))
    n = len(starts)
    with ProcessPoolExecutor(WORKERS) as pool:
        for i, k in enumerate(pool.map(part, range(n), starts, [s + STEP for s in starts], [size] * n)):
            if i % 10 == 0:
                print(f"part {k + 1}/{n}", flush=True)
    head = (b"##fileformat=VCFv4.2\n##snpdata=sites only (genotypes dropped) from " + url.encode() + b"\n"
            + b"".join(b"##INFO=<ID=%s,Number=1,Type=Integer,Description=\"Counted from the genotypes by snpdata fetch\">\n" % k
                       for k in (b"AC", b"AN", b"NS")) + b"#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n")
    with open(target + ".tmp", "wb") as out:
        out.write(gzip.compress(head))
        for k in range(n):
            with open(f"{target}.part{k:04d}", "rb") as f:
                out.write(f.read())
    os.rename(target + ".tmp", target)
    for k in range(n):
        os.remove(f"{target}.part{k:04d}")
    print("ok", target, flush=True)
