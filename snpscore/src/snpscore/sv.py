"""Annotate structural variants (SVs) against a release: each SV, or any genomic region, gets the evidence of
everything it overlaps and a tier from the same weights.yaml rules as a SNP (score.scored, unchanged). One row per
kept SV, in input order, plus <stem>.validation.json and <stem>.rejects.tsv, as annotate() writes them for SNPs.

An SV covers the 1-based bases pos..end. Layers are BED intervals (start, end], so an interval overlaps an SV when
start < SV end and end >= SV pos: a 1-bp SV overlaps exactly what a SNP at that position is inside. Insertions and
breakends cover the two bases either side of their junction. Left out, as they need one base and its alleles: the
sequence and assay checks, coding consequences, TF motif changes, public allele frequencies and probe-flank counts.

Per layer:
- chromatin: per condition the strongest state of the peaks the SV overlaps (weights.yaml active_states in their
  order, then weak_states, then any other state), so an SV counts as active in a condition when any peak it
  overlaps is; chromatin = it overlaps a robust ATAC peak; peaks = how many.
- region: region_class = the first class of the layer's `classes` the SV overlaps (CDS, splice region, 5' and 3'
  UTR, non-coding exon, intron: the most severe); region_classes = all it overlaps, in that order.
- gene (nearest): the gene the SV overlaps most (distance 0), else the nearest within max_distance of either end;
  genes = the genes it overlaps (names, else ids) and n_genes. Gene-keyed layers (orthologs, Ss4R, expression)
  follow that gene.
- other interval layers: <layer> = any overlap; numbers the largest (gerp_score), text the distinct values (at most
  MAX_VALUES); an interpolated layer (the genetic map) at the SV's first base.
- summit (nearest): the highest-ranked ATAC summit inside the SV (distance 0), else the nearest within max_distance.
- molQTL leads (format nfrasqual) inside the SV: n, tissues, kinds, best BF and features (display only, weight 0).
- the known-loci catalogue: the nearest entry within catalog.window bp of the SV (0 = inside it; entries with start
  and end count by their extent).
Overlaps are one IEJoin per layer on genome-wide coordinates (chromosome k at k * OFFSET), not a join per
chromosome."""
from __future__ import annotations

import json
import os
import re
import zlib
from pathlib import Path

import duckdb

from .annotate import connect, gene_sql, interval_sql, parquet_columns, user_message, write_in_order
from .formats import DETECT_CHARS, InputError, TooMany, _delim, _dropped, _open, _split, column_names, lit, norm, q
from .score import load_weights, scored

ALIASES = {  # output name -> header names read as it (lower case, other characters as _)
    "chrom": ("chrom", "chr", "chromosome", "seqnames", "seqname", "contig"),
    "start": ("start", "pos", "position", "begin", "from", "chromstart", "bp", "start_pos", "sv_start"),
    "end": ("end", "stop", "to", "chromend", "end_pos", "end_position", "sv_end"),
    "id": ("id", "name", "sv_id", "svid", "variant_id"),
    "svtype": ("svtype", "sv_type", "type", "variant_type"),
    "svlen": ("svlen", "sv_len", "length", "len", "size", "sv_length"),
}
RESERVED = tuple(ALIASES)
WORDS = {"DELETION": "DEL", "DUPLICATION": "DUP", "TANDEM_DUPLICATION": "DUP", "INVERSION": "INV", "INSERTION": "INS",
         "TRANSLOCATION": "BND", "TRA": "BND", "BREAKEND": "BND"}  # spelled-out types -> VCF SVTYPEs
TYPE_WORD = re.compile(r"(?i)^<?(DEL|DUP|INV|INS|CNV|BND|TRA|MEI|DELETION|DUPLICATION|INVERSION|INSERTION|TRANSLOCATION)"
                       r"(?:[:_]\w+)*>?$")
JUNCTION = ("INS", "BND")  # no reference span: the two bases either side of the junction
REGION = re.compile(r"^\s*[\w.]+:[\d,]+\s*[-–]\s*[\d,]+(?:\s|$)")
OFFSET = 10_000_000_000  # genome-wide coordinate of chromosome k: k * OFFSET + position
MAX_VALUES = 10  # distinct text values kept per layer column (e.g. regbuild_type); more end in ', ...'
ACCEPTED = ("Accepted: a VCF of structural variants (END, SVLEN and SVTYPE in INFO, symbolic alleles such as <DEL>, "
            "or sequence alleles); a BED file (chrom, start, end, name); a TSV/CSV table whose header names chrom "
            "(CHR, Chromosome), start (Pos, Begin) and end (Stop), or svlen (Length, Size) instead of end, optionally "
            "id (Name) and svtype (Type); or lines of 'chrom start end [type] [id]' or 'chrom:start-end [type] [id]' "
            "without a header. Coordinates are 1-based and inclusive, except in BED files (0-based start).")


