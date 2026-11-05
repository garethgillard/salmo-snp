"""Probe uniqueness against the Ss4R duplicate (ROADMAP I10, P6.8): how closely each SNP's flanks match the paired
region of the salmonid whole-genome duplication, where a probe could also hybridise. For a SNP whose nearest gene
has Ss4R ohnologs (the release's ss4r layer), the region scanned is each ohnolog's span, widened by the SNP's
distance to its gene and `margin` (50 kb) either side. Each flank (35 nt, Axiom's probe length) is searched on both
strands, ungapped: seeds of SEED nt find every match with at most len // SEED - 1 mismatches (4 for 35 nt, so
identities from 0.886 up), then each seed hit is extended to the whole flank; weaker matches are not reported (at
that level a 35-mer matches some 200 kb of sequence by chance). Standard library only; the genome is read with snpscore.fasta.

paralog_identity is the best match's identity of the cleaner flank (the side a probe design would pick): 1.0 means
an exact copy on both sides. A SNP with no ohnolog, or no match found, has none. Whether a value is too high is G's
to decide (weights.yaml assay.max_paralog_identity; null: shown, never a warning)."""
from __future__ import annotations

SEED = 7
COMPLEMENT = str.maketrans("ACGTN", "TGCAN")
MAX_REGION = 2_000_000  # bp scanned per ohnolog at most (the gene's span and margins, clipped around its middle)


def revcomp(s):
    return s.translate(COMPLEMENT)[::-1]


def best_match(probe, seq, k=SEED, skip=None):
    """(mismatches, offset, strand) of the best ungapped match of `probe` in `seq` on either strand with at most
    len(probe) // k - 1 mismatches (each such match holds one of the probe's non-overlapping k-nt seeds exactly), or
    None. Bases other than A, C, G and T in the probe (IUPAC codes of public variants, N) match anything. `skip`
    (lo, hi) leaves out matches starting in that range of seq (the SNP's own flank, when the region holds it)."""
    best, n = None, len(probe)
    limit = n // k - 1
    for strand, p in (("+", probe), ("-", revcomp(probe))):
        tried = set()
        for s in range(0, n - k + 1, k):
            seed = p[s:s + k]
            if any(c not in "ACGT" for c in seed):
                continue
            hit = seq.find(seed)
            while hit >= 0:
                start = hit - s
                if 0 <= start <= len(seq) - n and start not in tried and not (skip and skip[0] <= start <= skip[1]):
                    tried.add(start)
                    mm = sum(a != b for a, b in zip(p, seq[start:start + n]) if a in "ACGT")
                    if mm <= limit and (best is None or mm < best[0]):
                        best = (mm, start, strand)
                        if mm == 0:
                            return best
                hit = seq.find(seed, hit + 1)
    return best


def flanks(assay_flank, flank=35):
    """(left, right) of an assay_flank string 'LEFT[REF/ALT]RIGHT', uppercased, each the `flank` bases next to the SNP."""
    if not assay_flank or "[" not in assay_flank or "]" not in assay_flank:
        return None
    left, rest = assay_flank.split("[", 1)
    right = rest.split("]", 1)[1]
    return left.upper()[-flank:], right.upper()[:flank]


def scan(snps, genes, fasta, flank=35, margin=50_000):
    """snps: [{key, chrom, pos, ohnologs: [gene ids], gene_distance, assay_flank (or None: read from the genome)}];
    genes: {gene_id: (chrom, start, end)}; fasta: an object with fetch(chrom, start, end) (snpscore.fasta.Fasta).
    Returns {key: {paralog_identity, paralog_left, paralog_right, paralog_at, paralog_gene}} for the SNPs that have an
    ohnolog region; a flank's identity is None where it has no match with at most len // SEED - 1 mismatches (no close
    copy), and paralog_identity is None when either flank has none (that side is clean)."""
    regions = {}  # (chrom, start, end) -> sequence: ohnologs are shared by neighbouring SNPs
    out = {}
    for snp in snps:
        pair = flanks(snp.get("assay_flank"), flank)
        if pair is None:
            try:
                seq = fasta.fetch(snp["chrom"], snp["pos"] - 1 - flank, snp["pos"] + flank).upper()
            except KeyError:
                continue
            if len(seq) < 2 * flank + 1:
                continue
            pair = seq[:flank], seq[flank + 1:]
        dist = abs(int(snp.get("gene_distance") or 0))
        best = {}
        for gene in snp.get("ohnologs") or []:
            if gene not in genes:
                continue
            chrom, gs, ge = genes[gene]
            lo, hi = gs - margin - dist, ge + margin + dist
            if hi - lo > MAX_REGION:
                mid = (gs + ge) // 2
                lo, hi = mid - MAX_REGION // 2, mid + MAX_REGION // 2
            lo = max(0, lo)
            key = (chrom, lo, hi)
            if key not in regions:
                if len(regions) > 64:
                    regions.clear()
                try:
                    regions[key] = fasta.fetch(chrom, lo, hi).upper()
                except KeyError:  # a chromosome the genome lacks
                    regions[key] = ""
            seq = regions[key]
            own = (snp["pos"] - lo - 2 * flank - 10, snp["pos"] - lo + 10) if chrom == snp["chrom"] else None
            for side, probe in zip(("left", "right"), pair):
                m = best_match(probe, seq, skip=own)
                if m and (side not in best or m[0] < best[side][0]):
                    best[side] = (m[0], f"{chrom}:{lo + m[1] + 1:,}{m[2]}", gene)
        if not any(g in genes for g in snp.get("ohnologs") or []):
            continue
        ident = {side: None if side not in best else round(1 - best[side][0] / len(p), 3) for side, p in zip(("left", "right"), pair)}
        known = [v for v in ident.values() if v is not None]
        clean = min(known) if len(known) == 2 else None  # a side with no close match is the clean one
        where = max(best.values(), key=lambda b: -b[0]) if best else (None, None, None)
        out[snp["key"]] = {"paralog_identity": clean, "paralog_left": ident["left"], "paralog_right": ident["right"],
                           "paralog_at": where[1], "paralog_gene": where[2]}
    return out
