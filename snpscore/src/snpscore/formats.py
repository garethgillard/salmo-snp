"""Detect the layout of a SNP file and read it with DuckDB under standard column names.
Accepted: VCF; PLINK .bim/.map; BED (pos = end); Illumina-style manifest CSV ([Assay] section); Axiom-style annotation
CSV ('#%' comment lines); any TSV/CSV/space-separated table with a header (aliases below) or without one
(chrom pos [ref alt]); and lists of rs IDs (annotate places them through the release's rsid.parquet)."""
from __future__ import annotations

import csv
import gzip
import re
import zlib

# Columns that keep their name; every other input column is renamed in_<slug>. P7.1 (GWAS) adds aliases for p, beta...
RESERVED = ("chrom", "pos", "id", "ref", "alt", "p", "log10p", "beta", "se", "z", "af", "maf", "n", "a1", "a2")
MAX_EXTRA = 50  # passthrough columns kept; the rest are dropped with a note in the validation report
ALIASES = {  # reserved name -> header names read as it (lower case, other characters as _); the reserved name wins
    "chrom": ("chrom", "chr", "chromosome"),
    "pos": ("pos", "bp", "position", "mapinfo", "physical_position", "base_pair_location"),
    "id": ("id", "snp", "name", "marker", "rsid", "probe_set_id", "snp_id"),
    "ref": ("ref", "a2", "allele_a"),
    "alt": ("alt", "a1", "allele_b"),
}
ACCEPTED = ("Accepted: a VCF; PLINK .bim or .map; a BED file of 1-bp intervals; an Illumina manifest ([Assay] "
            "section) or Axiom annotation CSV; or a TSV/CSV table whose header names chrom (CHR, Chromosome) and pos "
            "(BP, Position, MapInfo, Physical Position), optionally id (SNP, Name, Marker, rsid, Probe Set ID), ref "
            "(REF, A2, Allele A) and alt (ALT, A1, Allele B); or lines of 'chrom pos [ref alt]' without a header; or "
            "a list of rs IDs (one per line, or an id column without chrom and pos).")
RS = re.compile(r"rs[0-9]+$", re.IGNORECASE)
PLINK = {"bim": ["chrom", "id", None, "pos", "alt", "ref"], "map": ["chrom", "id", None, "pos"]}  # None: cM, not read
HEADERLESS = {2: ["chrom", "pos"], 3: ["chrom", "pos", "id"], 4: ["chrom", "pos", "ref", "alt"]}
DETECT_CHARS = 1 << 20  # detect() reads at most this much of the (decompressed) file, however long its lines are


class InputError(ValueError):
    """A problem with the user's file or request. The message is safe to show: no SQL, paths or input lines."""


def q(ident):
    """SQL identifier, quoted."""
    return '"' + str(ident).replace('"', '""') + '"'


def lit(value):
    """SQL string literal, quoted."""
    return "'" + str(value).replace("'", "''") + "'"


def norm(name):
    return re.sub(r"[^a-z0-9]+", "_", name.strip().lstrip("#").lower()).strip("_")


def column_names(header, fixed=None):
    """Output name per header field (None = not read): aliases -> reserved names, other reserved names as they are,
    the first MAX_EXTRA other fields as in_<slug>. `fixed` maps field index -> name decided by the caller."""
    normed = [norm(h) for h in header]
    names = [(fixed or {}).get(i) for i in range(len(header))]
    for target, aliases in ALIASES.items():
        hits = [i for i, n in enumerate(normed) if n in aliases and names[i] is None]
        if hits:
            names[([i for i in hits if normed[i] == target] or hits)[0]] = target
    used, extra = set(names), 0
    for i, field in enumerate(header):
        if names[i] or not field.strip():
            continue
        if normed[i] in RESERVED and normed[i] not in used:
            names[i] = normed[i]
        elif extra < MAX_EXTRA:
            slug = base = "in_" + re.sub("[^A-Za-z0-9_]", "_", field)[:40]
            k = 1
            while slug in used:
                k += 1
                slug = f"{base}_{k}"
            names[i], extra = slug, extra + 1
        used.add(names[i])
    return names