# ---- reading ----

def _header(line):
    fields = [norm(f) for f in _split(line.lstrip("#"), _delim(line))]
    return any(f in ALIASES["chrom"] for f in fields) and any(f in ALIASES["start"] for f in fields)


def _extras(tokens):
    """Names of the fields after the coordinates of a headerless line: an SV type word is svtype, the next other
    field id, the rest in_col<n>."""
    out, first = [], len(tokens)
    for k, t in enumerate(tokens):
        name = "svtype" if TYPE_WORD.match(t) and "svtype" not in out else "id" if "id" not in out else f"in_col{first + k}"
        out.append(name)
    return out


def detect(path, header_lines=200):
    """Layout of an SV file: {format (vcf, bed, tsv, csv, text, noheader, regions), delim, skip, names (output name
    per field), header, dropped, gzip}. Raises InputError with the accepted layouts when it can't tell."""
    name = str(path).lower()
    name = name[:-3] if name.endswith(".gz") else name
    try:
        f, gz = _open(path)
        with f:
            text = f.read(DETECT_CHARS)
    except (OSError, EOFError, zlib.error):
        raise InputError("The file could not be read: it is not text, or a damaged .gz file.") from None
    lines = text.split("\n")
    if len(text) == DETECT_CHARS:
        lines.pop()  # cut off mid-line
    lines = [line.rstrip("\r") for line in lines[:header_lines]]
    layout = {"gzip": gz, "dropped": [], "header": []}
    vcf = any(line.startswith("#CHROM\t") and [norm(x) for x in line.split("\t")[1:5]] == ["pos", "id", "ref", "alt"]
              for line in lines)
    if name.endswith(".vcf") or vcf or any(line.startswith("##fileformat=VCF") for line in lines):
        return {**layout, "format": "vcf", "delim": "\t", "skip": 0, "names": ["chrom", "start", "id", "_ref", "_alt",
                                                                                None, None, "_info"]}
    i = 0
    while i < len(lines) and (not lines[i].strip() or lines[i].startswith(("track", "browser"))
                              or lines[i].startswith("#") and not _header(lines[i])):
        i += 1
    if i == len(lines):
        raise InputError("The file has no SV rows. " + ACCEPTED)
    line = lines[i]
    if name.endswith(".bed"):  # chrom, 0-based start, end, name; other BED columns are not read
        return {**layout, "format": "bed", "delim": " ", "skip": i + _header(line), "names": ["chrom", "start", "end", "id"]}
    if _header(line):
        delim = _delim(line)
        fields = _split(line.lstrip("#"), delim)
        names = column_names(fields, aliases=ALIASES, reserved=RESERVED)
        if "end" not in names and "svlen" not in names:
            raise InputError("The header has a chromosome and a start column but no end (or length) column. " + ACCEPTED)
        return {**layout, "format": {"\t": "tsv", ",": "csv", ";": "csv", " ": "text"}[delim], "delim": delim,
                "skip": i + 1, "header": fields, "names": names, "dropped": _dropped(fields, names)}
    if REGION.match(line):  # chrom:start-end [type] [id]
        return {**layout, "format": "regions", "delim": " ", "skip": i, "names": ["_region"] + _extras(line.split()[1:])}
    fields = line.split()
    if len(fields) >= 3 and fields[1].isdigit() and fields[2].isdigit():
        return {**layout, "format": "noheader", "delim": " ", "skip": i, "names": ["chrom", "start", "end"] + _extras(fields[3:])}
    raise InputError("The file layout was not recognised. " + ACCEPTED)


