"""Read bigWig and bigBed files (local path or allowlisted https URL) with the standard library only.
Remote files are read with HTTP Range requests over kept-alive connections: one request per tree node, the whole
chromosome tree in one request, and a shared byte-bounded cache, so opening a file and reading a window costs a few
small reads. Format: https://genome.ucsc.edu/goldenPath/help/bigWig.html (header, chromosome B+ tree, R-tree, zlib blocks).

Settings: SNPSCORE_CA_FILE (else SSL_CERT_FILE) is the CA bundle; SNPSCORE_RANGE_CACHE_MB (64) sizes the cache;
SNPSCORE_ALLOWED_HOSTS (comma-separated) replaces the host allowlist. Tests also set ALLOWED_SCHEMES."""
from __future__ import annotations

import collections
import concurrent.futures
import http.client
import logging
import os
import re
import ssl
import struct
import sys
import threading
import time
import weakref
import zlib
from urllib.parse import urlsplit

BIGWIG, BIGBED = 0x888FFC26, 0x8789F2EB
ALLOWED_HOSTS = {h.strip().lower() for h in os.environ.get("SNPSCORE_ALLOWED_HOSTS", "salmobase.org,ftp.ensembl.org").split(",")
                 if h.strip()}
ALLOWED_SCHEMES = ("https",)
CONNECT_TIMEOUT, READ_TIMEOUT, RETRIES = 3, 5, 2
MAX_PER_HOST = 16  # range requests in flight per host (salmobase serves static files; a browser view reads ~600)
HEAD = 131072  # first read of a file: header, zoom list and the chromosome tree (90 KB for Ssal_v3.1's 3,218 sequences)
CHROM_TREE_MAX = 256 * 1024  # read the whole chromosome tree at once when it is smaller than this
RTREE_GUESS = 256  # R-tree block size assumed when reading an index header and its root node together
WHOLE_FILE_MAX = 64 << 20  # read_all() limit for remote files (.fai, .gzi, trackDb.txt)
STATS = {"requests": 0, "bytes": 0}  # HTTP requests made by this process, for tests and timings

log = logging.getLogger(__name__)


class RemoteError(OSError):
    """The server answered, but not with exactly the bytes asked for."""


def check_url(url):
    """Raise ValueError unless url uses an allowed scheme (https, on its default port), an allowlisted host and no user
    info. Plain http (tests only, through ALLOWED_SCHEMES) may use any port."""
    parts = urlsplit(url)
    try:
        port = parts.port
    except ValueError:  # not a number
        port = -1
    if (parts.scheme not in ALLOWED_SCHEMES or parts.hostname not in ALLOWED_HOSTS or "@" in parts.netloc
            or (parts.scheme != "http" and port not in (None, 443))):
        raise ValueError(f"{url}: only {'/'.join(ALLOWED_SCHEMES)} URLs on {', '.join(sorted(ALLOWED_HOSTS))} are allowed")


class _LRU:
    """Byte-bounded least-recently-used cache, shared by all remote files."""

    def __init__(self, limit):
        self.limit, self.size, self.data, self.lock = limit, 0, collections.OrderedDict(), threading.Lock()

    def get(self, key):
        with self.lock:
            value = self.data.get(key)
            if value is not None:
                self.data.move_to_end(key)
            return value

    def put(self, key, value):
        with self.lock:
            if key not in self.data:
                self.data[key] = value
                self.size += len(value)
            while self.size > self.limit:
                self.size -= len(self.data.popitem(last=False)[1])

    def clear(self):
        with self.lock:
            self.data.clear()
            self.size = 0


_CACHE = _LRU(int(os.environ.get("SNPSCORE_RANGE_CACHE_MB", "64")) << 20)
_OPEN = collections.defaultdict(collections.OrderedDict)  # class -> opened objects, so headers are read once per process
_EXECUTOR = concurrent.futures.ThreadPoolExecutor(MAX_PER_HOST, thread_name_prefix="snpscore-bbi")
_SLOTS = collections.defaultdict(lambda: threading.BoundedSemaphore(MAX_PER_HOST))  # requests in flight per host
_CONNS = weakref.WeakSet()  # open connections of live threads, so clear_caches() can close them
_local = threading.local()  # this thread's connections (one per host) and deadline
_lock = threading.Lock()
_ssl = None


class _ThreadConns(dict):
    """One thread's connections, (scheme, host, port) -> connection. Closed when the thread ends and drops it."""

    def __del__(self):
        for conn in self.values():
            conn.close()


