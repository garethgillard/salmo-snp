"""Annotate a SNP list against a release: one row per kept input SNP, in input order, plus a validation report
(<out stem>.validation.json) and the rows that were dropped, with the reason (<out stem>.rejects.tsv)."""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import duckdb

from . import assay, coding, motif
from .fasta import Fasta
from .formats import ACCEPTED, InputError, TooMany, detect, lit, q, source
from .score import load_weights, scored

FLANK = 35  # probe flank either side of the SNP (Axiom); also used for GC and repeat content
REMOTE_SAMPLE = 200  # with a remote genome (HTTP ranges) only this many SNPs get the sequence checks
ASSEMBLY_WARNING = 0.10  # (mismatch + strand_flip) / checked above this: probably ICSASG_v2 coordinates or other strand
WRITE_PART = 250_000  # SNPs per sorted part when writing a long list (write_in_order)
ERRORS = (  # shown instead of DuckDB's own text, which can quote SQL, file paths or input lines
    (duckdb.ConversionException, "A value in the file has the wrong type, e.g. text where a number is expected."),
    (duckdb.OutOfMemoryException, "The file is too large to annotate here. Split it, or run snpscore locally."),
    (duckdb.PermissionException, "The file is in a location that may not be read."),
    (duckdb.InvalidInputException, "The file could not be read as a SNP table: check the delimiter and the header, "
                                   "and that every row has the same number of columns."),
    (duckdb.IOException, "The file could not be read."),
)


def connect(read_dirs=(), write_dir=None, threads=2, memory_limit="2GB"):
    """A DuckDB connection that can only read and write files under read_dirs and write_dir (also its spill
    directory; without write_dir it never spills, so a query over memory_limit fails instead of writing the rows to
    DuckDB's default .tmp in the working directory), has no network or extension loading, and can't change these
    settings."""
    dirs = {str(Path(d).resolve()) for d in [*read_dirs, *([write_dir] if write_dir else [])]}  # DuckDB refuses symlinks
    # DuckDB 1.2.2 refuses files in a listed folder when one of its subfolders is listed too, so list only the outer one
    dirs = [d for d in dirs if not any(d.startswith(other + os.sep) for other in dirs)]
    con = duckdb.connect()
    con.execute("SET allowed_directories = ?", [dirs])  # must come before enable_external_access = false
    spill = ""  # '' = no spilling: allowed_directories does not cover DuckDB's own temp files
    if write_dir:  # spill into the listed folder that holds write_dir: a nested temp_directory blocks its parent's files
        write = str(Path(write_dir).resolve())
        spill = next(d for d in dirs if write == d or write.startswith(d + os.sep))
    con.execute("SET temp_directory = ?", [spill])
    con.execute(f"SET memory_limit = {lit(memory_limit)}")
    con.execute(f"SET threads = {int(threads)}")
    for setting in ("autoinstall_known_extensions", "autoload_known_extensions", "enable_external_access"):
        con.execute(f"SET {setting} = false")
    con.execute("SET lock_configuration = true")
    return con


def user_message(error):
    return next((m for cls, m in ERRORS if isinstance(error, cls)), "The file could not be annotated. " + ACCEPTED)


