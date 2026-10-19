"""TF motif changes at SNPs, from JASPAR matrices (MEME format) and the genome, standard library only.

A motif window "matches" when its log-odds score has p < p_value under an even base background, as FIMO scores it
(pseudocount 0.1 shared by the background). A SNP *changes* a motif when, for a window covering the SNP on either
strand, one allele matches and the other doesn't, and the two alleles' scores differ by at least min_delta bits.
build precomputes this for the public sites inside robust ATAC peaks (the `motif` layer, layers.yaml); annotate
computes it for the other SNPs in a peak (add_effects, capped). Per SNP: changed (at least one motif), n (how many
motifs), tfs ('CTCF (G), FOXO3 (A)': the TF and the allele that matches, strongest change first, at most TOP) and
delta (the largest score difference between the alleles, bits).
"""
from __future__ import annotations

import math
import os
import re
from concurrent.futures import ProcessPoolExecutor

P_VALUE = 1e-5  # a window matches below this p-value (G, 2026-10-19; FIMO's default is 1e-4)
MIN_DELTA = 4  # bits between the alleles' scores (16-fold) for a change to count (G, 2026-10-19)
PSEUDO = 0.1  # FIMO's motif pseudocount, shared out by the background
TOP = 5  # TFs named in motif_tfs
CODE = {"A": 0, "C": 1, "G": 2, "T": 3}


def read_meme(path):
    """[(motif id, TF name, nsites, [[pA, pC, pG, pT] per position])] from a MEME motif file (JASPAR's download)."""
    out = []
    for block in open(path).read().split("\nMOTIF ")[1:]:
        head, *lines = block.strip().splitlines()
        mid, name = (head.split() + [""])[:2]
        nsites = float((re.search(r"nsites=\s*([0-9.]+)", block) or [0, 20])[1])
        rows = [[float(x) for x in line.split()] for line in lines if re.fullmatch(r"\s*([0-9.eE-]+\s+){3}[0-9.eE-]+\s*", line)]
        out.append((mid, name or mid, nsites, rows))
    return out


def log_odds(rows, nsites):
    """Per position [score of A, C, G, T] in bits: log2(p' / 0.25), p' = (p * nsites + PSEUDO * 0.25) / (nsites + PSEUDO)."""
    return [[math.log2((p * nsites + PSEUDO / 4) / (nsites + PSEUDO) / 0.25) for p in row] for row in rows]


def threshold(lo, p_value=P_VALUE, scale=10):
    """The lowest score (bits) whose chance of being reached by a random window is below p_value: the exact score
    distribution under an even background, with scores rounded to 1/scale bit."""
    dist = {0: 1.0}
    for col in lo:
        step = {}
        for s, prob in dist.items():
            for x in col:
                k = s + round(x * scale)
                step[k] = step.get(k, 0.0) + prob / 4
        dist = step
    tail = 0.0
    for s in sorted(dist, reverse=True):
        if tail + dist[s] > p_value:
            return (s + 1) / scale
        tail += dist[s]
    return min(dist) / scale


def matrices(path, p_value=P_VALUE):
    """[(motif id, TF name, log-odds rows, reverse-complement rows, threshold, probability rows)] for the motifs of a
    MEME file."""
    out = []
    for mid, name, nsites, rows in read_meme(path):
        lo = log_odds(rows, nsites)
        out.append((mid, name, lo, [col[::-1] for col in lo[::-1]], threshold(lo, p_value), rows))
    return out


def flank(motifs):
    """Bases needed either side of a SNP: the longest motif minus one (32 for JASPAR 2024)."""
    return max(len(m[2]) for m in motifs) - 1


