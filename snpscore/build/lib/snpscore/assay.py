"""Assay designability QC (P6.2): probe flanks from the soft-masked Ssal_v3.1 genome, with neighbouring public variants
as upper-case IUPAC codes (N for indels; KASP reads lower case as 'uncertain'), and pass / warn / fail / not_checked
rules from the weights.yaml 'assay' block (PROVISIONAL). annotate's sequence step reads the windows with iter_flanks()
and adds the columns with assay_sql(); export.py uses read_flanks() for the longer vendor flanks. Vendor rules
behind the defaults: docs/RESEARCH.md section 5."""
from __future__ import annotations

from .formats import lit, q

DEFAULTS = {  # weights.yaml 'assay' overrides these keys; PROVISIONAL, to confirm with the genotyping lab or vendor
    "flank": 35, "gc": [0.30, 0.70],
    "max_repeat": 0.9,  # soft-masked share; ~60% of the salmon genome is masked, so only a high share warns
    "max_homopolymer": 6,  # any base
    "homopolymer_by_base": None,  # optional, e.g. {G: 4, C: 4, A: 6, T: 6} (carp Axiom array, Xu 2014)
    "max_flank_variants": 0, "flank_variants_per_side": True,  # True: warn only when no side is clean (Axiom: one side)
    "warn_flags": ["lore", "blacklist", "strand_ambiguous"], "fail_ref_check": ["mismatch", "not_snp"],
}
REMOTE_MAX = 2000  # with a remote genome (HTTP ranges), longer lists are not_checked
BIN = 4096  # neighbour join: SNPs and public sites meet in fixed bins, so it is an equality join
IUPAC = {"A": "A", "C": "C", "G": "G", "T": "T", "AG": "R", "CT": "Y", "CG": "S", "AT": "W", "GT": "K", "AC": "M",
         "CGT": "B", "AGT": "D", "ACT": "H", "ACG": "V", "ACGT": "N"}
LABELS = {"lore": "LORe region", "blacklist": "blacklisted", "strand_ambiguous": "A/T or C/G (two probes)"}
TOPBOT_103 = "TOP/BOT cannot be determined (Illumina code 103)"
REF_CHECK = {"mismatch": "ref mismatch", "not_snp": "not a SNP", "swapped": "alleles swapped",
             "strand_flip": "alleles on the other strand"}


def rules(weights):
    """The assay rules: DEFAULTS updated with the weights.yaml 'assay' block."""
    return {**DEFAULTS, **((weights or {}).get("assay") or {})}


def iupac(alleles):
    """IUPAC code of a set of alleles ('N' when one of them is not a single base)."""
    bases = "".join(sorted(set(alleles)))
    return IUPAC.get(bases, "N") if all(len(a) == 1 for a in alleles) else "N"


def neighbours(con, chrom, flank, public_af):
    """({idx: {offset: [alleles]}}, {idx: 'REF/ALT'}) for the SNPs of `chrom` in table _flank_snps (idx, chrom, pos):
    the distinct alleles of the public variants within `flank` bp (offset 0 = the SNP's own position), and the public
    site at the SNP's own position with its REF/ALT order kept. One equality join through fixed-size bins."""
    f = int(flank)
    rows = con.execute(f"""
        WITH s AS (SELECT idx, pos, unnest(range((pos - {f}) // {BIN}, (pos + {f}) // {BIN} + 1)) AS bin
                   FROM _flank_snps WHERE chrom = $1),
        l AS (SELECT "end" AS p, ref, alt, "end" // {BIN} AS bin FROM read_parquet({lit(public_af)}) WHERE chrom = $1)
        SELECT s.idx, l.p - s.pos AS off, -- a string, not a list: DuckDB converts lists to Python slowly
               array_to_string(list_sort(list_distinct(flatten(list(string_split(l.ref || ',' || l.alt, ','))))), ','),
               min(l.ref || '/' || l.alt)
        FROM s JOIN l ON s.bin = l.bin AND abs(l.p - s.pos) <= {f}
        GROUP BY 1, 2""", [chrom]).fetchall()
    near, sites = {}, {}
    for idx, off, alleles, site in rows:
        near.setdefault(idx, {})[off] = alleles.split(",")
        if off == 0:
            sites[idx] = site
    return near, sites


def window(fasta, chrom, pos, flank, near=None):
    """(left, base, right, left_iupac, right_iupac) around 1-based pos: up to `flank` bases either side (clipped at
    the chromosome ends; base '' and no flanks beyond its end); the IUPAC versions are upper case, padded with N to
    `flank`, with the neighbouring public variants (near: {offset: alleles}) as IUPAC codes in lower case, which marks
    them for counting: assay_flank and the vendor files write them upper case."""
    start = max(0, pos - 1 - flank)
    seq = fasta.fetch(chrom, start, pos + flank)
    k = pos - 1 - start
    left, base, right = (seq[:k], seq[k], seq[k + 1:]) if k < len(seq) else ("", "", "")
    li, ri = list(left.upper().rjust(flank, "N")), list(right.upper().ljust(flank, "N"))
    for off, alleles in (near or {}).items():
        if -flank <= off < 0:
            li[flank + off] = iupac(alleles).lower()
        elif 0 < off <= flank:
            ri[off - 1] = iupac(alleles).lower()
    return left, base, right, "".join(li), "".join(ri)


