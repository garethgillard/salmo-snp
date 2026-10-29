"""GWAS summary statistics (ROADMAP M7): read and harmonise them (P7.1), lambda_GC, Manhattan and QQ data, greedy
distance clumping into loci (P7.2) and Wakefield approximate Bayes factor fine-mapping with a uniform or a functional
prior (P7.4). DuckDB SQL plus the stdlib; the portal draws the figures.

Accepted: GCTA-fastGWA, PLINK2 .glm, regenie, BOLT-LMM, GEMMA and any table whose header names a chromosome, a position
and p (or LOG10P, a z/t statistic, or beta and se), optionally id, alleles, beta, se, allele frequency and N (ALIASES).
Effects are per copy of the effect allele: A1/ALLELE1/effect_allele, else alt. After annotate, attach() turns the
alleles to the Ssal_v3.1 reference (ref = genome base, alt = effect allele; beta, z and af follow), using the genome
where it has sequence, else the public 12-fish sites.

    snpscore gwas sumstats.tsv --release release/dev --trait maturation -o gwas_out/
"""
from __future__ import annotations

import argparse
import json
import math
import os
import zlib
from pathlib import Path

import duckdb

from .annotate import annotate, connect, user_message
from .formats import InputError, TooMany, _delim, _open, _split, lit, norm, q, source
from .score import load_weights

CHI2_MEDIAN = 0.4549364231195724  # median of a chi-square with 1 df: lambda_GC = median(z^2) / this
# Fine-mapping and loci defaults; weights.yaml 'finemap' (PROVISIONAL) overrides them, the portal's form overrides that.
DEFAULTS = {"prior_sd": 0.2, "functional_lambda": 0.5, "coverage": 0.95, "significant": 5e-8, "suggestive": 1e-5,
            "window": 1_000_000, "near_lead": 2.0, "trait_sd": 1.0}
TRAIT_SD_RATIO = 2.0  # PROVISIONAL: warn when the trait SD used and the one se, N and af imply differ more than this
ALIASES = {  # canonical column -> header names (formats.norm), first match wins
    "chrom": ("chrom", "chr", "chromosome", "chr_name", "chromosome_name"),
    "pos": ("pos", "bp", "position", "base_pair_location", "ps", "physical_position", "genpos"),  # BOLT GENPOS is cM: BP wins
    "id": ("id", "snp", "rsid", "rs", "variant_id", "markername", "marker", "snp_id", "name"),
    "ea": ("a1", "allele1", "effect_allele", "ea", "tested_allele"),
    "oa": ("a2", "allele0", "allele2", "other_allele", "oa", "omitted", "nea", "non_effect_allele"),
    "ref": ("ref",),
    "alt": ("alt",),
    "beta": ("beta", "b", "effect", "estimate"),
    "or": ("or", "odds_ratio"),
    "se": ("se", "stderr", "standard_error", "se_beta", "sebeta", "log_or_se"),
    "p": ("p", "pval", "p_value", "pvalue", "p_bolt_lmm", "p_bolt_lmm_inf", "p_wald", "p_lrt", "p_score"),
    "log10p": ("log10p", "log10_p", "neglog10p", "neg_log10_p", "mlog10p", "minus_log10_p", "neglog10_pval"),
    "z": ("z", "zscore", "z_score", "z_stat", "zstat", "t_stat", "stat"),
    "af": ("af", "af1", "a1freq", "a1_freq", "eaf", "freq", "freq1", "effect_allele_frequency", "frq", "maf"),
    "n": ("n", "obs_ct", "n_obs", "neff", "samplesize", "n_total", "total_n"),
    "test": ("test",),
}
KINDS = [  # format name -> header names that identify it (any one set)
    ("BOLT-LMM", [{"p_bolt_lmm"}, {"p_bolt_lmm_inf"}]),
    ("regenie", [{"allele0", "allele1", "log10p"}, {"allele0", "allele1", "genpos"}]),
    ("GEMMA", [{"p_wald"}, {"ps", "allele1", "allele0"}]),
    ("PLINK2 .glm", [{"obs_ct"}, {"a1", "ref", "alt"}]),
    ("GCTA-fastGWA", [{"af1", "a1", "a2"}]),
]
ACCEPTED = ("GWAS summary statistics need a header naming the chromosome (CHR, CHROM), the position (POS, BP) and p "
            "(P, LOG10P, a z or t statistic, or BETA and SE). GCTA-fastGWA, PLINK2 .glm, regenie, BOLT-LMM and GEMMA "
            "files are read as they are; alleles (A1/A2, REF/ALT), BETA, SE, allele frequency and N are optional.")
REASONS = ("missing_chrom", "bad_pos", "unknown_chrom", "other_test", "bad_p", "no_p", "duplicate")
FM_COLUMNS = ("file_row_number", "id", "ref", "alt", "beta", "se", "z", "neglog10p", "af", "n", "harmonised", "tier",
              "tier_score", "tier_evidence", "region_class", "gene_name", "gene_ortholog_human", "gene_id", "lore")  # kept in fm


# ---- normal-distribution helpers in SQL (no underflow: p is carried as -log10 p) ----

def _horner(x, coefs):
    out = repr(coefs[0])
    for c in coefs[1:]:
        out = f"({out} * {x} + {c!r})"
    return out


