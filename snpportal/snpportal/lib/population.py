"""The user's own population (ROADMAP I9): per-SNP allele counts from their genotypes (a VCF) or a table of allele
frequencies, so a panel can be judged by the fish it is for rather than the pooled public panel. Genotypes are read as
the file streams and only counts are kept: af (ALT frequency), maf, n (fish with a call), call_rate and hwe_p (exact
test, Wigginton et al. 2005). Local installs only; the caller deletes the upload once counted."""
from __future__ import annotations

import csv
import gzip
import io
import re
from pathlib import Path

import duckdb

from snpscore.formats import InputError, lit

COLUMNS = ("chrom", "pos", "ref", "alt", "af", "maf", "n", "call_rate", "hwe_p")
TABLE_NAMES = {"chrom": ("chrom", "chr", "chromosome", "#chrom"), "pos": ("pos", "bp", "position"), "ref": ("ref",),
               "alt": ("alt",), "af": ("af", "alt_af", "alt_freq", "alt_freqs", "freq"), "maf": ("maf",),
               "n": ("n", "ns", "nchrobs", "obs_ct")}


def hwe_p(het, hom1, hom2):
    """Exact two-sided Hardy-Weinberg p for one SNP's genotype counts (Wigginton, Cutler and Abecasis 2005)."""
    n = het + hom1 + hom2
    if n == 0:
        return None
    homr, homc = sorted((hom1, hom2))
    rare = 2 * homr + het
    probs = [0.0] * (rare + 1)
    mid = rare * (2 * n - rare) // (2 * n)
    if mid % 2 != rare % 2:
        mid += 1
    probs[mid], total = 1.0, 1.0
    h, r, c = mid, (rare - mid) // 2, n - mid - (rare - mid) // 2
    while h >= 2:  # fewer heterozygotes
        probs[h - 2] = probs[h] * h * (h - 1) / (4.0 * (r + 1) * (c + 1))
        total += probs[h - 2]
        h, r, c = h - 2, r + 1, c + 1
    h, r, c = mid, (rare - mid) // 2, n - mid - (rare - mid) // 2
    while h <= rare - 2:  # more heterozygotes
        probs[h + 2] = probs[h] * 4.0 * r * c / ((h + 2) * (h + 1))
        total += probs[h + 2]
        h, r, c = h + 2, r - 1, c - 1
    return min(1.0, sum(p for p in probs if p <= probs[het] * (1 + 1e-9)) / total)


def _open_text(path):
    raw = open(path, "rb")
    head = raw.read(2)
    raw.seek(0)
    return io.TextIOWrapper(gzip.GzipFile(fileobj=raw) if head == b"\x1f\x8b" else raw, encoding="utf-8", errors="replace")


def vcf_rows(path):
    """(chrom, pos, ref, alt, af, maf, n, call_rate, hwe_p) per biallelic SNP of a VCF with genotypes."""
    samples = None
    with _open_text(path) as f:
        for line in f:
            if line.startswith("##"):
                continue
            fields = line.rstrip("\n\r").split("\t")
            if line.startswith("#CHROM"):
                samples = len(fields) - 9
                if samples < 1:
                    raise InputError("This VCF has no genotype columns: give one with the fish's genotypes, or a table of "
                                     "allele frequencies.")
                continue
            if samples is None or len(fields) < 10:
                continue
            chrom, pos, _, ref, alt = fields[:5]
            if len(ref) != 1 or len(alt) != 1 or ref == "." or alt == ".":
                continue  # biallelic SNPs only
            fmt = fields[8].split(":")
            gi = fmt.index("GT") if "GT" in fmt else 0
            hom_ref = het = hom_alt = 0
            for s in fields[9:]:
                gt = s.split(":")[gi] if gi else s.split(":", 1)[0]
                a = re.split(r"[/|]", gt)
                if len(a) != 2 or "." in a or not all(x in ("0", "1") for x in a):
                    continue  # missing, haploid or another allele
                k = a.count("1")
                hom_ref, het, hom_alt = hom_ref + (k == 0), het + (k == 1), hom_alt + (k == 2)
            n = hom_ref + het + hom_alt
            af = round((het + 2 * hom_alt) / (2 * n), 6) if n else None
            yield (chrom, int(pos), ref.upper(), alt.upper(), af, None if af is None else round(min(af, 1 - af), 6), n,
                   round(n / samples, 6), hwe_p(het, hom_ref, hom_alt))


