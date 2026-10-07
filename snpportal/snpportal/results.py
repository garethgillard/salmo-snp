"""Results of a finished job: the Overview (key numbers, the top SNPs, figures, upload QC), the Table (filters, columns
and the evidence drawer) and the figures (the full evidence card is in locus.py). Tiers for the chosen trait come from
the job's tiers.parquet (precomputed for every preset), so switching traits never rescores; snpscore.scored() runs per
request only for presets missing from it. The Overview reads summary.json (plus one small query for the top SNPs); the
table sorts and pages on the server in two steps (row numbers first, then that page's columns)."""
from __future__ import annotations

import os
import re
import uuid
from urllib.parse import urlencode

from django.http import Http404, HttpResponse
from django.urls import reverse
from django.utils.safestring import mark_safe

import snpscore
from snpscore import panel as snp_panel
from snpscore.formats import lit

from . import figures, jobs, palette
from .jobs import ident

PAGE_SIZE = 50
PAGE_SIZES = (25, 50, 100, 500)
TOP = 10  # SNPs in the Overview's top list (the report lists 20)
REGIONS = jobs.REGION_GROUPS
REGION_LABELS = {"coding": "coding (CDS, splice)", "UTR": "UTR", "exon": "non-coding exon", "intron": "intron",
                 "intergenic": "intergenic", "other": "other"}
CLASS_LABELS = {"CDS": "CDS", "splice_region": "splice region", "five_prime_UTR": "5′ UTR", "three_prime_UTR": "3′ UTR",
                "exon": "non-coding exon", "intron": "intron"}
HIDE = {  # checkbox -> (label, column it needs, SQL condition a SNP must meet to stay); hide_lore: older links (now in Assay)
    "hide_blacklist": ("blacklisted", "blacklist", "NOT blacklist"),
    "hide_lore": ("LORe", "lore", "NOT lore"),
    "hide_ambiguous": ("A/T or C/G", "strand_ambiguous", "NOT coalesce(strand_ambiguous, false)"),
    "hide_flank": ("variants within 35 bp", "flank_variants", "flank_variants = 0"),
    "hide_near_chip": ("near the chip", "near_chip", "NOT near_chip"),  # with a chip on the Panel tab (P6.6)
}
TIER_FILTERS = {"1": "tier = 1", "1-2": "tier <= 2", "1-3": "tier <= 3", "2": "tier = 2", "3": "tier = 3", "4": "tier = 4"}
ASSAY = {"pass": ("✓", "ok"), "warn": ("⚠", "warn"), "fail": ("✗", "fail"), "not_checked": ("–", "not_checked")}
CHECKED = "coalesce(assay_status, 'not_checked') IN ('pass', 'warn')"
ASSAY_FILTERS = {  # the Assay select of the Table and the Panel -> (label, SQL); older links' single statuses still work
    "ok": ("Pass + warn", CHECKED), "ok_nolore": ("Pass + warn, no LORe", f"{CHECKED} AND NOT coalesce(lore, false)"),
    "pass": ("Pass only", "assay_status = 'pass'")}
REASON_SQL = ("list_transform(string_split(coalesce(assay_reasons, ''), '; '), "  # as jobs.summarise counts them
              "x -> trim(regexp_replace(regexp_replace(x, '^[0-9]+ ', ''), '( +[0-9.+-]+)+$', '')))")
MAFS = ("0.01", "0.05", "0.1", "0.2")
MAF_TIP = "Minor allele frequency in 504 public fish, pooled; your strain can differ"
UNNAMED = "Unnamed in Ensembl; named by its human ortholog"
TERMS = {"active": "active in the trait's conditions", "active_elsewhere": "active elsewhere only",
         "weak": "weak state in the trait's conditions", "coding": "CDS", "splice": "splice region", "utr": "UTR",
         "constrained": "GERP constrained", "regbuild": "Ensembl regulatory", "molqtl": "molQTL lead (display only)"}
QUIET = ("unknown_chromosomes", "aliases_applied", "alias_warnings", "columns_renamed", "columns_dropped",
         "duplicates_merged", "indels", "multiallelic")  # upload QC lines left out when empty or zero
REJECTS = {"unknown_chrom": "unknown chromosome", "missing_chrom": "no chromosome", "bad_pos": "no valid position",
           "duplicate": "duplicates of an earlier row", "unknown_rsid": "rs IDs not in EVA release 9"}
REF_CHECKS = {"ok": "match the Ssal_v3.1 reference", "mismatch": "mismatch it", "strand_flip": "match on the other strand",
              "swapped": "have ref and alt swapped", "not_checked": "not checked (no alleles or sequence)"}
REASONS = {  # snpscore.assay reasons without their numbers -> label (others are shown as they are)
    "GC": "GC content out of range", "repeat": "repeat (soft-masked) flanks", "homopolymer": "long homopolymer",
    "flank variants": "public variants in the flanks", "flank variants on both sides": "public variants in both flanks",
    "N in flank": "N bases in the flanks", "ref mismatch": "ref allele not the genome's", "not a SNP": "not a SNP",
    "alleles on the other strand": "alleles on the other strand", "alleles unknown": "alleles unknown",
    "TOP/BOT cannot be determined (Illumina code 103)": "TOP/BOT undeterminable (Illumina)", "LORe region": "LORe region",
    "blacklisted": "blacklisted region", "A/T or C/G (two probes)": "A/T or C/G (two probes)",
    "chromosome not in the genome": "chromosome not in the genome",
    **{f"{b} run": f"long {b} run" for b in "ACGT"}}
FORMAT_NAMES = {"vcf": "VCF", "text": "text table", "tsv": "tab-separated table", "csv": "comma-separated table", "bim": "PLINK .bim", "map": "PLINK .map", "illumina": "Illumina manifest",
                "axiom": "Axiom annotation", "paste": "pasted positions", "rows": "public variants (genes or intervals)"}
STAGES = ["LateBlastulation", "MidGastrulation", "EarlySomitogenesis", "MidSomitogenesis", "LateSomitogenesis"]
STAGE_LABELS = figures.STAGE_LABELS
SAMPLES = "brain, gonad, liver and muscle of 12 AquaGen fish (BodyMap); 5 embryo stages from embryo pools (DevMap)"
NO_PEAK = f"No AQUA-FAANG peak in the 21 conditions sampled ({SAMPLES}). No immune tissue, gill or skin."
CARD_SQL = "SELECT * FROM v WHERE file_row_number = ?"  # the card reads one row, never the whole result

# Table columns, in display order: key -> (header, tooltip, columns (shown when any exists; () = always), sort [(SQL,
# ascending)]; ?desc=1 reverses every term). ?col= and the column chooser accept only these keys; {maf} in a sort is
# the MAF expression. p, beta and PIP exist for GWAS jobs only.
COLUMNS = {
    "id": ("SNP", "SNP id and alleles (ref > alt): click for its evidence", (), [("id", True)]),
    "position": ("Position", "Chromosome:position (1-based, Ssal_v3.1)", ("pos",), [("length(chrom)", True), ("chrom", True), ("pos", True)]),
    "p": ("p", "GWAS p value", ("neglog10p",), [("neglog10p", False)]),
    "beta": ("beta (se)", "GWAS effect of the alt allele (standard error)", ("beta",), [("beta", False)]),
    "tier": ("Tier", "1 = strongest functional evidence for this trait; 4 = no evidence found (not evidence of no effect)",
             ("tier",), [("tier", True), ("tier_score", False)]),
    "pip": ("PIP", "Posterior inclusion probability, uniform → functional prior; one causal variant per locus, no LD. "
            "Blank outside loci", ("pip_uniform",), [("pip_functional", False)]),
    "gene": ("Gene", "Nearest Ensembl 116 gene; ~NAME: unnamed in Ensembl, named by its human ortholog", ("gene_name", "gene_id"),
             [("coalesce(gene_name, gene_ortholog_human, gene_id)", True)]),
    "region": ("Region", "Genic region class (Ensembl 116 gene models)", ("region_class",), [("region_class", True)]),
    "distance": ("To gene", "Distance to the nearest gene", ("gene_distance",), [("gene_distance", True)]),
    "score": ("Score", "Tier score: the summed weights of the evidence terms", ("tier_score",), [("tier_score", True)]),
    "evidence": ("Evidence", "The evidence behind the tier", ("tier_evidence",), []),
    "chromatin": ("Chromatin", "AQUA-FAANG chromatin state in 21 conditions: Brain, Gonad, Liver, Muscle (immature F, M; "
                  "mature F, M), then 5 embryo stages. Underlined: the trait's conditions", ("chromatin",), []),
    "known": ("Known locus", "Near a published locus of the known-loci catalogue", ("known_locus",), [("known_locus_dist", True)]),
    "maf": ("MAF", MAF_TIP, ("maf", "af", "public_af_maf"), [("{maf}", True)]),
    "assay": ("Assay", "Assay design check of the probe flanks; hover for the reasons", ("assay_status",), [("assay_status", True)]),
    "alleles": ("Alleles", "Reference > alternative allele", ("ref", "alt"), []),
    "molqtl": ("molQTL", "Lead SNP of an eQTL (e) or caQTL (ca) in 12 fish; display only, never counted in tiers",
               ("molqtl",), [("molqtl_best_bf", True)]),
    "cm": ("cM (F/M)", "Genetic map position, female / male cM (Brekke et al. 2023 linkage map, interpolated)",
           ("cm_female",), [("cm_female", True)]),
    "gerp": ("GERP", "GERP constrained-element score (65 fish)", ("gerp_score",), [("gerp_score", True)]),
    "regbuild": ("Ensembl reg.", "Ensembl 116 regulatory build feature", ("regbuild_type",), [("regbuild_type", True)]),
    "flags": ("Flags", "Blacklisted region, LORe, A/T or C/G, public variants within 35 bp",
              ("blacklist", "lore", "strand_ambiguous", "flank_variants"), []),
    "ref_check": ("Ref. check", "Input ref allele against the Ssal_v3.1 genome", ("ref_check",), [("ref_check", True)]),
}
DEFAULT_COLUMNS = ("id", "gene", "region", "tier", "evidence", "chromatin", "known", "maf", "assay")
GWAS_COLUMNS = ("id", "p", "beta", "tier", "pip", "gene", "region", "chromatin")
EXTRA = {"id": ("id", "chrom", "pos", "ref", "alt"), "tier": ("tier_score", "tier_evidence", "tier_terms"), "known": ("known_locus_dist",),
         "evidence": ("tier_terms",),
         "gene": ("gene_ortholog_human",), "region": ("gene_distance",), "beta": ("se",), "pip": ("pip_functional",),
         "assay": ("assay_reasons", "blacklist", "lore", "strand_ambiguous", "flank_variants"),
         "molqtl": ("molqtl_tissues", "molqtl_kinds", "molqtl_features"), "cm": ("cm_male",)}  # also fetched
