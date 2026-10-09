"""Results of a finished job: the Overview (key numbers, genome-wide figures, upload QC), the Table (filters, columns
and the evidence drawer) and the figures (the full evidence card is in locus.py). Tiers for the chosen trait come from
the job's tiers.parquet (precomputed for every preset), so switching traits never rescores; snpscore.scored() runs per
request only for presets missing from it. The Overview reads summary.json; the table sorts and pages on the server in
two steps (row numbers first, then that page's columns)."""
from __future__ import annotations

import os
import re
import uuid
from types import SimpleNamespace
from urllib.parse import urlencode

from django.http import Http404, HttpResponse, QueryDict
from django.urls import reverse
from django.utils.safestring import mark_safe

import snpscore
from snpscore import panel as snp_panel
from snpscore.coding import AA
from snpscore.formats import lit

from . import figures, jobs, palette
from .jobs import ident

PAGE_SIZE = 50
PAGE_SIZES = (50, 100, 250, 500)  # rows per page, under the table
REGIONS = jobs.REGION_GROUPS
REGION_LABELS = {"coding": "coding (CDS, splice)", "UTR": "UTR", "exon": "non-coding exon", "intron": "intron",
                 "intergenic": "intergenic", "other": "other"}
CLASS_LABELS = {"CDS": "CDS", "splice_region": "splice region", "five_prime_UTR": "5′ UTR", "three_prime_UTR": "3′ UTR",
                "exon": "non-coding exon", "intron": "intron"}
CONSEQUENCES = {"missense_variant": "missense", "synonymous_variant": "synonymous", "stop_gained": "stop gained",
                "stop_lost": "stop lost", "start_lost": "start lost", "stop_retained_variant": "stop retained",
                "incomplete_terminal_codon_variant": "incomplete last codon", "coding_sequence_variant": "CDS",
                "splice_donor_variant": "splice donor", "splice_acceptor_variant": "splice acceptor"}  # snpscore.coding
PROTEIN = "('missense_variant', 'stop_gained', 'stop_lost', 'start_lost')"
SAME = "('synonymous_variant', 'stop_retained_variant')"
CONSEQUENCE_FILTERS = {  # the Consequence filter, as the column reads -> (label, SQL, columns it needs)
    "missense": ("protein-changing", f"coding_consequence IN {PROTEIN}", ("coding_consequence",)),
    "synonymous": ("synonymous", f"coding_consequence IN {SAME}", ("coding_consequence",)),
    "cds": ("coding (effect unknown)", f"region_class = 'CDS' AND coalesce(coding_consequence, '') NOT IN {PROTEIN[:-1]}, "
            f"{SAME[1:-1]}, 'splice_donor_variant', 'splice_acceptor_variant')", ("region_class", "coding_consequence")),
    "splice": ("splice site or region", "region_class = 'splice_region' OR coalesce(coding_consequence, '') IN "
               "('splice_donor_variant', 'splice_acceptor_variant')", ("region_class", "coding_consequence")),
    "utr5": ("5′ UTR", "region_class = 'five_prime_UTR'", ("region_class",)),
    "utr3": ("3′ UTR", "region_class = 'three_prime_UTR'", ("region_class",)),
    "exon": ("non-coding exon", "region_class = 'exon'", ("region_class",)),
    "intron": ("intron", "region_class = 'intron'", ("region_class",)),
    "intergenic": ("intergenic", "region_class IS NULL", ("region_class",)),
}
CONSEQUENCE_GROUPS = {"coding": ("missense", "synonymous", "cds", "splice"), "UTR": ("utr5", "utr3")}  # the Overview's groups
HIDE = {  # checkbox -> (label, column it needs, SQL condition a SNP must meet to stay); hide_lore: older links (now in Assay)
    "hide_blacklist": ("blacklisted", "blacklist", "NOT blacklist"),
    "hide_lore": ("LORe", "lore", "NOT lore"),
    "hide_ambiguous": ("A/T or C/G", "strand_ambiguous", "NOT coalesce(strand_ambiguous, false)"),
    "hide_flank": ("variants within 35 bp", "flank_variants", "flank_variants = 0"),
    "hide_near_chip": ("near the chip", "near_chip", "NOT near_chip"),  # with a chip on the Panel tab (P6.6)
}
TIER_SETS = {"1-2": ("1", "2"), "1-3": ("1", "2", "3"), "1-4": ("1", "2", "3", "4")}  # tier ranges of older links
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
TERMS = {"active": "active in the chosen conditions", "active_elsewhere": "active elsewhere only",
         "weak": "weak state in the chosen conditions", "coding": "CDS (protein change or unknown)", "synonymous": "CDS (synonymous)",
         "splice": "splice region", "utr": "UTR",
         "constrained": "GERP constrained", "regbuild": "Ensembl regulatory", "molqtl": "molQTL lead (display only)"}
GROUP_STARTS = ("dd-maf", "dd-more")  # gaps in the bar above the table (filters of hidden columns)
ACTIVITY = {  # Active in: what a SNP must be in, in at least one of the chosen conditions (PROVISIONAL, CLAUDE.md)
    "peak": ("Regulatory element", "inside an AQUA-FAANG robust ATAC peak (any chromatin state)"),
    "active": ("Active element", "inside a peak in an active state (Active_TSS or Active_enhancer: the +3 tier term)")}
