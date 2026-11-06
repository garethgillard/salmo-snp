"""Converting positions between assemblies (ROADMAP I19): ICSASG_v2 to Ssal_v3.1 for any position, not only rs IDs.

A conversion table holds collinear blocks: chrom, start, end (BED, on the assembly converted from), to_chrom, shift,
strand; a position p inside a block goes to p + shift ('+') or shift - p ('-'). snpdata build makes one from EVA's
rs IDs placed on both assemblies (rsid.parquet): runs of consecutive rs IDs (in ICSASG_v2 order) whose two
positions keep the same offset are collinear, so every position between the first and the last of a run converts
exactly; positions between runs (where an insertion or deletion changed the offset) don't. An alignment of two
assemblies (read_paf: prep/align_assemblies.py, fSalSal1; or read_chain, a UCSC chain) gives the same table, both ways."""
from __future__ import annotations

import gzip
import re

from .formats import lit

# ICSASG_v2 chromosomes 1-29 by their GenBank (CM003279.1-CM003307.1) and RefSeq (NC_027300.1-NC_027328.1) names
V2_ALIASES = {**{f"CM00{3279 + i}.1": str(i + 1) for i in range(29)}, **{f"NC_0{27300 + i}.1": str(i + 1) for i in range(29)}}


def chrom_sql(expr, aliases=None):
    """SQL for a chromosome name of the assembly converted from as '1'-'29': an accession of `aliases` ({name:
    chrom}, with or without its version), else 25, 025, chr25 or ssa25; NULL for anything else."""
    e = f"lower(trim({expr}))"
    pairs = {}
    for name, chrom in (aliases or {}).items():
        pairs[name.lower()] = pairs[name.lower().split(".")[0]] = str(chrom)
    number = f"try_cast(regexp_replace({e}, '^(chr|ssa)', '') AS INTEGER)"
    numbered = f"CASE WHEN ({number}) BETWEEN 1 AND 29 THEN ({number})::VARCHAR END"
    if not pairs:
        return f"({numbered})"
    named = "".join(f" WHEN {lit(k)} THEN {lit(v)}" for k, v in sorted(pairs.items()))
    return f"(CASE {e}{named} ELSE {numbered} END)"


def blocks_from_rsid_sql(rsid):
    """SQL for the conversion table from EVA's pairs (rsid.parquet: chrom, pos on Ssal_v3.1; v2_chrom, v2_pos): ICSASG_v2
    positions with one Ssal_v3.1 position only; consecutive pairs on the same two chromosomes with the same offset
    (pos - v2_pos: '+') or sum (pos + v2_pos: '-') are linked, and a run of links is a block from its first pair to its
    last (a change of strand starts a new run). A pair linked to neither neighbour is a block of its own (1 bp; its
    strand from the alleles)."""
    return f"""
        WITH p AS (SELECT v2_chrom, v2_pos, any_value(chrom) AS chrom, any_value(pos) AS pos,
                          bool_or(v2_ref <> ref AND translate(v2_ref, 'ACGT', 'TGCA') = ref) AS flipped
                   FROM read_parquet({lit(rsid)}) WHERE v2_pos IS NOT NULL AND chrom IS NOT NULL
                   GROUP BY 1, 2 HAVING count(DISTINCT (chrom, pos)) = 1),
        l AS (SELECT *, CASE WHEN lag(chrom) OVER w = chrom AND lag(pos - v2_pos) OVER w = pos - v2_pos THEN '+'
                             WHEN lag(chrom) OVER w = chrom AND lag(pos + v2_pos) OVER w = pos + v2_pos THEN '-' END AS link
              FROM p WINDOW w AS (PARTITION BY v2_chrom ORDER BY v2_pos)),
        n AS (SELECT *, lead(link) OVER w AS next_link, lag(link) OVER w AS prev_link FROM l
              WINDOW w AS (PARTITION BY v2_chrom ORDER BY v2_pos)),
        r AS (SELECT *, coalesce(link, next_link, CASE WHEN flipped THEN '-' ELSE '+' END) AS strand,  -- a new run where
                     sum(CASE WHEN link IS NULL OR link <> coalesce(prev_link, link) THEN 1 ELSE 0 END)  -- the link breaks
                         OVER (PARTITION BY v2_chrom ORDER BY v2_pos) AS run  -- or changes strand
              FROM n)
        SELECT v2_chrom AS chrom, min(v2_pos) - 1 AS start, max(v2_pos) AS "end", any_value(chrom) AS to_chrom,
               CASE WHEN any_value(strand) = '+' THEN any_value(pos - v2_pos) ELSE any_value(pos + v2_pos) END AS shift,
               any_value(strand) AS strand, count(*) AS pairs
        FROM r GROUP BY v2_chrom, run ORDER BY chrom, start"""