_ERFC = [0.17087277, -0.82215223, 1.48851587, -1.13520398, 0.27886807, -0.18628806, 0.09678418, 0.37409196,
         1.00002368, -1.26551223]  # Numerical Recipes erfcc: fractional error < 1.2e-7 everywhere
_A = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02, 1.383577518672690e+02,
      -3.066479806614716e+01, 2.506628277459239e+00]  # Acklam's inverse normal: relative error < 1.2e-9
_B = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02, 6.680131188771972e+01,
      -1.328068155288572e+01, 1.0]
_C = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00, -2.549732539343734e+00,
      4.374664141464968e+00, 2.938163982698783e+00]
_D = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00, 3.754408661907416e+00, 1.0]


def nlp_from_z_sql(z):
    """SQL: -log10 of the two-sided p of z, computed as log erfc(|z|/sqrt 2), so |z| = 60 gives 783.6, not inf."""
    x = f"(abs({z}) / sqrt(2))"
    t = f"(1 / (1 + 0.5 * {x}))"
    return f"(-(ln({t}) - {x} * {x} + {_horner(t, _ERFC)}) / ln(10))"


def z_from_nlp_sql(nlp):
    """SQL: |z| whose two-sided p has -log10 p = nlp (also for p = 1e-400)."""
    tail = f"({nlp} + log10(2))"  # -log10 of the one-sided p
    qq = f"sqrt(2 * ln(10) * {tail})"
    u = f"(0.5 * pow(10, -{nlp}) - 0.5)"
    r = f"({u} * {u})"
    return (f"(CASE WHEN {tail} > 1.6154 THEN -{_horner(qq, _C)} / {_horner(qq, _D)} "
            f"ELSE -{_horner(r, _A)} * {u} / {_horner(r, _B)} END)")


def p_text(nlp):
    """'3.2e-400' for -log10 p = 399.49: p as text without underflow."""
    if nlp is None:
        return ""
    if nlp < 4:
        return f"{10 ** -nlp:.3g}"
    e = math.floor(nlp)
    m = 10 ** (e - nlp)
    if m < 1:
        m, e = m * 10, e + 1
    return f"{m:.2g}e-{e}"


def settings(weights=None, report=None, **changes):
    """DEFAULTS, then the weights.yaml 'finemap' block, then the trait SD the statistics imply (the gwas.json `report`'s
    trait_sd_estimate), then `changes` (None values are ignored); `trait_sd_source` says which one set the trait SD.
    This is what gwas.json 'finemap' records and export.methods_text(finemap=) describes."""
    cfg = dict(DEFAULTS)
    cfg.update((weights or {}).get("finemap") or {})
    cfg["trait_sd_source"] = "weights.yaml (1 = a standardised trait)"
    if (report or {}).get("trait_sd_estimate"):
        cfg["trait_sd"], cfg["trait_sd_source"] = report["trait_sd_estimate"], "estimated from se, N and allele frequency"
    changes = {k: v for k, v in changes.items() if v is not None}
    cfg.update(changes)
    if "trait_sd" in changes:
        cfg["trait_sd_source"] = "given"
    return cfg


def trait_sd_implied(report, cfg):
    """The trait SD that se, N and af imply (report's trait_sd_estimate, median se x sqrt(2 N af (1 - af)), as coloc
    estimates sdY) when it differs more than TRAIT_SD_RATIO times from cfg's trait_sd (the SD fine-mapping divides the
    betas by), else None. W is on the SD scale: with betas in phenotype units and trait_sd 1, every Bayes factor is
    about 1 and the prior alone ranks the SNPs."""
    est, sd = (report or {}).get("trait_sd_estimate"), float(cfg["trait_sd"])
    return est if est and max(est / sd, sd / est) > TRAIT_SD_RATIO else None


def trait_sd_warning(report, cfg):
    """A sentence when trait_sd_implied() finds the trait SD used far from the implied one, else None."""
    est = trait_sd_implied(report, cfg)
    if est is None:
        return None
    return (f"Fine-mapping divides the betas by a trait SD of {float(cfg['trait_sd']):.3g}, but their se, N and allele "
            f"frequency imply {est:.3g}: PIPs and credible sets are only meaningful with the trait's own SD.")


# ---- reading ----

def column_names(header):
    """Canonical name per header field (None = not read)."""
    normed = [norm(h) for h in header]
    names = [None] * len(header)
    for target, aliases in ALIASES.items():
        hit = next((normed.index(a) for a in aliases if a in normed and names[normed.index(a)] is None), None)
        if hit is not None:
            names[hit] = target
    return names