def source(path, layout, limit=None):
    """SQL reading an SV file in `layout` (detect) as VARCHAR columns: chrom, start, end (as written), then id,
    svtype, svlen and the input's other columns as given; a VCF's _ref, _alt and _info for read_svs to turn into
    coordinates. At most `limit` rows."""
    gz = ", compression='gzip'" if layout["gzip"] else ", compression='none'"
    cap = "" if limit is None else f" LIMIT {int(limit)}"
    names, fmt = layout["names"], layout["format"]
    lines = f"""read_csv({lit(path)}, header=false, columns={{'line': 'VARCHAR'}}, delim='\x01', quote='', escape='',
                         auto_detect=false, skip={int(layout['skip'])}{gz})"""
    if fmt in ("vcf", "bed", "noheader", "regions"):
        split = "string_split(line, '\t')" if fmt == "vcf" else "string_split_regex(trim(line), '\\s+')"
        if fmt == "regions":  # the first field holds chrom:start-end
            split = (r"""[regexp_extract(trim(line), '^([\w.]+):', 1), replace(regexp_extract(trim(line), '^[\w.]+:([^-–\s]+)', 1), ',', ''),
                          replace(regexp_extract(trim(line), '^[\w.]+:[^-–\s]+\s*[-–]\s*(\S+)', 1), ',', '')]
                         || string_split_regex(trim(line), '\s+')[2:]""")
            names = ["chrom", "start", "end"] + names[1:]
        fields = ", ".join(f"nullif(nullif(f[{k + 1}], ''), '.') AS {q(n)}" for k, n in enumerate(names) if n)
        src = f"(SELECT {split} AS f FROM {lines} WHERE trim(line) <> '' AND NOT starts_with(line, '#'))"
    else:
        columns = ", ".join(f"{lit(n or f'_skip{k}')}: 'VARCHAR'" for k, n in enumerate(names))
        fields = ", ".join(q(n) for n in names if n)
        src = f"""read_csv({lit(path)}, header=false, columns={{{columns}}}, delim={lit(layout['delim'])}, quote='"',
                          escape='"', auto_detect=false, skip={int(layout['skip'])}, null_padding=true{gz})"""
    present = {n for n in names if n}
    missing = "".join(f", NULL::VARCHAR AS {n}" for n in ("end", "id", "svtype", "svlen") if n not in present)
    return f"SELECT chrom, start, * EXCLUDE (chrom, start){missing} FROM (SELECT {fields} FROM {src}{cap})"


def _type(expr):
    """SQL: an SV type as VCF writes it (DEL, DUP, INV, INS, CNV, BND, ...) from a type column or <DEL>-style allele."""
    word = f"upper(regexp_replace(trim({expr}), '^<|>$', '', 'g'))"
    cases = " ".join(f"WHEN {lit(k)} THEN {lit(v)}" for k, v in WORDS.items())
    return f"nullif(CASE split_part({word}, ':', 1) {cases} ELSE split_part({word}, ':', 1) END, '')"


