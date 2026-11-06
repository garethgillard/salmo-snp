"""Align two Atlantic salmon assemblies chromosome by chromosome (ROADMAP I19, I20) for snpdata build's `liftover` tables:
each chromosome 1-29 of the assembly converted from against the same chromosome of the other, with minimap2's asm5
preset (mappy, minimap2's Python binding: `pip install mappy`; only this script needs it). Same-numbered chromosomes
only: a whole-genome alignment would let the Ss4R duplicate of a region (on its paired chromosome) take its place.
Writes a PAF of the primary alignments with their CIGARs (cg:Z), and a names table of the second assembly (its
GenBank and RefSeq accessions -> 1-29) from its NCBI assembly report.

  pip install mappy
  python prep/align_assemblies.py data/raw/Salmo_salar.Ssal_v3.1.dna_sm.toplevel.fa.gz \\
      data/raw/GCA_965601325.1_fSalSal1_genomic.fna.gz data/raw/GCA_965601325.1_fSalSal1_assembly_report.txt \\
      data/raw/ssal31_to_fsalsal1.paf.gz data/raw/fsalsal1_names.tsv --threads 4

The first FASTA is the Ensembl Ssal_v3.1 genome (chromosomes named 1-29; bgzipped or gzipped); the second an NCBI
genome whose report names its chromosomes ssa01-ssa29. Each chromosome of the second is indexed once (a few GB) and
the first's is mapped in 2 Mb pieces on every core."""
from __future__ import annotations

import argparse
import gzip
import os
import re
import sys
import tempfile
import time
from pathlib import Path

CHROMS = [str(i) for i in range(1, 30)]


def chromosome(name):
    """'1'-'29' for ssa01, chr1, 01 or 1; else None."""
    m = re.fullmatch(r"(?:ssa|chr)?0*([0-9]+)", name.strip(), re.I)
    return m.group(1) if m and 1 <= int(m.group(1)) <= 29 else None


def report_names(report):
    """{accession: '1'-'29'} of an NCBI assembly report's chromosomes (GenBank and RefSeq accessions)."""
    out = {}
    for line in open(report):
        if line.startswith("#"):
            continue
        f = line.rstrip("\n").split("\t")
        if len(f) > 6 and f[1] == "assembled-molecule" and chromosome(f[0]):
            for acc in (f[4], f[6]):
                if acc and acc != "na":
                    out[acc] = chromosome(f[0])
    return out


def split(fasta, names, folder):
    """Write chromosomes 1-29 of `fasta` as folder/<chrom>.fa (names: accession -> chrom, or None to read 1-29 names)."""
    import mappy
    for name, seq, _ in mappy.fastx_read(str(fasta)):
        c = names.get(name) if names is not None else chromosome(name)
        if c in CHROMS and not (folder / f"{c}.fa").exists():
            (folder / f"{c}.fa").write_text(f">{c}\n{seq}\n")


def align(c, a_dir, b_dir, threads, chunk):
    """PAF lines (primary alignments, with cg:Z) of chromosome c of the first assembly against c of the second: the
    second's chromosome indexed once, the first's mapped in pieces of `chunk` bp on `threads` threads (mappy releases
    Python's lock while it maps), so memory stays small and every core works. Alignments stop at the pieces' ends."""
    import threading
    from concurrent.futures import ThreadPoolExecutor
    import mappy
    if not (a_dir / f"{c}.fa").exists() or not (b_dir / f"{c}.fa").exists():
        return []
    target = next(mappy.fastx_read(str(b_dir / f"{c}.fa")))[1]
    aligner = mappy.Aligner(seq=target, preset="asm5")
    query = next(mappy.fastx_read(str(a_dir / f"{c}.fa")))[1]
    local = threading.local()

    def piece(start):
        if not hasattr(local, "buf"):
            local.buf = mappy.ThreadBuffer()
        out = []
        for h in aligner.map(query[start:start + chunk], buf=local.buf):
            if h.is_primary:
                out.append("\t".join(map(str, (c, len(query), start + h.q_st, start + h.q_en, "+" if h.strand > 0 else "-", c,
                                                len(target), h.r_st, h.r_en, h.mlen, h.blen, h.mapq, "tp:A:P", f"cg:Z:{h.cigar_str}"))))
        return out
    with ThreadPoolExecutor(threads) as pool:
        return [line for lines in pool.map(piece, range(0, len(query), chunk)) for line in lines]


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("first", help="FASTA of the assembly converted from (chromosomes named 1-29)")
    p.add_argument("second", help="FASTA of the assembly converted to (NCBI accessions)")
    p.add_argument("report", help="the second assembly's NCBI assembly report")
    p.add_argument("paf", help="output PAF (.gz to compress)")
    p.add_argument("names", help="output: the second assembly's accessions and chromosome numbers (TSV)")
    p.add_argument("--threads", type=int, default=os.cpu_count() or 1)
    p.add_argument("--chunk", type=int, default=2_000_000, help="bp of the first assembly mapped at a time")
    p.add_argument("--chromosomes", default=",".join(CHROMS), help="comma-separated, e.g. 25 for a quick try")
    p.add_argument("--work", help="a folder for the chromosomes split out of both FASTAs (kept, so a rerun skips that)")
    a = p.parse_args()
    names = report_names(a.report)
    Path(a.names).write_text("accession\tchrom\n" + "".join(f"{k}\t{v}\n" for k, v in sorted(names.items())))
    with tempfile.TemporaryDirectory(dir=Path(a.paf).resolve().parent) as tmp:
        work = Path(a.work or tmp)
        first, second = work / "first", work / "second"
        first.mkdir(parents=True, exist_ok=True)
        second.mkdir(parents=True, exist_ok=True)
        split(a.first, None, first)
        split(a.second, names, second)
        opener = gzip.open if a.paf.endswith(".gz") else open
        with opener(a.paf, "wt") as out:
            for c in (c for c in a.chromosomes.split(",") if c in CHROMS):
                t = time.time()
                lines = align(c, first, second, a.threads, a.chunk)
                out.write("".join(line + "\n" for line in lines))
                print(f"chromosome {c}: {len(lines)} alignments, {time.time() - t:.0f} s", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