MORE = ("region", "active", "term", "known", "molqtl", "hide_blacklist", "hide_ambiguous", "hide_flank", "hide_near_chip",
        "hide_reason")  # filters under 'More filters'


# ---- opening a result with filters ----

def chip_view(con, d, rel, weights):
    """SQL adding on_chip, dist_to_chip, near_chip and novel_functional (tier 1-2, not near the chip) to `rel` by row
    number, or None without a chip. The per-row columns are computed once per chip, on chrom and pos only, into
    chip_rows_<sha>.parquet (snpscore.panel.compare_sql), so pages never ASOF-join the whole result."""
    chip = d / "chip.parquet"
    if not chip.exists() or not weights:
        return None
    rows = d / f"chip_rows_{jobs._file('sha256', chip)[:16]}.parquet"  # named by the chip's content (sha256 cached by mtime)
    if not rows.exists():
        narrow = f"(SELECT file_row_number, chrom, pos FROM read_parquet({lit(d / 'result.parquet')}, file_row_number=true))"
        sql = snp_panel.compare_sql(narrow, f"read_parquet({lit(chip)})", int(snp_panel.settings(weights)["chip_window"]), "NULL")
        tmp = d / f".chip-rows-{uuid.uuid4().hex}.parquet"
        con.execute(f"COPY (SELECT file_row_number, dist_to_chip, on_chip, near_chip FROM ({sql})) TO {lit(tmp)} (FORMAT parquet)")
        os.chmod(tmp, 0o600)
        os.replace(tmp, rows)
    return (f"SELECT t.*, c.dist_to_chip, c.on_chip, c.near_chip, coalesce(t.tier <= 2, false) AND NOT coalesce(c.near_chip, false) "
            f"AS novel_functional FROM {rel} t LEFT JOIN read_parquet({lit(rows)}) c USING (file_row_number)")


def _open(request, key, write=False, chip=False):
    """(connection with views r and v, column types, filters, chosen settings, weights) for a finished job: v is the
    result with the tiers of ?trait= (a GWAS job's p, beta and se; with `chip`, the chip columns when the Panel tab
    has a chip). The connection reads only the job folder (and writes there if `write`); like every
    jobs.connect() it can spill, so a sort of a 1.6M-row result does not run out of memory."""
    d = jobs.folder(key)
    if not (d / "result.parquet").exists():
        raise Http404("Result not found or expired")
    con = jobs.connect([d], d if write else None)
    con.execute(f"CREATE VIEW r AS SELECT * FROM read_parquet('{d / 'result.parquet'}', file_row_number=true)")
    columns = [c for c, in con.execute("SELECT column_name FROM (DESCRIBE r)").fetchall()]
    weights = jobs.weights(d)  # the job's snapshot, not the current release
    trait = request.GET.get("trait", "all")
    if weights:
        trait = trait if trait in weights["presets"] else "all"
        stored = []
        if (d / "tiers.parquet").exists():
            stored = [c for c, in con.execute(f"SELECT column_name FROM (DESCRIBE SELECT * FROM read_parquet('{d / 'tiers.parquet'}'))").fetchall()]
        picked = [c for c in jobs.TIER_COLUMNS if f"{c}__{trait}" in stored]
        if picked:
            drop = [c for c in jobs.TIER_COLUMNS if c in columns]
            keep = f"r.* EXCLUDE ({', '.join(drop)})" if drop else "r.*"
            tiers = ", ".join(f"t.{ident(f'{c}__{trait}')} AS {c}" for c in picked)
            con.execute(f"CREATE VIEW v0 AS SELECT {keep}, {tiers} FROM r JOIN read_parquet('{d / 'tiers.parquet'}') t "
                        "USING (file_row_number)")
        else:  # e.g. a custom preset, or a job made before tiers.parquet existed
            con.execute(f"CREATE VIEW v0 AS {jobs.scored_sql('r', weights, columns, trait, d)}")
    else:
        con.execute("CREATE VIEW v0 AS SELECT * FROM r")
    if (d / "gwas.parquet").exists():  # GWAS jobs: the association statistics for the Table's p and beta columns
        con.execute(f"CREATE VIEW v1 AS SELECT v0.*, s.neglog10p, s.beta, s.se FROM v0 "
                    f"LEFT JOIN read_parquet('{d / 'gwas.parquet'}') s USING (file_row_number)")
    else:
        con.execute("CREATE VIEW v1 AS SELECT * FROM v0")
    chipped = chip and chip_view(con, d, "v1", weights)  # the Panel tab's chip (P6.6), for the pages that use its columns
    con.execute(f"CREATE VIEW v AS {chipped or 'SELECT * FROM v1'}")
    types = dict(con.execute("SELECT column_name, column_type FROM (DESCRIBE v)").fetchall())
    conds = filters(request, types, weights)
    chosen = {"trait": trait}
    for params, _, _ in conds:
        chosen.update(params)
    return con, types, conds, chosen, weights


def open_result(request, key, write=False, chip=False):
    """DuckDB view `v` over a finished job's result with the tiers of ?trait=, and the WHERE clause of the table
    filters in the request (see filters()). Returns (connection, column types, WHERE clause, the request's settings)."""
    con, types, conds, chosen, _ = _open(request, key, write, chip)
    return con, types, _where(conds), chosen


def _where(conds):
    return ("WHERE " + " AND ".join(f"({sql})" for _, _, sql in conds)) if conds else ""


def _number(text):
    try:
        return float(text)
    except ValueError:
        return None


