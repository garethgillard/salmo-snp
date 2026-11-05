"""Converting positions between assemblies (ROADMAP I19): ICSASG_v2 to Ssal_v3.1 for any position, not only rs IDs.

A conversion table holds collinear blocks: chrom, start, end (BED, on the assembly converted from), to_chrom, shift,
strand; a position p inside a block goes to p + shift ('+') or shift - p ('-'). snpdata build makes one from EVA's
rs IDs placed on both assemblies (rsid.parquet): runs of consecutive rs IDs (in ICSASG_v2 order) whose two
positions keep the same offset are collinear, so every position between the first and the last of a run converts
exactly; positions between runs (where an insertion or deletion changed the offset) don't. A chain file from a
whole-genome alignment (read_chain) gives the same table, for the new assembly later."""
from __future__ import annotations

import gzip
import re

from .formats import lit

V2_GENBANK = re.compile(r"^CM00(\d{4})(\.\d+)?$", re.I)  # ICSASG_v2 chromosomes 1-29: CM003279.1-CM003307.1
V2_REFSEQ = re.compile(r"^NC_0(\d{5})(\.\d+)?$", re.I)  # and NC_027300.1-NC_027328.1


def v2_chrom_sql(expr):
    """SQL for an ICSASG_v2 chromosome name as '1'-'29' (25, chr25, ssa25, CM003303.1, NC_027324.1), else NULL."""
    e = f"lower(trim({expr}))"
    number = f"""CASE WHEN regexp_full_match({e}, 'cm00[0-9]{{4}}(\\.[0-9]+)?') THEN try_cast(substr({e}, 5, 4) AS INTEGER) - 3278
                      WHEN regexp_full_match({e}, 'nc_0[0-9]{{5}}(\\.[0-9]+)?') THEN try_cast(substr({e}, 5, 5) AS INTEGER) - 27299
                      ELSE try_cast(regexp_replace({e}, '^(chr|ssa)', '') AS INTEGER) END"""
    return f"CASE WHEN ({number}) BETWEEN 1 AND 29 THEN ({number})::VARCHAR END"


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


def lift(con, blocks, table="raw"):
    """Rewrite `table`'s chrom and pos from ICSASG_v2 to Ssal_v3.1 through the conversion table `blocks` (parquet),
    alleles complemented on '-' blocks; adds _lift ('ICSASG_v2 <chrom>:<pos>' as given, or 'liftover_unmapped').
    Returns {converted, complemented, unmapped}."""
    cols = [r[0] for r in con.execute(f"DESCRIBE {table}").fetchall()]
    flip = lambda c: f"CASE WHEN b.strand = '-' THEN translate(upper(r.{c}), 'ACGT', 'TGCA') ELSE r.{c} END AS {c}"  # noqa: E731
    replace = ", ".join(["b.to_chrom AS chrom",
                         "(CASE WHEN b.strand = '+' THEN r._v2pos + b.shift ELSE b.shift - r._v2pos END)::VARCHAR AS pos"]
                        + [flip(c) for c in ("ref", "alt") if c in cols])
    con.execute(f"CREATE OR REPLACE TEMP TABLE _blocks AS SELECT * FROM read_parquet({lit(blocks)})")  # tables, not a CTE
    con.execute(f"""CREATE OR REPLACE TEMP TABLE _v2 AS SELECT *, {v2_chrom_sql('chrom')} AS _v2chrom,  -- over a file: a slow plan
                        CASE WHEN regexp_full_match(trim(pos), '[0-9]+') THEN try_cast(trim(pos) AS BIGINT) END AS _v2pos FROM {table}""")
    con.execute(f"""CREATE OR REPLACE TABLE {table} AS
        WITH j AS (SELECT r.*, b.to_chrom, b.shift, b.strand, b."end" AS _bend FROM _v2 r
                   ASOF LEFT JOIN _blocks b ON b.chrom = r._v2chrom AND r._v2pos > b.start)
        SELECT r.* EXCLUDE (_v2chrom, _v2pos, to_chrom, shift, strand, _bend) REPLACE ({replace.replace('b.', 'r.')}),
               CASE WHEN r._v2pos <= r._bend THEN 'ICSASG_v2 ' || trim(r.chrom) || ':' || r._v2pos
                    ELSE 'liftover_unmapped' END AS _lift, coalesce(r.strand = '-' AND r._v2pos <= r._bend, false) AS _lift_flip
        FROM j r ORDER BY r.idx""")
    con.execute("DROP TABLE _blocks; DROP TABLE _v2")
    con.execute(f"""UPDATE {table} SET chrom = NULL, pos = NULL WHERE _lift = 'liftover_unmapped'""")
    out = con.execute(f"""SELECT count(*) FILTER (WHERE _lift <> 'liftover_unmapped'), count(*) FILTER (WHERE _lift_flip),
                                 count(*) FILTER (WHERE _lift = 'liftover_unmapped') FROM {table}""").fetchall()[0]
    con.execute(f"ALTER TABLE {table} DROP COLUMN _lift_flip")
    return dict(zip(("converted", "complemented", "unmapped"), out))