def table_rows(path):
    """(chrom, pos, ref, alt, af, maf, n, None, None) from a frequency table with a header (chrom, pos, and af or maf;
    ref, alt and n optional; tabs, commas or spaces)."""
    with _open_text(path) as f:
        sample = f.read(65536)
        f.seek(0)
        delim = "\t" if "\t" in sample else "," if "," in sample.splitlines()[0] else " "
        reader = csv.reader(f, delimiter=delim, skipinitialspace=delim == " ")
        header = [h.strip().lower() for h in next(reader)]
        col = {k: next((header.index(a) for a in names if a in header), None) for k, names in TABLE_NAMES.items()}
        if col["chrom"] is None or col["pos"] is None or (col["af"] is None and col["maf"] is None):
            raise InputError("A frequency table needs a header with chrom and pos columns, and af (ALT allele frequency) "
                             "or maf.")
        num = lambda row, k: float(row[col[k]]) if col[k] is not None and row[col[k]] not in ("", ".", "NA") else None  # noqa: E731
        for row in reader:
            try:
                af = num(row, "af")
                maf = num(row, "maf") if af is None else round(min(af, 1 - af), 6)
                n = num(row, "n")
                yield (row[col["chrom"]], int(float(row[col["pos"]])),
                       row[col["ref"]].upper() if col["ref"] is not None else None,
                       row[col["alt"]].upper() if col["alt"] is not None else None, af, maf,
                       None if n is None else int(n), None, None)
            except (ValueError, IndexError):
                continue


def count(path, release_dir, out):
    """Count the population file at `path` (a VCF with genotypes, else a frequency table) into `out` (Parquet with
    COLUMNS, chromosomes through the release's aliases, one row per position and allele pair). Returns {format,
    sites, fish (VCF only)}. Nothing but these counts is written."""
    with _open_text(path) as f:
        start = f.read(4096)
    is_vcf = start.startswith("##fileformat=VCF") or "\n#CHROM\t" in start or start.startswith("#CHROM\t")
    rows = vcf_rows(path) if is_vcf else table_rows(path)
    out = Path(out)
    tmp = out.with_name(f".{out.name}.tsv")
    fish = None
    with open(tmp, "w", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        for r in rows:
            w.writerow(["" if x is None else x for x in r])
    if is_vcf:
        with _open_text(path) as f:
            fish = next((len(line.split("\t")) - 9 for line in f if line.startswith("#CHROM")), None)
    con = duckdb.connect()
    alias = Path(release_dir) / "alias.parquet"
    rename = (f"coalesce((SELECT a.chrom FROM read_parquet({lit(alias)}) a WHERE a.alias = lower(t.chrom) LIMIT 1), t.chrom)"
              if alias.exists() else "t.chrom")
    types = "{'chrom': 'VARCHAR', 'pos': 'BIGINT', 'ref': 'VARCHAR', 'alt': 'VARCHAR', 'af': 'DOUBLE', 'maf': 'DOUBLE', " \
            "'n': 'BIGINT', 'call_rate': 'DOUBLE', 'hwe_p': 'DOUBLE'}"
    try:
        con.execute(f"""COPY (SELECT {rename} AS chrom, * EXCLUDE (chrom) FROM read_csv({lit(tmp)}, delim='\t', header=false,
                        columns={types}, nullstr='') t
                        QUALIFY row_number() OVER (PARTITION BY chrom, pos, ref, alt ORDER BY n DESC NULLS LAST) = 1
                        ORDER BY TRY_CAST(chrom AS INTEGER), chrom, pos) TO {lit(out)} (FORMAT parquet)""")
        sites = con.execute(f"SELECT count(*) FROM read_parquet({lit(out)})").fetchall()[0][0]
    finally:
        con.close()
        tmp.unlink(missing_ok=True)
    if not sites:
        raise InputError("No SNPs with allele counts or frequencies were found in this file.")
    return {"format": "VCF genotypes" if is_vcf else "frequency table", "sites": sites, "fish": fish}


def join_sql(view, pops):
    """SQL adding pop_<slug>_{af, maf, n, call_rate, hwe_p} to `view` (chrom, pos, ref, alt) for pops [(slug, parquet)]:
    matched on position and alleles, the frequency turned to the view's alt when the alleles are swapped; a table
    without alleles matches on position."""
    cols = joins = ""
    for i, (slug, path) in enumerate(pops):
        t, c = f"p{i}", f"pop_{slug}_"
        swapped = f"({t}.ref = v.alt AND {t}.alt = v.ref)"
        cols += (f", CASE WHEN {swapped} THEN 1 - {t}.af ELSE {t}.af END AS \"{c}af\", {t}.maf AS \"{c}maf\", "
                 f"{t}.n AS \"{c}n\", {t}.call_rate AS \"{c}call_rate\", {t}.hwe_p AS \"{c}hwe_p\"")
        joins += (f" LEFT JOIN read_parquet({lit(path)}) {t} ON {t}.chrom = v.chrom AND {t}.pos = v.pos AND "
                  f"({t}.ref IS NULL OR ({t}.ref = v.ref AND {t}.alt = v.alt) OR {swapped})")
    return f"SELECT v.*{cols} FROM {view} v{joins}"