def _connection(scheme, host, port):
    conns = getattr(_local, "conns", None)
    if conns is None:
        conns = _local.conns = _ThreadConns()
    if (scheme, host, port) not in conns:
        global _ssl
        if scheme == "https" and _ssl is None:
            _ssl = ssl.create_default_context(cafile=os.environ.get("SNPSCORE_CA_FILE") or os.environ.get("SSL_CERT_FILE") or None)
        cls = http.client.HTTPSConnection if scheme == "https" else http.client.HTTPConnection
        kwargs = {"context": _ssl} if scheme == "https" else {}
        conns[(scheme, host, port)] = conn = cls(host, port, timeout=CONNECT_TIMEOUT, **kwargs)
        with _lock:
            _CONNS.add(conn)
    return conns[(scheme, host, port)]


def _time_left():
    """Seconds left before this thread's deadline (set by bins_many), or None without one."""
    deadline = getattr(_local, "deadline", None)
    if deadline is None:
        return None
    left = deadline - time.monotonic()
    if left <= 0:
        raise TimeoutError("deadline passed")
    return left


def _read_timeout():
    """READ_TIMEOUT, shortened to what is left of this thread's deadline."""
    left = _time_left()
    return READ_TIMEOUT if left is None else min(READ_TIMEOUT, left)


def _get(url, offset=None, size=None):
    """(bytes, file size) of a byte range, or of the whole file when offset is None, over this thread's kept-alive
    connection to the host. Retries connection errors; any status other than 206 (200 for a whole file) is an error."""
    check_url(url)
    parts = urlsplit(url)
    path = parts.path + ("?" + parts.query if parts.query else "")
    headers = {"Range": f"bytes={offset}-{offset + size - 1}"} if offset is not None else {}
    with _lock:
        slot = _SLOTS[parts.hostname]
    for attempt in range(RETRIES + 1):
        if not slot.acquire(timeout=_time_left()):  # waits for a free slot no longer than the deadline
            raise TimeoutError(f"{url}: all {MAX_PER_HOST} connections to {parts.hostname} busy until the deadline")
        conn = _connection(parts.scheme, parts.hostname, parts.port)
        try:
            timeout = _read_timeout()
            if conn.sock is None:
                conn.timeout = min(CONNECT_TIMEOUT, timeout)
                conn.connect()
            conn.sock.settimeout(timeout)
            conn.request("GET", path, headers=headers)
            data, total = _body(url, conn.getresponse(), offset, size)
            with _lock:
                STATS["requests"] += 1
                STATS["bytes"] += len(data)
            return data, total
        except (ConnectionError, http.client.HTTPException, ssl.SSLEOFError) as e:  # e.g. an idle connection the server closed
            conn.close()
            if attempt == RETRIES:
                raise RemoteError(f"{url}: {e!r}") from e
        except BaseException:
            conn.close()  # never leave an unread body (e.g. a whole file sent as 200) on the connection
            raise
        finally:
            slot.release()


def _body(url, resp, offset, size):
    length = resp.getheader("Content-Length")
    if offset is None:
        if resp.status != 200 or length is None or int(length) > WHOLE_FILE_MAX:
            raise RemoteError(f"{url}: status {resp.status}, Content-Length {length}")
        n, total = int(length), int(length)
    else:
        if resp.status != 206:
            raise RemoteError(f"{url}: expected 206 Partial Content for a Range request, got {resp.status}")
        m = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", resp.getheader("Content-Range", ""))
        total = int(m.group(3)) if m else 0
        if not m or int(m.group(1)) != offset or int(m.group(2)) != min(offset + size, total) - 1:
            raise RemoteError(f"{url}: Content-Range {resp.getheader('Content-Range')!r} does not match bytes={offset}-{offset + size - 1}")
        n = int(m.group(2)) - offset + 1
        if length is not None and int(length) != n:
            raise RemoteError(f"{url}: Content-Length {length} does not match Content-Range")
    data = resp.read(n)
    if len(data) != n:
        raise RemoteError(f"{url}: short read ({len(data)} of {n} bytes)")
    return data, total


def read_all(location):
    """Whole file (local path or allowlisted URL); for small files such as .fai, .gzi and trackDb.txt."""
    location = str(location)
    if "://" in location:
        return _get(location)[0]
    with open(location, "rb") as f:
        return f.read()


def clear_caches():
    """Forget cached bytes and opened files, and close all connections (they reconnect when next used).
    For tests and cold timings only: it also closes connections other threads may be using."""
    _CACHE.clear()
    with _lock:
        _OPEN.clear()
        for conn in list(_CONNS):
            conn.close()
        STATS.update(requests=0, bytes=0)