def _open(path):
    with open(path, "rb") as f:
        gz = f.read(2) == b"\x1f\x8b"
    return (gzip.open if gz else open)(path, "rt", errors="replace", newline=""), gz


def _delim(line):
    return "\t" if "\t" in line else "," if "," in line else ";" if ";" in line else " "


def _split(line, delim):
    return line.split() if delim == " " else next(csv.reader([line], delimiter=delim))


def _is_header(line):
    return any(norm(f) in ALIASES["chrom"] + ALIASES["pos"] for f in _split(line, _delim(line)))


def detect(path, header_lines=200):
    """Layout of a SNP file, a dict: format, delim (' ' = runs of whitespace), skip (lines before the data),
    header (fields), names (output name per field, None = not read), dropped (fields over MAX_EXTRA), gzip.
    Looks at the first header_lines lines within DETECT_CHARS. Raises InputError with the accepted layouts if it
    can't tell, or if the file can't be read."""
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
    layout = {"gzip": gz, "dropped": []}
    # Other tables may start with '#CHROM' too: only VCF's own next columns make it a VCF
    vcf_header = any(line.startswith("#CHROM\t") and list(map(norm, line.split("\t")[1:5])) == ["pos", "id", "ref", "alt"]
                     for line in lines)
    if name.endswith(".vcf") or vcf_header or any(line.startswith("##fileformat=VCF") for line in lines):
        header = ["chrom", "pos", "id", "ref", "alt"]
        return {**layout, "format": "vcf", "delim": "\t", "skip": 0, "header": header, "names": header}
    for ext, header in PLINK.items():
        if name.endswith("." + ext):
            return {**layout, "format": "plink_" + ext, "delim": " ", "skip": 0, "header": header, "names": header}
    if name.endswith(".bed"):  # 0-based start, 1-based end: a SNP is the 1-bp interval ending at pos
        skip = 0
        while skip < len(lines) and (not lines[skip].strip() or lines[skip].startswith(("#", "track", "browser"))
                                     or _is_header(lines[skip])):
            skip += 1
        return {**layout, "format": "bed", "delim": " ", "skip": skip, "header": ["chrom", "start", "end", "name"],
                "names": ["chrom", None, "pos", "id"]}
    sections = [i for i, line in enumerate(lines) if line.split(",")[0].strip() == "[Assay]"]
    if sections:  # Illumina manifest: the [Assay] table, up to the next [section] (cut in source()); SNP holds [A/G]
        skip = sections[0] + 2
        if skip > len(lines):
            raise InputError("The manifest's [Assay] section has no header line. " + ACCEPTED)
        header = _split(lines[skip - 1], ",")
        names = column_names(header, {i: "_alleles" for i, h in enumerate(header) if norm(h) == "snp"})
        return {**layout, "format": "illumina_manifest", "delim": ",", "skip": skip, "header": header, "names": names,
                "dropped": _dropped(header, names)}
    i = 0
    while i < len(lines) and (not lines[i].strip() or lines[i].startswith("#") and not _is_header(lines[i])):
        i += 1
    if i == len(lines):
        raise InputError("The file has no SNP rows. " + ACCEPTED)
    delim = _delim(lines[i])
    fields = _split(lines[i], delim)
    axiom = any(line.startswith("#%") for line in lines[:i]) or "probe_set_id" in map(norm, fields)
    fmt = "axiom_annotation" if axiom else {"\t": "tsv", ",": "csv", ";": "csv", " ": "text"}[delim]
    names = column_names(fields)
    k = names.index("id") if "id" in names else None  # rs IDs in an id column can stand in for chrom and pos
    rs = k is not None and any(len(r) > k and RS.match(r[k].strip())
                               for r in (_split(line, delim) for line in lines[i + 1:i + 21] if line.strip()))
    if _is_header(lines[i]) or rs:
        if ("chrom" not in names or "pos" not in names) and not rs:
            raise InputError("The header has no recognised chromosome and position columns. " + ACCEPTED)
        return {**layout, "format": fmt, "delim": delim, "skip": i + 1, "header": fields, "names": names,
                "dropped": _dropped(fields, names)}
    if RS.match(fields[0].strip()):  # rs IDs without a header (other columns kept as in_col2, ...)
        header = ["id"] + [f"col{k + 1}" for k in range(1, len(fields))]
        return {**layout, "format": fmt + "_noheader", "delim": delim, "skip": i, "header": header,
                "names": column_names(header)}
    if len(fields) >= 2 and fields[1].strip().isdigit():
        header = HEADERLESS.get(len(fields), ["chrom", "pos", "id", "ref", "alt"])
        header = header + [f"col{k + 1}" for k in range(len(header), len(fields))]
        return {**layout, "format": fmt + "_noheader", "delim": delim, "skip": i, "header": header,
                "names": column_names(header)}
    raise InputError("The file layout was not recognised. " + ACCEPTED)