def detect(path, header_lines=200):
    """Layout for formats.source(): the header is the first line naming a chromosome and a position column (comment
    lines before it are skipped), plus the format's name."""
    lines = []
    try:
        f, gz = _open(path)
        with f:
            for _ in range(header_lines):
                line = f.readline(1 << 16)
                if not line:
                    break
                lines.append(line.rstrip("\r\n"))
    except (OSError, EOFError, zlib.error):
        raise InputError("The file could not be read: it is not text, or a damaged .gz file.") from None
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        delim = _delim(line)
        fields = _split(line, delim)
        names = column_names(fields)
        if "chrom" in names and "pos" in names:
            if not ({"p", "log10p", "z"} & set(names) or "se" in names and ({"beta", "or"} & set(names))):
                raise InputError("The header has no p-value column. " + ACCEPTED)
            normed = {norm(h) for h in fields}
            kind = next((k for k, sets in KINDS if any(s <= normed for s in sets)), "generic table")
            return {"format": kind, "delim": delim, "skip": i + 1, "header": fields, "names": names, "gzip": gz,
                    "dropped": [], "synthetic": any(x.startswith("# SYNTHETIC") for x in lines[:i])}
    raise InputError(ACCEPTED)


def read(con, path, known=(), alias=None, max_snps=None):
    """Load summary statistics into table `ss` (row, chrom, pos, id, ea, oa, beta, se, z, z_from_p, neglog10p, af, n):
    chromosomes through `alias`, rows on other chromosomes than `known` dropped (unplaced scaffolds), one SELECT
    deriving z (beta/se, else the z column, else from p) and -log10 p (from the p text, mantissa and exponent apart, so
    1e-400 stays 400; else LOG10P; else from z). Returns the validation report."""
    layout = detect(path)
    names = [n for n in layout["names"] if n]
    limit = int(max_snps) + 1 if max_snps else None
    con.execute(f"CREATE OR REPLACE TEMP TABLE raw AS SELECT row_number() OVER () AS row, * FROM ({source(path, layout, limit)})")
    rows = con.execute("SELECT count(*) FROM raw").fetchone()[0]
    if max_snps and rows > max_snps:
        raise TooMany(f"The file has more than {max_snps:,} rows. Split it, or run snpscore locally.")

    def text(c):
        return f"nullif(upper(trim(r.{q(c)})), '')" if c in names else "NULL::VARCHAR"

    def num(c):
        return f"try_cast(nullif(trim(r.{q(c)}), '') AS DOUBLE)" if c in names else "NULL::DOUBLE"

    ea, oa, ref, alt = text("ea"), text("oa"), text("ref"), text("alt")
    if "ea" not in names:  # no A1 column: the effect allele is alt, the other allele the given one, else ref
        ea, oa = alt, (oa if "oa" in names else ref)
    elif "oa" not in names and "ref" in names and "alt" in names:  # PLINK2 without OMITTED: the other of REF/ALT
        oa = f"CASE WHEN {ref} = {ea} THEN {alt} ELSE {ref} END"
    beta = num("beta") if "beta" in names else f"CASE WHEN {num('or')} > 0 THEN ln({num('or')}) END"
    p = f"lower(trim(r.{q('p')}))" if "p" in names else "NULL::VARCHAR"
    mant = f"try_cast(regexp_extract({p}, '^([0-9]*\\.?[0-9]+)(e[-+]?[0-9]+)?$', 1) AS DOUBLE)"
    expo = f"coalesce(try_cast(regexp_extract({p}, '^[0-9]*\\.?[0-9]+e([-+]?[0-9]+)$', 1) AS INTEGER), 0)"
    mapped, join = "trim(r.chrom)", ""
    if alias:
        mapped, join = "coalesce(a.chrom, trim(r.chrom))", f"LEFT JOIN read_parquet({lit(alias)}) a ON a.alias = lower(trim(r.chrom))"
    known_sql = f"chrom NOT IN ({', '.join(lit(c) for c in known)})" if known else "false"
    con.execute(f"""CREATE OR REPLACE TEMP TABLE parsed AS
        SELECT *, CASE WHEN z0 IS NOT NULL THEN z0 ELSE CASE WHEN beta < 0 THEN -1 ELSE 1 END * {z_from_nlp_sql('neglog10p')} END AS z,
               z0 IS NULL AND neglog10p IS NOT NULL AS z_from_p
        FROM (SELECT *, CASE WHEN nlp_p >= -1e-9 THEN greatest(nlp_p, 0) WHEN nlp_p IS NULL THEN coalesce(abs(log10p), {nlp_from_z_sql('z0')}) END AS neglog10p
              FROM (SELECT r.row, nullif({mapped}, '') AS chrom,
                           CASE WHEN regexp_full_match(trim(r.pos), '[0-9]+') THEN try_cast(trim(r.pos) AS BIGINT) END AS pos,
                           nullif(trim({'r.' + q('id') if 'id' in names else 'NULL'}), '') AS id, {ea} AS ea, {oa} AS oa,
                           {beta} AS beta, CASE WHEN {num('se')} > 0 THEN {num('se')} END AS se,
                           CASE WHEN {beta} IS NOT NULL AND {num('se')} > 0 THEN {beta} / {num('se')} ELSE {num('z')} END AS z0,
                           CASE WHEN {mant} > 0 THEN -(log10({mant}) + {expo}) END AS nlp_p, {mant} AS p_mant, {num('log10p')} AS log10p,
                           CASE WHEN {num('af')} BETWEEN 0 AND 1 THEN {num('af')} END AS af,
                           CASE WHEN {num('n')} > 0 THEN {num('n')} END AS n, {text('test')} AS test
                    FROM raw r {join}))""")
    con.execute(f"""CREATE OR REPLACE TEMP TABLE checked AS
        SELECT *, CASE WHEN chrom IS NULL THEN 'missing_chrom' WHEN pos IS NULL OR pos < 1 THEN 'bad_pos'
                       WHEN {known_sql} THEN 'unknown_chrom' WHEN test IS NOT NULL AND test <> 'ADD' THEN 'other_test'
                       WHEN nlp_p < -1e-9 OR p_mant = 0 AND neglog10p IS NULL THEN 'bad_p'
                       WHEN neglog10p IS NULL OR z IS NULL THEN 'no_p'
                       WHEN row_number() OVER (PARTITION BY chrom, pos, oa, ea ORDER BY row) > 1 THEN 'duplicate' END AS reason
        FROM parsed""")
    con.execute("""CREATE OR REPLACE TABLE ss AS SELECT row, chrom, pos, id, ea, oa, beta, se, z, z_from_p, neglog10p, af, n
                   FROM checked WHERE reason IS NULL ORDER BY row""")
    kept, with_beta, with_alleles, from_p, with_af_n, lam, top, sig, sd = con.execute(f"""SELECT count(*),
        count(*) FILTER (WHERE beta IS NOT NULL AND se IS NOT NULL), count(*) FILTER (WHERE ea IS NOT NULL AND oa IS NOT NULL),
        count(*) FILTER (WHERE z_from_p), count(*) FILTER (WHERE af IS NOT NULL AND n IS NOT NULL),
        median(z * z) / {CHI2_MEDIAN}, max(neglog10p), count(*) FILTER (WHERE neglog10p >= {-math.log10(DEFAULTS['significant'])}),
        median(se * sqrt(2 * n * af * (1 - af))) FILTER (WHERE af > 0 AND af < 1) -- the trait SD (se^2 ~ SD^2 / (2 N af (1-af)))
        FROM ss""").fetchone()
    dropped = dict(con.execute("SELECT reason, count(*) FROM checked WHERE reason IS NOT NULL GROUP BY 1 ORDER BY 2 DESC, 1").fetchall())
    report = {
        "format": layout["format"], "rows_read": rows, "kept": kept, "dropped": dropped,
        "unknown_chromosomes": [{"name": (n or "")[:40], "rows": c} for n, c in con.execute(
            "SELECT chrom, count(*) FROM checked WHERE reason = 'unknown_chrom' GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 10").fetchall()],
        "columns": {h: n for h, n in zip(layout["header"], layout["names"]) if n},
        "with_beta_se": round(with_beta / kept, 4) if kept else 0, "with_alleles": round(with_alleles / kept, 4) if kept else 0,
        "z_from_p": from_p, "with_af_n": with_af_n, "lambda_gc": round(lam, 4) if lam is not None else None,
        "max_neglog10p": round(top, 3) if top is not None else None, "min_p": p_text(top), "n_significant": sig,
        "trait_sd_estimate": float(f"{sd:.6g}") if sd else None, "synthetic": layout["synthetic"],
    }
    con.execute("DROP TABLE raw; DROP TABLE parsed; DROP TABLE checked")
    return report