def read_chain(path):
    """(chrom, start, end, to_chrom, shift, strand) blocks of a UCSC chain file (gzipped or not): the aligned blocks
    of each chain, from its target (the assembly converted from) to its query; chromosome names as in the file."""
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rt") as f:
        for line in f:
            fields = line.split()
            if not fields:
                continue
            if fields[0] == "chain":
                t_name, t_pos, q_name, q_size, q_strand, q_pos = fields[2], int(fields[5]), fields[7], int(fields[8]), fields[9], int(fields[10])
                continue
            size = int(fields[0])
            if q_strand == "+":  # p (1-based) -> q_pos + (p - t_pos)
                yield t_name, t_pos, t_pos + size, q_name, q_pos - t_pos, "+"
            else:  # on the query's reverse strand: forward 1-based q_size - (q_pos + p - 1 - t_pos)
                yield t_name, t_pos, t_pos + size, q_name, q_size - q_pos + t_pos + 1, "-"
            if len(fields) == 3:
                t_pos, q_pos = t_pos + size + int(fields[1]), q_pos + size + int(fields[2])


def read_paf(path, reverse=False, min_mapq=0):
    """(chrom, start, end, to_chrom, shift, strand) blocks of a PAF with CIGARs (cg:Z; prep/align_assemblies.py), from
    its query to its target, or from target to query with `reverse`: one block per run of aligned bases (M, =, X),
    insertions and deletions between them. Only primary alignments (tp:A:P, or no tp tag) with mapq >= min_mapq."""
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rt") as f:
        for line in f:
            x = line.rstrip("\n").split("\t")
            tags = dict(t.split(":", 2)[0::2] for t in x[12:] if t.count(":") >= 2)
            if len(x) < 12 or int(x[11]) < min_mapq or tags.get("tp", "P") != "P" or "cg" not in tags:
                continue
            qname, qs, qe, strand, tname, ts = x[0], int(x[2]), int(x[3]), x[4], x[5], int(x[7])
            q, t = qs if strand == "+" else qe, ts  # the query is walked backwards on '-'
            for n, op in re.findall(r"(\d+)([MIDNSHP=X])", tags["cg"]):
                n = int(n)
                if op in "M=X":
                    if strand == "+":
                        b = (qname, q, q + n, tname, t - q, "+") if not reverse else (tname, t, t + n, qname, q - t, "+")
                        q += n
                    else:  # query forward 1-based p -> target t + q + 1 - p, and back the same way
                        b = (qname, q - n, q, tname, t + q + 1, "-") if not reverse else (tname, t, t + n, qname, t + q + 1, "-")
                        q -= n
                    t += n
                    yield b
                elif op == "I":
                    q += n if strand == "+" else -n
                elif op in "DN":
                    t += n