def read_svs(con, path, known, alias=None, max_svs=None):
    """Load an SV file into table `svs` (idx = input row, chrom, pos, end, length, svtype, id, svlen, then the input's
    other columns as in_<name>) and the rows that can't be used into `rejects` (row, chrom, start, end, ..., reason:
    missing_chrom, bad_pos, bad_end, unknown_chrom, duplicate). Chromosome names go through `alias`; `known` lists
    the release's chromosomes. Returns the validation report."""
    layout = detect(path)
    limit = int(max_svs) + 1 if max_svs else None
    con.execute(f"CREATE OR REPLACE TABLE raw AS SELECT row_number() OVER () AS idx, * FROM ({source(path, layout, limit)})")
    rows = con.execute("SELECT count(*) FROM raw").fetchone()[0]
    if max_svs and rows > max_svs:
        raise TooMany(f"The file has more than {max_svs:,} SVs. Split it, or run snpscore locally.")
    con.execute("CREATE OR REPLACE TEMP TABLE known AS SELECT unnest(?::VARCHAR[]) AS chrom", [list(known)])
    mapped, join, warning = "trim(r.chrom)", "", "NULL"
    if alias:
        mapped, join = "coalesce(a.chrom, trim(r.chrom))", f"LEFT JOIN read_parquet({lit(alias)}) a ON a.alias = lower(trim(r.chrom))"
        warning = "a.warning" if "warning" in parquet_columns(con, alias) else "NULL"
    number = "CASE WHEN regexp_full_match(trim({0}), '[0-9]+') THEN try_cast(trim({0}) AS BIGINT) END"
    junction = ", ".join(lit(t) for t in JUNCTION)
    if layout["format"] == "vcf":  # POS is the base before an event that has a padding base (<DEL>, or ACGT>A)
        ref, alt = "upper(r._ref)", "upper(split_part(r._alt, ',', 1))"
        info = lambda key: f"nullif(regexp_extract(r._info, '(?:^|;){key}=([^;]+)', 1), '')"  # noqa: E731
        bnd = f"regexp_matches({alt}, '[\\[\\]]')"
        typed = f"""SELECT * REPLACE (coalesce({_type(info('SVTYPE'))}, CASE WHEN starts_with({alt}, '<') THEN {_type(alt)}
                                          WHEN {bnd} THEN 'BND' WHEN length({ref}) > length({alt}) THEN 'DEL'
                                          WHEN length({alt}) > length({ref}) THEN 'INS' WHEN length({ref}) = 1 THEN 'SNV'
                                          ELSE 'MNV' END) AS svtype,
                                 abs(try_cast({info('SVLEN')} AS BIGINT)) AS svlen),
                           {number.format('r.start')} AS p, try_cast({info('END')} AS BIGINT) AS info_end"""
        coords = f"""CASE WHEN svtype IN ({junction}) OR {bnd} THEN p
                          WHEN starts_with({alt}, '<') OR length({ref}) > 1 AND left({ref}, 1) = left({alt}, 1) THEN p + 1
                          ELSE p END AS pos,
                     CASE WHEN svtype IN ({junction}) OR {bnd} THEN p + 1
                          WHEN starts_with({alt}, '<') THEN CASE WHEN coalesce(info_end, p + svlen) IS NOT NULL
                                                                 THEN greatest(coalesce(info_end, p + svlen), p + 1) END
                          ELSE p + length({ref}) - 1 END AS e"""
    elif layout["format"] == "bed":  # 0-based start; a zero-length interval is a junction (an insertion point)
        typed = f"""SELECT * REPLACE ({_type('r.svtype')} AS svtype, abs(try_cast(trim(r.svlen) AS BIGINT)) AS svlen),
                           {number.format('r.start')} AS a, {number.format('r."end"')} AS b"""
        coords = "CASE WHEN b = a THEN a ELSE a + 1 END AS pos, CASE WHEN b = a THEN a + 1 ELSE b END AS e"
    else:  # 1-based and inclusive; no end: the length (svlen) from start, or the junction of an insertion
        typed = f"""SELECT * REPLACE ({_type('r.svtype')} AS svtype, abs(try_cast(trim(r.svlen) AS BIGINT)) AS svlen),
                           {number.format('r.start')} AS p, {number.format('r."end"')} AS b"""
        coords = f"""p AS pos,
                     CASE WHEN p IS NULL THEN NULL WHEN b IS NOT NULL THEN CASE WHEN svtype IN ({junction}) AND b = p THEN p + 1 ELSE b END
                          WHEN r."end" IS NOT NULL THEN NULL WHEN svtype IN ({junction}) THEN p + 1
                          WHEN svlen IS NOT NULL THEN p + svlen - 1 END AS e"""
    con.execute(f"""CREATE OR REPLACE TABLE checked AS
        WITH t AS (SELECT r.*, nullif({mapped}, '') AS m_chrom, {warning} AS alias_warning FROM raw r {join}),
        typed AS ({typed} FROM t r),
        c AS (SELECT r.*, {coords} FROM typed r)
        SELECT *, CASE WHEN m_chrom IS NULL THEN 'missing_chrom' WHEN pos IS NULL OR pos < 1 THEN 'bad_pos'
                       WHEN e IS NULL OR e < pos THEN 'bad_end' WHEN m_chrom NOT IN (SELECT chrom FROM known) THEN 'unknown_chrom'
                       WHEN row_number() OVER (PARTITION BY m_chrom, pos, e, coalesce(svtype, '') ORDER BY idx) > 1 THEN 'duplicate'
                  END AS reason
        FROM c""")
    extra = [c for c in (r[0] for r in con.execute("DESCRIBE raw").fetchall()) if c.startswith("in_")]
    keep = ", ".join(["idx", "m_chrom AS chrom", "pos", 'e AS "end"', 'e - pos + 1 AS length', "svtype", "id", "svlen"]
                     + [q(c) for c in extra])
    con.execute(f"CREATE OR REPLACE TABLE svs AS SELECT {keep} FROM checked WHERE reason IS NULL")
    if not con.execute("SELECT count(*) FROM svs WHERE svlen IS NOT NULL").fetchone()[0]:
        con.execute("ALTER TABLE svs DROP COLUMN svlen")
    con.execute("""CREATE OR REPLACE TABLE rejects AS SELECT idx AS row, chrom, start, "end", id, svtype, reason
                   FROM checked WHERE reason IS NOT NULL""")

    def fetch(sql):
        return con.execute(sql).fetchall()

    kept = fetch("SELECT count(*) FROM svs")[0][0]
    report = {
        "format": layout["format"],
        "rows_read": rows,
        "svs_kept": kept,
        "rejected": dict(fetch("SELECT reason, count(*) FROM rejects GROUP BY 1 ORDER BY 2 DESC, 1")),
        "unknown_chromosomes": [{"name": n[:40], "rows": c} for n, c in fetch(
            "SELECT trim(chrom), count(*) FROM checked WHERE reason = 'unknown_chrom' GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 10")],
        "aliases_applied": [{"from": x[:40], "to": y, "rows": c} for x, y, c in fetch(
            "SELECT trim(chrom), m_chrom, count(*) FROM checked WHERE m_chrom <> trim(chrom) GROUP BY 1, 2 ORDER BY 3 DESC, 1 LIMIT 50")],
        "columns_renamed": {h: n for h, n in zip(layout["header"], layout["names"]) if n and n.startswith("in_")},
        "columns_dropped": layout["dropped"],
        "svtypes": dict(fetch("SELECT coalesce(svtype, 'not given'), count(*) FROM svs GROUP BY 1 ORDER BY 2 DESC, 1")),
    }
    if kept:
        report["length"] = dict(zip(("min", "median", "max"), fetch(
            "SELECT min(length), CAST(median(length) AS BIGINT), max(length) FROM svs")[0]))
    warnings = fetch("""SELECT trim(chrom), m_chrom, count(*), any_value(alias_warning) FROM checked
                        WHERE alias_warning IS NOT NULL GROUP BY 1, 2 ORDER BY 3 DESC, 1""")
    if warnings:
        report["alias_warnings"] = [{"from": x[:40], "to": y, "rows": c, "message": m} for x, y, c, m in warnings]
    report["duplicates_merged"] = report["rejected"].get("duplicate", 0)
    con.execute("DROP TABLE raw; DROP TABLE checked")
    return report


