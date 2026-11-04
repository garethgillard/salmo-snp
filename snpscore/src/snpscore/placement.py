"""Placing SNPs by their flank sequence (ROADMAP I18): a chip manifest's probe or flank sequence (Axiom 'Flank',
Illumina 'SourceSeq' or 'TopGenomicSeq': LEFT[A/B]RIGHT) puts its SNPs on Ssal_v3.1 whatever assembly its positions
are on, by an exact match of the K bases either side of the SNP against the same bases at every known variant site
(the release's flank_keys.parquet, which snpdata build makes from the genome). A key is the 2K bases packed two bits
each (K = 16: one 64-bit number), on the strand that sorts first, so a flank given on either strand finds its site.
Keys found at more than one site are left out of the release, so a placement is unique among the known sites."""
from __future__ import annotations

import csv

from .formats import lit

K = 16
CODE = {"A": 0, "C": 1, "G": 2, "T": 3}
COMPLEMENT = str.maketrans("ACGT", "TGCA")
FLANK_COLUMNS = ("in_flank", "in_sourceseq", "in_topgenomicseq", "in_flank_seq", "in_probe_seq")  # first one present


def pack(seq):
    v = 0
    for c in seq:
        v = v * 4 + CODE[c]
    return v


def key(left, right, k=K):
    """(key, canonical): the packed 2k bases around a SNP (the k before it and the k after it) on the strand that
    sorts first, and whether that is the strand given; None unless both sides have k A, C, G or T bases."""
    s = (left[-k:] + right[:k]).upper()
    if len(s) != 2 * k or any(c not in CODE for c in s):
        return None
    r = s.translate(COMPLEMENT)[::-1]
    return (pack(s), True) if s <= r else (pack(r), False)


def split(flank):
    """(left, right) of a manifest sequence 'LEFT[A/B]RIGHT', or None."""
    if not flank or "[" not in flank or "]" not in flank:
        return None
    left, rest = flank.split("[", 1)
    return left.strip(), rest.split("]", 1)[1].strip()


def site_keys(sites, fasta, out, k=K):
    """Write key, chrom, pos, canonical (TSV) for each (chrom, pos) of `sites` (sorted by chromosome; pos 1-based)
    from `fasta` (snpscore.fasta.Fasta), each chromosome read once. Returns the rows written."""
    n, here, seq = 0, None, ""
    with open(out, "w", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        for chrom, pos in sites:
            if chrom != here:
                here = chrom
                seq = fasta.fetch(chrom, 0, fasta.index[chrom][0]) if chrom in fasta.index else ""
            if pos - 1 - k < 0 or pos + k > len(seq):
                continue
            got = key(seq[pos - 1 - k:pos - 1], seq[pos:pos + k], k)
            if got:
                w.writerow([got[0], chrom, pos, "true" if got[1] else "false"])
                n += 1
    return n


def place(con, flank_keys, table="raw", k=K):
    """Rewrite `table`'s chrom and pos from its flank column (FLANK_COLUMNS) where the flank's key is a known site in
    flank_keys.parquet, with ref and alt complemented when the flank is on the genome's other strand; adds _flank
    ('flank' or 'flank_not_found'). Returns {placed, complemented, not_found, column}, or None without a flank column."""
    cols = [r[0] for r in con.execute(f"DESCRIBE {table}").fetchall()]
    column = next((c for want in FLANK_COLUMNS for c in cols if c.lower() == want), None)
    if column is None:
        return None
    rows = []
    for (flank,) in con.execute(f'SELECT DISTINCT "{column}" FROM {table} WHERE "{column}" IS NOT NULL').fetchall():
        pair = split(flank)
        got = key(*pair, k) if pair else None
        if got:
            rows.append((flank, got[0], got[1]))
    con.execute("CREATE OR REPLACE TEMP TABLE _fk (flank VARCHAR, key UBIGINT, canonical BOOLEAN)")
    if rows:
        con.executemany("INSERT INTO _fk VALUES (?, ?, ?)", rows)
    flip = lambda c: f"CASE WHEN p.flip THEN translate(upper(r.{c}), 'ACGT', 'TGCA') ELSE r.{c} END AS {c}"  # noqa: E731
    alleles = [c for c in ("ref", "alt") if c in cols]
    replace = ", ".join(["p.chrom AS chrom", "p.pos::VARCHAR AS pos"] + [flip(c) for c in alleles])
    con.execute(f"""CREATE OR REPLACE TABLE {table} AS
        WITH p AS (SELECT f.flank, s.chrom, s.pos, f.canonical <> s.canonical AS flip
                   FROM _fk f JOIN read_parquet({lit(flank_keys)}) s USING (key))
        SELECT r.* REPLACE ({replace}), CASE WHEN p.chrom IS NULL THEN 'flank_not_found' ELSE 'flank' END AS _flank,
               coalesce(p.flip, false) AS _flank_flip
        FROM {table} r LEFT JOIN p ON p.flank = r."{column}" ORDER BY r.idx""")
    placed, flipped, missing = con.execute(f"""SELECT count(*) FILTER (WHERE _flank = 'flank'), count(*) FILTER (WHERE _flank_flip),
                                                  count(*) FILTER (WHERE _flank = 'flank_not_found') FROM {table}""").fetchall()[0]
    con.execute(f"ALTER TABLE {table} DROP COLUMN _flank_flip")
    con.execute("DROP TABLE _fk")
    return {"placed": placed, "complemented": flipped, "not_found": missing, "column": column}