def lift(con, blocks, table="raw", label="ICSASG_v2", aliases=None):
    """Rewrite `table`'s chrom and pos from the assembly `label` to the release's through the conversion table
    `blocks` (parquet), chromosome names through `aliases` (ICSASG_v2: V2_ALIASES), alleles complemented on '-' blocks;
    adds _lift ('<label> <chrom>:<pos>' as given, or 'liftover_unmapped'). Returns {converted, complemented, unmapped}."""
    aliases = V2_ALIASES if aliases is None and label == "ICSASG_v2" else aliases
    cols = [r[0] for r in con.execute(f"DESCRIBE {table}").fetchall()]
    flip = lambda c: f"CASE WHEN b.strand = '-' THEN translate(upper(r.{c}), 'ACGT', 'TGCA') ELSE r.{c} END AS {c}"  # noqa: E731
    replace = ", ".join(["b.to_chrom AS chrom",
                         "(CASE WHEN b.strand = '+' THEN r._v2pos + b.shift ELSE b.shift - r._v2pos END)::VARCHAR AS pos"]
                        + [flip(c) for c in ("ref", "alt") if c in cols])
    con.execute(f"CREATE OR REPLACE TEMP TABLE _blocks AS SELECT * FROM read_parquet({lit(blocks)})")  # tables, not a CTE
    con.execute(f"""CREATE OR REPLACE TEMP TABLE _v2 AS SELECT *, {chrom_sql('chrom', aliases)} AS _v2chrom,  -- over a file: a slow plan
                        CASE WHEN regexp_full_match(trim(pos), '[0-9]+') THEN try_cast(trim(pos) AS BIGINT) END AS _v2pos FROM {table}""")
    con.execute(f"""CREATE OR REPLACE TABLE {table} AS
        WITH j AS (SELECT r.*, b.to_chrom, b.shift, b.strand, b."end" AS _bend FROM _v2 r
                   ASOF LEFT JOIN _blocks b ON b.chrom = r._v2chrom AND r._v2pos > b.start)
        SELECT r.* EXCLUDE (_v2chrom, _v2pos, to_chrom, shift, strand, _bend) REPLACE ({replace.replace('b.', 'r.')}),
               CASE WHEN r._v2pos <= r._bend THEN {lit(label + ' ')} || trim(r.chrom) || ':' || r._v2pos
                    ELSE 'liftover_unmapped' END AS _lift, coalesce(r.strand = '-' AND r._v2pos <= r._bend, false) AS _lift_flip
        FROM j r ORDER BY r.idx""")
    con.execute("DROP TABLE _blocks; DROP TABLE _v2")
    con.execute(f"""UPDATE {table} SET chrom = NULL, pos = NULL WHERE _lift = 'liftover_unmapped'""")
    out = con.execute(f"""SELECT count(*) FILTER (WHERE _lift <> 'liftover_unmapped'), count(*) FILTER (WHERE _lift_flip),
                                 count(*) FILTER (WHERE _lift = 'liftover_unmapped') FROM {table}""").fetchall()[0]
    con.execute(f"ALTER TABLE {table} DROP COLUMN _lift_flip")
    return dict(zip(("converted", "complemented", "unmapped"), out))


def positions(con, rel, blocks, label, out="_lifted"):
    """View `out`: `rel` (with chrom, pos) plus <label>_chrom and <label>_pos, its positions on another assembly through
    the conversion table `blocks` (liftover_to_<name>.parquet), NULL outside it."""
    c = re.sub(r"[^A-Za-z0-9_]", "_", label)
    con.execute(f"CREATE OR REPLACE TEMP TABLE {out}_blocks AS SELECT * FROM read_parquet({lit(blocks)})")  # one per view
    con.execute(f"""CREATE OR REPLACE TEMP VIEW {out} AS SELECT r.*,
                        CASE WHEN r.pos <= b."end" THEN b.to_chrom END AS "{c}_chrom",
                        CASE WHEN r.pos <= b."end" THEN CASE WHEN b.strand = '+' THEN r.pos + b.shift ELSE b.shift - r.pos END END
                            AS "{c}_pos"
                    FROM {rel} r ASOF LEFT JOIN {out}_blocks b ON b.chrom = r.chrom AND r.pos > b.start""")
    return out