def no_svs_message(report, manifest=None):
    from .annotate import assembly_names
    names = ", ".join(f"'{u['name']}' ({u['rows']})" for u in report["unknown_chromosomes"][:3])
    if names:
        return f"No SVs are on {assembly_names(manifest or {})[2]}. Most common chromosome names in the file: {names}."
    if report["rejected"].get("bad_end"):
        return ("No SVs have both a start and an end (or a length) with end at or after start: check the columns, and "
                "that a VCF has END or SVLEN in INFO for symbolic alleles. " + ACCEPTED)
    return "No SVs have a chromosome and whole-number start and end. " + ACCEPTED


# ---- overlaps, one query per layer on the narrow table `span` (idx, chrom, pos, end, gp, ge) ----

def overlapping(parquet, columns="l.*"):
    """SQL: (idx, the layer's `columns`) for every SV x layer interval that overlap (start < SV end, end >= SV pos),
    as an IEJoin on genome-wide coordinates."""
    return f"""SELECT s.idx, {columns} FROM span s JOIN (
                   SELECT l.*, k.k * {OFFSET} + l.start AS _gs, k.k * {OFFSET} + l."end" AS _ge
                   FROM read_parquet({lit(parquet)}) l JOIN chroms k USING (chrom)) l
               ON l._gs < s.ge AND l._ge >= s.gp"""


def distinct_text(expr):
    """SQL: the distinct non-NULL values of `expr`, sorted, at most MAX_VALUES, joined by ', ' (NULL for none)."""
    items = f"list_sort(list_distinct(list({expr})))"
    return (f"nullif(array_to_string({items}[1:{MAX_VALUES}], ', ') || "
            f"CASE WHEN len({items}) > {MAX_VALUES} THEN ', ...' ELSE '' END, '')")