def cached(cls, location, limit=32):
    """One cls(location) per process (BBIFile, Fasta): the `limit` most recently used of each class, so bigWigs never
    push out the genome. A local file is reopened when it changes. An opened salmobase bigWig holds about 0.65 MB
    outside the byte-bounded cache (its 3,200-3,800 sequence names and its first read); reopening one whose first
    read is still in that cache costs about 2 ms and no request."""
    location = str(location)
    key = (location, None if "://" in location else os.stat(location).st_mtime_ns)
    with _lock:
        opened = _OPEN[cls]
        if key in opened:
            opened.move_to_end(key)
            return opened[key]
    obj = cls(location)
    with _lock:
        opened[key] = obj
        while len(opened) > limit:
            opened.popitem(last=False)
    return obj


class Source:
    """Random access to a local file, or to an allowlisted URL through the shared cache.
    The first read at offset 0 is kept as `head`; reads inside it cost nothing."""

    def __init__(self, location):
        self.location = str(location)
        self.remote = "://" in self.location
        if self.remote:
            check_url(self.location)
        self.file = None if self.remote else open(self.location, "rb")
        self.lock = threading.Lock()
        self.head, self.size = b"", None  # size: total bytes, once a server has said

    def read(self, offset, size):
        if not self.remote:
            with self.lock:
                self.file.seek(offset)
                return self.file.read(size)
        head = self.head
        if offset + size <= len(head) or len(head) == self.size:
            return head[offset:offset + size]
        data = _CACHE.get((self.location, offset, size))
        if data is None:
            start = max(offset, len(head))  # the part already in head is not asked for again
            data, self.size = _get(self.location, start, offset + size - start)
            data = head[offset:start] + data
            _CACHE.put((self.location, offset, size), data)
        if offset == 0 and len(data) > len(self.head):
            self.head = data
        return data