def iter_flanks(con, fasta, rows, flank, public_af=None):
    """(idx, left, base, right, left_iupac, right_iupac, public site 'REF/ALT' or None) for the SNPs of the SQL relation
    `rows` (idx, chrom, pos) that are on the genome's chromosomes, in genome order (see window). One chromosome's
    SNPs and neighbours at a time, so a long list never sits in Python memory."""
    con.execute(f"CREATE OR REPLACE TEMP TABLE _flank_snps AS SELECT idx, chrom, pos FROM {rows} WHERE pos > 0")
    for chrom, in con.execute("SELECT DISTINCT chrom FROM _flank_snps ORDER BY chrom").fetchall():
        if chrom not in fasta.index:
            continue
        near, sites = neighbours(con, chrom, flank, public_af) if public_af else ({}, {})
        for idx, pos in con.execute("SELECT idx, pos FROM _flank_snps WHERE chrom = ? ORDER BY pos", [chrom]).fetchall():
            yield (idx,) + window(fasta, chrom, pos, flank, near.get(idx)) + (sites.get(idx),)


def read_flanks(con, fasta, rows, flank, public_af=None):
    """{idx: (left, base, right, left_iupac, right_iupac, public site 'REF/ALT' or None)} (see iter_flanks)."""
    return {x[0]: x[1:] for x in iter_flanks(con, fasta, rows, flank, public_af)}


def walk_sql(left, right):
    """SQL: the distance i of the first flank pair (n-i, n+i) with one A/T and one C/G base (Illumina's TOP/BOT walk for
    A/T and C/G SNPs; IUPAC codes, N and lower case are skipped), NULL when the flanks run out (Illumina code 103)."""
    five, three = f"substr({left}, length({left}) + 1 - i, 1)", f"substr({right}, i, 1)"
    return (f"list_filter(range(1, least(length({left}), length({right})) + 1), i -> ({five} IN ('A', 'T') AND {three} "
            f"IN ('C', 'G')) OR ({five} IN ('C', 'G') AND {three} IN ('A', 'T')))[1]")


def breakdown(con, rel):
    """{reason: SNPs} over the assay_reasons of `rel`, numbers stripped ('repeat 0.97' counts as 'repeat'), most
    frequent first; a SNP counts once per reason, so the counts add up to more than the SNPs that have reasons."""
    return dict(con.execute(rf"""SELECT regexp_replace(r, '\s*[0-9(].*$', '') AS reason, count(*) FROM (
        SELECT unnest(string_split(assay_reasons, '; ')) AS r FROM {rel}) GROUP BY 1 ORDER BY 2 DESC, 1""").fetchall())