def chromatin_sql(name, cols, parquet, weights):
    """<name> (overlaps a peak), peaks (how many), and per condition the strongest state of the overlapped peaks."""
    order = [*(weights or {}).get("active_states", []), *(weights or {}).get("weak_states", [])]
    conditions = [c for c in cols if c != "summary"]

    def rank(c):  # NULL without a state, so arg_min skips the peaks that have none in this condition
        cases = "".join(f" WHEN o.{q(c)} = {lit(s)} THEN {i}" for i, s in enumerate(order))
        return f"CASE WHEN o.{q(c)} IS NULL THEN NULL{cases} ELSE {len(order)} END"

    values = "".join(f", arg_min(o.{q(c)}, {rank(c)}) AS {q(name + '_' + c)}" for c in conditions)
    return f"""SELECT s.idx, count(o.idx) > 0 AS {q(name)}, count(o.idx) AS peaks{values}
               FROM span s LEFT JOIN ({overlapping(parquet)}) o USING (idx) GROUP BY s.idx"""


def region_sql(name, cols, parquet, layer):
    """<name>, <name>_class (the most severe class overlapped: first in the layer's `classes`) and region_classes."""
    classes = list(layer.get("classes") or [])
    rank = "CASE o.class " + " ".join(f"WHEN {lit(c)} THEN {i}" for i, c in enumerate(classes)) + f" ELSE {len(classes)} END"
    names = "[" + ", ".join(lit(c) for c in classes) + "]"
    return f"""SELECT s.idx, count(o.idx) > 0 AS {q(name)}, arg_min(o.class, {rank}) AS {q(name + '_class')},
                      nullif(array_to_string(list_transform(list_sort(list_distinct(list(CASE WHEN o.class IS NOT NULL THEN {rank} END))),
                                                            lambda r: coalesce(list_extract({names}, r + 1), 'other')), ','), '') AS region_classes
               FROM span s LEFT JOIN ({overlapping(parquet)}) o USING (idx) GROUP BY s.idx"""


def overlap_sql(con, name, cols, parquet):
    """<name> = any overlap; per column the largest number, any true flag, or the distinct text values."""
    types = dict(con.execute(f"SELECT column_name, column_type FROM (DESCRIBE SELECT * FROM read_parquet({lit(parquet)}))").fetchall())
    values = ""
    for c in cols:
        kind = types.get(c, "VARCHAR")
        agg = (f"bool_or(o.{q(c)})" if kind == "BOOLEAN" else
               f"max(o.{q(c)})" if any(t in kind for t in ("INT", "DOUBLE", "FLOAT", "DECIMAL", "REAL")) else
               distinct_text(f"o.{q(c)}::VARCHAR"))
        values += f", {agg} AS {q(name + '_' + c)}"
    return f"""SELECT s.idx, count(o.idx) > 0 AS {q(name)}{values}
               FROM span s LEFT JOIN ({overlapping(parquet)}) o USING (idx) GROUP BY s.idx"""


def molqtl_sql(name, parquet):
    """The nf-RASQUAL lead SNPs inside the SV: <name>, _n, _tissues, _kinds, _best_bf and _features (best first)."""
    def union(c):
        return (f"nullif(array_to_string(list_sort(list_distinct(flatten(list(string_split(o.{q(c)}, ','))))), ','), '')")
    return f"""SELECT s.idx, count(o.idx) > 0 AS {q(name)}, sum(o.n)::BIGINT AS {q(name + '_n')},
                      {union('tissues')} AS {q(name + '_tissues')}, {union('kinds')} AS {q(name + '_kinds')},
                      min(o.best_bf) AS {q(name + '_best_bf')},
                      string_agg(o.features, '; ' ORDER BY o.best_bf) AS {q(name + '_features')}
               FROM span s LEFT JOIN ({overlapping(parquet)}) o USING (idx) GROUP BY s.idx"""