def hits(seq, w, ref, alt, motifs, min_delta=0):
    """The motifs one allele matches and the other doesn't, by at least min_delta bits, in a window seq (upper case)
    with the SNP at index w, largest change first: [{id, tf, strand, start (window index of the motif's first base on
    the + strand), ref_score, alt_score, cut, allele (that matches), delta, probs (the motif's rows, as on its own
    strand)}]; [] when ref, alt or the window hold anything but A, C, G and T. A motif counts once, at its strongest
    change over positions and strands."""
    r, a = CODE.get(ref), CODE.get(alt)
    if r is None or a is None or any(b not in CODE for b in seq):
        return []
    codes = [CODE[b] for b in seq]
    get = list.__getitem__
    out = []
    for mid, name, fwd, rev, cut, probs in motifs:
        best = None
        for strand, rows in (("+", fwd), ("-", rev)):
            n = len(rows)
            for st in range(max(0, w - n + 1), min(w, len(codes) - n) + 1):
                s_ref = sum(map(get, rows, codes[st:st + n]))
                col = rows[w - st]
                s_alt = s_ref - col[r] + col[a]
                if (s_ref >= cut) != (s_alt >= cut) and abs(s_alt - s_ref) >= min_delta:
                    d = abs(s_alt - s_ref)
                    if best is None or d > best[0]:
                        best = (d, strand, st, s_ref, s_alt)
        if best:
            d, strand, st, s_ref, s_alt = best
            out.append({"id": mid, "tf": name, "strand": strand, "start": st, "ref_score": round(s_ref, 2),
                        "alt_score": round(s_alt, 2), "cut": cut, "allele": ref if s_ref >= cut else alt,
                        "delta": d, "probs": probs})
    return sorted(out, key=lambda h: (-h["delta"], h["tf"]))


def changes(seq, w, ref, alt, motifs, min_delta=0):
    """[(|delta|, TF, allele that matches)] of hits()."""
    return [(h["delta"], h["tf"], h["allele"]) for h in hits(seq, w, ref, alt, motifs, min_delta)]


def summary(found):
    """(changed, n, tfs, delta) of changes()."""
    names = ", ".join(f"{name} ({allele})" for _, name, allele in found[:TOP]) + (f" +{len(found) - TOP} more" if len(found) > TOP else "")
    return (bool(found), len(found), names or None, round(found[0][0], 2) if found else None)


_MOTIFS, _MIN_DELTA = None, MIN_DELTA


def _start(path, p_value, min_delta):
    global _MOTIFS, _MIN_DELTA
    _MOTIFS, _MIN_DELTA = matrices(path, p_value), min_delta


def _chunk(job):
    """Worker: [(key, summary)] for [(key, seq, w, ref, alt)]."""
    return [(key, summary(changes(seq, w, ref, alt, _MOTIFS, _MIN_DELTA))) for key, seq, w, ref, alt in job]


def effects(windows, meme, p_value=P_VALUE, min_delta=MIN_DELTA, processes=None, chunk=2000):
    """Yield (key, (changed, n, tfs, delta)) for (key, seq, w, ref, alt) windows. With processes=1 in this process
    (annotate, inside a web worker); otherwise on every CPU core (build), the motifs read once per worker process."""
    if processes == 1:
        _start(str(meme), p_value, min_delta)
        yield from _chunk(list(windows))
        return
    batch = []
    with ProcessPoolExecutor(processes or os.cpu_count() or 1, initializer=_start,
                             initargs=(str(meme), p_value, min_delta)) as pool:
        futures = []
        for item in windows:
            batch.append(item)
            if len(batch) == chunk:
                futures.append(pool.submit(_chunk, batch))
                batch = []
        if batch:
            futures.append(pool.submit(_chunk, batch))
        for f in futures:
            yield from f.result()


ANNOTATE_MAX = 2000  # SNPs annotate computes itself (in-peak, not a precomputed site); the rest stay not checked


def windows(fasta, rows, w):
    """(key, window, w, ref, alt) for (key, chrom, pos, ref, alt) rows in genome order, read from a Fasta; rows on a
    chromosome the genome lacks are left out (not checked)."""
    for key, chrom, pos, ref, alt in rows:
        if chrom in fasta.index:
            yield key, fasta.fetch(chrom, pos - 1 - w, pos + w).upper(), w, ref, alt


