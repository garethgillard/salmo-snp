"""Placing SNPs by their flank sequence (ROADMAP I18): a chip manifest's probe or flank sequence (Axiom 'Flank',
Illumina 'SourceSeq' or 'TopGenomicSeq': LEFT[A/B]RIGHT) puts its SNPs on Ssal_v3.1 whatever assembly its positions
are on, by an exact match of the K bases either side of the SNP against the same bases at every known variant site
(the release's flank_keys.parquet, which snpdata build makes from the genome). A key is the 2K bases packed two bits
each (K = 16: one 64-bit number), on the strand that sorts first, so a flank given on either strand finds its site.
Keys found at more than one site are left out of the release, so a placement is unique among the known sites. Each
placement is then checked against the genome: every A, C, G or T of the manifest's whole flank (Axiom gives 35 bases a
side) must be the genome's base there, so a key shared with a duplicated region (e.g. the Ss4R duplicate) whose outer
flank differs places nothing. No mismatch is tolerated (DECISIONS #34: G's to decide)."""
from __future__ import annotations

import csv

from .assay import REMOTE_MAX
from .fasta import Fasta
from .formats import lit

K = 16
CODE = {"A": 0, "C": 1, "G": 2, "T": 3}
COMPLEMENT = str.maketrans("ACGT", "TGCA")
FLANK_COLUMNS = ("in_flank", "in_sourceseq", "in_topgenomicseq", "in_flank_seq", "in_probe_seq")  # first one present
RS_COLUMNS = ("in_dbsnp_rs_id", "in_dbsnp_rsid", "in_dbsnp", "in_rs_id", "in_rsid")  # rs IDs beside a probe set id (Axiom)
MISSES = {  # why a row's flank placed nothing: the reject reasons, in plain words after a count (describe)
    "no_flank": "with no flank sequence",
    "flank_too_short": f"with fewer than {K} A, C, G or T bases next to the SNP on a side",
    "flank_unknown_site": "not at a known variant site",
    "flank_genome_mismatch": "whose full flank differs from the genome at the site it matches (perhaps a duplicated "
                             "region, such as the Ss4R duplicate)",
}


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


def agrees(fasta, flank, chrom, pos, flip):
    """Whether every A, C, G or T of a manifest flank 'LEFT[A/B]RIGHT' (all of it, however long) is the genome's base
    around chrom:pos (the SNP, 1-based), the flank turned to the genome's strand when `flip`. Other letters in the
    flank (IUPAC codes, N) and N in the genome, or bases past the chromosome's ends, are skipped."""
    left, right = (s.upper() for s in split(flank))
    if flip:
        left, right = right.translate(COMPLEMENT)[::-1], left.translate(COMPLEMENT)[::-1]
    start = pos - 1 - len(left)
    seq = ("N" * max(0, -start) + fasta.fetch(chrom, start, pos + len(right)).upper()).ljust(len(left) + 1 + len(right), "N")
    return all(a == b for a, b in zip(left + right, seq[:len(left)] + seq[len(left) + 1:]) if a in CODE and b in CODE)