TERM_SHORT = {"active": "active", "active_elsewhere": "active elsewhere", "weak": "weak", "coding": "CDS", "synonymous": "synonymous",
              "splice": "splice", "utr": "UTR", "constrained": "constrained", "regbuild": "Ensembl reg.", "molqtl": "molQTL"}
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
    "tier": ("Tier", "1 = strongest functional evidence for the chosen conditions; 4 = no evidence found (not evidence of no effect)",
             ("tier",), [("tier", True), ("tier_score", False)]),
    "score": ("Score", "Tier score: the summed weights of the SNP's evidence (its card lists them)", ("tier_score",),
              [("tier_score", False)]),
    "id": ("SNP locus", "SNP id, its position (Ssal_v3.1, 1-based) when the id doesn't say it, and alleles (ref > alt): "
           "click for its card", (), [("length(chrom)", True), ("chrom", True), ("pos", True)]),
    "p": ("p", "GWAS p value", ("neglog10p",), [("neglog10p", False)]),
    "beta": ("beta (se)", "GWAS effect of the alt allele (standard error)", ("beta",), [("beta", False)]),
    "pip": ("PIP", "Posterior inclusion probability, uniform → functional prior; one causal variant per locus, no LD. "
            "Blank outside loci", ("pip_uniform",), [("pip_functional", False)]),
    "gene": ("Gene", "Nearest Ensembl 116 gene (and how far, when the SNP is outside it); ~NAME: unnamed in Ensembl, named "
             "by its human ortholog", ("gene_name", "gene_id"),
             [("coalesce(gene_name, gene_ortholog_human, gene_id)", True)]),
    "region": ("Consequence", "Where the SNP falls in the nearest gene and, in coding sequence, its effect on the protein "
               "(Ensembl 116 gene models)", ("region_class",), [("region_class", True)]),
    "chromatin": ("Chromatin", "AQUA-FAANG chromatin state in 21 conditions: Brain, Gonad, Liver, Muscle (immature F, M; "
                  "mature F, M), then 5 embryo stages. Underlined: the chosen conditions", ("chromatin",), []),
    "known": ("Known locus", "A published locus of the known-loci catalogue within the window: this SNP, or one nearby (how "
              "far); * a caveat (hover)", ("known_locus",), [("known_locus_dist", True)]),
    "molqtl": ("molQTL", "Lead SNP of an eQTL (e) or caQTL (ca) in 12 fish; display only, never counted in tiers",
               ("molqtl",), [("molqtl_best_bf", True)]),
    "gerp": ("GERP", "GERP constrained-element score (65 fish)", ("gerp_score",), [("gerp_score", True)]),
    "regbuild": ("Ensembl reg.", "Ensembl 116 regulatory build feature", ("regbuild_type",), [("regbuild_type", True)]),
    "maf": ("MAF", MAF_TIP, ("maf", "af", "public_af_maf"), [("{maf}", True)]),
    "cm": ("cM (F/M)", "Genetic map position, female / male cM (Brekke et al. 2023 linkage map, interpolated)",
           ("cm_female",), [("cm_female", True)]),
    "assay": ("Assay", "Assay design check of the probe flanks; hover for the reasons", ("assay_status",), [("assay_status", True)]),
    "flags": ("Flags", "Blacklisted region, LORe, A/T or C/G, public variants within 35 bp",
              ("blacklist", "lore", "strand_ambiguous", "flank_variants"), []),
    "ref_check": ("Ref. check", "Input ref allele against the Ssal_v3.1 genome", ("ref_check",), [("ref_check", True)]),
}  # in display order: the score, the SNP, where it is, what it is, then genotyping
NUMERIC = ("score", "p", "beta", "pip", "gerp", "maf", "cm")  # right-aligned, header and cells
DEFAULT_COLUMNS = ("tier", "score", "id", "gene", "region", "chromatin", "known", "maf", "assay")
GWAS_COLUMNS = ("tier", "score", "id", "p", "beta", "pip", "gene", "region", "chromatin")
EXTRA = {"id": ("id", "chrom", "pos", "ref", "alt"), "tier": ("tier_score", "tier_evidence", "tier_terms", "coding_hgvsp", "known_locus",
                                                                "known_locus_dist"), "known": ("known_locus_dist",),
         "gene": ("gene_ortholog_human", "gene_distance"), "region": ("gene_distance", "coding_consequence", "coding_hgvsp", "coding_transcript", "coding_note"), "beta": ("se",), "pip": ("pip_functional",),
         "assay": ("assay_reasons", "blacklist", "lore", "strand_ambiguous", "flank_variants"),
         "molqtl": ("molqtl_tissues", "molqtl_kinds", "molqtl_features"), "cm": ("cm_male",)}  # also fetched


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
    trait = "all"
    if weights:
        trait = jobs.requested_trait(request.GET.get, request.GET.getlist, weights["presets"])
        path, suffix = jobs.trait_tiers(d, weights, trait)  # a new set of conditions is scored on its first view
        stored = [c for c, in con.execute(f"SELECT column_name FROM (DESCRIBE SELECT * FROM read_parquet('{path}'))").fetchall()] if path else []
        picked = [c for c in jobs.TIER_COLUMNS if f"{c}__{suffix}" in stored]
        if picked:
            drop = [c for c in jobs.TIER_COLUMNS if c in columns]
            keep = f"r.* EXCLUDE ({', '.join(drop)})" if drop else "r.*"
            tiers = ", ".join(f"t.{ident(f'{c}__{suffix}')} AS {c}" for c in picked)
            con.execute(f"CREATE VIEW v0 AS SELECT {keep}, {tiers} FROM r JOIN read_parquet('{path}') t USING (file_row_number)")
        else:  # a job made before tiers.parquet existed
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
    conds = filters(request, types, weights) + [m for m in [manual(d)] if m]  # the − rows: out of the selection
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


def picks(request, name):
    """The values of a multi-choice filter: ticked boxes send one each, links carry them comma-joined."""
    return list(dict.fromkeys(x for v in request.GET.getlist(name) for x in v.split(",") if x))


def tier_text(tiers):
    """'1–3' for a run of tiers, else '1, 3'."""
    t = [int(x) for x in tiers]
    return f"{t[0]}–{t[-1]}" if len(t) > 2 and t == list(range(t[0], t[-1] + 1)) else ", ".join(map(str, t))


def consequences(values, types):
    """The Consequence filter's values in the column's order, the Overview's groups ('coding', 'UTR') spelled out;
    those whose columns the result lacks are dropped (without coding_consequence, CDS stands for all of coding)."""
    wanted = {y for x in values for y in CONSEQUENCE_GROUPS.get(x, (x,))}
    if "coding_consequence" not in types and wanted & {"missense", "synonymous"}:
        wanted |= {"cds"}
    return [k for k, (_, _, needs) in CONSEQUENCE_FILTERS.items()
            if k in wanted and needs[0] in types and (k not in ("missense", "synonymous") or "coding_consequence" in types)]


def consequence_sql(key, types):
    sql = CONSEQUENCE_FILTERS[key][1]
    return sql if "coding_consequence" in types else sql.split(" AND coalesce(coding_consequence")[0].split(" OR coalesce(coding_consequence")[0]