def nearest_sql(name, cols, parquet, layer):
    """The gene the SV overlaps most (lowest start on a tie), else the nearest gene ending before it or starting
    after it (distance from the nearer end; ties to the lower start), within max_distance; genes and n_genes: every
    gene it overlaps. Another nearest layer (one without an id: the ATAC summits) gives its values and distance the
    same way, without the lists; of the features an SV overlaps equally, the one with the highest `rank` when the
    layer has that column, so an SV takes the strongest summit inside it."""
    values = "".join(f", g.{q(c)} AS {q(name + '_' + c)}" for c in cols)
    tie = "".join(f", {q(c)}" for c in cols)
    genes = "id" in cols  # the gene layer: also lists the genes overlapped
    label = "coalesce(o.name, o.id)" if {"name", "id"} <= set(cols) else "o.id" if genes else "NULL"
    strongest = '"rank" DESC, ' if "rank" in cols else ""
    lists = ", l.genes, coalesce(l.n_genes, 0) AS n_genes" if genes else ""
    return f"""
        WITH f AS (SELECT * FROM read_parquet({lit(parquet)})),
        o AS ({overlapping(parquet, 'l.* EXCLUDE (_gs, _ge), least(l."end", s."end") - greatest(l.start, s.pos - 1) AS _bases')}),
        best AS (SELECT * FROM o QUALIFY row_number() OVER (PARTITION BY idx ORDER BY _bases DESC, {strongest}start{tie}) = 1),
        listed AS (SELECT idx, string_agg({label}, ', ' ORDER BY o.start{', o.id' if genes else ''}) AS genes, count(*) AS n_genes FROM o GROUP BY idx),
        up AS (SELECT * FROM f QUALIFY row_number() OVER (PARTITION BY chrom, "end" ORDER BY start{tie}) = 1),
        down AS (SELECT * FROM f QUALIFY row_number() OVER (PARTITION BY chrom, start ORDER BY "end"{tie}) = 1),
        j AS (SELECT s.idx, s.pos - u."end" AS du, d.start + 1 - s."end" AS dd, u AS gu, d AS gd
              FROM span s ASOF LEFT JOIN up u ON s.chrom = u.chrom AND s.pos > u."end"
                          ASOF LEFT JOIN down d ON s.chrom = d.chrom AND s."end" <= d.start),
        pick AS (SELECT j.idx, CASE WHEN b.idx IS NOT NULL THEN 0 ELSE least(du, dd) END AS distance,
                        CASE WHEN b.idx IS NOT NULL THEN {{{', '.join(f"{lit(c)}: b.{q(c)}" for c in ['chrom', 'start', 'end', *cols])}}}
                             WHEN du <= coalesce(dd, du) THEN gu ELSE gd END AS g
                 FROM j LEFT JOIN best b USING (idx))
        SELECT p.idx{lists}{values}, p.distance AS {q(name + '_distance')}
        FROM pick p LEFT JOIN listed l USING (idx)
        WHERE p.distance <= {int(layer['max_distance'])} OR l.idx IS NOT NULL"""


def known_sql(con, catalog, window):
    """The nearest catalogue entry within `window` bp of each SV: a position (pos), else an interval (start, end);
    distance 0 when it is inside the SV, or the SV inside it."""
    cols = parquet_columns(con, catalog) if str(catalog).endswith(".parquet") else [r[0] for r in con.execute(
        f"DESCRIBE SELECT * FROM read_csv({lit(catalog)}, delim='\t', header=true, all_varchar=true, quote='')").fetchall()]
    a = "coalesce(try_cast(pos AS BIGINT), try_cast(start AS BIGINT))" if {"start", "end"} <= set(cols) else "try_cast(pos AS BIGINT)"
    b = 'coalesce(try_cast(pos AS BIGINT), try_cast("end" AS BIGINT))' if {"start", "end"} <= set(cols) else "try_cast(pos AS BIGINT)"
    return f"""
        WITH k AS (SELECT chrom, id, {a} AS a, {b} AS b
                   FROM read_csv({lit(catalog)}, delim='\t', header=true, all_varchar=true, quote='')),
        n AS (SELECT s.idx, k.id, greatest(0, k.a - s."end", s.pos - k.b) AS dist
              FROM span s JOIN k ON s.chrom = k.chrom AND k.a <= s."end" + {int(window)} AND k.b >= s.pos - {int(window)}
              QUALIFY row_number() OVER (PARTITION BY s.idx ORDER BY dist, k.id) = 1)
        SELECT idx, id AS known_locus, dist AS known_locus_dist FROM n"""


def annotate_svs(svs_path, release_dir, out_path, trait="all", progress=None, max_svs=None, threads=2,
                 memory_limit="2GB"):
    """Write the annotated SVs to out_path (Parquet if it ends in .parquet, CSV if .csv, else TSV), and next to it
    <stem>.validation.json and <stem>.rejects.tsv. `progress(stage)` is called with stage names. Problems with the
    input raise InputError with a safe message."""
    path, release, out = Path(svs_path).resolve(), Path(release_dir).resolve(), Path(out_path).resolve()
    step = progress or (lambda stage: None)
    manifest = json.loads((release / "manifest.json").read_text())
    weights = load_weights()
    if weights and trait not in weights["presets"]:
        raise InputError(f"Unknown trait preset '{trait}'. Choose from: {', '.join(weights['presets'])}")
    con = connect([path.parent, release], out.parent, threads, memory_limit)
    try:
        report = _annotate(con, path, release, out, manifest, weights, trait, step, max_svs)
    except duckdb.Error as e:
        if os.environ.get("SNPSCORE_DEBUG"):
            raise
        raise InputError(user_message(e).replace("SNP table", "SV table")) from None
    finally:
        con.close()
    if not report["svs_kept"]:
        raise InputError(no_svs_message(report, manifest))
    return Path(out_path)