def prepare(path, release_dir, out_dir, threads=2, memory_limit="2GB", max_snps=None):
    """Read summary statistics into <out_dir>/sumstats.parquet and write <out_dir>/gwas.json (the validation report)
    and <out_dir>/input.snps.tsv (chrom, pos, id, ref = other allele, alt = effect allele, row = the sumstats row,
    which annotate keeps as in_row for attach) for annotate. Returns the TSV's path. Problems with the file raise
    InputError with a safe message."""
    path, release, out = Path(path).resolve(), Path(release_dir).resolve(), Path(out_dir).resolve()
    manifest = json.loads((release / "manifest.json").read_text())
    alias = release / "alias.parquet"
    con = connect([path.parent, release], out, threads, memory_limit)
    snps = out / "input.snps.tsv"
    try:
        report = read(con, path, list(manifest.get("chrom_sizes") or []), alias if alias.exists() else None, max_snps)
        if report["kept"]:
            con.execute(f"COPY (SELECT * FROM ss ORDER BY row) TO {lit(out / 'sumstats.parquet')} (FORMAT parquet)")
            con.execute(f"COPY (SELECT chrom, pos, id, oa AS ref, ea AS alt, row FROM ss ORDER BY row) TO {lit(snps)} "
                        "(HEADER, DELIMITER '\t')")
    except duckdb.Error as e:
        if os.environ.get("SNPSCORE_DEBUG"):
            raise
        raise InputError(user_message(e)) from None
    finally:
        con.close()
    (out / "gwas.json").write_text(json.dumps(report, indent=1))
    if not report["kept"]:
        names = ", ".join(f"'{u['name']}' ({u['rows']})" for u in report["unknown_chromosomes"][:3])
        raise InputError("No rows have a Ssal_v3.1 chromosome (1-29 or an alias), a whole-number position and a usable p."
                         + (f" Most common chromosome names in the file: {names}." if names else ""))
    return snps