def _dropped(header, names):
    return [h for h, n in zip(header, names) if n is None and h.strip()]


def source(path, layout, limit=None):
    """SQL reading a SNP file in `layout` (from detect) as VARCHAR columns: chrom, pos, then the rest by output name.
    At most `limit` rows are read (a manifest's [Assay] table ends at the next '[section]' line within them)."""
    names, skip, fmt = layout["names"], layout["skip"], layout["format"]
    gz = ", compression='gzip'" if layout["gzip"] else ", compression='none'"
    cap = "" if limit is None else f" LIMIT {int(limit)}"
    if fmt == "vcf":  # first 5 columns only: genotypes are never read
        return f"""SELECT chrom, pos, nullif(id, '.') AS id, ref, nullif(alt, '.') AS alt
                   FROM read_csv({lit(path)}, header=false, all_varchar=true, delim='\t', comment='#', quote='',
                                 names=['chrom', 'pos', 'id', 'ref', 'alt'], null_padding=true{gz}){cap}"""
    if layout["delim"] == " ":  # runs of spaces or tabs: read whole lines and split them
        missing = "'0'" if fmt.startswith("plink") else "''"
        expr = {}
        if fmt == "bed":  # only 1-bp intervals give a pos (their end); longer ones are rejected as bad_pos
            expr["pos"] = "CASE WHEN try_cast(f[3] AS BIGINT) = try_cast(f[2] AS BIGINT) + 1 THEN f[3] END"
        fields = ", ".join(f"{expr.get(n, f'nullif(f[{i + 1}], {missing})')} AS {q(n)}" for i, n in enumerate(names) if n)
        src = f"""(SELECT string_split_regex(trim(line), '\\s+') AS f FROM read_csv({lit(path)}, header=false,
                   columns={{'line': 'VARCHAR'}}, delim='\x01', quote='', escape='', auto_detect=false, skip={skip}{gz})
                   WHERE trim(line) <> '' AND NOT starts_with(line, '#'))"""
    else:
        columns = ", ".join(f"{lit(n or f'_skip{i}')}: 'VARCHAR'" for i, n in enumerate(names))
        fields = ", ".join(q(n) for n in names if n)
        src = f"""read_csv({lit(path)}, header=false, columns={{{columns}}}, delim={lit(layout['delim'])}, quote='"',
                          escape='"', auto_detect=false, skip={skip}, null_padding=true{gz})"""
    if "_alleles" in names:
        fields = fields.replace(q("_alleles"), r"""regexp_extract(_alleles, '\[([^/]+)/([^\]]+)\]', 1) AS ref,
                                                  regexp_extract(_alleles, '\[([^/]+)/([^\]]+)\]', 2) AS alt""")
    if fmt == "illumina_manifest":  # drop every row from the first one starting '[' (rows stay in file order)
        first = q(names[0] or "_skip0")
        src = f"""(SELECT * EXCLUDE (_end) FROM (
                       SELECT *, bool_or(starts_with({first}, '[')) OVER (ROWS UNBOUNDED PRECEDING) AS _end
                       FROM (SELECT * FROM {src}{cap})) WHERE NOT _end)"""
        cap = ""
    missing = "".join(f"NULL::VARCHAR AS {n}, " for n in ("chrom", "pos") if n not in names)  # a list of rs IDs
    return f"SELECT chrom, pos, * EXCLUDE (chrom, pos) FROM (SELECT {missing}{fields} FROM {src}{cap})"