def layer_sql(con, meme, layer, out, genome, tmp):
    """The `motif` layer: changed, n, tfs and delta for the sites of the built layer layer['sites'] inside
    layer['within'] (single-base alleles), on every CPU core. Writes a TSV at `tmp` and returns SQL reading it."""
    from .fasta import Fasta
    from .formats import lit
    sites, within = out / f"{layer['sites']}.parquet", out / f"{layer['within']}.parquet"
    rows = con.execute(f"""SELECT v.chrom, v.chrom, v."end", v.ref, v.alt FROM read_parquet({lit(sites)}) v
        ASOF JOIN read_parquet({lit(within)}) p ON p.chrom = v.chrom AND v."end" > p.start
        WHERE v."end" <= p."end" AND length(v.ref) = 1 AND length(v.alt) = 1 ORDER BY v.chrom, v."end" """).fetchall()
    w = flank(matrices(meme, layer.get("p_value", P_VALUE)))
    keyed = [((c, p, r, a), c, p, r, a) for _, c, p, r, a in rows]
    with open(tmp, "w") as f:
        for (c, p, r, a), (changed, n, tfs, delta) in effects(windows(Fasta(str(genome)), keyed, w), meme,
                                                              layer.get("p_value", P_VALUE), layer.get("min_delta", MIN_DELTA)):
            f.write(f"{c}\t{p - 1}\t{p}\t{r}\t{a}\t{str(changed).lower()}\t{n}\t{tfs or ''}\t{'' if delta is None else delta}\n")
    return f"""SELECT * FROM read_csv({lit(tmp)}, delim='\t', header=false, quote='', auto_detect=false, nullstr='',
               columns={{'chrom': 'VARCHAR', 'start': 'BIGINT', 'end': 'BIGINT', 'ref': 'VARCHAR', 'alt': 'VARCHAR',
                         'changed': 'BOOLEAN', 'n': 'INTEGER', 'tfs': 'VARCHAR', 'delta': 'DOUBLE'}})"""


def add_effects(con, location, meme, layer):
    """Fill the motif columns of `snps` for the SNPs in a robust ATAC peak that the precomputed layer doesn't hold
    (not public sites, or other alleles): at most ANNOTATE_MAX, in genome order, in this process. Returns
    {computed, not_checked}."""
    from .fasta import Fasta
    todo = """FROM snps s JOIN pos p USING (idx) WHERE coalesce(s.chromatin, false) AND NOT coalesce(s.motif, false)
              AND length(p.ref) = 1 AND length(p.alt) = 1"""
    total = con.execute(f"SELECT count(*) {todo}").fetchone()[0]
    rows = con.execute(f"SELECT s.idx, p.chrom, p.pos, p.ref, p.alt {todo} ORDER BY p.chrom, p.pos LIMIT {ANNOTATE_MAX}").fetchall()
    if rows:
        p_value, min_delta = layer.get("p_value", P_VALUE), layer.get("min_delta", MIN_DELTA)
        w = flank(matrices(meme, p_value))
        found = list(effects(windows(Fasta(location), rows, w), meme, p_value, min_delta, processes=1))
    else:
        found = []
    if found:
        con.execute("CREATE OR REPLACE TEMP TABLE _motif (idx BIGINT, changed BOOLEAN, n INTEGER, tfs VARCHAR, delta DOUBLE)")
        con.executemany("INSERT INTO _motif VALUES (?, ?, ?, ?, ?)", [(k, *s) for k, s in found])
        con.execute("""UPDATE snps SET motif = true, motif_changed = m.changed, motif_n = m.n, motif_tfs = m.tfs,
                       motif_delta = m.delta FROM _motif m WHERE snps.idx = m.idx""")
        con.execute("DROP TABLE _motif")
    return {"computed": len(found), "not_checked": total - len(found)}