def attach(out_dir, threads=2, memory_limit="2GB"):
    """gwas.parquet: sumstats.parquet joined to annotate's result.parquet (file_row_number) by the sumstats row (in_row,
    which is then dropped from result.parquet), so rows that annotate moved from ICSASG_v2 by their rs ID keep their
    statistics. Positions and alleles are the annotated ones, turned to the Ssal_v3.1 reference: by the genome base
    where the genome has sequence, else by the public 12-fish site's alleles (public_af_alleles). Swapped rows get
    -beta, -z and 1 - af; strand flips are complemented; rows that can't be checked keep their alleles (harmonised =
    unchecked / mismatch / not_snp / no_alleles). Updates gwas.json."""
    d = Path(out_dir).resolve()
    tmp = d / f".result-{os.getpid()}.parquet"  # result.parquet without the in_row helper, in the same row order
    con = connect([d], d, threads, memory_limit)
    try:
        con.execute(f"CREATE VIEW r AS SELECT * FROM read_parquet({lit(d / 'result.parquet')}, file_row_number=true)")
        cols = [c for c, in con.execute("SELECT column_name FROM (DESCRIBE r)").fetchall()]
        gb = "r.genome_base" if "genome_base" in cols else "NULL"
        pa = "r.public_af_alleles" if "public_af_alleles" in cols else "NULL"
        flip = "translate({}, 'ACGT', 'TGCA')"
        status = f"""CASE WHEN ea IS NULL OR oa IS NULL THEN 'no_alleles'
            WHEN length(ea) <> 1 OR length(oa) <> 1 THEN 'not_snp'
            WHEN g IN ('A', 'C', 'G', 'T') THEN CASE WHEN oa = g THEN 'ok' WHEN ea = g THEN 'swapped'
                WHEN {flip.format('oa')} = g THEN 'strand_flip' WHEN {flip.format('ea')} = g THEN 'strand_flip_swapped'
                ELSE 'mismatch' END
            WHEN pa IN ('same', 'swapped', 'strand_flip', 'strand_flip_swapped') THEN replace(pa, 'same', 'ok')
            ELSE 'unchecked' END"""
        swap = "h IN ('swapped', 'strand_flip_swapped')"
        con.execute(f"""COPY (
            SELECT file_row_number, row, chrom, pos, id,
                   CASE h WHEN 'swapped' THEN ea WHEN 'strand_flip' THEN {flip.format('oa')}
                          WHEN 'strand_flip_swapped' THEN {flip.format('ea')} ELSE oa END AS ref,
                   CASE h WHEN 'swapped' THEN oa WHEN 'strand_flip' THEN {flip.format('ea')}
                          WHEN 'strand_flip_swapped' THEN {flip.format('oa')} ELSE ea END AS alt,
                   CASE WHEN {swap} THEN -beta ELSE beta END AS beta, se, CASE WHEN {swap} THEN -z ELSE z END AS z, z_from_p,
                   neglog10p, CASE WHEN {swap} THEN 1 - af ELSE af END AS af, n, h AS harmonised,
                   CASE WHEN g IN ('A', 'C', 'G', 'T') THEN 'genome' WHEN h IN ('ok', 'swapped', 'strand_flip', 'strand_flip_swapped')
                        THEN 'public sites' END AS harmonised_by
            FROM (SELECT *, {status} AS h FROM (
                SELECT r.file_row_number, r.chrom, r.pos, upper(r.ref) AS oa, upper(r.alt) AS ea, {gb} AS g, {pa} AS pa,
                       s.* EXCLUDE (chrom, pos, oa, ea)
                FROM read_parquet({lit(d / 'sumstats.parquet')}) s JOIN r ON r.in_row::BIGINT = s.row))
            ORDER BY row) TO {lit(d / 'gwas.parquet')} (FORMAT parquet)""")
        counts = dict(con.execute(f"SELECT harmonised, count(*) FROM read_parquet({lit(d / 'gwas.parquet')}) GROUP BY 1 ORDER BY 2 DESC").fetchall())
        con.execute(f"COPY (SELECT * EXCLUDE (file_row_number, in_row) FROM r) TO {lit(tmp)} (FORMAT parquet)")
        os.replace(tmp, d / "result.parquet")
    finally:
        con.close()
        tmp.unlink(missing_ok=True)
    report = json.loads((d / "gwas.json").read_text())
    report["harmonised"] = counts
    report["annotated"] = sum(counts.values())
    (d / "gwas.json").write_text(json.dumps(report, indent=1))
    return report


# ---- figures' data, loci and fine-mapping on a table or view with the gwas.parquet columns (+ tier, tier_score, ...) ----

def columns_of(con, table):
    return [c for c, in con.execute(f"SELECT column_name FROM (DESCRIBE {table})").fetchall()]


def lambda_gc(con, table, by=None):
    """lambda_GC = median(z^2) / 0.4549: a number, or {stratum: (n, lambda)} with `by` (an SQL expression)."""
    if by is None:
        return con.execute(f"SELECT median(z * z) / {CHI2_MEDIAN} FROM {table}").fetchone()[0]
    return {s: (n, lam) for s, n, lam in con.execute(
        f"SELECT {by}, count(*), median(z * z) / {CHI2_MEDIAN} FROM {table} WHERE z IS NOT NULL GROUP BY 1 ORDER BY 1").fetchall()}


