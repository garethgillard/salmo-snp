"""Pike CNEs on a salmonid genome (G, 2026-11-26): the conserved non-coding elements of Baudement et al. 2026
(Supplementary Data 4: northern pike fEsoLuc1 coordinates as BED, with each element's id and the age of its oldest
clade), projected through AQUA-FAANG's salmon-trout-pike whole-genome alignment (MAF files referenced to the salmonid
genome, one per salmon chromosome). Every alignment column where the reference and pike both have a base, and the pike
base lies in a CNE, gives that reference base; runs of such bases with one CNE id are the layer's intervals.

fetch() writes the result as the `cne` layer's BED (chrom, start, end, id, age), sorted and without overlaps: where two
CNEs reach one reference base (a duplicated pike row, or a trout block in two files) the older CNE has it.
Pure Python, one process per MAF file (about 5 minutes for salmon on 4 cores). From the scoring chat's script."""
from __future__ import annotations

import bisect
import gzip
import os
import re
import tempfile
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

# The clades of the paper's CNE ages, oldest first: where CNEs overlap, the older one is kept.
AGES = ("Euteleostomi", "Actinopteri", "Neopterygii", "Teleostei", "Clupeocephala", "Euteleosteomorpha",
        "Protacanthopterygii")


def age_rank(age):
    return AGES.index(age) if age in AGES else len(AGES)


def load_cnes(path):
    """{pike chromosome: (starts, ends, ids, ages)} from the paper's space-separated file (header: chromosome start end
    cne_id age; BED coordinates), sorted by start. Overlapping CNEs are cut so that every pike base has one: the older."""
    by = defaultdict(list)
    with open(path) as f:
        next(f)
        for line in f:
            fields = line.split()
            if len(fields) >= 5:
                by[fields[0]].append((int(fields[1]), int(fields[2]), fields[3], fields[4]))
    out = {}
    for chrom, rows in by.items():
        rows = merge(rows)
        out[chrom] = tuple([r[i] for r in rows] for i in range(4))
    return out


def merge(runs):
    """(start, end, id, age) intervals of one chromosome without overlaps: where they overlap, the oldest CNE (then
    the lowest id) has the bases; neighbouring pieces of one CNE are joined. Sorted by start."""
    runs = sorted(runs)
    if all(a[1] <= b[0] for a, b in zip(runs, runs[1:])):
        return runs
    edges = sorted({p for r in runs for p in r[:2]})
    out, active, i = [], [], 0
    for left, right in zip(edges, edges[1:]):  # each stretch between two edges has one set of covering runs
        while i < len(runs) and runs[i][0] <= left:
            active.append(runs[i])
            i += 1
        active = [r for r in active if r[1] > left]
        if not active:
            continue
        _, _, cid, age = min(active, key=lambda r: (age_rank(r[3]), r[2]))
        if out and out[-1][1] == left and out[-1][2] == cid:
            out[-1] = (out[-1][0], right, cid, age)
        else:
            out.append((left, right, cid, age))
    return out


def _plus_span(start, size, strand, src):
    return (start, start + size) if strand == "+" else (src - start - size, src - start)