def place(con, flank_keys, table="raw", genome=None, k=K):
    """Rewrite `table`'s chrom and pos from its flank column (FLANK_COLUMNS) where the flank's key is a known site in
    flank_keys.parquet and, with `genome` (a snpscore.fasta location), the whole flank is the genome's there (agrees);
    ref and alt are complemented when the flank is on the genome's other strand. Rows it doesn't place get chrom and
    pos NULL. Adds _flank: 'flank', or why not (a MISSES key). Returns {placed, complemented, missed: {reason: rows},
    genome: 'checked' or why not, column}, or None without a flank column."""
    cols = [r[0] for r in con.execute(f"DESCRIBE {table}").fetchall()]
    column = next((c for want in FLANK_COLUMNS for c in cols if c.lower() == want), None)
    if column is None:
        return None
    rows = []
    for (flank,) in con.execute(f'SELECT DISTINCT "{column}" FROM {table} WHERE "{column}" IS NOT NULL').fetchall():
        pair = split(flank)
        got = key(*pair, k) if pair else None
        rows.append((flank, *(got or (None, None)), None if got else "flank_too_short" if pair else "no_flank"))
    con.execute("CREATE OR REPLACE TEMP TABLE _fk (flank VARCHAR, key UBIGINT, canonical BOOLEAN, miss VARCHAR)")
    if rows:
        con.executemany("INSERT INTO _fk VALUES (?, ?, ?, ?)", rows)
    con.execute(f"""CREATE OR REPLACE TEMP TABLE _fp AS SELECT f.flank, s.chrom, s.pos, f.canonical <> s.canonical AS flip
                    FROM _fk f JOIN read_parquet({lit(flank_keys)}) s USING (key)""")
    checked = check_genome(con, genome)
    flip = lambda c: f"CASE WHEN p.flip THEN translate(upper(r.{c}), 'ACGT', 'TGCA') ELSE r.{c} END AS {c}"  # noqa: E731
    alleles = [c for c in ("ref", "alt") if c in cols]
    replace = ", ".join(["p.chrom AS chrom", "p.pos::VARCHAR AS pos"] + [flip(c) for c in alleles])
    con.execute(f"""CREATE OR REPLACE TABLE {table} AS
        SELECT r.* REPLACE ({replace}),
               CASE WHEN p.chrom IS NOT NULL THEN 'flank' WHEN f.flank IS NULL THEN 'no_flank'
                    ELSE coalesce(f.miss, 'flank_unknown_site') END AS _flank, coalesce(p.flip, false) AS _flank_flip
        FROM {table} r LEFT JOIN _fk f ON f.flank = r."{column}" LEFT JOIN _fp p ON p.flank = r."{column}" ORDER BY r.idx""")
    placed, flipped = con.execute(f"SELECT count(*) FILTER (WHERE _flank = 'flank'), count(*) FILTER (WHERE _flank_flip) "
                                  f"FROM {table}").fetchall()[0]
    missed = dict(con.execute(f"SELECT _flank, count(*) FROM {table} WHERE _flank <> 'flank' GROUP BY 1").fetchall())
    con.execute(f"ALTER TABLE {table} DROP COLUMN _flank_flip")
    con.execute("DROP TABLE _fk; DROP TABLE _fp")
    return {"placed": placed, "complemented": flipped, "missed": {m: missed[m] for m in MISSES if m in missed},
            "genome": checked, "column": column}


def check_genome(con, genome):
    """Drop from _fp (flank, chrom, pos, flip) the placements whose flank the genome contradicts (agrees), marking them
    flank_genome_mismatch in _fk. Returns 'checked', or why the genome was not read."""
    if not genome:
        return "no genome for this release"
    rows = con.execute("SELECT flank, chrom, pos, flip FROM _fp ORDER BY chrom, pos").fetchall()
    if str(genome).startswith(("http://", "https://")) and len(rows) > REMOTE_MAX:
        return f"the genome is read remotely, which is too slow for over {REMOTE_MAX:,} markers: `salmo-snp download` fetches it"
    try:
        fasta = Fasta(genome)
        bad = [(f,) for f, chrom, pos, flip in rows if not agrees(fasta, f, chrom, pos, flip)]
    except OSError:
        return "the genome could not be read"
    if bad:
        con.execute("CREATE OR REPLACE TEMP TABLE _bad (flank VARCHAR)")
        con.executemany("INSERT INTO _bad VALUES (?)", bad)
        con.execute("UPDATE _fk SET miss = 'flank_genome_mismatch' WHERE flank IN (SELECT flank FROM _bad)")
        con.execute("DELETE FROM _fp WHERE flank IN (SELECT flank FROM _bad)")
        con.execute("DROP TABLE _bad")
    return "checked"


def describe(block):
    """A validation report's `flank` block (place, plus read_snps' rs ID agreement) in plain words: a list of sentences,
    for the CLI and the chip card."""
    text = f"Placed by flank sequence: {block['placed']:,} marker{'' if block['placed'] == 1 else 's'}"
    if block.get("complemented"):
        text += f" ({block['complemented']:,} given on the other strand)"
    genome = block.get("genome")
    lines = [text + (", each checked against the genome." if genome == "checked" else
                     f"; not checked against the genome ({genome})." if genome else ".")]
    if block.get("missed"):
        lines.append("Not placed: " + "; ".join(f"{v:,} {MISSES.get(m, m)}" for m, v in block["missed"].items()) + ".")
    r = block.get("rsid")
    if r:
        lines.append(f"Against the manifest's rs IDs: {r['same']:,} at the same position, {r['different']:,} at another "
                     f"position (kept at the flank's position for now), {r['flank_only']:,} placed by flank "
                     f"only, {r['rsid_only']:,} by rs ID only.")
    return lines