def read_snps(con, path, known, alias=None, max_snps=None, rsid=None):
    """Load a SNP file into table `snps` (idx = input row, chrom, pos, then the other columns) and the rows that can't
    be used into `rejects` (row, chrom, pos, ..., reason). Chromosome names go through `alias` (alias.parquet);
    `known` lists the release's chromosomes. With `rsid` (rsid.parquet), a row whose id is an rs ID is placed on
    Ssal_v3.1 when it has no position, or moved there when its position is the rs ID's ICSASG_v2 position
    (column position_source; alleles complemented where the two assemblies' strands differ). Returns the counts."""
    layout = detect(path)
    limit = int(max_snps) + 1 if max_snps else None
    con.execute(f"CREATE OR REPLACE TABLE raw AS SELECT row_number() OVER () AS idx, * FROM ({source(path, layout, limit)})")
    rows = con.execute("SELECT count(*) FROM raw").fetchone()[0]
    if max_snps and rows > max_snps:
        raise TooMany(f"The file has more than {max_snps:,} SNPs. Split it, or run snpscore locally.")
    cols = [r[0] for r in con.execute("DESCRIBE raw").fetchall()]
    con.execute("CREATE OR REPLACE TEMP TABLE known AS SELECT unnest(?::VARCHAR[]) AS chrom", [list(known)])
    mapped, join, warning = "trim(r.chrom)", "", "NULL"
    if alias:
        mapped, join = "coalesce(a.chrom, trim(r.chrom))", f"LEFT JOIN read_parquet({lit(alias)}) a ON a.alias = lower(trim(r.chrom))"
        warning = "a.warning" if "warning" in parquet_columns(con, alias) else "NULL"
    is_rs = "regexp_full_match(lower(trim(r.id)), 'rs[0-9]+')" if "id" in cols else "false"
    use_rs = rsid and con.execute(f"SELECT count(*) FROM raw r WHERE {is_rs}").fetchone()[0] > 0
    x = ("x.chrom AS x_chrom, x.pos AS x_pos, x.ref AS x_ref, x.v2_chrom, x.v2_pos, x.v2_ref" if use_rs else
         "NULL::VARCHAR AS x_chrom, NULL::BIGINT AS x_pos, NULL::VARCHAR AS x_ref, NULL::VARCHAR AS v2_chrom, "
         "NULL::BIGINT AS v2_pos, NULL::VARCHAR AS v2_ref")
    if use_rs:
        join += f" LEFT JOIN read_parquet({lit(rsid)}) x ON {is_rs} AND x.rs = try_cast(substr(trim(r.id), 3) AS BIGINT)"
    alleles = "ref" in cols and "alt" in cols
    flip = ", ".join(f"CASE WHEN flip THEN translate(upper({c}), 'ACGT', 'TGCA') ELSE {c} END AS {c}"
                     for c in ("ref", "alt") if c in cols)
    key = "chrom, pos" + (", upper(ref), upper(alt)" if alleles else "")
    con.execute(f"""CREATE OR REPLACE TABLE checked AS
        WITH j AS (SELECT r.idx, nullif({mapped}, '') AS m_chrom, -- whole numbers only: no rounding of 100.5 or 2.9e7
                          CASE WHEN regexp_full_match(trim(r.pos), '[0-9]+') THEN try_cast(trim(r.pos) AS BIGINT) END AS m_pos,
                          {warning} AS alias_warning, {is_rs} AS is_rs, {x},
                          r.chrom AS input_chrom, r.pos AS input_pos, r.* EXCLUDE (idx, chrom, pos) FROM raw r {join}),
        p AS (SELECT * EXCLUDE (x_chrom, x_pos, x_ref, v2_chrom, v2_pos, v2_ref),
                     CASE WHEN x_chrom IS NULL THEN NULL WHEN m_chrom IS NULL OR m_pos IS NULL THEN 'rsid'
                          WHEN m_pos = v2_pos AND NOT (m_chrom = x_chrom AND m_pos = x_pos)
                               AND (m_chrom = v2_chrom OR m_chrom NOT IN (SELECT chrom FROM known))
                               THEN 'ICSASG_v2 ' || trim(input_chrom) || ':' || m_pos END AS position_source,
                     x_chrom, x_pos, coalesce(v2_ref <> x_ref AND translate(v2_ref, 'ACGT', 'TGCA') = x_ref, false) AS v2_flip
              FROM j),
        c AS (SELECT idx, CASE WHEN position_source IS NULL THEN m_chrom ELSE x_chrom END AS chrom,
                     CASE WHEN position_source IS NULL THEN m_pos ELSE x_pos END AS pos,
                     * EXCLUDE (idx, m_chrom, m_pos, x_chrom, x_pos, v2_flip),
                     starts_with(position_source, 'ICSASG_v2') AND v2_flip AS flip FROM p),
        d AS (SELECT * {f"REPLACE ({flip})" if flip else ""} FROM c)
        SELECT *,
               CASE WHEN chrom IS NULL AND is_rs AND position_source IS NULL THEN 'unknown_rsid'
                    WHEN chrom IS NULL THEN 'missing_chrom' WHEN pos IS NULL OR pos < 1 THEN 'bad_pos'
                    WHEN chrom NOT IN (SELECT chrom FROM known) THEN 'unknown_chrom'
                    WHEN row_number() OVER (PARTITION BY {key} ORDER BY idx) > 1 THEN 'duplicate' END AS reason
        FROM d""")
    placed = con.execute("SELECT count(*) FROM checked WHERE position_source IS NOT NULL AND reason IS NULL").fetchone()[0]
    helper = "input_chrom, input_pos, reason, alias_warning, is_rs, flip" + ("" if placed else ", position_source")
    con.execute(f"CREATE OR REPLACE TABLE snps AS SELECT * EXCLUDE ({helper}) FROM checked WHERE reason IS NULL")
    extra = "".join(f", {c}" for c in ("id", "ref", "alt") if c in cols)
    con.execute(f"""CREATE OR REPLACE TABLE rejects AS SELECT idx AS row, input_chrom AS chrom, input_pos AS pos{extra}, reason
                    FROM checked WHERE reason IS NOT NULL""")

    def fetch(sql):
        return con.execute(sql).fetchall()

    kept = fetch("SELECT count(*) FROM snps")[0][0]
    report = {
        "format": layout["format"],
        "rows_read": rows,
        "snps_kept": kept,
        "rejected": dict(fetch("SELECT reason, count(*) FROM rejects GROUP BY 1 ORDER BY 2 DESC, 1")),
        "unknown_chromosomes": [{"name": n[:40], "rows": c} for n, c in fetch(
            "SELECT input_chrom, count(*) FROM checked WHERE reason = 'unknown_chrom' GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 10")],
        "aliases_applied": [{"from": a[:40], "to": b, "rows": c} for a, b, c in fetch(
            """SELECT trim(input_chrom), chrom, count(*) FROM checked WHERE chrom <> trim(input_chrom)
               AND position_source IS NULL GROUP BY 1, 2 ORDER BY 3 DESC, 1 LIMIT 50""")],
        "columns_renamed": {h: n for h, n in zip(layout["header"], layout["names"]) if n and n.startswith("in_")},
        "columns_dropped": layout["dropped"],
    }
    warnings = fetch("""SELECT trim(input_chrom), chrom, count(*), any_value(alias_warning) FROM checked
                        WHERE alias_warning IS NOT NULL GROUP BY 1, 2 ORDER BY 3 DESC, 1""")
    if warnings:
        report["alias_warnings"] = [{"from": a[:40], "to": b, "rows": c, "message": m} for a, b, c, m in warnings]
    if use_rs:
        report["rsid"] = dict(zip(("placed", "moved_from_icsasg_v2", "alleles_complemented", "unknown"), fetch(
            """SELECT count(*) FILTER (WHERE position_source = 'rsid' AND reason IS NULL),
                      count(*) FILTER (WHERE starts_with(position_source, 'ICSASG_v2') AND reason IS NULL),
                      count(*) FILTER (WHERE flip AND reason IS NULL), count(*) FILTER (WHERE reason = 'unknown_rsid')
               FROM checked""")[0]))
    report["duplicates_merged"] = report["rejected"].get("duplicate", 0)
    if alleles:
        report["indels"], report["multiallelic"] = fetch("""SELECT count(*) FILTER (WHERE (length(ref) <> 1 OR length(alt) <> 1)
            AND NOT contains(alt, ',')), count(*) FILTER (WHERE contains(alt, ',')) FROM snps""")[0]
    con.execute("DROP TABLE raw; DROP TABLE checked")  # free their memory for large lists
    return report