def manhattan(con, table, thin_below=2.0, bin_bp=50_000):
    """[(chrom, pos, neglog10p, tier)] for a Manhattan plot: every SNP with -log10 p >= thin_below (p <= 0.01), else
    only the strongest per bin_bp bin."""
    tier = "tier" if "tier" in columns_of(con, table) else "NULL::INTEGER"
    return con.execute(f"""SELECT chrom, pos, neglog10p, {tier} FROM {table} WHERE neglog10p >= {thin_below}
        UNION ALL SELECT chrom, arg_max(pos, neglog10p), max(neglog10p), arg_max({tier}, neglog10p) FROM {table}
                  WHERE neglog10p < {thin_below} GROUP BY chrom, pos // {int(bin_bp)}""").fetchall()


def qq(con, table, by, keep=1000):
    """{stratum: {n, lambda, points [(expected, observed) -log10 p], band [(expected, low, high)]}} per value of the SQL
    expression `by`: the top `keep` ranks and about `keep` more spread over the rest. The band is the 95% interval of
    each order statistic (gamma approximation)."""
    lams = lambda_gc(con, table, by)
    out = {s: {"n": n, "lambda": lam, "points": [], "band": []} for s, (n, lam) in lams.items()}
    for s, n, r, nlp in con.execute(f"""SELECT s, n, r, nlp FROM (
            SELECT {by} AS s, neglog10p AS nlp, count(*) OVER (PARTITION BY {by}) AS n,
                   row_number() OVER (PARTITION BY {by} ORDER BY neglog10p DESC) AS r FROM {table} WHERE neglog10p IS NOT NULL)
            WHERE r <= {keep} OR r % greatest(1, n // {keep}) = 0 OR r = n ORDER BY s, r""").fetchall():
        if s not in out:
            continue
        e = -math.log10((r - 0.5) / n)
        out[s]["points"].append((e, nlp))
        lo, hi = _gamma_q(0.975, r) / n, _gamma_q(0.025, r) / n
        out[s]["band"].append((e, -math.log10(min(1.0, lo)), -math.log10(min(1.0, hi))))
    return out


def _gamma_q(prob, k):
    """Quantile of Gamma(k, 1): exact for k = 1, Wilson-Hilferty otherwise (for the QQ band)."""
    if k == 1:
        return -math.log(1 - prob)
    from statistics import NormalDist
    nu, zq = 2 * k, NormalDist().inv_cdf(prob)
    return nu * (1 - 2 / (9 * nu) + zq * math.sqrt(2 / (9 * nu))) ** 3 / 2


def _gene(cols, t="t"):
    parts = [f"{t}.{c}" for c in ("gene_name",) if c in cols]
    parts += [f"'~' || {t}.gene_ortholog_human" for c in ("gene_ortholog_human",) if c in cols]
    parts += [f"{t}.gene_id" for c in ("gene_id",) if c in cols]
    return f"coalesce({', '.join(parts)})" if parts else "NULL"


def clump(con, table, cfg=None):
    """Greedy distance clumping: the strongest SNP with p < suggestive leads a locus of every SNP within `window` bp;
    the strongest SNP outside all loci so far leads the next. Returns [{locus, chrom, lead, id, neglog10p, beta, se,
    significant, start, end (span of the locus' suggestive SNPs), lo, hi (lead +- window), n_snps, n_significant,
    and when the columns exist: n_tier12_near (tier 1-2 within near_lead log10 units of the lead), candidate (best
    tier_score there), candidate_tier, gene, candidate_gene, lore, row (the lead's file_row_number)}], strongest first.
    Leaves temp table `loci`."""
    cfg = cfg or settings()
    sugg, sig, win = -math.log10(cfg["suggestive"]), -math.log10(cfg["significant"]), int(cfg["window"])
    leads, taken = [], {}
    for chrom, pos, nlp in con.execute(f"SELECT chrom, pos, neglog10p FROM {table} WHERE neglog10p >= {sugg} "
                                       "ORDER BY neglog10p DESC, chrom, pos").fetchall():
        if not any(abs(pos - p) <= win for p in taken.get(chrom, ())):
            taken.setdefault(chrom, []).append(pos)
            leads.append((chrom, pos, nlp))
    if not leads:
        return []
    values = ", ".join(f"({i}, {lit(c)}, {p}, {nlp!r})" for i, (c, p, nlp) in enumerate(leads, 1))
    con.execute(f"CREATE OR REPLACE TEMP TABLE loci AS SELECT * FROM (VALUES {values}) l(locus, chrom, lead, lead_nlp)")
    cols = columns_of(con, table)
    label = "coalesce(t.id, t.chrom || ':' || t.pos)"
    near = f"t.neglog10p >= l.lead_nlp - {float(cfg['near_lead'])}"
    extra = []
    if "tier" in cols:
        extra.append(f"count(*) FILTER (WHERE t.tier <= 2 AND {near}) AS n_tier12_near")
    if "tier_score" in cols:
        extra += [f"arg_max({label}, t.tier_score * 10000 + least(t.neglog10p, 9999)) FILTER (WHERE {near}) AS candidate",
                  f"arg_max(t.tier, t.tier_score * 10000 + least(t.neglog10p, 9999)) FILTER (WHERE {near}) AS candidate_tier" if "tier" in cols else "NULL AS candidate_tier",
                  f"arg_max({_gene(cols)}, t.tier_score * 10000 + least(t.neglog10p, 9999)) FILTER (WHERE {near}) AS candidate_gene"]
    extra.append(f"arg_max({_gene(cols)}, t.neglog10p) FILTER (WHERE t.pos = l.lead) AS gene")
    if "file_row_number" in cols:
        extra.append("arg_max(t.file_row_number, t.neglog10p) FILTER (WHERE t.pos = l.lead) AS row")
    if "lore" in cols:
        extra.append("bool_or(t.lore) FILTER (WHERE t.pos = l.lead) AS lore")
    rows = con.execute(f"""SELECT l.locus, l.chrom, l.lead, arg_max({label}, t.neglog10p) FILTER (WHERE t.pos = l.lead) AS id,
               l.lead_nlp AS neglog10p, arg_max(t.beta, t.neglog10p) FILTER (WHERE t.pos = l.lead) AS beta,
               arg_max(t.se, t.neglog10p) FILTER (WHERE t.pos = l.lead) AS se, l.lead_nlp >= {sig} AS significant,
               min(t.pos) FILTER (WHERE t.neglog10p >= {sugg}) AS start, max(t.pos) FILTER (WHERE t.neglog10p >= {sugg}) AS "end",
               greatest(1, l.lead - {win}) AS lo, l.lead + {win} AS hi, count(*) AS n_snps,
               count(*) FILTER (WHERE t.neglog10p >= {sig}) AS n_significant, {', '.join(extra)}
        FROM loci l JOIN {table} t ON t.chrom = l.chrom AND t.pos BETWEEN l.lead - {win} AND l.lead + {win}
        GROUP BY l.locus, l.chrom, l.lead, l.lead_nlp ORDER BY l.locus""")
    names = [x[0] for x in rows.description]
    return [dict(zip(names, r)) for r in rows.fetchall()]