def filters(request, types, weights):
    """[(URL parameters, chip label, SQL)] for the whitelisted filters in the request whose columns exist. Other
    parameters are ignored; values are checked or quoted before they reach SQL."""
    get, out = request.GET.get, []
    tiers = sorted({t for x in picks(request, "tier") or [{"1": "1", "2": "1-2", "3": "1-3"}.get(get("max_tier", ""), "")]
                    for t in TIER_SETS.get(x, [x]) if t in TIER_SETS["1-4"]})  # max_tier, 1-2: older links
    if tiers and len(tiers) < 4 and "tier" in types:
        out.append(({"tier": ",".join(tiers)}, f"Tier {tier_text(tiers)}", f"tier IN ({', '.join(tiers)})"))
    regions = [x for x in consequences(picks(request, "region"), types)]
    if regions:  # any of them
        out.append(({"region": ",".join(regions)}, "Consequence: " + ", ".join(CONSEQUENCE_FILTERS[x][0] for x in regions),
                    " OR ".join(f"({consequence_sql(x, types)})" for x in regions)))
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
    statuses = {s for x in picks(request, "assay") for s in (("pass", "warn") if x in ("ok", "ok_nolore") else (x,))}  # ok: older links
    statuses = [s for s in ASSAY if s in statuses]
    if "assay_status" in types and statuses and len(statuses) < len(ASSAY):  # any of them
        out.append(({"assay": ",".join(statuses)}, "Assay: " + ", ".join(s.replace("_", " ") for s in statuses),
                    f"coalesce(assay_status, 'not_checked') IN ({', '.join(lit(s) for s in statuses)})"))
    nolore = "ok_nolore" in picks(request, "assay")
    if get("known") == "1" and "known_locus" in types:
        out.append(({"known": "1"}, "Known loci only", "known_locus IS NOT NULL"))
    if get("molqtl") == "1" and "molqtl" in types:
        out.append(({"molqtl": "1"}, "molQTL lead SNPs", "coalesce(molqtl, false)"))
    active = get("active", "")
    if weights and active and f"chromatin_{active}" in types and f"chromatin_{active}" not in snpscore.score.NOT_CONDITIONS:
        states = ", ".join(lit(s) for s in weights.get("active_states", [])) or "NULL"
        out.append(({"active": active}, f"Active in {condition_label(active)}", f"{ident('chromatin_' + active)} IN ({states})"))
    trait = jobs.requested_trait(get, request.GET.getlist, weights["presets"]) if weights else "all"
    if trait != "all" and conditions_of(types):  # Active in: SNPs in an element of at least one of its conditions
        level = get("act") if get("act") in ACTIVITY else "peak"
        states = ", ".join(lit(s) for s in weights.get("active_states", [])) or "NULL"
        test = "IS NOT NULL" if level == "peak" else f"IN ({states})"  # a peak has a state; active: TSS or enhancer
        mine = snpscore.score.preset_conditions(weights, list(types), trait)[0]
        out.append(({"trait": trait, **({"act": level} if level != "peak" else {})},
                    f"Active in {jobs.trait_label(trait)}" + (" (active state)" if level != "peak" else ""),
                    " OR ".join(f"{ident('chromatin_' + c)} {test}" for c in mine) or "false"))
    terms = [t for t in picks(request, "term") if t in (weights or {}).get("weights", {})]
    if terms and "tier_terms" in types:  # several: any of them (links carry them comma-joined)
        out.append(({"term": ",".join(terms)}, "Evidence: " + ", ".join(TERMS.get(t, t) for t in terms),
                    f"list_has_any(list_transform(tier_terms, x -> x.term), [{', '.join(lit(t) for t in terms)}])"))
    for name, (label, column, condition) in HIDE.items():
        if (get(name) or name == "hide_lore" and nolore) and column in types:
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
    """The conditions a trait's tiers use, e.g. 'maturation: Brain, Gonad'; an Active-in selection's label names them."""
    if jobs.selection(trait):
        return jobs.trait_label(trait)
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

def tier_facets(con, view, conds, types, summary, trait):
    """[(tier, SNPs)] under every filter but the tier one, so each tier's count says what ticking it would show (the
    whole list's from summary.json when nothing else filters)."""
    if "tier" not in types:
        return []
    others = [c for c in conds if "tier" not in c[0]]
    if not others and (summary.get("tiers") or {}).get(trait):
        return sorted((int(x), k) for x, k in summary["tiers"][trait].items())
    return con.execute(f"SELECT tier, count(*) FROM {view} {_where(others)} GROUP BY tier ORDER BY tier").fetchall()