def parquet_columns(con, parquet):
    return [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet({lit(parquet)})").fetchall()]


def rsid(release_dir, rs):
    """Where an rs ID ('rs863754587' or 863754587) is, from the release's rsid.parquet (EVA release 9): a dict with
    rs, chrom, pos, ref, alt (Ssal_v3.1) and v2_chrom, v2_pos, v2_ref, v2_alt (ICSASG_v2, None when not placed there
    once), or None when the release doesn't have it."""
    release = Path(release_dir).resolve()
    number = str(rs).strip().lower()
    number = number[2:] if number.startswith("rs") else number
    if not number.isdigit() or not (release / "rsid.parquet").exists():
        return None
    con = connect([release])
    try:
        rel = con.execute(f"SELECT * FROM read_parquet({lit(release / 'rsid.parquet')}) WHERE rs = ?", [int(number)])
        row = rel.fetchone()
        return None if row is None else {**dict(zip([d[0] for d in rel.description], row)), "rs": f"rs{int(number)}"}
    finally:
        con.close()


def no_snps_message(report):
    if report["rejected"].get("unknown_rsid") == report["rows_read"]:
        return ("None of the rs IDs are in this release's EVA release 9 table (or they are placed more than once). "
                "Add chrom and pos columns, or check the IDs.")
    names = ", ".join(f"'{u['name']}' ({u['rows']})" for u in report["unknown_chromosomes"][:3])
    if names:
        return (f"No SNPs are on Ssal_v3.1 chromosomes 1-29 or their aliases (e.g. 25, chr25, ssa25, NC_059466.1). "
                f"Most common chromosome names in the file: {names}.")
    return "No SNPs have a chromosome and a whole-number position. " + ACCEPTED


# Each layer type is one query on the narrow table `pos` (idx, chrom, pos, ref, alt) giving idx plus the layer's columns.

def interval_sql(name, cols, parquet, layer):
    # ASOF picks the last interval starting before pos; it's a hit if it also ends at or after pos. With `interpolate`,
    # each <column> (its value at start) is interpolated linearly towards <column>_next (its value at end).
    hit = 'l."end" >= s.pos'
    if layer.get("interpolate"):
        values = "".join(f""", CASE WHEN {hit} THEN round(l.{q(c)} + (s.pos - l.start) / (l."end" - l.start)
                                       * (l.{q(c + '_next')} - l.{q(c)}), 3) END AS {q(name + '_' + c)}"""
                         for c in cols if not c.endswith("_next"))
    else:
        values = "".join(f", CASE WHEN {hit} THEN l.{q(c)} END AS {q(name + '_' + c)}" for c in cols)
    if layer.get("id"):
        values += f""", CASE WHEN {hit} THEN l.chrom || ':' || l.start || '-' || l."end" END AS {q(name + '_id')}"""
    return f"""SELECT s.idx, coalesce({hit}, false) AS {q(name)}{values}
               FROM pos s ASOF LEFT JOIN read_parquet({lit(parquet)}) l ON s.chrom = l.chrom AND s.pos > l.start"""


def nearest_sql(name, cols, parquet, layer):
    # Three ASOF joins instead of a range join: the nearest feature ending before pos (up), the nearest starting at or
    # after it (down), and a feature containing it (body: of the features in start order, those that end beyond all
    # earlier ones; the first of them ending at or after pos contains it if it starts before pos, and has the lowest
    # start of all features that do). Ties go to the lower start, as features are ranked by distance, start.
    values = "".join(f", g.{q(c)} AS {q(name + '_' + c)}" for c in cols)
    tie = "".join(f", {q(c)}" for c in cols)  # features with the same start and end: lowest values first
    return f"""
        WITH f AS (SELECT * FROM read_parquet({lit(parquet)})),
        body AS (SELECT * EXCLUDE (prev) FROM (
                     SELECT *, max("end") OVER (PARTITION BY chrom ORDER BY start, "end"{tie}
                                                ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS prev FROM f)
                 WHERE prev IS NULL OR "end" > prev),
        up AS (SELECT * FROM f QUALIFY row_number() OVER (PARTITION BY chrom, "end" ORDER BY start{tie}) = 1),
        down AS (SELECT * FROM f QUALIFY row_number() OVER (PARTITION BY chrom, start ORDER BY "end"{tie}) = 1),
        j AS (SELECT s.idx, CASE WHEN b.start < s.pos THEN 0 END AS d0, s.pos - u."end" AS du, d.start + 1 - s.pos AS dd,
                     b AS gb, u AS gu, d AS gd
              FROM pos s ASOF LEFT JOIN body b ON s.chrom = b.chrom AND s.pos <= b."end"
                         ASOF LEFT JOIN up u ON s.chrom = u.chrom AND s.pos > u."end"
                         ASOF LEFT JOIN down d ON s.chrom = d.chrom AND s.pos <= d.start)
        SELECT idx{values}, distance AS {q(name + '_distance')}
        FROM (SELECT idx, coalesce(d0, least(du, dd)) AS distance,
                     CASE WHEN d0 = 0 THEN gb WHEN du <= coalesce(dd, du) THEN gu ELSE gd END AS g FROM j)
        WHERE distance <= {int(layer['max_distance'])}"""


def count_sql(name, cols, parquet, layer):
    # Points in [pos - w, pos + w] other than the SNP's own position. SNPs and points meet in fixed bins (assay.BIN),
    # each SNP in every bin its window touches, so it is an equality join (numbering all 7.6M points cost ~10 s).
    w, b = int(layer["window"]), assay.BIN
    return f"""
        WITH s AS (SELECT idx, chrom, pos, unnest(range((pos - {w}) // {b}, (pos + {w}) // {b} + 1)) AS bin FROM pos),
        l AS (SELECT chrom, "end" AS p, "end" // {b} AS bin FROM read_parquet({lit(parquet)})),
        n AS (SELECT s.idx, count(*) AS n FROM s JOIN l ON s.chrom = l.chrom AND s.bin = l.bin
              WHERE abs(l.p - s.pos) <= {w} AND l.p <> s.pos GROUP BY 1)
        SELECT p.idx, coalesce(n.n, 0) AS {q(name)} FROM pos p LEFT JOIN n USING (idx)"""


def point_sql(name, cols, parquet, layer):
    # Exact position match. With input alleles, <layer>_alleles says how they compare with the layer's ref/alt, and the
    # ALT allele frequencies and count are turned to the input alt when they are swapped. A site with other alleles
    # (a different variant at the same position) is no hit: <layer> is false and every value NULL, alleles 'other'.
    fref, falt = "translate(s.ref, 'ACGT', 'TGCA')", "translate(s.alt, 'ACGT', 'TGCA')"
    match = f"""WHEN s.ref = l.ref AND (s.alt IS NULL OR s.alt = l.alt) THEN 'same'
                WHEN s.ref = l.alt AND (s.alt IS NULL OR s.alt = l.ref) THEN 'swapped'
                WHEN {fref} = l.ref AND (s.alt IS NULL OR {falt} = l.alt) THEN 'strand_flip'
                WHEN {fref} = l.alt AND (s.alt IS NULL OR {falt} = l.ref) THEN 'strand_flip_swapped'"""
    def swapped(c):  # an ALT allele frequency (af, <population>_af) or count (ac, with an) in the input's alt allele
        return (f"round(1 - {q(c)}, 6)" if c == "af" or c.endswith("_af") else
                f"{q('an')} - {q(c)}" if c == "ac" and "an" in cols else None)
    values = "".join(", CASE WHEN m = 'other' THEN NULL"
                     + (f" WHEN m IN ('swapped', 'strand_flip_swapped') THEN {swapped(c)}" if swapped(c) else "")
                     + f" ELSE {q(c)} END AS {q(name + '_' + c)}" for c in cols if c not in ("ref", "alt"))
    return f"""
        SELECT idx, found AND m IS DISTINCT FROM 'other' AS {q(name)}{values}, m AS {q(name + '_alleles')} FROM (
            SELECT s.idx, l."end" IS NOT NULL AS found, l.*,
                   CASE WHEN l."end" IS NULL OR s.ref IS NULL THEN NULL {match} ELSE 'other' END AS m
            FROM pos s LEFT JOIN read_parquet({lit(parquet)}) l ON s.chrom = l.chrom AND s.pos = l."end"
            QUALIFY row_number() OVER (PARTITION BY s.idx ORDER BY m = 'same' DESC, m = 'swapped' DESC,
                                       m = 'strand_flip' DESC, m = 'strand_flip_swapped' DESC, l.ref, l.alt) = 1)"""


def known_sql(catalog, window):
    # Nearest catalogue SNP within `window` bp. At its exact position, the effect allele in the input's alleles: on
    # the other strand when only its complement is one of them; the note says which input allele it is.
    tr = "translate(e, 'ACGT', 'TGCA')"
    return f"""
        WITH k AS (SELECT chrom, try_cast(pos AS BIGINT) AS pos, id, nullif(upper(trim(effect_allele)), '') AS e
                   FROM read_csv({lit(catalog)}, delim='\t', header=true, all_varchar=true, quote='')),
        n AS (SELECT s.idx, s.ref, s.alt, k.id, abs(k.pos - s.pos) AS dist, CASE WHEN k.pos = s.pos THEN k.e END AS e
              FROM pos s JOIN k ON s.chrom = k.chrom AND k.pos BETWEEN s.pos - {int(window)} AND s.pos + {int(window)}
              QUALIFY row_number() OVER (PARTITION BY s.idx ORDER BY dist, k.id) = 1)
        SELECT idx, id AS known_locus, dist AS known_locus_dist,
               CASE WHEN ref IS NOT NULL AND e NOT IN (ref, coalesce(alt, '')) AND {tr} IN (ref, alt) THEN {tr} ELSE e END
                   AS known_effect_allele,
               CASE WHEN e IS NULL OR ref IS NULL THEN NULL WHEN e = alt THEN 'alt' WHEN e = ref THEN 'ref'
                    WHEN {tr} = alt THEN 'alt, other strand' WHEN {tr} = ref THEN 'ref, other strand'
                    ELSE 'not one of the input alleles' END AS known_effect_note
        FROM n"""


def gene_sql(name, cols, parquet, gene_table):
    # Keyed by gene_id: values for the SNP's nearest gene.
    values = "".join(f", l.{q(c)} AS {q(name + '_' + c)}" for c in cols)
    return f"SELECT g.idx{values} FROM {gene_table} g LEFT JOIN read_parquet({lit(parquet)}) l ON g.gene_id = l.gene_id"


LAYER_SQL = {"interval": interval_sql, "nearest": nearest_sql, "count": count_sql, "point": point_sql}


def genome_location(manifest):
    """$SNPSCORE_GENOME (a server's own copy of the release's genome) if set, else the release's genome file in
    $SNPSCORE_GENOME_DIR (salmo-snp's data folder, which may hold the genomes of several releases) when it is there,
    else the local path if the release's build machine had it and it is still there, else its URL (or None)."""
    genome = manifest.get("genome")
    if not genome:
        return None
    if os.environ.get("SNPSCORE_GENOME"):
        return os.environ["SNPSCORE_GENOME"]
    name = genome.get("file") or (genome.get("url") or "").rsplit("/", 1)[-1]
    here = Path(os.environ["SNPSCORE_GENOME_DIR"]) / name if os.environ.get("SNPSCORE_GENOME_DIR") and name else None
    if here and all(Path(f"{here}{ext}").exists() for ext in ("", ".fai", ".gzi")):
        return str(here)
    return genome["path"] if genome.get("path") and Path(genome["path"]).exists() else genome["url"]


def add_sequence_checks(con, location, write_dir, weights=None, public_af=None):
    """genome_base, ref_check (ok / swapped / strand_flip / mismatch / not_snp / not_checked), flank_gc and
    flank_repeat (soft-masked share) of the FLANK bases either side, then the assay columns (assay.py). Python only
    reads each SNP's window, in genome order so blocks are decompressed once; the rest is SQL. With a remote genome,
    lists of up to assay.REMOTE_MAX SNPs are read whole; longer ones get the reference check on REMOTE_SAMPLE SNPs
    and no assay check (not_checked)."""
    fasta, rules = Fasta(location), assay.rules(weights)
    remote = location.startswith("http")
    full = not remote or con.execute("SELECT count(*) FROM pos").fetchone()[0] <= assay.REMOTE_MAX
    rows = "pos" if full else f"(SELECT * FROM pos ORDER BY hash(idx) LIMIT {REMOTE_SAMPLE})"
    flank = int(rules["flank"])
    width = max(flank, FLANK)
    tmp = Path(write_dir) / f".sequence-{uuid.uuid4().hex}.tsv"
    try:
        windows = assay.iter_flanks(con, fasta, rows, width, public_af if full else None)
        with open(tmp, "w") as out:  # each window is written as it is read: nothing is kept per SNP in Python
            for idx, left, base, right, li, ri, pub in windows:
                f = left[len(left) - FLANK:] + right[:FLANK] if base else ""  # flank_gc and flank_repeat: FLANK bases
                lw, rw = left.rjust(width, "N")[width - flank:], right.ljust(width, "N")[:flank]  # the assay's flanks
                li, ri = li[width - flank:], ri[:flank]
                nv = sum(c.islower() for c in li + ri)
                out.write(f"{idx}\t{base}\t{f}\t{lw}\t{rw}\t{li}\t{ri}\t{nv}\t{pub or ''}\n")
        con.execute(f"""CREATE OR REPLACE TEMP TABLE windows AS SELECT * FROM read_csv({lit(tmp)}, delim='\t',
            header=false, auto_detect=false, quote='', columns={{'idx': 'BIGINT', 'base': 'VARCHAR', 'f': 'VARCHAR',
            'lw': 'VARCHAR', 'rw': 'VARCHAR', 'li': 'VARCHAR', 'ri': 'VARCHAR', 'nv': 'INTEGER', 'pub': 'VARCHAR'}})""")
    finally:
        tmp.unlink(missing_ok=True)
    flip = "translate({}, 'ACGT', 'TGCA')"
    con.execute(f"""CREATE OR REPLACE TABLE snps AS
        WITH q AS (SELECT idx, upper(base) AS genome_base,
                          round((length(f) - length(replace(replace(upper(f), 'G', ''), 'C', '')))
                                / nullif(length(regexp_replace(upper(f), '[^ACGT]', '', 'g')), 0), 3) AS flank_gc,
                          round(length(regexp_replace(f, '[^a-z]', '', 'g')) / nullif(length(f), 0), 3) AS flank_repeat
                   FROM windows)
        SELECT s.*, q.* EXCLUDE (idx),
               CASE WHEN q.genome_base IS NULL OR q.genome_base NOT IN ('A', 'C', 'G', 'T') OR p.ref IS NULL
                        THEN 'not_checked'
                    WHEN length(p.ref) <> 1 OR length(coalesce(p.alt, 'N')) <> 1 THEN 'not_snp'
                    WHEN p.ref = q.genome_base THEN 'ok' WHEN p.alt = q.genome_base THEN 'swapped'
                    WHEN q.genome_base IN ({flip.format('p.ref')}, {flip.format('p.alt')}) THEN 'strand_flip'
                    ELSE 'mismatch' END AS ref_check
        FROM snps s JOIN pos p USING (idx) LEFT JOIN q USING (idx)""")
    columns = [r[0] for r in con.execute("DESCRIBE snps").fetchall()]
    disabled = None if full else f"genome read remotely: lists over {assay.REMOTE_MAX:,} SNPs are not checked"
    windows = "(SELECT * FROM windows WHERE false)" if disabled else "windows"
    con.execute(f"CREATE OR REPLACE TABLE snps AS {assay.assay_sql('snps', windows, rules, columns, disabled)}")
    con.execute("DROP TABLE windows; DROP TABLE IF EXISTS _flank_snps")  # frees them before the output is written


def annotate(snps_path, release_dir, out_path, trait="all", sequence=True, progress=None, max_snps=None,
             threads=2, memory_limit="2GB"):
    """Write the annotated SNPs to out_path: Parquet if it ends in .parquet, CSV if .csv, otherwise TSV, and next to it
    <stem>.validation.json and <stem>.rejects.tsv. Adds the release's layers, the known-loci catalogue, the sequence
    checks and assay QC (if the release knows where the genome is and `sequence`) and the tier columns for the preset.
    `progress(stage)` is called with stage names. Problems with the input raise InputError with a safe message."""
    path, release, out = Path(snps_path).resolve(), Path(release_dir).resolve(), Path(out_path).resolve()
    step = progress or (lambda stage: None)
    manifest = json.loads((release / "manifest.json").read_text())
    weights = load_weights()
    if weights and trait not in weights["presets"]:
        raise InputError(f"Unknown trait preset '{trait}'. Choose from: {', '.join(weights['presets'])}")
    con = connect([path.parent, release], out.parent, threads, memory_limit)
    try:
        report = _annotate(con, path, release, out, manifest, weights, trait, sequence, step, max_snps)
    except duckdb.Error as e:
        if os.environ.get("SNPSCORE_DEBUG"):
            raise
        raise InputError(user_message(e)) from None
    finally:
        con.close()
    if not report["snps_kept"]:
        raise InputError(no_snps_message(report))
    return Path(out_path)


def _annotate(con, path, release, out, manifest, weights, trait, sequence, step, max_snps):
    step("reading")
    known = manifest.get("chrom_sizes") or [r[0] for r in con.execute(" UNION ".join(
        f"SELECT DISTINCT chrom FROM read_parquet({lit(release / (l['name'] + '.parquet'))})"
        for l in manifest["layers"] if l["type"] == "interval")).fetchall()]
    alias, rsid_table = release / "alias.parquet", release / "rsid.parquet"
    report = read_snps(con, path, known, alias if alias.exists() else None, max_snps,
                       rsid_table if rsid_table.exists() else None)
    stem = out.parent / out.stem
    if report["snps_kept"]:
        cols = [r[0] for r in con.execute("DESCRIBE snps").fetchall()]
        alleles = "ref" in cols and "alt" in cols
        allele_cols = "upper(ref) AS ref, upper(alt) AS alt" if alleles else "NULL::VARCHAR AS ref, NULL::VARCHAR AS alt"
        con.execute(f"CREATE OR REPLACE TABLE pos AS SELECT idx, chrom, pos, {allele_cols} FROM snps")

        step("layers")
        tables, gene_table = [], None
        for i, layer in enumerate(manifest["layers"]):
            name, cols_, parquet = layer["name"], layer["columns"], release / f"{layer['name']}.parquet"
            if layer["type"] in LAYER_SQL:
                sql = LAYER_SQL[layer["type"]](name, cols_, parquet, layer)
                if layer["type"] == "point" and not alleles:
                    sql = f"SELECT * EXCLUDE ({q(name + '_alleles')}) FROM ({sql})"
            elif layer["type"] == "gene" and gene_table:
                sql = gene_sql(name, cols_, parquet, gene_table)
            else:
                continue  # 'features' layers are for the viewers, not annotated
            con.execute(f"CREATE OR REPLACE TABLE layer_{i} AS {sql}")
            tables.append(f"layer_{i}")
            if "gene_id" in [r[0] for r in con.execute(f"DESCRIBE layer_{i}").fetchall()]:
                gene_table = gene_table or f"(SELECT idx, gene_id FROM layer_{i})"
        catalog = manifest.get("catalog")
        if catalog and (release / catalog["file"]).exists():
            con.execute(f"CREATE OR REPLACE TABLE known_loci AS {known_sql(release / catalog['file'], catalog['window'])}")
            tables.append("known_loci")
        joins = "".join(f" LEFT JOIN {t} USING (idx)" for t in tables)
        con.execute(f"CREATE OR REPLACE TABLE snps AS SELECT * FROM snps{joins}")
        for t in tables:
            con.execute(f"DROP TABLE {t}")

        location = genome_location(manifest) if sequence else None
        if location:
            step("sequence")
            report["ref_check_sampled"] = location.startswith("http") and report["snps_kept"] > assay.REMOTE_MAX
            point = next((l for l in manifest["layers"] if l["name"] == "public_af"), None)  # public sites with alleles
            try:
                add_sequence_checks(con, location, out.parent, weights, point and release / point["file"])
                report["ref_check"] = dict(con.execute("SELECT ref_check, count(*) FROM snps GROUP BY 1 ORDER BY 1").fetchall())
                report["assembly"] = assembly_verdict(report["ref_check"])
                report["assay"] = dict(con.execute("SELECT assay_status, count(*) FROM snps GROUP BY 1 ORDER BY 1").fetchall())
                report["assay_reasons"] = assay.breakdown(con, "(SELECT assay_reasons FROM snps WHERE assay_status IN ('warn', 'fail'))")
                models = next((l for l in manifest["layers"] if l.get("format") == "gff3_transcripts"), None)
                if models and (release / models["file"]).exists() and not report["ref_check_sampled"]:
                    step("coding")  # table `coding` (idx, coding_*), joined below
                    coding.consequences(con, location, release / models["file"], point and release / point["file"])
                    for key, col in (("coding", "coding_consequence"), ("coding_notes", "coding_note")):
                        report[key] = dict(con.execute(f"SELECT {col}, count(*) FROM coding WHERE {col} IS NOT NULL "
                                                       "GROUP BY 1 ORDER BY 2 DESC, 1").fetchall())
                layer = next((l for l in manifest["layers"] if l.get("format") == "motif_effects"), None)
                if layer and (release / layer["meme"]).exists() and not location.startswith("http"):
                    step("motifs")  # in-peak SNPs that the precomputed layer doesn't hold (not public sites)
                    report["motif"] = motif.add_effects(con, location, release / layer["meme"], layer)
            except OSError:  # remote genome unreachable: annotate without the sequence columns
                report["assembly"] = {"verdict": "not_checked", "checked": 0, "message": "The genome could not be read."}
        # A/T and C/G SNPs read the same on both strands, which some genotyping assays can't tell apart.
        ambiguous = ", upper(ref) || upper(alt) IN ('AT', 'TA', 'CG', 'GC') AS strand_ambiguous" if alleles else ""
        has_coding = "coding" in report
        if ambiguous or has_coding:  # one rewrite of the whole table for both
            coding_cols = "".join(f", c.{c}" for c in coding.COLUMNS) if has_coding else ""
            con.execute(f"""CREATE OR REPLACE TABLE snps AS SELECT s.*{coding_cols}{ambiguous}
                            FROM snps s{' LEFT JOIN coding c USING (idx)' if has_coding else ''}""")
            con.execute("DROP TABLE IF EXISTS coding")
        if weights:
            step("scoring")
            columns = [r[0] for r in con.execute("DESCRIBE snps").fetchall()]
            synthetic = [l["name"] for l in manifest["layers"] if l.get("synthetic")]
            con.execute(f"CREATE OR REPLACE TABLE snps AS {scored('snps', weights, columns, trait, synthetic)}")

        step("writing")
        write_in_order(con, out)
    con.execute(f"COPY (SELECT * FROM rejects ORDER BY row) TO {lit(str(stem) + '.rejects.tsv')} (HEADER, DELIMITER '\t')")
    Path(str(stem) + ".validation.json").write_text(json.dumps(report, indent=2))
    return report


def write_in_order(con, out, table="snps", key="idx", drop="idx", options=None):
    """COPY `table` without the `drop` columns to out in `key` order, with the COPY `options` (default: Parquet, CSV
    or TSV by out's suffix). A long table is sorted in key ranges of WRITE_PART into Parquet parts next to out, which
    are then copied in turn (DuckDB keeps the order of a file list): one ORDER BY over ~1.6M annotated SNPs runs out
    of memory at 2 GB (DuckDB 1.2.2)."""
    fmt = options or ("FORMAT parquet" if out.suffix == ".parquet" else "HEADER, DELIMITER ','" if out.suffix == ".csv"
                      else "HEADER, DELIMITER '\t'")
    n, top = con.execute(f"SELECT count(*), max({key}) FROM {table}").fetchone()
    if n <= WRITE_PART:
        con.execute(f"COPY (SELECT * EXCLUDE ({drop}) FROM {table} ORDER BY {key}) TO {lit(out)} ({fmt})")
        return
    parts = [out.parent / f".{out.name}.{uuid.uuid4().hex}.part{i}.parquet" for i in range(top // WRITE_PART + 1)]
    try:
        for i, part in enumerate(parts):
            con.execute(f"COPY (SELECT * EXCLUDE ({drop}) FROM {table} WHERE {key} >= {i * WRITE_PART} "
                        f"AND {key} < {(i + 1) * WRITE_PART} ORDER BY {key}) TO {lit(part)} (FORMAT parquet)")
        con.execute(f"COPY (SELECT * FROM read_parquet([{', '.join(lit(p) for p in parts)}])) TO {lit(out)} ({fmt})")
    finally:
        for part in parts:
            part.unlink(missing_ok=True)


def assembly_verdict(counts):
    """'ok', 'warning' (too many alleles disagree with the genome) or 'not_checked', with the shares behind it."""
    checked = sum(counts.get(k, 0) for k in ("ok", "swapped", "strand_flip", "mismatch"))
    if not checked:
        return {"verdict": "not_checked", "checked": 0}
    share = (counts.get("mismatch", 0) + counts.get("strand_flip", 0)) / checked
    verdict = {"verdict": "warning" if share > ASSEMBLY_WARNING else "ok", "checked": checked,
               "mismatch_or_flip_share": round(share, 3)}
    if share > ASSEMBLY_WARNING:
        verdict["message"] = (f"{share:.0%} of the checked alleles don't match the Ssal_v3.1 reference base: these look "
                              "like ICSASG_v2 coordinates or alleles on the other strand.")
    return verdict