class BBIFile:
    """A bigWig or bigBed file. Opening it reads the header and the chromosome list (one or two reads)."""

    def __init__(self, location):
        self.location = str(location)
        self.src = Source(location)
        head = self.src.read(0, HEAD)
        (magic, _, zooms, chrom_tree, self.data_offset, self.index_offset, _, _, self.autosql_offset, _,
         self.compressed, _) = struct.unpack_from("<IHHQQQHHQQIQ", head)
        if magic not in (BIGWIG, BIGBED):
            raise ValueError(f"{location} is not a bigWig or bigBed file")
        self.kind = "bigwig" if magic == BIGWIG else "bigbed"
        # zoom levels: (bases per summary record, data offset, index offset), finest first
        self.zooms = [struct.unpack_from("<I4xQQ", head, 64 + 24 * i) for i in range(zooms)]
        self.chroms = {}  # name -> (id, size)
        self._chrom_tree(chrom_tree)

    def _chrom_tree(self, off):
        """Walk the chromosome B+ tree: from one read of the whole tree when it ends at the data section and is small
        enough (as bedGraphToBigWig writes it), else one read per node. Names are interned: files list mostly the
        same sequences (only those with data, so the trees themselves differ)."""
        _, block, key_size, val_size = struct.unpack_from("<IIII", self.src.read(off, 32))
        whole = off < self.data_offset <= off + CHROM_TREE_MAX
        tree = self.src.read(off, self.data_offset - off) if whole else None
        item = key_size + val_size
        stack = [off + 32]
        while stack:
            at = stack.pop()
            node = tree[at - off:at - off + 4 + block * item] if whole else self.src.read(at, 4 + block * item)
            leaf, n = struct.unpack_from("<B1xH", node)
            for i in range(n):
                p = 4 + i * item
                key = sys.intern(node[p:p + key_size].rstrip(b"\0").decode())
                if leaf:
                    self.chroms[key] = struct.unpack_from("<II", node, p + key_size)
                else:
                    stack.append(struct.unpack_from("<Q", node, p + key_size)[0])

    def _blocks(self, index_offset, chrom_id, start, end):
        """(offset, size) of every data block overlapping chrom_id:start-end, in file order, through an R-tree
        index. The index header and root node come in one read, then one read per node visited."""
        first = self.src.read(index_offset, 48 + 4 + RTREE_GUESS * 32)
        block = struct.unpack_from("<I", first, 4)[0]
        found = []

        def node(off):
            data = first[48:] if off == index_offset + 48 and block <= RTREE_GUESS else self.src.read(off, 4 + block * 32)
            leaf, n = struct.unpack_from("<B1xH", data)
            for i in range(n):
                sc, sb, ec, eb = struct.unpack_from("<IIII", data, 4 + i * (32 if leaf else 24))
                if (sc, sb) < (chrom_id, end) and (ec, eb) > (chrom_id, start):
                    if leaf:
                        found.append(struct.unpack_from("<QQ", data, 4 + i * 32 + 16))
                    else:
                        node(struct.unpack_from("<Q", data, 4 + i * 24 + 16)[0])

        node(index_offset + 48)
        return found

    def _data(self, index_offset, chrom, start, end):
        if chrom not in self.chroms:
            return
        chrom_id = self.chroms[chrom][0]
        for offset, size in self._blocks(index_offset, chrom_id, start, end):
            raw = self.src.read(offset, size)
            yield chrom_id, zlib.decompress(raw) if self.compressed else raw

    def values(self, chrom, start, end):
        """bigWig: [(start, end, value)] of the raw data overlapping start-end (BED coordinates)."""
        out = []
        for chrom_id, data in self._data(self.index_offset, chrom, start, end):
            pos = 0
            while pos < len(data):
                cid, c_start, _, step, span, kind, n = struct.unpack_from("<IIIIIB1xH", data, pos)
                pos += 24
                for i in range(n):
                    if kind == 1:  # bedGraph
                        s, e, v = struct.unpack_from("<IIf", data, pos)
                        pos += 12
                    elif kind == 2:  # variableStep
                        s, v = struct.unpack_from("<If", data, pos)
                        e = s + span
                        pos += 8
                    else:  # fixedStep
                        (v,) = struct.unpack_from("<f", data, pos)
                        s = c_start + i * step
                        e = s + span
                        pos += 4
                    if cid == chrom_id and s < end and e > start:
                        out.append((s, e, v))
        return out

    def summaries(self, zoom, chrom, start, end):
        """bigWig: [(start, end, mean)] of the zoom level `zoom` (an item of self.zooms) overlapping start-end."""
        out = []
        for chrom_id, data in self._data(zoom[2], chrom, start, end):
            for pos in range(0, len(data), 32):
                cid, s, e, count, _, _, total, _ = struct.unpack_from("<IIIIffff", data, pos)
                if cid == chrom_id and count and s < end and e > start:
                    out.append((s, e, total / count))
        return out

    def bins(self, chrom, start, end, n):
        """bigWig: mean value in each of n equal bins across start-end (None where there is no data).
        Reads the coarsest zoom level whose bases per record are at most the bases per bin, else the raw data."""
        if n < 1 or end <= start:
            raise ValueError(f"bins needs n >= 1 and start < end, not n={n} and {start}-{end}")
        width = (end - start) / n
        zooms = [z for z in self.zooms if z[0] <= width]
        records = self.summaries(max(zooms), chrom, start, end) if zooms else self.values(chrom, start, end)
        sums, covered = [0.0] * n, [0] * n
        for s, e, v in records:
            first, last = max(0, int((s - start) / width)), min(n - 1, int((e - 1 - start) / width))
            for b in range(first, last + 1):
                lo, hi = max(s, start + b * width), min(e, start + (b + 1) * width)
                if hi > lo:
                    sums[b] += v * (hi - lo)
                    covered[b] += hi - lo
        return [sums[b] / covered[b] if covered[b] else None for b in range(n)]

    def entries(self, chrom, start, end):
        """bigBed: [(start, end, rest)] overlapping start-end; `rest` is the tab-separated remaining fields."""
        out = []
        for chrom_id, data in self._data(self.index_offset, chrom, start, end):
            pos = 0
            while pos < len(data):
                cid, s, e = struct.unpack_from("<III", data, pos)
                stop = data.index(b"\0", pos + 12)
                if cid == chrom_id and s < end and e > start:
                    out.append((s, e, data[pos + 12:stop].decode()))
                pos = stop + 1
        return out

    def all_entries(self):
        """bigBed: every (chrom, start, end, rest), chromosome by chromosome."""
        names = {cid: name for name, (cid, _) in self.chroms.items()}
        for name, (cid, size) in sorted(self.chroms.items(), key=lambda kv: kv[1][0]):
            for s, e, rest in self.entries(name, 0, size):
                yield names[cid], s, e, rest


def open_bbi(location):
    """The process-wide BBIFile for a location (opened once)."""
    return cached(BBIFile, location)


def _bins_task(location, chrom, start, end, n, deadline):
    _local.deadline = deadline
    try:
        return open_bbi(location).bins(chrom, start, end, n)
    finally:
        _local.deadline = None


def bins_many(locations, chrom, start, end, n, deadline=4.0):
    """bins() for several bigWigs in parallel: one list per location, or None for a track that failed or missed
    the deadline (seconds). Late tracks stop at their next request instead of finishing in the background."""
    until = time.monotonic() + deadline
    futures = [_EXECUTOR.submit(_bins_task, loc, chrom, start, end, n, until) for loc in locations]
    concurrent.futures.wait(futures, timeout=deadline)
    out = []
    for loc, f in zip(locations, futures):
        if f.done() and f.exception() is None:
            out.append(f.result())
        else:
            log.warning("no signal from %s: %r", loc, f.exception() if f.done() else "deadline passed")
            f.cancel()
            out.append(None)
    return out