def finemap(con, table, loci, cfg=None):
    """Wakefield ABF fine-mapping per locus (lead +- window), assuming one causal variant and no LD:
    V = (se / trait_sd)^2, or 1 / (2 N af (1 - af)) without se; W = prior_sd^2;
    log ABF = 0.5 ln(V / (V + W)) + 0.5 z^2 W / (V + W); prior uniform, or functional pi ~ exp(lambda tier_score).
    PIPs come from a log-sum-exp window query; the credible set takes SNPs in descending PIP until `coverage`.
    Leaves temp table `fm` (locus, chrom, pos, id, ..., log_abf, pip_uniform, pip_functional, cs_uniform,
    cs_functional) and returns {locus: {n, size_uniform, size_functional, coverage_uniform, coverage_functional,
    prior_ratio, top_uniform, top_functional}}; n = 0 when no SNP has se, or N and af."""
    cfg = cfg or settings()
    if not loci:
        return {}
    w, lam, sd, cov = float(cfg["prior_sd"]) ** 2, float(cfg["functional_lambda"]), float(cfg["trait_sd"]), float(cfg["coverage"])
    cols = columns_of(con, table)
    score = "coalesce(t.tier_score, 0)" if "tier_score" in cols else "0"
    keep = ", ".join(f"t.{q(c)}" for c in FM_COLUMNS if c in cols)
    con.execute(f"""CREATE OR REPLACE TEMP TABLE fm AS
        WITH s AS (SELECT l.locus, t.chrom, t.pos, {keep}, {score} AS prior_score,
                          CASE WHEN t.se > 0 THEN pow(t.se / {sd}, 2)
                               WHEN t.n > 0 AND t.af > 0 AND t.af < 1 THEN 1.0 / (2 * t.n * t.af * (1 - t.af)) END AS v
                   FROM loci l JOIN {table} t ON t.chrom = l.chrom AND t.pos BETWEEN greatest(1, l.lead - {int(cfg['window'])})
                                                 AND l.lead + {int(cfg['window'])}
                   WHERE l.locus IN ({', '.join(str(x['locus']) for x in loci)}) AND t.z IS NOT NULL),
             a AS (SELECT *, 0.5 * ln(v / (v + {w})) + 0.5 * z * z * {w} / (v + {w}) AS log_abf FROM s WHERE v IS NOT NULL),
             b AS (SELECT *, exp(log_abf - max(log_abf) OVER l) AS bu,
                          exp(log_abf + {lam} * prior_score - max(log_abf + {lam} * prior_score) OVER l) AS bf
                   FROM a WINDOW l AS (PARTITION BY locus)),
             c AS (SELECT * EXCLUDE (bu, bf), bu / sum(bu) OVER l AS pip_uniform, bf / sum(bf) OVER l AS pip_functional
                   FROM b WINDOW l AS (PARTITION BY locus))
        SELECT *, sum(pip_uniform) OVER (PARTITION BY locus ORDER BY pip_uniform DESC, pos ROWS UNBOUNDED PRECEDING)
                  - pip_uniform < {cov} AS cs_uniform,
                  sum(pip_functional) OVER (PARTITION BY locus ORDER BY pip_functional DESC, pos ROWS UNBOUNDED PRECEDING)
                  - pip_functional < {cov} AS cs_functional
        FROM c""")
    label = "coalesce(id, chrom || ':' || pos)"
    out = {x["locus"]: {"n": 0, "size_uniform": None, "size_functional": None} for x in loci}
    for locus, n, su, sf, cu, cf, ratio, tu, pu, tf, pf in con.execute(f"""SELECT locus, count(*),
            count(*) FILTER (WHERE cs_uniform), count(*) FILTER (WHERE cs_functional),
            sum(pip_uniform) FILTER (WHERE cs_uniform), sum(pip_functional) FILTER (WHERE cs_functional),
            exp({lam} * (max(prior_score) - min(prior_score))), arg_max({label}, pip_uniform), max(pip_uniform),
            arg_max({label}, pip_functional), max(pip_functional) FROM fm GROUP BY locus ORDER BY locus""").fetchall():
        out[locus] = {"n": n, "size_uniform": su, "size_functional": sf, "coverage_uniform": cu, "coverage_functional": cf,
                      "prior_ratio": ratio, "top_uniform": tu, "pip_top_uniform": pu, "top_functional": tf, "pip_top_functional": pf}
    return out