def table(request, key, job=None):
    """Context for the Table tab: one page of rows sorted and paged on the server, the filters (one row, the rest under
    'More filters'), chips, the column chooser, an empty-state hint and the evidence drawer (?snp=<row>). Fast on 1.6M
    rows: page row numbers are found first using only the filter and sort columns, then only that page's columns are
    read. GWAS jobs show p, beta and the PIPs of association.analyse()."""
    gwas = (job or {}).get("input_kind") == "gwas"
    d, ask = jobs.folder(key), request.GET.get
    picks_out = unselected(d)  # the selector column: exclude=<row> marks it −, include=<row> + again, include_all=1 all +
    changed = picks_out | ({int(ask("exclude"))} if ask("exclude", "").isdecimal() else set())
    changed -= {int(ask("include"))} if ask("include", "").isdecimal() else set()
    if ask("include_all"):
        changed = set()
    if changed != picks_out:
        keep_unselected(d, changed)
        picks_out = changed
    if gwas:  # association.analyse's connection: view v plus the fine-mapping (table fm) of the loci, for the PIPs
        from . import association
        a = association.analyse(request, key)
        con, weights = a["con"], jobs.weights(jobs.folder(key))
        pips = ("SELECT file_row_number, max(pip_uniform) AS pip_uniform, max(pip_functional) AS pip_functional FROM fm GROUP BY 1"
                if a["loci"] else "SELECT NULL::BIGINT AS file_row_number, NULL::DOUBLE AS pip_uniform, NULL::DOUBLE AS pip_functional")
        con.execute(f"CREATE VIEW vt AS SELECT v.*, f.pip_uniform, f.pip_functional FROM v LEFT JOIN ({pips}) f USING (file_row_number)")
        types = dict(con.execute("SELECT column_name, column_type FROM (DESCRIBE vt)").fetchall())
        conds = filters(request, types, weights) + [m for m in [manual(d)] if m]
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
    picked = [k for k in available if k == "id" or k in request.GET.getlist("col")] if get("cols") else default  # the SNP always
    custom_cols = set(picked) != set(default)  # the chooser sends every ticked column: short URLs for the default
    shown = list(picked if custom_cols else default)
    sort = get("sort", "")
    explicit = sort in available and bool(COLUMNS[sort][3])
    sort = sort if explicit else ("p" if gwas and "p" in available else "tier" if "tier" in available else "")
    desc = get("desc") == "1"
    size = int(get("size")) if get("size", "").isdecimal() and int(get("size")) in PAGE_SIZES else PAGE_SIZE

    total = con.execute("SELECT count(*) FROM r").fetchone()[0]
    every, mark = [c for c in conds if c[1] != UNSELECTED], next((c for c in conds if c[1] == UNSELECTED), None)
    view_picks = get("picked") if get("picked") in ("in", "out") and mark else "all"
    shown_conds = every + ([mark] if view_picks == "in" else [({}, "Unselected only", mark[2].replace("NOT IN", "IN"))]
                           if view_picks == "out" else [])
    selection_conds, conds = conds, shown_conds  # the selection leaves the − rows out; the table shows what the selector asks
    where = _where(conds)
    order = [f"{sql.format(maf=maf)} {'ASC' if asc != desc else 'DESC'} NULLS LAST" for sql, asc in (COLUMNS[sort][3] if sort else [])]
    # Count and page on the raw result r (no tiers join) unless the filters or the sort use a column only v has right
    only_v = (set(types) - {c for c, in con.execute("SELECT column_name FROM (DESCRIBE r)").fetchall()}) | set(jobs.TIER_COLUMNS)
    uses_v = any(re.search(rf"\b{re.escape(c)}\b", sql) for c in only_v for sql in [where] + order)
    src = view if gwas or uses_v else "r"
    matching = con.execute(f"SELECT count(*) FROM {src} {where}").fetchone()[0] if conds else total
    n_out = con.execute(f"SELECT count(*) FROM {view} {_where(every + [({}, '', mark[2].replace('NOT IN', 'IN'))])}").fetchone()[0] \
        if mark else 0  # − rows among the filtered ones
    n_every = matching if view_picks == "all" else con.execute(f"SELECT count(*) FROM {view} {_where(every)}").fetchone()[0]
    pages = max(1, -(-matching // size))
    page = min(int(get("page")) if get("page", "").isdecimal() else 1, pages) or 1
    ids = [i for i, in con.execute(f"SELECT file_row_number FROM {src} {where} ORDER BY {', '.join(order + ['file_row_number'])} "
                                   f"LIMIT {size} OFFSET {(page - 1) * size}").fetchall()]
    conditions = conditions_of(types)
    in_preset = set(snpscore.score.preset_conditions(weights, list(types), chosen["trait"])[0]) if weights and conditions else set()
    caveats = _known_caveats() if "known" in shown else {}
    rows = _page(con, view, ids, types, shown, maf, conditions, in_preset, (weights or {}).get("active_states", []), caveats)

    base = {"tab": "table", **chosen, **settings, "sort": sort if explicit else "", "desc": "1" if desc else "",
            "size": str(size) if size != PAGE_SIZE else "", "cols": "1" if custom_cols else "",
            "col": [k for k in shown if k != "id"] if custom_cols else [], "picked": "" if view_picks == "all" else view_picks}

    def link(drop=(), **changes):
        params = {k: v for k, v in base.items() if k not in drop}
        params.update(changes)
        return "?" + urlencode({k: v for k, v in params.items() if v not in ("", None, [])}, doseq=True)

    keep_selection(jobs.folder(key), urlencode({k: v for k, v in base.items() if k != "tab" and v not in ("", None, [])}, doseq=True))
    here = page if page > 1 else None
    snp = int(get("snp")) if get("snp", "").isdecimal() else None
    for r in rows:
        r["href"] = link(page=here, snp=r["n"])
        r["out"] = r["n"] in picks_out  # the selector: + in the selection, − taken out (one click each way)
        r["pick"] = link(page=here, **({"include": r["n"]} if r["out"] else {"exclude": r["n"]}))
    filter_keys = [k for params, _, _ in conds for k in params]
    chips = [(label, link(drop=list(params), page=None)) for params, label, _ in conds]
    suggest = None
    if conds and not matching and len(conds) > 1:  # name the filter that removes the most on its own
        counts = con.execute("SELECT " + ", ".join(f"count(*) FILTER (WHERE {_where(conds[:i] + conds[i + 1:])[6:]})"
                                                   for i in range(len(conds))) + f" FROM {view}").fetchone()
        best = max(range(len(conds)), key=lambda i: counts[i])
        if counts[best]:
            suggest = (conds[best][1], counts[best], chips[best][1])

    # The filter bar: dropdowns (a summary of the choice, a panel applied on change) in this order. 'list' panels tick
    # any of several values ('Any' clears them), 'radio' panels pick one; Active in, Location and More have their own.
    tier_counts = tier_facets(con, view, conds, types, summary, chosen["trait"])
    ticked = {k: [x for x in chosen.get(k, "").split(",") if x] for k in ("tier", "region", "assay", "term")}
    dds = []

    def dd(kind, key, label, summary, active, tip="", **more):
        ticks = more.get("tissues") or (more.get("options") if kind == "list" else ())
        dds.append({"kind": kind, "id": f"dd-{key}", "label": label, "summary": summary, "on": active, "tip": tip,
                    "anyon": not any(x[2 if len(x) > 2 else 1] for x in ticks), **more})  # 'Any' ticked: nothing else is

    if weights and conditions:  # the conditions tiers score against: tissues, maturity and sex, or a trait preset
        tissues, maturity, sex = jobs.selection_of(chosen["trait"], weights["presets"])
        every = len(tissues) == len(jobs.TISSUES)
        level = chosen.get("act", "peak")
        dd("active", "active", "Active in", jobs.trait_label(chosen["trait"]) + (" · active state" if level != "peak" else ""),
           chosen["trait"] != "all", "SNPs active in at least one of these conditions; tiers count activity there",
           tissues=[(x, x in tissues and not every) for x in jobs.TISSUES],
           maturity=[("", "any", not maturity)] + [(x, x.lower(), x == maturity) for x in jobs.MATURITIES],
           sex=[("", "any", not sex)] + [(x, x.lower(), x == sex) for x in jobs.SEXES],
           levels=[(k, label, tip, k == level) for k, (label, tip) in ACTIVITY.items()], column="chromatin",
           reset=link(trait=None, act=None, page=None) if chosen["trait"] != "all" else None)
    if "tier" in types:
        counts = dict(tier_counts)
        dd("list", "tier", "Tier", f"{tier_text(ticked['tier'])}" if ticked["tier"] else "any", bool(ticked["tier"]),
           "1 = strongest functional evidence for these conditions; 4 = no evidence found", name="tier", any="Any tier", column="tier",
           options=[(str(x), f"Tier {x}", str(x) in ticked["tier"], f"{counts.get(x, 0):,}") for x in (1, 2, 3, 4)])
    if weights and "tier_terms" in types:
        dd("list", "term", "Evidence", ", ".join(TERM_SHORT.get(x, x) for x in ticked["term"]) or "any", bool(ticked["term"]),
           "SNPs with any of the ticked evidence terms (the score sums their weights)", name="term", any="Any evidence", column="score",
           options=[(x, TERMS.get(x, x), x in ticked["term"], "") for x in weights.get("weights", {})])
    if "region_class" in types:
        offered = consequences(CONSEQUENCE_FILTERS, types)
        dd("list", "region", "Consequence", ", ".join(CONSEQUENCE_FILTERS[x][0] for x in ticked["region"]) or "any",
           bool(ticked["region"]), "Where the SNP falls in the nearest gene, and its effect on the protein; any of the ticked ones",
           name="region", any="Any consequence", column="region",
           options=[(x, CONSEQUENCE_FILTERS[x][0], x in ticked["region"], "") for x in offered])
    chroms = sorted((summary.get("chrom_tiers", {}).get(chosen["trait"]) or {}), key=_chrom_key) or \
        sorted((c for c, in con.execute("SELECT DISTINCT chrom FROM r").fetchall()), key=_chrom_key)
    where_text = next((label for params, label, _ in conds if "chrom" in params), "any")
    dd("location", "where", "Location", where_text.replace("Chromosome ", "chr"), "chrom" in chosen,
       "A chromosome, or a range on it (start exclusive, end inclusive)", chroms=[(c, c == chosen.get("chrom")) for c in chroms],
       column="id")
    if any(c in types for c in ("gene_name", "gene_id")):
        dd("gene", "gene", "Gene", chosen.get("gene", ""), bool(chosen.get("gene")), "A gene's name, Ensembl id or ortholog",
           value=chosen.get("gene", ""), column="gene")
    if maf:
        dd("radio", "maf", "MAF", f"≥ {chosen['min_maf']}" if "min_maf" in chosen else "any", "min_maf" in chosen,
           MAF_TIP if maf_source == "public" else "Your maf/af column", name="min_maf", column="maf",
           options=[("", "any", "min_maf" not in chosen)] + [(m, f"≥ {m}", chosen.get("min_maf") == m) for m in MAFS])
    if "assay_status" in types:
        extras = [("hide_lore", "not in LORe regions", "hide_lore" in chosen)] if "lore" in types else []
        dd("list", "assay", "Assay", ", ".join(x.replace("_", " ") for x in ticked["assay"]) + (" · no LORe" if "hide_lore" in chosen else "")
           or "any", bool(ticked["assay"]) or "hide_lore" in chosen,
           "Assay design check of the probe flanks. LORe: duplicated chromosomes still pair, probes may cross-hybridise",
           name="assay", any="Any status", options=[(x, x.replace("_", " "), x in ticked["assay"], "") for x in ASSAY], extras=extras,
           column="assay")
    if "known_locus" in types:
        dd("more", "known", "Known locus", "near one", "known" in chosen, extras=[("known", "only SNPs near a known locus", "known" in chosen)],
           column="known")
    if "molqtl" in types:
        dd("more", "molqtl", "molQTL", "leads", "molqtl" in chosen, extras=[("molqtl", "only molQTL lead SNPs", "molqtl" in chosen)],
           column="molqtl")
    checks = [(name, f"hide {label}", name in chosen) for name, (label, column, _) in HIDE.items() if column in types and name != "hide_lore"]
    n_on = sum(c for _, _, c in checks)
    if checks:
        dd("more", "more", "Flags", f"{n_on} hidden" if n_on else "", bool(n_on), "Leave out flagged SNPs", extras=checks, column="flags")
    pick = {"kind": "pick", "id": "dd-pick", "label": "Selected", "on": view_picks != "all",
            "summary": {"all": "", "in": "+ only", "out": "− only"}[view_picks],
            "views": [("", f"all rows ({n_every:,})", view_picks == "all"), ("in", f"selected, + ({n_every - n_out:,})", view_picks == "in"),
                      ("out", f"unselected, − ({n_out:,})", view_picks == "out")] if n_out else [],
            "reset": link(include_all=1, picked=None, page=None) if n_out else None}
    for x in dds:  # a filter sits on its column when the table shows it, else in the bar above
        x["header"] = x.get("column") in shown
    on_column = {x["column"]: x for x in dds if x["header"]}

    headers = []
    for k in shown:
        label, tip, _, sorts = COLUMNS[k]
        if k == "maf" and maf_source == "yours":
            tip = "Minor allele frequency from your maf or af column"
        on = k == sort
        href = link(sort=k, desc="1" if on and not desc else "", page=None) if sorts else None
        headers.append((k, label, tip, href, ("descending" if desc else "ascending") if on else "", on_column.get(k),
                        "sp-num" if k in NUMERIC else "sp-ctr" if k == "tier" else ""))
    shown_tiers = tier_counts if not ticked["tier"] else \
        [(x, k) for x, k in tier_counts if str(x) in ticked["tier"]]  # the tiers of the rows the table shows
    filtered = urlencode(chosen)
    return {
        "total": total, "matching": matching, "first": (page - 1) * size + 1 if matching else 0,
        "last": min(page * size, matching), "chosen": chosen, "query": urlencode({"trait": chosen["trait"], **settings}),
        "added": int(get("added")) if get("added", "").isdecimal() else None,
        "panel_error": {"empty": "No SNPs in this selection to add.",
                        "many": f"Narrow the selection to at most {int(jobs.setting('SNPPORTAL_MAX_PANEL_SNPS', 50_000)):,} SNPs to add it to the panel."
                        }.get(get("panel_error", "")),
        "dds": dds, "pick": pick, "n_selected": n_every - n_out, "n_out": n_out,
        "shown_tiers": [(x, k) for x, k in shown_tiers if x is not None and k],
        "active_set": any(x["kind"] == "active" for x in dds), "groups": GROUP_STARTS,
        "gene": chosen.get("gene", "") if any(c in types for c in ("gene_name", "gene_id")) else None,
        "start": chosen.get("start", ""), "end": chosen.get("end", ""),
        "hidden": [(k, base[k]) for k in ("sort", "desc", "size") if base[k]]  # and filters with no control on the form
        + [(k, chosen[k]) for k in ("hide_reason", "max_maf", "active") if k in chosen] + list(settings.items()),
        "columns": [(k, COLUMNS[k][0], k in shown) for k in available if k != "id"], "chips": chips,
        "clear": link(drop=filter_keys, page=None) if conds else None, "suggest": suggest,
        "headers": headers, "shown": shown, "rows": rows, "page": page, "pages": pages,
        "prev": link(page=page - 1) if page > 1 else None, "next": link(page=page + 1) if page < pages else None,
        "sizes": [(s, link(size=str(s) if s != PAGE_SIZE else None, page=None), s == size) for s in PAGE_SIZES],
        "download": f"{reverse('snpportal:download', args=[key])}?{filtered}" if selection_conds else None,
        "vendor": f"?{urlencode({'tab': 'export', 'scope': 'filtered', **chosen})}" if selection_conds and not gwas else None,
        "snp": snp, "drawer": _drawer(request, key, job, snp, link(page=here)) if snp is not None else None,
    }


def _page(con, view, ids, types, shown, maf, conditions, in_preset, active_states, caveats):
    """Display-ready rows for the row numbers `ids`, in that order. Reads only the shown columns."""
    if not ids:
        return []
    wanted = {"file_row_number"} | {c for k in shown for c in COLUMNS[k][2] + EXTRA.get(k, ()) if c in types}
    if "chromatin" in shown:
        wanted |= {f"chromatin_{c}" for c in conditions}
    select = ", ".join(map(ident, sorted(wanted))) + (f", {maf} AS _maf" if maf and "maf" in shown else "")
    cur = con.execute(f"SELECT {select} FROM {view} WHERE file_row_number IN ({', '.join(str(int(i)) for i in ids)})")
    names = [x[0] for x in cur.description]
    found = {r["file_row_number"]: r for r in (dict(zip(names, x)) for x in cur.fetchall())}
    groups = condition_groups(conditions)
    return [_row(found[i], groups, in_preset, set(active_states), caveats) for i in ids if i in found]


def _dist(bp):
    return f"{bp:,} bp" if bp < 1000 else f"{bp / 1000:,.1f} kb"


def locus_note(g):
    """The SNP locus cell's grey note: the position when the id doesn't hold it, and the alleles when it doesn't
    ('28_15139512_A_C' needs none; 'vgll3_Met54Thr' gets '25:28,996,360 · C>T')."""
    name, pos, ref, alt = g("id") if g("id") not in (None, ".") else "", g("pos"), g("ref"), g("alt")
    where = f"{g('chrom')}:{pos:,}" if name and str(pos) not in name else ""
    alleles = _alleles(g) if not (ref and alt and any(f"{ref}{s}{alt}" in name for s in "_>/:")) else ""
    return " · ".join(x for x in (where, alleles) if x)


def _row(r, groups, in_preset, active_states, caveats):
    """One table row as display values (the template adds the markup)."""
    from snpscore.gwas import p_text
    g = r.get
    distance = g("gene_distance")
    out = {"n": r["file_row_number"], "id": g("id") if g("id") not in (None, ".") else None, "chrom": g("chrom"), "pos": g("pos"),
           "alleles": _alleles(g), "tier": g("tier"), "score": g("tier_score"),
           "evidence": with_published(evidence_text(g("tier_evidence"), g("tier_terms")), g),  # the Tier cell's tooltip
           "known": g("known_locus"), "known_dist": g("known_locus_dist"), "caveat": caveats.get(g("known_locus")),
           "gene": gene_label(g("gene_name"), g("gene_id"), g("gene_ortholog_human")), "gene_id": g("gene_id") or "",
           "note": locus_note(g), "known_where": "this SNP" if not g("known_locus_dist") else _dist(g("known_locus_dist")),
           "region": region_text(g), "region_tip": coding_tip(g),
           "distance": _dist(distance) if distance else "",  # outside the gene only
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


def region_text(g):
    """The Region cell: the coding consequence where there is one ('missense', 'splice donor'), else the region class."""
    return CONSEQUENCES.get(g("coding_consequence") or "") or CLASS_LABELS.get(g("region_class"), g("region_class")) or "intergenic"


def coding_tip(g):
    """'p.Thr46Met · ENSSSAT00000230965' for the Region cell's tooltip; 'amino-acid effect not computed: alleles
    unknown · ENSSSAT…' for a CDS SNP without one; or ''."""
    unknown = g("coding_consequence") == "coding_sequence_variant" or (g("region_class") == "CDS" and not g("coding_consequence"))
    why = ("amino-acid effect not computed" + (f": {g('coding_note')}" if g("coding_note") else "")) if unknown else None
    return " · ".join(x for x in (why, g("coding_hgvsp"), g("coding_transcript")) if x)


PUBLISHED = re.compile(r"(?:^|_)([A-Z][a-z]{2}|[ACDEFGHIKLMNPQRSTVWY])(\d+)([A-Z][a-z]{2}|[ACDEFGHIKLMNPQRSTVWY*])(?=_|$)")


def published_as(known_id, hgvsp):
    """The catalogue id's amino-acid label ('Met54Thr' of vgll3_Met54Thr, 'S167P' of cdh1_S167P) when its residue or
    its direction differs from the computed hgvsp ('p.Thr46Met'), else None."""
    m, h = PUBLISHED.search(known_id or ""), re.match(r"p\.([A-Z][a-z]{2})(\d+)([A-Z][a-z]{2}|=|\?)", hgvsp or "")
    if not m or not h:
        return None
    ref, pos, alt = AA.get(m.group(1), m.group(1)), int(m.group(2)), AA.get(m.group(3), m.group(3))
    computed = h.group(1) if h.group(3) == "=" else h.group(3)
    return None if (ref, pos) == (h.group(1), int(h.group(2))) and computed in (alt, "?") else m.group(0).lstrip("_")


def with_published(evidence, g):
    """Evidence text with the catalogue's label after a computed amino-acid change that differs from it, for a SNP at
    the published position: 'missense p.Thr46Met (published Met54Thr)'."""
    hgvsp = g("coding_hgvsp")
    published = published_as(g("known_locus"), hgvsp) if hgvsp and g("known_locus_dist") == 0 else None
    return evidence.replace(hgvsp, f"{hgvsp} (published {published})", 1) if published and hgvsp in evidence else evidence


def coding_label(g, known_id=None, known_dist=None):
    """'Missense p.Thr46Met (ENSSSAT00000230965; published as Met54Thr)' for the card, None without a consequence.
    The published label is the catalogue id's at this exact position, when it differs (published_as)."""
    consequence = g("coding_consequence")
    if not consequence:
        return None
    if consequence == "coding_sequence_variant":
        return f"CDS (amino-acid effect not computed: {g('coding_note') or 'alleles unknown'})"
    notes = [x for x in (g("coding_transcript"),) if x]
    published = published_as(known_id, g("coding_hgvsp")) if known_dist == 0 else None
    if published:
        notes.append(f"published as {published}")
    if g("coding_note"):
        notes.append(g("coding_note"))
    text = CONSEQUENCES.get(consequence, consequence).capitalize() + (f" {g('coding_hgvsp')}" if g("coding_hgvsp") else "")
    return text + (f" ({'; '.join(notes)})" if notes else "")


CDS_TEXT = "CDS (amino-acid effect not computed)"
CODING_TERMS = ("coding", "synonymous", "splice")  # tier terms whose text the coding consequence replaces


def tier_parts(g):
    """[(text, weight)] of the evidence terms that count, as the card and the drawer show them: the coding consequence
    in words for the coding terms (coding_label), condition lists spelled out, a bare CDS with its qualifier; weight
    None for results whose tier_terms don't match tier_evidence."""
    parts = [x for x in (g("tier_evidence") or "").split("; ") if x]
    terms = g("tier_terms") or []
    terms = terms if len(terms) == len(parts) else [None] * len(parts)
    coding = coding_label(g, g("known_locus"), g("known_locus_dist"))
    return [(coding if coding and t and t["term"] in CODING_TERMS else re.sub(r"^CDS\b", CDS_TEXT, evidence_text(p)),
             t["weight"] if t else None) for p, t in zip(parts, terms) if not t or t["weight"]]


def _drawer(request, key, job, row, close):
    """The Table's evidence drawer: the SNP's full card (locus.job_card) and the link that closes it; None when the
    row doesn't exist."""
    from . import locus  # locus imports this module
    ctx = locus.job_card(request, key, row, job or jobs.read(key))
    return ctx and {**ctx, "close": close}


# ---- the top SNPs (the report) ----

def top(request, key, job, n):
    """{rows, matching, ties, gwas} for the first `n` SNPs with the request's trait and table filters, ordered as the
    Table: tier, then score (highest first), then list order; GWAS jobs by p. `ties` says how many SNPs share the
    tier and score at the cut, when the cut splits them."""
    con, types, where, chosen = open_result(request, key)
    gwas = job.get("input_kind") == "gwas" and "neglog10p" in types
    maf, _ = jobs.maf_sql(types)
    cols = [c for c in ("chrom", "pos", "id", "ref", "alt", "tier", "tier_score", "tier_evidence", "tier_terms", "coding_hgvsp", "gene_name", "gene_id",
                        "gene_ortholog_human", "known_locus", "known_locus_dist", "assay_status",
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
            "tier": g("tier"), "score": g("tier_score"), "evidence": with_published(evidence_text(g("tier_evidence"), g("tier_terms")), g),
            "gene": gene_label(g("gene_name"), g("gene_id"), g("gene_ortholog_human")),
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


def _fig_summary(c, link, desc):
    """The key numbers, then the SNPs per tier and genic region (each over the public background's split, when the
    release has one), near a known locus and by assay check (not for GWAS jobs)."""
    s, trait, bg = c["s"], c["trait"], c["background"]
    tiers = s.get("tiers", {}).get(trait)
    if not tiers:
        return None
    n, href = s.get("n_rows") or sum(tiers.values()), link or (lambda **_: None)
    top2 = int(tiers.get("1", 0)) + int(tiers.get("2", 0))
    public = _shares((bg.get("tiers") or {}).get(trait))
    chroms = len([k for k, v in (s.get("chrom_tiers", {}).get(trait) or {}).items() if sum(v.values())])
    head = [(f"{n:,}", "SNPs scored", f"on {chroms} chromosome{'' if chroms == 1 else 's'}" if chroms else "", None),
            (f"{top2:,}", f"in tier 1–2 for {c['preset']}",
             f"{pct(top2, n)} of the list" + (f"; {100 * (public.get('1', 0) + public.get('2', 0)):.1f}% of public sites" if public else ""),
             href(tier="1-2"))]
    if c.get("loci"):
        head.append((f"{c['loci'][0]:,}", "loci", "on the Association tab", c["loci"][1]))
    names = {t: figures.TIER_NAMES[t].capitalize() for t in (1, 2, 3, 4)}
    groups = [{"title": f"Tier for {c['preset']}", "note": "1 = strongest functional evidence" + (" · thin bar: public sites" if public else ""),
               "parts": [(names[t], int(tiers.get(str(t), 0)), palette.TIERS[t][0], href(tier=str(t))) for t in (1, 2, 3, 4)],
               "background": [(names[t], public.get(str(t), 0), palette.TIERS[t][0]) for t in (1, 2, 3, 4)] if public else None}]
    regions, region_bg = s.get("region_tiers", {}).get(trait) or {}, background_regions(bg)
    label = {g: REGION_LABELS[g].split(" (")[0] for g in list(REGIONS) + ["other"]}
    groups.append({"title": "Gene region", "note": "Ensembl 116" + (" · thin bar: public sites" if region_bg else ""),
                   "parts": [(label[g], sum(regions.get(g, {}).values()), palette.REGIONS[g], href(region=g) if g in REGIONS else None)
                             for g in list(REGIONS) + ["other"]],
                   "background": [(label[g], region_bg.get(g, 0), palette.REGIONS[g]) for g in list(REGIONS) + ["other"]] if region_bg else None})
    if "known" in s.get("counts", {}):
        window = (c["manifest"].get("catalog") or {}).get("window")
        near = s["counts"]["known"]
        groups.append({"title": "Near a known locus", "note": f"within {window / 1000:g} kb of a published locus" if window else "",
                       "parts": [("near one", near, palette.GREY[700], href(known="1")), ("further away", n - near, palette.GREY[200], None)]})
    if s.get("assay") and c["job"].get("input_kind") != "gwas":
        groups.append({"title": "Assay check", "note": "probe flanks for genotyping assays",
                       "parts": [(k.replace("_", " "), s["assay"].get(k, 0), palette.STATUS[ASSAY[k][1]][2], href(assay=k)) for k in ASSAY]})
    for g in groups:
        g["parts"] = [p for p in g["parts"] if p[1]]
        if g.get("background"):
            g["background"] = [b for b in g["background"] if b[1]]
    svg = figures.summary(head, [g for g in groups if g["parts"]], f"Summary, {c['preset']}", desc, c["synthetic"])
    return svg, ["group", "category", "snps", "public_share"], \
        [(g["title"], p[0], p[1], next((f"{b[1]:.5f}" for b in g.get("background") or () if b[0] == p[0]), "")) for g in groups for p in g["parts"]]


def _fig_ideogram(c, link, desc):
    bins = c["s"].get("bins", {}).get(c["trait"])
    if bins is None:
        return None
    sizes = {k: int(v) for k, v in (c["manifest"].get("chrom_sizes") or {}).items()}
    for chrom, b, *_ in bins:
        sizes[chrom] = max(sizes.get(chrom, 0), int((b + 1) * 1e6))
    chroms = [(k, sizes[k]) for k in sorted(sizes, key=_chrom_key)]
    href = (lambda chrom, start, end, tier: link(chrom=chrom, start=start, end=end, tier=tier)) if link else None
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
    "summary": ("Summary", "How the SNPs scored for all 21 conditions (tier 1 = strongest functional evidence, tier 4 = no "
                "evidence found, not evidence of no effect), where they fall relative to genes, how many are near a "
                "published locus and how they did in the assay design check. Thin bars: the same split for the release's "
                "public sites, for comparison. Click a number, a part of a bar or its legend entry to list those SNPs.",
                _fig_summary),
    "ideogram": ("Where the SNPs are", "Chromosomes to scale (Ssal_v3.1). Each 1 Mb bin holding SNPs is shaded: blue when "
                 "some are in tier 1–2 (darker = more of them), grey when none are. On the right: each chromosome's SNPs "
                 "and, as a bar, its tier 1–2 SNPs. Click a bin, chromosome or bar to list those SNPs.", _fig_ideogram),
    "conditions": ("Active chromatin per condition", "Share of the SNPs in an active chromatin state in each of the 21 "
                   "AQUA-FAANG conditions; × = fold over a background of public sites, when the release has one. "
                   "Click a cell to list those SNPs.", _fig_conditions),
    "regions": ("Genic region by tier", "SNPs per genic region class (Ensembl 116), split by tier; the black tick is "
                "the share expected from a background of public sites. Click a bar to list those SNPs.", _fig_regions),
    "terms": ("Evidence behind the tiers", "For each evidence term (its weight in brackets), the SNPs it applies to, split "
              "by the tier they end in. A SNP can have several terms.", _fig_terms),
    "maf": ("Minor allele frequency", "MAF from your maf or af column when the list has one, else 504 public fish (wild "
            "and farmed, pooled; your strain can differ). Light bars: below 0.05. Black ticks: the count expected from a "
            "background of public sites. Click a bar to list those SNPs.", _fig_maf),
}
OPEN = ("summary", "ideogram")  # side by side on the Overview (GWAS jobs: conditions beside); the rest under 'More charts'


def _figure_context(key, job, trait, summary, d):
    return {"key": key, "job": job, "trait": trait, "preset": jobs.trait_label(trait), "s": summary, "weights": jobs.weights(d),
            "manifest": jobs.manifest(d), "background": background(),
            "synthetic": bool(job.get("synthetic_input") or job.get("synthetic_layers")),
            "chip": jobs.read_json(d / "chip.json") if (d / "chip.parquet").exists() else {}}


# ---- the Table's selection: its filters (Active in among them) and view, kept per job ----

UNSELECTED = "Unselected SNPs (−)"


def unselected(d):
    """The rows taken out of the selection by hand (the Table's − marks), kept in unselected.json of the job."""
    return set(jobs.read_json(d / "unselected.json").get("rows", []))


def keep_unselected(d, rows):
    jobs._write_json(d / "unselected.json", {"rows": sorted(rows)})


def manual(d):
    """The filter that leaves the − rows out of the selection, or None when there are none."""
    rows = unselected(d)
    return ({}, UNSELECTED, f"file_row_number NOT IN ({', '.join(map(str, sorted(rows)))})") if rows else None

def selection(d):
    """The Table's current selection of a job as a query string ('' = the whole list): the Panel designs from it, the
    Export tab offers it and the Table tab link returns to it. selection.json in the job folder, so it lasts."""
    return jobs.read_json(d / "selection.json").get("query", "")


def keep_selection(d, query):
    if selection(d) != query:
        jobs._write_json(d / "selection.json", {"query": query, "updated_utc": jobs.utc()})


def selection_request(query):
    """A stand-in request whose GET is a saved selection, for filters() and requested_trait()."""
    return SimpleNamespace(GET=QueryDict(query))


def table_link(trait="all"):
    """Overview and Panel marks link to the Table tab with only their filter: a new selection (Active in reset)."""
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
    """Context for the Overview tab, the landing page of the whole list (no Table filters, tiers for all conditions):
    the summary (key numbers and how the SNPs split), the other figures whose data exist, upload warnings and the
    upload QC line. Reads summary.json and validation.json (GWAS jobs: their loci)."""
    d = jobs.folder(key)
    trait, s = "all", summary_of(d)
    gwas = job.get("input_kind") == "gwas"
    c = _figure_context(key, job, trait, s, d)
    if gwas:  # the summary's headline counts the loci and links the Association tab
        from . import association
        c["loci"] = (len(association.analyse(request, key)["loci"]),
                     f"{reverse('snpportal:association', args=[key])}?{urlencode({'trait': trait, **gwas_settings(request)})}")
    link = table_link(trait)
    figs = {}
    for name, (_, info, build) in FIGURES.items():
        if gwas and name not in ("summary", "conditions"):
            continue
        built = build(c, link, info)
        if built:
            figs[name] = figure_card(c, name, built[0])
    pair = OPEN if "ideogram" in figs else ("summary", "conditions")  # GWAS jobs have no ideogram here
    validation = {} if gwas else jobs.read_json(d / "validation.json")
    qc_items, qc_warning = qc(validation)
    rejected = sum(v for v in (validation.get("rejected") or {}).values() if isinstance(v, int))
    return {
        "figs": {k: v for k, v in figs.items() if k in pair}, "more_figs": [v for k, v in figs.items() if k not in pair],
        "warnings": warnings_of(validation) if validation else [],
        "qc_items": qc_items, "qc_warning": qc_warning, "qc_alias": validation.get("alias_warnings") or [],
        "qc_line": qc_line(validation), "qc_open": qc_problem(validation),
        "rejects": (d / "rejects.tsv").exists() and bool(rejected), "trait": trait, "trait_label": jobs.trait_label(trait),
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
    trait, s = "all", summary_of(d)  # the Overview's figures: the whole list, all conditions
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