def assay_sql(snps, windows, rules_, columns, disabled=None):
    """SQL adding assay_flank, assay_gc, assay_repeat, assay_homopolymer, assay_n, assay_status and assay_reasons to
    `snps` (annotate's table, with ref_check and the layer `columns`). `windows` has idx, base, lw, rw (genome flanks),
    li, ri (flanks with IUPAC codes, neighbours in lower case) and pub (public alleles at the SNP).
    `disabled` is the reason when nothing could be checked (a remote genome and a long list). Each reason starts with
    its name, then any numbers (see breakdown)."""
    lo, hi = rules_["gc"]
    flip = "translate({}, 'ACGT', 'TGCA')"
    alleles_known = "ref" in columns and "alt" in columns
    ref, alt = ("upper(s.ref)", "upper(s.alt)") if alleles_known else ("NULL::VARCHAR", "NULL::VARCHAR")
    shown = f"""CASE WHEN {ref} IS NULL THEN coalesce(w.pub, coalesce(upper(w.base), 'N') || '/?')
                     WHEN s.ref_check = 'strand_flip' THEN {flip.format(ref)} || '/' || coalesce({flip.format(alt)}, '?')
                     ELSE {ref} || '/' || coalesce({alt}, '?') END"""

    def longest(x, bases="ACGT"):  # longest single-base run
        runs = "|".join(b + "+" for b in bases)
        return f"coalesce(list_max(list_transform(regexp_extract_all(upper({x}), '{runs}'), r -> length(r))), 0)"

    def texts(cases):
        return f"list_filter([{', '.join(cases)}], x -> x IS NOT NULL)"

    fails = [f"CASE WHEN ref_check = {lit(c)} THEN {lit(REF_CHECK.get(c, c))} END" for c in rules_["fail_ref_check"]]
    fails.append("CASE WHEN assay_n > 0 THEN 'N in flank' END")
    k = int(rules_["max_flank_variants"])
    warns = [
        "CASE WHEN ref_check = 'strand_flip' THEN 'alleles on the other strand' END",
        "CASE WHEN _no_alleles THEN 'alleles unknown' END",
        f"CASE WHEN assay_gc < {float(lo)} OR assay_gc > {float(hi)} THEN 'GC ' || assay_gc END",
        f"CASE WHEN assay_repeat > {float(rules_['max_repeat'])} THEN 'repeat ' || assay_repeat END",
        f"CASE WHEN assay_homopolymer > {int(rules_['max_homopolymer'])} THEN 'homopolymer ' || assay_homopolymer END",
        f"CASE WHEN least(_nl, _nr) > {k} THEN 'flank variants on both sides ' || _nl || ' + ' || _nr END"
        if rules_.get("flank_variants_per_side") else
        f"CASE WHEN _nl + _nr > {k} THEN 'flank variants ' || (_nl + _nr) END",
        f"CASE WHEN _ambiguous AND _walk IS NULL AND assay_n = 0 THEN {lit(TOPBOT_103)} END",  # (N in flank fails)
    ]
    by_base = sorted((str(b).upper(), int(n)) for b, n in (rules_.get("homopolymer_by_base") or {}).items()
                     if str(b).upper() in ("A", "C", "G", "T"))
    for base, limit in by_base:
        warns.append(f"CASE WHEN _run_{base} > {limit} THEN '{base} run ' || _run_{base} END")
    for flag in rules_["warn_flags"]:
        if flag in columns:
            warns.append(f"CASE WHEN {q(flag)} THEN {lit(LABELS.get(flag, flag))} END")
        elif flag == "strand_ambiguous" and alleles_known:  # annotate adds this column after the assay checks
            warns.append(f"CASE WHEN upper(ref) || upper(alt) IN ('AT', 'TA', 'CG', 'GC') THEN {lit(LABELS[flag])} END")
    if disabled:
        status, reasons = "'not_checked'", lit(disabled)
    else:
        status = ("CASE WHEN NOT _checked THEN 'not_checked' WHEN len(_fails) > 0 THEN 'fail' "
                  "WHEN len(_warns) > 0 THEN 'warn' ELSE 'pass' END")
        reasons = ("CASE WHEN NOT _checked THEN 'chromosome not in the genome' "
                   "ELSE nullif(array_to_string(_fails || _warns, '; '), '') END")
    runs = "".join(f", greatest({longest('w.lw', b)}, {longest('w.rw', b)}) AS _run_{b}" for b, _ in by_base)
    helpers = ", ".join(["_checked", "_no_alleles", "_nl", "_nr", "_walk", "_ambiguous", "_fails", "_warns"]
                        + [f"_run_{b}" for b, _ in by_base])
    ambiguous = f"regexp_replace({shown}, '[^ACGT]', '', 'g') IN ('AT', 'TA', 'CG', 'GC')"
    neighbours = "length(regexp_replace(w.{}, '[^a-z]', '', 'g'))"  # neighbours are the lower-case codes in li/ri
    return f"""
        SELECT * EXCLUDE ({helpers}), {status} AS assay_status, {reasons} AS assay_reasons
        FROM (SELECT *, {texts(fails)} AS _fails, {texts(warns)} AS _warns FROM (
            SELECT s.*,
                   CASE WHEN w.idx IS NOT NULL THEN upper(w.li) || '[' || {shown} || ']' || upper(w.ri) END AS assay_flank,
                   round((length(w.g) - length(replace(replace(w.g, 'G', ''), 'C', '')))
                         / nullif(length(regexp_replace(w.g, '[^ACGT]', '', 'g')), 0), 3) AS assay_gc,
                   round(length(regexp_replace(w.lw || w.rw, '[^a-z]', '', 'g')) / length(w.lw || w.rw), 3) AS assay_repeat,
                   CASE WHEN w.idx IS NOT NULL THEN greatest({longest('w.lw')}, {longest('w.rw')}) END AS assay_homopolymer,
                   length(w.g) + 1 - length(replace(w.g || coalesce(upper(w.base), 'N'), 'N', '')) AS assay_n,
                   w.idx IS NOT NULL AS _checked, {ref} IS NULL AND w.pub IS NULL AS _no_alleles,
                   {neighbours.format('li')} AS _nl, {neighbours.format('ri')} AS _nr,
                   w.idx IS NOT NULL AND {ambiguous} AS _ambiguous,
                   CASE WHEN w.idx IS NOT NULL AND {ambiguous} THEN {walk_sql('w.li', 'w.ri')} END AS _walk{runs}
            FROM {snps} s LEFT JOIN (SELECT *, upper(lw || rw) AS g FROM {windows}) w USING (idx)))"""