def filters(request, types, weights):
    """[(URL parameters, chip label, SQL)] for the whitelisted filters in the request whose columns exist. Other
    parameters are ignored; values are checked or quoted before they reach SQL."""
    get, out = request.GET.get, []
    tier = get("tier", "") or {"1": "1", "2": "1-2", "3": "1-3"}.get(get("max_tier", ""), "")  # max_tier: older links
    if tier in TIER_FILTERS and "tier" in types:
        out.append(({"tier": tier}, f"Tier {tier.replace('-', '–')}", TIER_FILTERS[tier]))
    region = get("region", "")
    if region in REGIONS and "region_class" in types:
        out.append(({"region": region}, f"Region: {REGION_LABELS[region]}", REGIONS[region]))
    chrom, start, end = get("chrom", ""), get("start", ""), get("end", "")
    if re.fullmatch(r"[\w.]{1,40}", chrom):
        if start.isdecimal() and end.isdecimal() and int(start) < int(end):  # start < pos <= end, as for layers
            out.append(({"chrom": chrom, "start": start, "end": end}, f"{chrom}:{int(start):,}–{int(end):,}",
                        f"chrom = {lit(chrom)} AND pos > {int(start)} AND pos <= {int(end)}"))
        else:
            out.append(({"chrom": chrom}, f"Chromosome {chrom}", f"chrom = {lit(chrom)}"))
    gene = get("gene", "").strip()[:40]
    names = [c for c in ("gene_name", "gene_id", "gene_ortholog_human", "gene_ortholog_zebrafish") if c in types]
    if gene and names:
        out.append(({"gene": gene}, f"Gene: {gene}", " OR ".join(f"contains(lower({c}), {lit(gene.lower())})" for c in names)))
    maf, _ = jobs.maf_sql(types)
    for param, op, label in (("min_maf", ">=", "MAF ≥"), ("max_maf", "<", "MAF <")):
        value = _number(get(param, ""))
        if maf and value is not None and 0 <= value <= 0.5:
            out.append(({param: get(param)}, f"{label} {value:g}", f"{maf} {op} {value!r}"))
    assay = get("assay", "")
    if "assay_status" in types and assay in ASSAY_FILTERS and (assay != "ok_nolore" or "lore" in types):
        out.append(({"assay": assay}, f"Assay: {ASSAY_FILTERS[assay][0]}", ASSAY_FILTERS[assay][1]))
    elif "assay_status" in types and assay in ASSAY:  # one status (older links, Assay readiness bars)
        out.append(({"assay": assay}, f"Assay: {assay.replace('_', ' ')}", f"coalesce(assay_status, 'not_checked') = {lit(assay)}"))
    if get("known") == "1" and "known_locus" in types:
        out.append(({"known": "1"}, "Known loci only", "known_locus IS NOT NULL"))
    if get("molqtl") == "1" and "molqtl" in types:
        out.append(({"molqtl": "1"}, "molQTL lead SNPs", "coalesce(molqtl, false)"))
    active = get("active", "")
    if weights and active and f"chromatin_{active}" in types and f"chromatin_{active}" not in snpscore.score.NOT_CONDITIONS:
        states = ", ".join(lit(s) for s in weights.get("active_states", [])) or "NULL"
        out.append(({"active": active}, f"Active in {condition_label(active)}", f"{ident('chromatin_' + active)} IN ({states})"))
    term = get("term", "")
    if weights and term in weights.get("weights", {}) and "tier_terms" in types:
        out.append(({"term": term}, f"Evidence: {TERMS.get(term, term)}", f"list_contains(list_transform(tier_terms, x -> x.term), {lit(term)})"))
    for name, (label, column, condition) in HIDE.items():
        if get(name) and column in types:
            out.append(({name: "1"}, f"Hide {label}", condition))
    reason = get("hide_reason", "")[:80]
    if reason and "assay_reasons" in types:  # 'hide in table' of the Panel tab's Assay readiness reasons
        out.append(({"hide_reason": reason}, f"Hide {REASONS.get(reason, reason)}", f"NOT list_contains({REASON_SQL}, {lit(reason)})"))
    return out


# ---- conditions, labels ----

def conditions_of(columns):
    """Chromatin condition names, tissues first (alphabetical: immature F, M, mature F, M), then the embryo stages."""
    found = [c[len("chromatin_"):] for c in columns if c.startswith("chromatin_") and c not in snpscore.score.NOT_CONDITIONS]
    return sorted(found, key=lambda c: (c in STAGES, STAGES.index(c) if c in STAGES else 0, c))


def condition_groups(conditions):
    """[(group, [(short label, condition)])]: one group per tissue, and 'Embryo' for the stages."""
    groups = {}
    for c in conditions:
        tissue, _, rest = c.partition("_")
        group, label = (tissue, " ".join([rest.split("_")[0][:3]] + [p[:1] for p in rest.split("_")[1:]])) if rest \
            else ("Embryo", STAGE_LABELS.get(c, c[:8]))
        groups.setdefault(group, []).append((label, c))
    return list(groups.items())


def condition_label(c):
    tissue, _, rest = c.partition("_")
    return f"{tissue} {rest.replace('_', ' ').lower()}" if rest else c


def trait_tip(weights, trait):
    """The Trait control's tooltip: the conditions a trait's tiers use, e.g. 'maturation: Brain, Gonad'."""
    prefixes = list(((weights or {}).get("presets") or {}).get(trait) or [])
    if not prefixes:
        text = "all 21 conditions"
    elif set(prefixes) <= set(STAGES):
        text = f"{len(prefixes)} embryo stages"
    else:
        text = ", ".join(prefixes) + (" only" if len(prefixes) == 1 else "")
    if "disease" in trait:
        text += " (no immune tissue, gill or skin sampled)"
    return f"{jobs.trait_label(trait)}: {text}"


def gene_label(name, gene_id, human):
    """explore.display_name: the Ensembl name, else the known-loci catalogue's name ('vgll3'), else '~VGLL3' from the
    human ortholog (UNNAMED is its tooltip), else the gene id; '' without a gene."""
    from . import explore  # explore imports locus, which imports this module
    return explore.display_name(name, explore.aliases().get(gene_id), human, gene_id) if name or gene_id or human else ""


def evidence_text(evidence, terms=None):
    """tier_evidence as shown: without the terms that count nothing (weight 0, e.g. molQTL leads: display only) and
    with condition lists spelled out ('active: Brain, E somit., Gonad')."""
    parts = [x for x in (evidence or "").split("; ") if x]
    if terms is not None and len(terms) == len(parts):  # both list the fired terms in the same order
        parts = [x for x, t in zip(parts, terms) if t["weight"]]
    out = []
    for x in parts:
        head, sep, items = x.partition(": ")
        out.append(head + sep + ", ".join(STAGE_LABELS.get(i, i) for i in items.split(",")) if sep else x)
    return "; ".join(out)


def reason_text(reason):
    """One snpscore assay reason in words, with its number and unit: 'repeat 1.0' -> 'repeat (soft-masked) flanks
    (100%)', 'GC 0.72' -> 'GC content out of range (72%)', 'homopolymer 7' -> 'long homopolymer (7 bases)'."""
    m = re.fullmatch(r"(?:[0-9]+ )?(.*?)((?: +[0-9.+-]+)*)", reason.strip())
    name, value = m.group(1), m.group(2).strip()
    if value and name in ("GC", "repeat"):
        try:
            value = f"{float(value):.0%}"
        except ValueError:
            pass
    elif value and (name == "homopolymer" or name.endswith(" run")):
        value += " bases"
    return REASONS.get(name, name) + (f" ({value})" if value else "")


def reasons_text(reasons):
    """assay_reasons ('repeat 1.0; LORe region') in words, '; ' between them."""
    return "; ".join(reason_text(r) for r in (reasons or "").split("; ") if r.strip())


def gwas_settings(request):
    """A GWAS job's fine-mapping settings in the request (association.FIELDS), for links that keep them."""
    from . import association  # association imports this module
    return association.query_of(request)


def pct(k, n):
    if not n:
        return "–"
    share = 100 * k / n
    return "<0.1%" if 0 < share < 0.1 else f"{share:.1f}%"


def _chrom_key(chrom):
    return (0, int(chrom), "") if chrom.isdecimal() else (1, 0, chrom)


def _snp_name(g):
    return g("id") if g("id") not in (None, ".") else f"{g('chrom')}:{g('pos')}"


def _alleles(g):
    return f"{g('ref')}>{g('alt')}" if g("ref") and g("alt") else (g("ref") or "")


def _known_caveats():
    """{catalogue id: caveat labels} for the known-loci rows with a caveat ('suggestive', 'position inferred', ...)."""
    from . import explore  # explore imports locus, which imports this module
    return {r["id"]: ", ".join(b[1] for b in r["badges"] if b[0] == "caveat") for r in explore.catalogue()
            if any(b[0] == "caveat" for b in r["badges"])}


def _assay_tip(g):
    """An assay badge's tooltip: snpscore's reasons in words, then the flags they don't name."""
    reasons = reasons_text(g("assay_reasons"))
    extra = [text for column, text, word in (("blacklist", "blacklisted region", "blacklist"),
                                             ("lore", "LORe: probes may cross-hybridise", "LORe"),
                                             ("strand_ambiguous", "A/T or C/G: strand-ambiguous", "A/T"))
             if g(column) and word not in reasons]
    if g("flank_variants"):
        extra.append(f"{g('flank_variants')} public variants within 35 bp")
    return "; ".join(x for x in [reasons] + extra if x)


# ---- the Table tab ----