def project_block(rows, cnes, emit, reference="Ssal_A"):
    """The CNE bases of one MAF block (rows: name, start, size, strand, source size, text) on its reference row."""
    ref = [r for r in rows if r[0].startswith(reference + ".")]
    pikes = [r for r in rows if r[0].startswith("Eluc.")]
    if len(ref) != 1 or not pikes:
        return
    rname, rstart, _, rstrand, rsrc, rtext = ref[0]
    rchrom = rname.split(".", 1)[1]
    for pname, pstart, psize, pstrand, psrc, ptext in pikes:
        found = cnes.get(pname.split(".", 1)[1])
        if not found:
            continue
        starts, ends, ids, ages = found
        lo, hi = _plus_span(pstart, psize, pstrand, psrc)
        k = bisect.bisect_right(ends, lo)
        if k >= len(starts) or starts[k] >= hi:  # no CNE in this block's stretch of pike
            continue
        ri = pi = 0  # bases of each row passed so far
        run = None  # [chrom, start, end, id, age]
        for rc, pc in zip(rtext, ptext):
            if rc != "-" and pc != "-":
                rpos = rstart + ri if rstrand == "+" else rsrc - 1 - (rstart + ri)
                ppos = pstart + pi if pstrand == "+" else psrc - 1 - (pstart + pi)
                j = bisect.bisect_right(ends, ppos)
                if j < len(starts) and starts[j] <= ppos:
                    cid = ids[j]
                    if run and run[3] == cid and rpos == run[2]:
                        run[2] += 1
                    elif run and run[3] == cid and rpos == run[1] - 1:
                        run[1] -= 1
                    else:
                        if run:
                            emit(run)
                        run = [rchrom, rpos, rpos + 1, cid, ages[j]]
            if rc != "-":
                ri += 1
            if pc != "-":
                pi += 1
        if run:
            emit(run)


def project_maf(lines, cnes, reference="Ssal_A"):
    """[(chrom, start, end, id, age)] of the CNE bases on the reference in a MAF's text lines."""
    out, rows = [], []
    emit = lambda r: out.append(tuple(r))  # noqa: E731
    for line in lines:
        if line.startswith("s"):
            p = line.split()
            rows.append((p[1], int(p[2]), int(p[3]), p[4], int(p[5]), p[6]))
        elif line.startswith("a"):
            if rows:
                project_block(rows, cnes, emit, reference)
            rows = []
    if rows:
        project_block(rows, cnes, emit, reference)
    return out


def _project_file(job):
    location, cne_path, reference = job
    cnes = load_cnes(cne_path)
    if "://" not in location:
        with gzip.open(location, "rt") as f:
            return location, project_maf(f, cnes, reference)
    with tempfile.NamedTemporaryFile(suffix=".maf.gz") as tmp:  # downloaded whole, so a dropped connection resumes
        from .build import download
        download(location, Path(tmp.name))
        with gzip.open(tmp.name, "rt") as f:
            return location, project_maf(f, cnes, reference)


def natural(chrom):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", chrom)]


def project(cne_path, mafs, target, reference="Ssal_A", workers=None):
    """Write `target`: the CNEs of `cne_path` on the reference of the MAF files (paths or URLs), as BED without
    overlaps (chrom, start, end, id, age), chromosomes in natural order. Returns {runs, bases, ids, files}."""
    workers = workers or min(4, os.cpu_count() or 1, len(mafs))
    by = defaultdict(list)
    jobs = [(m, str(cne_path), reference) for m in mafs]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for location, runs in pool.map(_project_file, jobs):
            print(f"snpdata: {location}: {len(runs):,} CNE runs", flush=True)
            for chrom, start, end, cid, age in runs:
                by[chrom].append((start, end, cid, age))
    n = bases = 0
    ids = set()
    with open(target, "w") as out:
        for chrom in sorted(by, key=natural):
            for start, end, cid, age in merge(by[chrom]):
                out.write(f"{chrom}\t{start}\t{end}\t{cid}\t{age}\n")
                n, bases = n + 1, bases + end - start
                ids.add(cid)
    return {"runs": n, "bases": bases, "ids": len(ids), "files": len(mafs)}


def maf_locations(spec):
    """The MAF files of a layers.yaml `cnes` block: `maf` with {n} formatted for n = 1..files (e.g. ssa{n:02d})."""
    return [spec["maf"].format(n=n) for n in range(1, int(spec["files"]) + 1)]


if __name__ == "__main__":  # python -m snpdata.cne <cne file> <out.bed> <reference> <maf> [<maf> ...]
    import sys
    print(project(sys.argv[1], sys.argv[4:], sys.argv[2], sys.argv[3]))