# ---- the whole pipeline, for the command line and the tests ----

def run(sumstats, release_dir, out_dir, trait="all", threads=2, memory_limit="2GB", **changes):
    """sumstats -> out_dir: sumstats.parquet, result.parquet (annotate, tiers for `trait`), gwas.parquet, gwas.json
    (with the fine-mapping settings used, `finemap`, and any `warnings`), loci.tsv and finemap.tsv. `changes` override
    the fine-mapping settings (trait_sd defaults to the one se, N and af imply). Returns (report, loci, summary)."""
    release, out = Path(release_dir).resolve(), Path(out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    snps = prepare(sumstats, release, out, threads, memory_limit)
    try:
        annotate(snps, release, out / "result.parquet", trait=trait, threads=threads, memory_limit=memory_limit)
    finally:
        snps.unlink(missing_ok=True)
    report = attach(out, threads, memory_limit)
    cfg = settings(load_weights(), report, **changes)
    report["finemap"] = {k: cfg[k] for k in [*DEFAULTS, "trait_sd_source"]}
    report["warnings"] = [w for w in [trait_sd_warning(report, cfg)] if w]
    (out / "gwas.json").write_text(json.dumps(report, indent=1))
    con = connect([out], out, threads, memory_limit)
    try:
        con.execute(view_sql(out))
        loci = clump(con, "g", cfg)
        summary = finemap(con, "g", loci, cfg)
        for x in loci:
            x.update({k: v for k, v in summary.get(x["locus"], {}).items() if k.startswith("size_")})
        if loci:
            header = list(loci[0])
            (out / "loci.tsv").write_text("\t".join(header) + "\n" + "".join(
                "\t".join("" if x[k] is None else str(x[k]) for k in header) + "\n" for x in loci))
            con.execute(f"COPY (SELECT * FROM fm ORDER BY locus, pip_functional DESC) TO "
                        f"{lit(out / 'finemap.tsv')} (HEADER, DELIMITER '\t')")
    finally:
        con.close()
    return report, loci, summary


def view_sql(d, name="g"):
    """CREATE VIEW `name`: gwas.parquet with the tier columns and gene, region and LORe columns of result.parquet."""
    d = Path(d)
    return (f"CREATE OR REPLACE VIEW {name} AS SELECT g.*, r.* EXCLUDE (file_row_number, chrom, pos, id, ref, alt) "
            f"FROM read_parquet({lit(d / 'gwas.parquet')}) g JOIN read_parquet({lit(d / 'result.parquet')}, file_row_number=true) r "
            "USING (file_row_number)")


def main(argv=None):
    p = argparse.ArgumentParser(prog="snpscore gwas", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("sumstats")
    p.add_argument("--release", required=True)
    p.add_argument("--trait", default="all", help="trait preset whose tier_score sets the functional prior")
    p.add_argument("-o", "--out", default="gwas_out", help="folder for the outputs")
    for name in ("prior_sd", "functional_lambda", "coverage", "significant", "suggestive", "trait_sd"):
        p.add_argument("--" + name.replace("_", "-"), type=float, dest=name)
    p.add_argument("--window", type=int, help="bp either side of a lead SNP")
    p.add_argument("--threads", type=int, default=4)
    p.add_argument("--memory", default="4GB")
    args = p.parse_args(argv)
    changes = {k: getattr(args, k) for k in DEFAULTS if k not in ("near_lead",)}
    try:
        report, loci, summary = run(args.sumstats, args.release, args.out, args.trait, args.threads, args.memory, **changes)
    except InputError as e:
        raise SystemExit(f"error: {e}")
    print(f"{report['format']}: {report['kept']:,} of {report['rows_read']:,} rows kept, lambda_GC {report['lambda_gc']}; "
          f"trait SD {report['finemap']['trait_sd']:g} ({report['finemap']['trait_sd_source']})")
    for w in report["warnings"]:
        print("warning: " + w)
    for x in loci:
        s = summary.get(x["locus"], {})
        print(f"locus {x['locus']}: {x['chrom']}:{x['lead']} {x['id']} p {p_text(x['neglog10p'])}"
              f"{'' if x['significant'] else ' (suggestive)'}; credible set {s.get('size_uniform')} -> {s.get('size_functional')}")


if __name__ == "__main__":
    main()