def _annotate(con, path, release, out, manifest, weights, trait, step, max_svs):
    step("reading")
    known = list(manifest.get("chrom_sizes") or {}) or [r[0] for r in con.execute(" UNION ".join(
        f"SELECT DISTINCT chrom FROM read_parquet({lit(release / (x['name'] + '.parquet'))})"
        for x in manifest["layers"] if x["type"] == "interval")).fetchall()]
    alias = release / "alias.parquet"
    report = read_svs(con, path, known, alias if alias.exists() else None, max_svs)
    stem = out.parent / out.stem
    if report["svs_kept"]:
        con.execute("CREATE OR REPLACE TEMP TABLE chroms AS SELECT unnest(?::VARCHAR[]) AS chrom, "
                    "generate_subscripts(?::VARCHAR[], 1) AS k", [known, known])
        con.execute(f"""CREATE OR REPLACE TABLE span AS SELECT s.idx, s.chrom, s.pos, s."end", k.k * {OFFSET} + s.pos AS gp,
                        k.k * {OFFSET} + s."end" AS ge FROM svs s JOIN chroms k USING (chrom)""")
        con.execute("CREATE OR REPLACE TABLE pos AS SELECT idx, chrom, pos FROM svs")  # for layers read at the first base

        step("layers")
        tables, gene_table = [], None
        for i, layer in enumerate(manifest["layers"]):
            name, cols, parquet, kind = layer["name"], layer["columns"], release / f"{layer['name']}.parquet", layer["type"]
            if kind == "interval" and name == "chromatin":
                sql = chromatin_sql(name, cols, parquet, weights)
            elif kind == "interval" and layer.get("classes"):
                sql = region_sql(name, cols, parquet, layer)
            elif kind == "interval" and layer.get("interpolate"):
                sql = interval_sql(name, cols, parquet, layer)  # the genetic map: at the SV's first base
            elif kind == "interval":
                sql = overlap_sql(con, name, cols, parquet)
            elif kind == "nearest":
                sql = nearest_sql(name, cols, parquet, layer)
            elif kind == "gene" and gene_table:
                sql = gene_sql(name, cols, parquet, gene_table)
            elif kind == "point" and layer.get("format") == "nfrasqual":
                sql = molqtl_sql(name, parquet)
            else:
                continue  # one base and its alleles (public sites, motifs, flank counts, variant scores) or viewers only
            con.execute(f"CREATE OR REPLACE TABLE layer_{i} AS {sql}")
            tables.append(f"layer_{i}")
            if f"{name}_id" in [r[0] for r in con.execute(f"DESCRIBE layer_{i}").fetchall()] and kind == "nearest":
                gene_table = gene_table or f"(SELECT idx, {q(name + '_id')} AS gene_id FROM layer_{i})"
        catalog = manifest.get("catalog")
        if catalog and (release / catalog["file"]).exists():
            con.execute(f"CREATE OR REPLACE TABLE known_loci AS {known_sql(con, release / catalog['file'], catalog['window'])}")
            tables.append("known_loci")
        joins = "".join(f" LEFT JOIN {t} USING (idx)" for t in tables)
        con.execute(f"CREATE OR REPLACE TABLE svs AS SELECT * FROM svs{joins}")
        for t in tables:
            con.execute(f"DROP TABLE {t}")
        if weights:
            step("scoring")
            columns = [r[0] for r in con.execute("DESCRIBE svs").fetchall()]
            synthetic = [x["name"] for x in manifest["layers"] if x.get("synthetic")]
            con.execute(f"CREATE OR REPLACE TABLE svs AS {scored('svs', weights, columns, trait, synthetic)}")
        step("writing")
        write_in_order(con, out, table="svs")
    con.execute(f"COPY (SELECT * FROM rejects ORDER BY row) TO {lit(str(stem) + '.rejects.tsv')} (HEADER, DELIMITER '\t')")
    Path(str(stem) + ".validation.json").write_text(json.dumps(report, indent=2))
    return report