def table(request, key, job=None):
    """Context for the Table tab: one page of rows sorted and paged on the server, the filters (one row, the rest under
    'More filters'), chips, the column chooser, an empty-state hint and the evidence drawer (?snp=<row>). Fast on 1.6M
    rows: page row numbers are found first using only the filter and sort columns, then only that page's columns are
    read. GWAS jobs show p, beta and the PIPs of association.analyse()."""
    gwas = (job or {}).get("input_kind") == "gwas"
    if gwas:  # association.analyse's connection: view v plus the fine-mapping (table fm) of the loci, for the PIPs
        from . import association
        a = association.analyse(request, key)
        con, weights = a["con"], jobs.weights(jobs.folder(key))
        pips = ("SELECT file_row_number, max(pip_uniform) AS pip_uniform, max(pip_functional) AS pip_functional FROM fm GROUP BY 1"
                if a["loci"] else "SELECT NULL::BIGINT AS file_row_number, NULL::DOUBLE AS pip_uniform, NULL::DOUBLE AS pip_functional")
        con.execute(f"CREATE VIEW vt AS SELECT v.*, f.pip_uniform, f.pip_functional FROM v LEFT JOIN ({pips}) f USING (file_row_number)")
        types = dict(con.execute("SELECT column_name, column_type FROM (DESCRIBE vt)").fetchall())
        conds = filters(request, types, weights)
        settings = a["query"]  # the fine-mapping settings travel with every link, as the PIPs depend on them
        chosen = {"trait": a["trait"], **{k: v for params, _, _ in conds for k, v in params.items()}}
    else:
        con, types, conds, chosen, weights = _open(request, key, chip=True)  # chip columns joined by row number (chip_view)
        settings = {}
    view = "vt" if gwas else "v"
    get = request.GET.get
    summary = jobs.read_json(jobs.folder(key) / "summary.json")
    maf, maf_source = jobs.maf_sql(types)
    available = [k for k, (_, _, needs, _) in COLUMNS.items() if not needs or any(c in types for c in needs)]
    default = [k for k in (GWAS_COLUMNS if gwas else DEFAULT_COLUMNS) if k in available]
    picked = ["id"] + [k for k in available if k != "id" and k in request.GET.getlist("col")] if get("cols") else default
    custom_cols = set(picked) - {"position"} != set(default)  # the chooser sends every ticked column: short URLs for the default
    shown = list(picked if custom_cols else default)
    sort = get("sort", "")
    explicit = sort in available and bool(COLUMNS[sort][3])
    sort = sort if explicit else ("p" if gwas and "p" in available else "tier" if "tier" in available else "")
    desc = get("desc") == "1"
    size = int(get("size")) if get("size", "").isdecimal() and int(get("size")) in PAGE_SIZES else PAGE_SIZE

    total = con.execute("SELECT count(*) FROM r").fetchone()[0]
    where = _where(conds)
    order = [f"{sql.format(maf=maf)} {'ASC' if asc != desc else 'DESC'} NULLS LAST" for sql, asc in (COLUMNS[sort][3] if sort else [])]
    # Count and page on the raw result r (no tiers join) unless the filters or the sort use a column only v has right
    only_v = (set(types) - {c for c, in con.execute("SELECT column_name FROM (DESCRIBE r)").fetchall()}) | set(jobs.TIER_COLUMNS)
    uses_v = any(re.search(rf"\b{re.escape(c)}\b", sql) for c in only_v for sql in [where] + order)
    src = view if gwas or uses_v else "r"
    matching = con.execute(f"SELECT count(*) FROM {src} {where}").fetchone()[0] if conds else total
    pages = max(1, -(-matching // size))
    page = min(int(get("page")) if get("page", "").isdecimal() else 1, pages) or 1
    ids = [i for i, in con.execute(f"SELECT file_row_number FROM {src} {where} ORDER BY {', '.join(order + ['file_row_number'])} "
                                   f"LIMIT {size} OFFSET {(page - 1) * size}").fetchall()]
    conditions = conditions_of(types)
    in_preset = set(snpscore.score.preset_conditions(weights, list(types), chosen["trait"])[0]) if weights and conditions else set()
    caveats = _known_caveats() if "known" in shown else {}
    rows = _page(con, view, ids, types, shown, maf, conditions, in_preset, (weights or {}).get("active_states", []), caveats)
    if not custom_cols and any(r["id"] and str(r["pos"]) not in r["id"] for r in rows):
        shown.insert(1, "position")  # ids such as rs or AX numbers don't say where the SNP is

    base = {"tab": "table", **chosen, **settings, "sort": sort if explicit else "", "desc": "1" if desc else "",
            "size": str(size) if size != PAGE_SIZE else "", "cols": "1" if custom_cols else "",
            "col": shown[1:] if custom_cols else []}

    def link(drop=(), **changes):
        params = {k: v for k, v in base.items() if k not in drop}
        params.update(changes)
        return "?" + urlencode({k: v for k, v in params.items() if v not in ("", None, [])}, doseq=True)

    here = page if page > 1 else None
    snp = int(get("snp")) if get("snp", "").isdecimal() else None
    for r in rows:
        r["href"] = link(page=here, snp=r["n"])
    filter_keys = [k for params, _, _ in conds for k in params]
    chips = [(label, link(drop=list(params), page=None)) for params, label, _ in conds]
    suggest = None
    if conds and not matching and len(conds) > 1:  # name the filter that removes the most on its own
        counts = con.execute("SELECT " + ", ".join(f"count(*) FILTER (WHERE {_where(conds[:i] + conds[i + 1:])[6:]})"
                                                   for i in range(len(conds))) + f" FROM {view}").fetchone()
        best = max(range(len(conds)), key=lambda i: counts[i])
        if counts[best]:
            suggest = (conds[best][1], counts[best], chips[best][1])

    selects, more = [], []  # (name, label, [(value, text)], current value, tooltip)

    def select(into, name, label, values, current=None, any_label="any", tip=""):
        current = chosen.get(name, "") if current is None else current
        values = [("", any_label)] * bool(any_label) + list(values)
        if current and current not in [v for v, _ in values]:
            values.append((current, current))
        into.append((name, label, values, current, tip))

    chroms = sorted((summary.get("chrom_tiers", {}).get(chosen["trait"]) or {}), key=_chrom_key) or \
        sorted((c for c, in con.execute("SELECT DISTINCT chrom FROM r").fetchall()), key=_chrom_key)
    if "tier" in types:
        select(selects, "tier", "Tier", [(t, t.replace("-", "–")) for t in TIER_FILTERS])
    select(selects, "chrom", "Chromosome", [(c, c) for c in chroms])
    if maf:
        select(selects, "min_maf", "Min MAF", [(m, m) for m in MAFS], tip=MAF_TIP if maf_source == "public" else "Your maf/af column")
    if "assay_status" in types:
        select(selects, "assay", "Assay", [(k, label) for k, (label, _) in ASSAY_FILTERS.items() if k != "ok_nolore" or "lore" in types],
               any_label="All", tip="LORe: region where the duplicated chromosomes still pair; probes may cross-hybridise")
    if "region_class" in types:
        select(more, "region", "Region", [(r, REGION_LABELS[r]) for r in REGIONS])
    if weights and conditions:
        select(more, "active", "Active in", [(c, condition_label(c)) for c in conditions])
    if weights and "tier_terms" in types:
        select(more, "term", "Evidence", [(t, TERMS.get(t, t)) for t in weights.get("weights", {})])
    select(more, "size", "Rows", [(str(s), str(s)) for s in PAGE_SIZES], str(size), None)
    checks = ([("known", "known loci only", "known" in chosen)] if "known_locus" in types else []) + \
        ([("molqtl", "molQTL lead SNPs", "molqtl" in chosen)] if "molqtl" in types else []) + \
        [(name, f"hide {label}", name in chosen) for name, (label, column, _) in HIDE.items() if column in types and name != "hide_lore"]
    n_more = sum(k in chosen for k in MORE) + (size != PAGE_SIZE) + custom_cols

    headers = []
    for k in shown:
        label, tip, _, sorts = COLUMNS[k]
        if k == "maf" and maf_source == "yours":
            tip = "Minor allele frequency from your maf or af column"
        on = k == sort
        href = link(sort=k, desc="1" if on and not desc else "", page=None) if sorts else None
        headers.append((k, label, tip, href, ("descending" if desc else "ascending") if on else ""))
    tier_counts = sorted((summary.get("tiers") or {}).get(chosen["trait"], {}).items()) or (
        con.execute(f"SELECT tier, count(*) FROM {view} GROUP BY tier ORDER BY tier").fetchall() if "tier" in types else [])
    filtered = urlencode(chosen)
    return {
        "total": total, "matching": matching, "first": (page - 1) * size + 1 if matching else 0,
        "last": min(page * size, matching), "tiers": tier_counts, "chosen": chosen, "query": urlencode({"trait": chosen["trait"], **settings}),
        "selects": selects, "more": more, "checks": checks, "n_more": n_more,
        "gene": chosen.get("gene", "") if any(c in types for c in ("gene_name", "gene_id")) else None,
        "start": chosen.get("start", ""), "end": chosen.get("end", ""),
        "hidden": [(k, base[k]) for k in ("sort", "desc") if base[k]]  # and filters with no control on the form
        + [(k, chosen[k]) for k in ("hide_lore", "hide_reason", "max_maf") if k in chosen] + list(settings.items()),
        "columns": [(k, COLUMNS[k][0], k in shown) for k in available if k != "id"], "chips": chips,
        "clear": link(drop=filter_keys, page=None) if conds else None, "suggest": suggest,
        "headers": headers, "shown": shown, "rows": rows, "page": page, "pages": pages,
        "prev": link(page=page - 1) if page > 1 else None, "next": link(page=page + 1) if page < pages else None,
        "download": f"{reverse('snpportal:download', args=[key])}?{filtered}" if conds else None,
        "vendor": f"?{urlencode({'tab': 'export', 'scope': 'filtered', **chosen})}" if conds and not gwas else None,
        "keep": [(k, x) for k, v in base.items() if k not in ("tab", "trait") for x in (v if isinstance(v, list) else [v]) if x],
        "snp": snp, "drawer": _drawer(con, view, snp, types, weights, chosen["trait"], key, conditions, in_preset,
                                      link(page=here), settings) if snp is not None else None,
    }


def _page(con, view, ids, types, shown, maf, conditions, in_preset, active_states, caveats):
    """Display-ready rows for the row numbers `ids`, in that order. Reads only the shown columns."""
    if not ids:
        return []
    wanted = {"file_row_number"} | {c for k in shown + ["position"] for c in COLUMNS[k][2] + EXTRA.get(k, ()) if c in types}
    if "chromatin" in shown:
        wanted |= {f"chromatin_{c}" for c in conditions}
    select = ", ".join(map(ident, sorted(wanted))) + (f", {maf} AS _maf" if maf and "maf" in shown else "")
    cur = con.execute(f"SELECT {select} FROM {view} WHERE file_row_number IN ({', '.join(str(int(i)) for i in ids)})")
    names = [x[0] for x in cur.description]
    found = {r["file_row_number"]: r for r in (dict(zip(names, x)) for x in cur.fetchall())}
    groups = condition_groups(conditions)
    return [_row(found[i], groups, in_preset, set(active_states), caveats) for i in ids if i in found]


def _row(r, groups, in_preset, active_states, caveats):
    """One table row as display values (the template adds the markup)."""
    from snpscore.gwas import p_text
    g = r.get
    distance = g("gene_distance")
    out = {"n": r["file_row_number"], "id": g("id") if g("id") not in (None, ".") else None, "chrom": g("chrom"), "pos": g("pos"),
           "alleles": _alleles(g), "tier": g("tier"), "score": g("tier_score"), "evidence": evidence_text(g("tier_evidence"), g("tier_terms")),
           "known": g("known_locus"), "known_dist": g("known_locus_dist"), "caveat": caveats.get(g("known_locus")),
           "gene": gene_label(g("gene_name"), g("gene_id"), g("gene_ortholog_human")), "gene_id": g("gene_id") or "",
           "region": CLASS_LABELS.get(g("region_class"), g("region_class")) or "intergenic",
           "distance": "" if distance is None else "in gene" if distance == 0 else
           f"{distance:,} bp" if distance < 1000 else f"{distance / 1000:,.1f} kb",
           "gerp": "" if g("gerp_score") is None else f"{g('gerp_score'):.1f}", "regbuild": g("regbuild_type") or "",
           "maf": "" if g("_maf") is None else f"{g('_maf'):.2f}", "ref_check": g("ref_check") or "",
           "cm": "" if g("cm_female") is None else f"{g('cm_female'):.1f} / {g('cm_male'):.1f}" if g("cm_male") is not None else f"{g('cm_female'):.1f}",
           "p": p_text(g("neglog10p")), "beta": "" if g("beta") is None else f"{g('beta'):.3f}" + (f" ({g('se'):.3f})" if g("se") is not None else ""),
           "pip": "" if g("pip_uniform") is None else f"{g('pip_uniform'):.2f} → {g('pip_functional'):.2f}"}
    out["gene_tip"] = UNNAMED if out["gene"].startswith("~") else out["gene_id"]
    if g("molqtl"):  # 'Brain, Gonad (e, ca)', the features as the tooltip
        out["molqtl"] = (f"{(g('molqtl_tissues') or '').replace(',', ', ')} ({(g('molqtl_kinds') or '').replace(',', ', ')})",
                         g("molqtl_features") or "")
    status = g("assay_status") or ("not_checked" if "assay_status" in r else None)
    out["assay"] = (ASSAY.get(status, ("?", "not_checked")) + (status.replace("_", " "), _assay_tip(g))) if status else None
    flags = []
    if g("blacklist"):
        flags.append(("⚠", "blacklisted", "In a blacklisted region: no peak here means 'can't tell'"))
    if g("lore"):
        flags.append(("⚠", "LORe", "Region where the duplicated chromosomes still pair; probes may cross-hybridise"))
    if g("strand_ambiguous"):
        flags.append(("⇄", "A/T-C/G", "Strand-ambiguous; needs care on arrays"))
    if g("flank_variants"):
        flags.append(("⚠", f"{g('flank_variants')} near", "Public variants within 35 bp"))
    out["flags"] = flags
    if "chromatin" in r or any(k.startswith("chromatin_") for k in r):
        cells, active, peaks = [], 0, 0
        for group, items in groups:
            row = []
            for label, c in items:
                state = g(f"chromatin_{c}")
                active += state in active_states
                peaks += bool(state)
                cls = (f"st-{state}" if state in palette.STATES else "sp-bc-other") if state else ""
                row.append((cls + (" in" if c in in_preset else ""), f"{group} {label}: {(state or 'no peak').replace('_', ' ')}"))
            cells.append(row)
        out["barcode"] = cells
        out["barcode_label"] = f"Active in {active}, a peak in {peaks} of {sum(len(i) for _, i in groups)} conditions"
    return out


def tier_line(tier, evidence, terms):
    """'Tier 2 · CDS (amino-acid effect not computed) +3': the tier and the evidence terms that fired, with weights."""
    if tier is None:
        return ""
    counted = [t for t in terms or [] if t["weight"]]
    evidence = evidence_text(evidence, terms)
    if tier == 4 or not evidence:
        return f"Tier {tier} · no evidence found (not evidence of no effect)"
    parts = evidence.split("; ")
    if len(counted) == len(parts):
        parts = [f"{p} +{t['weight']}" for p, t in zip(parts, counted)]
    return f"Tier {tier} · " + " · ".join(re.sub(r"^CDS\b", "CDS (amino-acid effect not computed)", p) for p in parts)


def _drawer(con, view, row, types, weights, trait, key, conditions, in_preset, close, settings=None):
    """The Table's evidence drawer for one SNP: the tier line, the known locus with its caveat, one chromatin line, one
    assay line and a link to the full card; None when the row doesn't exist."""
    cur = con.execute(f"SELECT * FROM {view} WHERE file_row_number = ?", [row])
    hit = cur.fetchone()
    if hit is None:
        return None
    snp = dict(zip([d[0] for d in cur.description], hit))
    g = snp.get
    active_states = set((weights or {}).get("active_states", []))
    labels = {c: f"{group} {label}" for group, items in condition_groups(conditions) for label, c in items}
    active = [c for c in conditions if g(f"chromatin_{c}") in active_states]
    peaks = sum(bool(g(f"chromatin_{c}")) for c in conditions)
    if not conditions:
        chromatin = ""
    elif active:
        mine = sum(c in in_preset for c in active)
        chromatin = (f"Active in {len(active)} of {len(conditions)} conditions ({mine} of the trait's): "
                     + ", ".join(labels[c] for c in active[:6]) + (", ..." if len(active) > 6 else ""))
    elif peaks:
        chromatin = f"A peak in {peaks} of {len(conditions)} conditions, in no active state."
    else:
        chromatin = NO_PEAK + (" Blacklisted region: no peak here means can't tell, not inactive." if g("blacklist") else "")
    known = None
    if g("known_locus"):
        dist = g("known_locus_dist")
        known = {"name": g("known_locus"), "where": "at this position" if not dist else f"{dist:,} bp away",
                 "note": f"effect allele {g('known_effect_allele')}" + (f" (your {g('known_effect_note')})" if g("known_effect_note") else "")
                 if g("known_effect_allele") else "", "caveat": _known_caveats().get(g("known_locus"))}
    status = g("assay_status") or ("not_checked" if "assay_status" in types else None)
    return {"name": _snp_name(g), "alleles": _alleles(g), "position": f"{g('chrom')}:{g('pos'):,}", "tier": g("tier"),
            "tier_line": tier_line(g("tier"), g("tier_evidence"), g("tier_terms")),
            "gene": gene_label(g("gene_name"), g("gene_id"), g("gene_ortholog_human")), "known": known, "chromatin": chromatin,
            "assay": status and f"Assay: {status.replace('_', ' ')}" + (f" ({_assay_tip(g)})" if _assay_tip(g) else ""),
            "card": f"{reverse('snpportal:card', args=[key, row])}?{urlencode({'trait': trait, **(settings or {})})}", "close": close}


# ---- the top SNPs (Overview and report) ----

def top(request, key, job, n=TOP):
    """{rows, matching, ties, gwas} for the first `n` SNPs with the request's trait and table filters, ordered as the
    Table: tier, then score (highest first), then list order; GWAS jobs by p. `ties` says how many SNPs share the
    tier and score at the cut, when the cut splits them."""
    con, types, where, chosen = open_result(request, key)
    gwas = job.get("input_kind") == "gwas" and "neglog10p" in types
    maf, _ = jobs.maf_sql(types)
    cols = [c for c in ("chrom", "pos", "id", "ref", "alt", "tier", "tier_score", "tier_evidence", "tier_terms", "gene_name", "gene_id",
                        "gene_ortholog_human", "region_class", "known_locus", "known_locus_dist", "assay_status",
                        "assay_reasons", "neglog10p", "lore", "blacklist", "strand_ambiguous", "flank_variants") if c in types]
    order = "neglog10p DESC NULLS LAST, " if gwas else \
        "tier ASC NULLS LAST, tier_score DESC NULLS LAST, " if {"tier", "tier_score"} <= set(types) else ""
    cur = con.execute(f"SELECT file_row_number, {', '.join(map(ident, cols))}{f', {maf} AS _maf' if maf else ''} "
                      f"FROM v {where} ORDER BY {order}file_row_number LIMIT {int(n)}")
    names = [d[0] for d in cur.description]
    q = urlencode({"trait": chosen["trait"], **gwas_settings(request)})
    caveats = _known_caveats() if "known_locus" in types else {}
    rows = []
    for r in (dict(zip(names, x)) for x in cur.fetchall()):
        g = r.get
        status = g("assay_status") or ("not_checked" if "assay_status" in types else None)
        rows.append({
            "url": f"{reverse('snpportal:card', args=[key, r['file_row_number']])}?{q}", "n": r["file_row_number"],
            "snp": _snp_name(g), "position": f"{g('chrom')}:{g('pos'):,}", "alleles": _alleles(g),
            "tier": g("tier"), "score": g("tier_score"), "evidence": evidence_text(g("tier_evidence"), g("tier_terms")),
            "gene": gene_label(g("gene_name"), g("gene_id"), g("gene_ortholog_human")),
            "region": CLASS_LABELS.get(g("region_class"), g("region_class")) or "intergenic",
            "known": g("known_locus") or "", "known_dist": g("known_locus_dist"), "caveat": caveats.get(g("known_locus")),
            "maf": "" if g("_maf") is None else f"{g('_maf'):.2f}", "p": "",
            "assay": (ASSAY.get(status, ("?", "not_checked")) + (status.replace("_", " "), _assay_tip(g))) if status else None})
        if gwas:
            from snpscore.gwas import p_text
            rows[-1]["p"] = p_text(g("neglog10p"))
        rows[-1]["gene_tip"] = UNNAMED if rows[-1]["gene"].startswith("~") else g("gene_id") or ""
    matching = con.execute(f"SELECT count(*) FROM v {where}").fetchone()[0]
    ties = None
    if rows and not gwas and len(rows) < matching and rows[-1]["tier"] is not None:
        t, s = rows[-1]["tier"], rows[-1]["score"]
        cut = f"tier = {int(t)} AND tier_score = {int(s)}" if s is not None else f"tier = {int(t)} AND tier_score IS NULL"
        tied = con.execute(f"SELECT count(*) FROM v {where} {'AND' if where else 'WHERE'} {cut}").fetchone()[0]
        shown = sum(r["tier"] == t and r["score"] == s for r in rows)
        if tied > shown:
            at = "the top score" if (rows[0]["tier"], rows[0]["score"]) == (t, s) else f"tier {t}, score {s}"
            ties = f"{shown} of {tied:,} SNPs tied at {at} are shown; ties in list order."
    return {"rows": rows, "matching": matching, "ties": ties, "gwas": gwas, "chosen": chosen, "columns": set(types)}


# ---- the Overview tab and its figures ----

def summary_of(d):
    """summary.json, rebuilt once for jobs made before the current summary version (cheap next to scoring)."""
    s = jobs.read_json(d / "summary.json")
    if s.get("version", 0) < jobs.SUMMARY_VERSION and (d / "result.parquet").exists():
        s = jobs.refresh_summary(d)
    return s


def background():
    """The release's public background (pool/background.json from `snpscore pool`), or {} when it has no pool."""
    return jobs.read_json(jobs.release() / "pool" / "background.json")


def _shares(values):
    """{name: share} from the {n, share} dicts of background.json (or plain shares)."""
    values = {k: v.get("share") if isinstance(v, dict) else v for k, v in (values or {}).items()}
    return {k: float(v) for k, v in values.items() if isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 1}


def background_regions(bg):
    """{region group: share of the background's sites}, from its region-class shares."""
    out = {}
    for cls, share in _shares(bg.get("region_class")).items():
        group = next((g for g, test in (("coding", cls in ("CDS", "splice_region")), ("intergenic", cls in ("intergenic", "None", "")),
                                        ("UTR", cls.endswith("UTR")), ("exon", cls == "exon"), ("intron", cls == "intron")) if test), "other")
        out[group] = out.get(group, 0) + share
    return out


def _tier_segments(counts, total, label, href):
    return [(counts.get(str(t), 0), palette.TIERS[t][0], f"{label}, tier {t}: {counts.get(str(t), 0):,} SNPs ({pct(counts.get(str(t), 0), total)})",
             href(t) if href else None) for t in (1, 2, 3, 4) if counts.get(str(t))]


def _fig_tiers(c, link, desc):
    counts = c["s"].get("tiers", {}).get(c["trait"])
    if not counts:
        return None
    svg = figures.tier_bar(counts, f"SNPs per tier, {c['preset']}", desc, c["synthetic"],
                           {t: link(tier=t) for t in counts} if link else None)
    return svg, ["tier", "snps"], sorted(counts.items())


def _fig_ideogram(c, link, desc):
    bins = c["s"].get("bins", {}).get(c["trait"])
    if bins is None:
        return None
    sizes = {k: int(v) for k, v in (c["manifest"].get("chrom_sizes") or {}).items()}
    for chrom, b, *_ in bins:
        sizes[chrom] = max(sizes.get(chrom, 0), int((b + 1) * 1e6))
    chroms = [(k, sizes[k]) for k in sorted(sizes, key=_chrom_key)]
    href = (lambda chrom, start, end: link(chrom=chrom, start=start, end=end)) if link else None
    chip = c.get("chip") or {}  # the Panel tab's reference chip, as ticks (P6.6)
    svg = figures.ideogram(chroms, bins, c["s"]["chrom_tiers"].get(c["trait"], {}), f"SNPs along the genome, {c['preset']}",
                           desc, c["synthetic"] or bool(chip.get("synthetic")), href, chip.get("density"),
                           (chip.get("label") or "chip").lower())
    return svg, ["chrom", "start", "end", "snps", "tier1", "tier2", "tier3", "tier4"], \
        [(chrom, int(b * 1e6), int((b + 1) * 1e6), sum(n), *n) for chrom, b, *n in bins]


def _fig_conditions(c, link, desc):
    s = c["s"]
    counts, n = s.get("conditions"), s.get("n_rows") or 1
    if not counts:
        return None
    bg = _shares(c["background"].get("active_by_condition"))
    chosen = set(snpscore.score.preset_conditions(c["weights"], ["chromatin_" + x for x in counts], c["trait"])[0]) if c["weights"] else set()
    rows, tsv = [], []
    for group, cells in condition_groups(conditions_of("chromatin_" + x for x in counts)):
        out = []
        for label, cond in cells:
            share = counts[cond] / n
            fold = share / bg[cond] if bg.get(cond) else None
            out.append((label, cond, share, fold, cond in chosen))
            tsv.append((cond, counts[cond], f"{share:.5f}", f"{bg[cond]:.5f}" if cond in bg else "", f"{fold:.3f}" if fold else "",
                        "yes" if cond in chosen else "no"))
        rows.append((group, palette.TISSUES.get(group, palette.GREY[500]), out))
    svg = figures.heatmap(rows, f"Active chromatin per condition, {c['preset']}", desc, c["synthetic"],
                          (lambda cond: link(active=cond)) if link else None)
    return svg, ["condition", "snps_active", "share", "background_share", "fold", "in_preset"], tsv


def _fig_regions(c, link, desc):
    counts = c["s"].get("region_tiers", {}).get(c["trait"])
    if not counts:
        return None
    n = sum(sum(t.values()) for t in counts.values())
    bg = background_regions(c["background"])
    rows, tsv = [], []
    for g in [g for g in list(REGIONS) + ["other"] if g in counts or g in bg]:
        k = counts.get(g, {})
        filt = link and g in REGIONS
        rows.append({"label": REGION_LABELS[g], "href": link(region=g) if filt else None,
                     "segments": _tier_segments(k, n, REGION_LABELS[g], (lambda t, g=g: link(region=g, tier=str(t))) if filt else None),
                     "tick": (bg[g] * n, f"Public background: {100 * bg[g]:.1f}% of SNPs") if g in bg else None,
                     "note": f"{sum(k.values()):,} ({pct(sum(k.values()), n)})"})
        tsv += [(g, t, k.get(str(t), 0), f"{bg[g]:.5f}" if g in bg else "") for t in (1, 2, 3, 4)]
    legend = [(palette.TIERS[t][0], figures.TIER_NAMES[t]) for t in (1, 2, 3, 4)] + ([(palette.GREY[900], "background share")] if bg else [])
    svg = figures.hbars(rows, f"Genic region by tier, {c['preset']}", desc, c["synthetic"], legend)
    return svg, ["region", "tier", "snps", "background_share"], tsv


def _fig_terms(c, link, desc):
    counts = c["s"].get("terms", {}).get(c["trait"])
    if not counts:
        return None
    weights = (c["weights"] or {}).get("weights", {})
    n = c["s"].get("n_rows") or 1
    rows, tsv = [], []
    for term in [t for t in weights if t in counts] + [t for t in counts if t not in weights]:
        k = counts[term]
        label = f"{TERMS.get(term, term)} (+{weights[term]})" if term in weights else term
        rows.append({"label": label, "href": link(term=term) if link else None, "note": f"{sum(k.values()):,} ({pct(sum(k.values()), n)})",
                     "segments": _tier_segments(k, n, label, (lambda t, term=term: link(term=term, tier=str(t))) if link else None)})
        tsv += [(term, weights.get(term, ""), t, k.get(str(t), 0)) for t in (1, 2, 3, 4)]
    svg = figures.hbars(rows, f"Evidence behind the tiers, {c['preset']}", desc, c["synthetic"],
                        [(palette.TIERS[t][0], figures.TIER_NAMES[t]) for t in (1, 2, 3, 4)])
    return svg, ["term", "weight", "tier", "snps"], tsv


def _fig_maf(c, link, desc):
    m = c["s"].get("maf")
    if not m:
        return None
    width, bars, tsv = m["width"], [], []
    n = sum(m["bins"]) + m["missing"]
    bg = _shares(c["background"].get("maf_histogram")) if m["source"] == "public" else {}  # same public AF: comparable
    for i, k in enumerate(m["bins"]):
        lo, hi = round(i * width, 4), round((i + 1) * width, 4)
        share = bg.get(f"{lo:.2f}-{hi:.2f}")
        tip = f"MAF {lo:.2f}–{hi:.2f}: {k:,} SNPs ({pct(k, n)})" + (f"; public background {100 * share:.1f}%" if share is not None else "")
        href = link(min_maf=f"{lo:g}", max_maf=None if i == len(m["bins"]) - 1 else f"{hi:g}") if link else None
        bars.append((f"{lo:.2f}", k, palette.TIERS[3][0] if hi <= 0.05 + 1e-9 else palette.ACCENT, tip, href,
                     None if share is None else share * n))
        tsv.append((f"{lo:g}", f"{hi:g}", k, "" if share is None else f"{share:.5f}"))
    if m["missing"]:
        share = bg.get("unknown")
        bars.append(("none", m["missing"], palette.GREY[300], f"No allele frequency: {m['missing']:,} SNPs ({pct(m['missing'], n)})", None,
                     None if share is None else share * n))
        tsv.append(("NA", "NA", m["missing"], "" if share is None else f"{share:.5f}"))
    source = "your maf/af column" if m["source"] == "yours" else "504 public fish, pooled"
    svg = figures.histogram(bars, "Minor allele frequency", desc, c["synthetic"],
                            f"MAF bin (lower edge) from {source}" + ("; black ticks: public background" if bg else ""))
    return svg, ["maf_from", "maf_to", "snps", "background_share"], tsv


FIGURES = {  # name -> (card title, (i) definition, builder(context, link or None, desc) -> (svg, header, rows) or None)
    "tiers": ("SNPs per tier", "Tier 1 = strongest functional evidence for this trait; tier 4 = no evidence found (not "
              "evidence of no effect). Click a tier to list its SNPs.", _fig_tiers),
    "ideogram": ("Where the SNPs are", "Chromosomes to scale (Ssal_v3.1). Each 1 Mb bin is coloured by the best tier among "
                 "its SNPs (grey: tier 4 only); the bar on the right splits each chromosome's SNPs by tier. Click a bin "
                 "to list its SNPs.", _fig_ideogram),
    "conditions": ("Active chromatin per condition", "Share of the SNPs in an active chromatin state in each of the 21 "
                   "AQUA-FAANG conditions; × = fold over a background of public sites, when the release has one. "
                   "Outlined: the trait's conditions. Click a cell to list those SNPs.", _fig_conditions),
    "regions": ("Genic region by tier", "SNPs per genic region class (Ensembl 116), split by tier; the black tick is "
                "the share expected from a background of public sites. Click a bar to list those SNPs.", _fig_regions),
    "terms": ("Evidence behind the tiers", "For each evidence term (its weight in brackets), the SNPs it applies to, split "
              "by the tier they end in. A SNP can have several terms.", _fig_terms),
    "maf": ("Minor allele frequency", "MAF from your maf or af column when the list has one, else 504 public fish (wild "
            "and farmed, pooled; your strain can differ). Light bars: below 0.05. Black ticks: the count expected from a "
            "background of public sites. Click a bar to list those SNPs.", _fig_maf),
}
OPEN = ("tiers", "ideogram", "conditions")  # open on the Overview; the rest are under 'More charts'


def _figure_context(key, job, trait, summary, d):
    return {"key": key, "job": job, "trait": trait, "preset": jobs.trait_label(trait), "s": summary, "weights": jobs.weights(d),
            "manifest": jobs.manifest(d), "background": background(),
            "synthetic": bool(job.get("synthetic_input") or job.get("synthetic_layers")),
            "chip": jobs.read_json(d / "chip.json") if (d / "chip.parquet").exists() else {}}


def _trait(request, summary):
    trait = request.GET.get("trait", "all")
    return trait if trait in summary.get("tiers", {}) else "all"


def table_link(trait):
    """Overview marks link to the Table tab with their filter (plus the trait)."""
    def link(**params):
        return "?" + urlencode({k: v for k, v in {"tab": "table", "trait": trait, **params}.items() if v is not None})
    return link


def figure_card(c, name, svg):
    """Data for the _figure.html partial (provenance goes in the downloads, not on screen)."""
    url = reverse("snpportal:figure", args=[c["key"], name])
    query = urlencode({"trait": c["trait"]})
    return {"name": name, "title": FIGURES[name][0], "svg": mark_safe(svg), "svg_url": f"{url}?{query}",
            "tsv_url": f"{url}?{query}&format=tsv", "info": FIGURES[name][1]}


def overview(request, key, job):
    """Context for the Overview tab: key numbers, the top SNPs, the figures whose data exist and the upload QC line.
    Reads summary.json and validation.json, plus one top-N query."""
    d = jobs.folder(key)
    s = summary_of(d)
    trait = _trait(request, s)
    gwas = job.get("input_kind") == "gwas"
    c = _figure_context(key, job, trait, s, d)
    link = table_link(trait)
    figs = {}
    for name, (_, info, build) in FIGURES.items():
        if gwas and name not in ("tiers", "conditions"):
            continue
        built = build(c, link, info)
        if built:
            figs[name] = figure_card(c, name, built[0])
    validation = {} if gwas else jobs.read_json(d / "validation.json")
    best = top(request, key, job)
    tiers = s.get("tiers", {}).get(trait) or {}
    loci = None
    if gwas:
        from . import association
        loci = len(association.analyse(request, key)["loci"])
    qc_items, qc_warning = qc(validation)
    rejected = sum(v for v in (validation.get("rejected") or {}).values() if isinstance(v, int))
    association = f"{reverse('snpportal:association', args=[key])}?{urlencode({'trait': trait, **gwas_settings(request)})}" if gwas else None
    tiles = kpis(s, trait, validation, link, jobs.manifest(d), loci)
    for k in tiles:
        if k["label"] == "loci":
            k["href"] = association
    return {
        "kpis": tiles,
        "figs": {k: v for k, v in figs.items() if k in OPEN}, "more_figs": [v for k, v in figs.items() if k not in OPEN],
        "top": best, "n_top": int(tiers.get("1", 0)) + int(tiers.get("2", 0)), "top_link": link(tier="1-2"),
        "association": association,
        "qc_items": qc_items, "qc_warning": qc_warning, "qc_alias": validation.get("alias_warnings") or [],
        "qc_line": qc_line(validation), "qc_open": qc_problem(validation),
        "rejects": (d / "rejects.tsv").exists() and bool(rejected), "trait": trait, "trait_label": jobs.trait_label(trait),
        "keep": [(k, v) for k, v in best["chosen"].items() if k != "trait"] + list(gwas_settings(request).items()),
    }


def warnings_of(validation):
    """Short upload warnings from validation.json."""
    out = []
    if (validation.get("assembly") or {}).get("verdict") == "warning":
        out.append("assembly or strand mismatch")
    rejected = sum(v for v in (validation.get("rejected") or {}).values() if isinstance(v, int))
    if rejected:
        out.append(f"{rejected:,} rows rejected")
    if validation.get("columns_dropped"):
        out.append(f"{len(validation['columns_dropped'])} columns dropped")
    if validation.get("alias_warnings"):
        out.append("chromosome name warning")
    return out


def kpis(s, trait, validation, link, manifest=None, loci=None):
    """The key-number tiles [{value, label, note, href, warn}]: SNPs scored, tier 1-2, near a known locus and assay
    pass (GWAS jobs: loci instead of assay pass). They show at 0, as 0 is a finding; upload warnings only above 0."""
    n = s.get("n_rows") or 0
    out = [{"value": f"{n:,}", "label": "SNPs scored"}]
    tiers = s.get("tiers", {}).get(trait)
    if tiers is not None:
        top2 = int(tiers.get("1", 0)) + int(tiers.get("2", 0))
        out.append({"value": f"{top2:,}", "label": "tier 1–2", "note": f"{pct(top2, n)} of the SNPs", "href": link(tier="1-2")})
    if loci is not None:
        out.append({"value": f"{loci:,}", "label": "loci", "note": "see Association"})
    if "known" in s.get("counts", {}):
        window = ((manifest or {}).get("catalog") or {}).get("window")
        out.append({"value": f"{s['counts']['known']:,}", "label": "near a known locus",
                    "note": f"within {window / 1000:g} kb" if window else "", "href": link(known="1")})
    if s.get("assay") and loci is None:
        checked = n - s["assay"].get("not_checked", 0)
        out.append({"value": pct(s["assay"].get("pass", 0), checked), "label": "assay pass", "note": f"of {checked:,} checked",
                    "href": link(assay="pass")})
    found = warnings_of(validation) if validation else []
    if found:
        out.append({"value": f"{len(found)}", "label": "upload warnings", "note": "; ".join(found), "href": "#qc", "warn": True})
    return out


def qc_line(v):
    """'37 rows read · 37 scored · 0 rejected · Ssal_v3.1 confirmed': the upload QC in one line."""
    if not v:
        return ""
    rejected = sum(x for x in (v.get("rejected") or {}).values() if isinstance(x, int))
    verdict = (v.get("assembly") or {}).get("verdict")
    parts = [f"{v['rows_read']:,} rows read" if isinstance(v.get("rows_read"), int) else None,
             f"{v['snps_kept']:,} scored" if isinstance(v.get("snps_kept"), int) else None, f"{rejected:,} rejected",
             {"ok": "Ssal_v3.1 confirmed", "warning": "check the assembly"}.get(verdict, "assembly not checked")]
    return " · ".join(x for x in parts if x)


def qc_problem(v):
    """True when the upload QC should open by itself: fewer scored than read, rejected, merged, indel or multi-allelic
    rows, unknown or aliased chromosomes, unplaced or moved rs IDs, an assembly or reference-allele problem."""
    if not v:
        return False
    rsid, ref = v.get("rsid") or {}, v.get("ref_check") or {}
    rejected = sum(x for x in (v.get("rejected") or {}).values() if isinstance(x, int))
    fewer = isinstance(v.get("rows_read"), int) and isinstance(v.get("snps_kept"), int) and v["snps_kept"] < v["rows_read"]
    return bool(fewer or rejected or v.get("duplicates_merged") or v.get("indels") or v.get("multiallelic")
                or v.get("unknown_chromosomes") or v.get("alias_warnings") or rsid.get("unknown") or rsid.get("moved_from_icsasg_v2")
                or (v.get("assembly") or {}).get("verdict") == "warning"
                or any(ref.get(k) for k in ("mismatch", "strand_flip", "swapped")))


def figure(request, key, name, job):
    """A figure as a standalone SVG (provenance in <desc>, no links) or, with ?format=tsv, its data; ?plain=1 drops
    the '#' provenance lines."""
    if name not in FIGURES:
        raise Http404("No such figure")
    d = jobs.folder(key)
    s = summary_of(d)
    trait = _trait(request, s)
    lines = [] if request.GET.get("plain") else jobs.provenance(job, trait)
    built = FIGURES[name][2](_figure_context(key, job, trait, s, d), None, "\n".join(lines) or FIGURES[name][1])
    if built is None:
        raise Http404("No such figure")
    svg, header, rows = built
    if request.GET.get("format") == "tsv":
        body = "\n".join(lines + ["\t".join(header)] + ["\t".join(str(x) for x in r) for r in rows]) + "\n"
        response = HttpResponse(body, content_type="text/tab-separated-values; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{name}_{trait}.tsv"'
        return response
    response = HttpResponse(svg, content_type="image/svg+xml")
    response["Content-Disposition"] = f'attachment; filename="{name}_{trait}.svg"'
    return response


def qc(validation):
    """([(label, text)], warning or None) from snpscore's validation.json, in words; keys this portal doesn't know are
    shown as they are. The warning is snpscore's assembly verdict, so its threshold lives in one place."""
    v, items = validation, []

    def n(x):
        return f"{x:,}" if isinstance(x, int) and not isinstance(x, bool) else str(x)

    def counts(d, words=None):
        return ", ".join(f"{n(k)} {(words or {}).get(name, name.replace('_', ' '))}" for name, k in (d or {}).items()) or "none"

    def moves(rows, arrow=" → "):
        return "; ".join(f"{r.get('from', r.get('name'))}{arrow + str(r['to']) if 'to' in r else ''} ({n(r.get('rows'))} rows)"
                         + (f": {r['message']}" if r.get("message") else "") for r in rows or []) or "none"

    words = {
        "format": ("File format", lambda x: FORMAT_NAMES.get(x, x)),
        "rows_read": ("Rows read", n), "snps_kept": ("SNPs scored", n),
        "rejected": ("Rows rejected", lambda x: counts(x, REJECTS)),
        "unknown_chromosomes": ("Unknown chromosomes", moves),
        "aliases_applied": ("Chromosome names translated", moves),
        "alias_warnings": ("Chromosome name warnings", moves),
        "columns_renamed": ("Other columns, kept as", lambda x: ", ".join(f"{a} → {b}" for a, b in x.items()) or "none"),
        "columns_dropped": ("Columns not kept", lambda x: ", ".join(map(str, x)) or "none"),
        "rsid": ("Placed by rs ID (EVA release 9)", lambda x: f"{n(x.get('placed', 0))} by their Ssal_v3.1 rs position, "
                 f"{n(x.get('moved_from_icsasg_v2', 0))} moved from ICSASG_v2 ({n(x.get('alleles_complemented', 0))} with alleles "
                 f"complemented), {n(x.get('unknown', 0))} unknown"),
        "duplicates_merged": ("Duplicate rows dropped", n), "indels": ("Indels", n), "multiallelic": ("Multi-allelic rows", n),
        "ref_check": ("Reference alleles", lambda x: counts(x, REF_CHECKS)),
        "assay": ("Assay status", counts),
        "assay_reasons": ("Assay reasons", lambda x: counts(x, REASONS)),
    }
    for key, value in v.items():
        if key in ("ref_check_sampled", "assembly") or key in QUIET and not value:
            continue
        label, fmt = words.get(key, (key.replace("_", " ").capitalize(), _plain))
        items.append((label, fmt(value)))
        if key == "ref_check" and v.get("ref_check_sampled"):
            items[-1] = (label, items[-1][1] + " (a sample of the SNPs: the genome is read remotely)")
    assembly = v.get("assembly") if isinstance(v.get("assembly"), dict) else {}
    warning = None
    if assembly:
        verdict, checked = assembly.get("verdict"), assembly.get("checked") or 0
        share = assembly.get("mismatch_or_flip_share")
        text = {"ok": f"Ssal_v3.1 confirmed: {share or 0:.1%} of {n(checked)} checked SNPs mismatch or flip",
                "warning": f"check the assembly: {share or 0:.1%} of {n(checked)} checked SNPs mismatch or flip"}.get(
            verdict, f"not checked{': ' + assembly['message'] if assembly.get('message') else ' (no alleles to compare)'}")
        items.append(("Assembly check", text))
        if verdict == "warning":
            warning = assembly.get("message") or "Many checked alleles don't match the Ssal_v3.1 reference base."
    return items, warning


def _plain(value):
    """A validation value as short text: {'name': 'ssa25', 'rows': 3} -> 'ssa25 (3)'."""
    if isinstance(value, dict):
        if "rows" in value:
            return " → ".join(str(v) for k, v in value.items() if k != "rows") + f" ({_plain(value['rows'])})"
        return ", ".join(f"{k}: {_plain(v)}" for k, v in value.items()) or "none"
    if isinstance(value, list):
        return ", ".join(_plain(v) for v in value) or "none"
    if isinstance(value, bool):
        return "yes" if value else "no"
    return f"{value:,}" if isinstance(value, int) else str(value)
