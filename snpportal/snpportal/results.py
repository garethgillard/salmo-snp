"""Results of a finished job: the overview dashboard, the sortable and filterable table and the figures (the evidence
card is in locus.py). Tiers for the chosen preset come from the job's tiers.parquet (precomputed for every preset), so
switching presets never rescores; snpscore.scored() runs per request only for presets missing from it. The overview reads
only summary.json; the table sorts and pages on the server in two steps (row numbers first, then that page's columns)."""
from __future__ import annotations

import re
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
REGIONS = jobs.REGION_GROUPS
REGION_LABELS = {"coding": "coding (CDS, splice)", "UTR": "UTR", "exon": "non-coding exon", "intron": "intron",
                 "intergenic": "intergenic", "other": "other"}
CLASS_LABELS = {"CDS": "CDS", "splice_region": "splice region", "five_prime_UTR": "5′ UTR", "three_prime_UTR": "3′ UTR",
                "exon": "non-coding exon", "intron": "intron"}
HIDE = {  # checkbox -> (label, column it needs, SQL condition a SNP must meet to stay)
    "hide_blacklist": ("blacklisted", "blacklist", "NOT blacklist"),
    "hide_lore": ("LORe", "lore", "NOT lore"),
    "hide_ambiguous": ("A/T or C/G", "strand_ambiguous", "NOT coalesce(strand_ambiguous, false)"),
    "hide_flank": ("variants within 35 bp", "flank_variants", "flank_variants = 0"),
    "hide_near_chip": ("near the chip", "near_chip", "NOT near_chip"),  # with a chip on the Panel tab (P6.6)
}
FLAGS = {"blacklist": ("blacklisted region", "hide_blacklist"), "lore": ("LORe region", "hide_lore"),
         "strand_ambiguous": ("A/T or C/G", "hide_ambiguous"), "flank_variants": ("public variants within 35 bp", "hide_flank")}
TIER_FILTERS = {"1": "tier = 1", "1-2": "tier <= 2", "1-3": "tier <= 3", "2": "tier = 2", "3": "tier = 3", "4": "tier = 4"}
ASSAY = {"pass": ("✓", "ok"), "warn": ("⚠", "warn"), "fail": ("✗", "fail"), "not_checked": ("–", "not_checked")}
MAFS = ("0.01", "0.05", "0.1", "0.2")
TERMS = {"active": "active in the preset", "active_elsewhere": "active elsewhere only", "weak": "weak state in the preset",
         "coding": "CDS", "splice": "splice region", "utr": "UTR", "constrained": "GERP constrained",
         "regbuild": "Ensembl regulatory", "molqtl": "molQTL lead (display only)"}
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
    "TOP/BOT cannot be determined (Illumina code 103)": "TOP/BOT undeterminable (Illumina 103)", "LORe region": "LORe region",
    "blacklisted": "blacklisted region", "A/T or C/G (two probes)": "A/T or C/G (two probes)",
    "chromosome not in the genome": "chromosome not in the genome",
    **{f"{b} run": f"long {b} run" for b in "ACGT"}}
FORMAT_NAMES = {"vcf": "VCF", "text": "text table", "tsv": "tab-separated table", "csv": "comma-separated table", "bim": "PLINK .bim", "map": "PLINK .map", "illumina": "Illumina manifest",
                "axiom": "Axiom annotation", "paste": "pasted positions", "rows": "public variants (genes or intervals)"}
STAGES = ["LateBlastulation", "MidGastrulation", "EarlySomitogenesis", "MidSomitogenesis", "LateSomitogenesis"]
STAGE_LABELS = {"LateBlastulation": "Blastula", "MidGastrulation": "Gastrula", "EarlySomitogenesis": "E somit.",
                "MidSomitogenesis": "M somit.", "LateSomitogenesis": "L somit."}
CARD_SQL = "SELECT * FROM v WHERE file_row_number = ?"  # the card reads one row, never the whole result

# Table columns: key -> (group, header, tooltip, columns (shown when any exists; () = always), sort [(SQL, ascending)];
# ?desc=1 reverses every term).
# ?col= and the column chooser accept only these keys; {maf} in a sort is the MAF expression.
COLUMNS = {
    "id": ("Variant", "SNP", "SNP id: opens its evidence card", (), [("id", True)]),
    "position": ("Variant", "Position", "Chromosome:position (1-based, Ssal_v3.1)", ("pos",),
                 [("length(chrom)", True), ("chrom", True), ("pos", True)]),  # 9 before 10, cheaply
    "alleles": ("Variant", "Alleles", "Reference > alternative allele", ("ref", "alt"), []),
    "tier": ("Priority", "Tier", "1 = strongest functional evidence for the preset, 4 = none (PROVISIONAL rules)",
             ("tier",), [("tier", True), ("tier_score", False)]),
    "score": ("Priority", "Score", "tier_score: the summed weights of the evidence terms", ("tier_score",), [("tier_score", True)]),
    "evidence": ("Priority", "Evidence", "The evidence behind the tier", ("tier_evidence",), []),
    "known": ("Priority", "Known locus", "Near a published locus of the known-loci catalogue", ("known_locus",),
              [("known_locus_dist", True)]),
    "gene": ("Location", "Gene", "Nearest Ensembl 116 gene; unnamed genes show their human ortholog", ("gene_name", "gene_id"),
             [("coalesce(gene_name, gene_ortholog_human, gene_id)", True)]),
    "region": ("Location", "Region", "Genic region class (Ensembl 116 gene models)", ("region_class",), [("region_class", True)]),
    "distance": ("Location", "To gene", "Distance to the nearest gene", ("gene_distance",), [("gene_distance", True)]),
    "chromatin": ("Regulation", "Chromatin, 21 conditions", "AQUA-FAANG ChromHMM state: Brain, Gonad, Liver, Muscle "
                  "(immature F, M; mature F, M), then 5 embryo stages. Underlined: in the preset", ("chromatin",), []),
    "gerp": ("Regulation", "GERP", "GERP constrained-element score (65 fish)", ("gerp_score",), [("gerp_score", True)]),
    "regbuild": ("Regulation", "Ensembl reg.", "Ensembl 116 regulatory build feature", ("regbuild_type",), [("regbuild_type", True)]),
    "molqtl": ("Regulation", "molQTL", "Lead SNP of an nf-RASQUAL eQTL (e) or caQTL (ca) in 12 fish, eigenMT-adjusted p < 0.1 "
               "(PROVISIONAL); display only, never counted in tiers", ("molqtl",), [("molqtl_best_bf", True)]),
    "cm": ("Location", "cM (F/M)", "Genetic map position, female / male cM (Brekke et al. 2023 linkage map, interpolated)",
           ("cm_female",), [("cm_female", True)]),
    "maf": ("Assay", "MAF", f"Minor allele frequency: your maf/af column, else the public one ({jobs.PUBLIC_AF})", ("maf", "af", "public_af_maf"),
            [("{maf}", True)]),
    "assay": ("Assay", "Assay", "Assay design status (PROVISIONAL thresholds)", ("assay_status",), [("assay_status", True)]),
    "flags": ("Assay", "Flags", "Blacklisted region, LORe (near-identical ohnolog), A/T or C/G, public variants within 35 bp",
              ("blacklist", "lore", "strand_ambiguous", "flank_variants"), []),
    "ref_check": ("Assay", "Ref. check", "Input ref allele against the Ssal_v3.1 genome", ("ref_check",), [("ref_check", True)]),
}
DEFAULT_COLUMNS = ("id", "position", "alleles", "tier", "known", "gene", "region", "chromatin", "molqtl", "maf", "assay", "flags")
EXTRA = {"id": ("chrom", "pos"), "tier": ("tier_score", "tier_evidence"), "known": ("known_locus_dist",),
         "gene": ("gene_ortholog_human",), "assay": ("assay_reasons",), "region": ("gene_distance",),
         "molqtl": ("molqtl_tissues", "molqtl_kinds", "molqtl_features"), "cm": ("cm_male",)}  # also fetched


# ---- opening a result with filters ----

def _open(request, key, write=False):
    """(connection with views r and v, column types, filters, chosen settings, weights) for a finished job: v is the
    result with the tiers of ?trait= (and the chip columns when the Panel tab has a chip). The connection reads only the
    job folder (and writes there if `write`)."""
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
    chip = d / "chip.parquet"
    if chip.exists() and weights:  # the Panel tab's chip adds on_chip, dist_to_chip, near_chip and novel_functional (P6.6)
        window = int(snp_panel.settings(weights)["chip_window"])
        con.execute(f"CREATE VIEW v AS {snp_panel.compare_sql('v0', f'read_parquet({lit(chip)})', window)}")
    else:
        con.execute("CREATE VIEW v AS SELECT * FROM v0")
    types = dict(con.execute("SELECT column_name, column_type FROM (DESCRIBE v)").fetchall())
    conds = filters(request, types, weights)
    chosen = {"trait": trait}
    for params, _, _ in conds:
        chosen.update(params)
    return con, types, conds, chosen, weights


def open_result(request, key, write=False):
    """DuckDB view `v` over a finished job's result with the tiers of ?trait=, and the WHERE clause of the table
    filters in the request (see filters()). Returns (connection, column types, WHERE clause, the request's settings)."""
    con, types, conds, chosen, _ = _open(request, key, write)
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
    if assay in ASSAY and "assay_status" in types:
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


def gene_label(name, gene_id, human):
    """The Ensembl name, else 'unnamed (human VGLL3)' from the ortholog, else the gene id."""
    if name:
        return name
    if human:
        return f"unnamed (human {human.replace(',', ', ')})"
    return gene_id or ""


def pct(k, n):
    if not n:
        return "–"
    share = 100 * k / n
    return "<0.1%" if 0 < share < 0.1 else f"{share:.1f}%"


def _chrom_key(chrom):
    return (0, int(chrom), "") if chrom.isdecimal() else (1, 0, chrom)


# ---- the Table tab ----

def table(request, key):
    """Context for the Table tab: one page of rows sorted and paged on the server, filter controls and chips, the
    column chooser and an empty-state hint. Fast on 1.6M rows: page row numbers are found first using only the
    filter and sort columns, then only that page's columns are read."""
    con, types, conds, chosen, weights = _open(request, key)
    get = request.GET.get
    summary = jobs.read_json(jobs.folder(key) / "summary.json")
    maf, maf_source = jobs.maf_sql(types)
    available = [k for k, (_, _, _, needs, _) in COLUMNS.items() if not needs or any(c in types for c in needs)]
    default = [k for k in DEFAULT_COLUMNS if k in available]
    shown = ["id"] + [k for k in available if k != "id" and k in request.GET.getlist("col")] if get("cols") else default
    custom = shown != default  # the chooser sends every ticked column; keep URLs short when that is the default set
    sort = get("sort", "")
    explicit = sort in available and bool(COLUMNS[sort][4])
    sort = sort if explicit else ("tier" if "tier" in available else "")
    desc = get("desc") == "1"
    size = int(get("size")) if get("size", "").isdecimal() and int(get("size")) in PAGE_SIZES else PAGE_SIZE

    total = con.execute("SELECT count(*) FROM r").fetchone()[0]
    where = _where(conds)
    src = "v" if sort in ("tier", "score") or {"tier", "term"} & set(chosen) else "r"  # skip the tiers join when unused
    matching = con.execute(f"SELECT count(*) FROM {src} {where}").fetchone()[0] if conds else total
    pages = max(1, -(-matching // size))
    page = min(int(get("page")) if get("page", "").isdecimal() else 1, pages) or 1
    order = [f"{sql.format(maf=maf)} {'ASC' if asc != desc else 'DESC'} NULLS LAST" for sql, asc in (COLUMNS[sort][4] if sort else [])]
    ids = [i for i, in con.execute(f"SELECT file_row_number FROM {src} {where} ORDER BY {', '.join(order + ['file_row_number'])} "
                                   f"LIMIT {size} OFFSET {(page - 1) * size}").fetchall()]
    conditions = conditions_of(types)
    in_preset = set(snpscore.score.preset_conditions(weights, list(types), chosen["trait"])[0]) if weights and conditions else set()
    rows = _page(con, ids, types, shown, maf, conditions, in_preset, (weights or {}).get("active_states", []))

    base = {"tab": "table", **chosen, "sort": sort if explicit else "", "desc": "1" if desc else "",
            "size": str(size) if size != PAGE_SIZE else "", "cols": "1" if custom else "", "col": shown[1:] if custom else []}

    def link(drop=(), **changes):
        params = {k: v for k, v in base.items() if k not in drop}
        params.update(changes)
        return "?" + urlencode({k: v for k, v in params.items() if v not in ("", None, [])}, doseq=True)

    filter_keys = [k for params, _, _ in conds for k in params]
    chips = [(label, link(drop=list(params), page=None)) for params, label, _ in conds]
    suggest = None
    if conds and not matching and len(conds) > 1:  # name the filter that removes the most on its own
        counts = con.execute("SELECT " + ", ".join(f"count(*) FILTER (WHERE {_where(conds[:i] + conds[i + 1:])[6:]})"
                                                   for i in range(len(conds))) + " FROM v").fetchone()
        best = max(range(len(conds)), key=lambda i: counts[i])
        if counts[best]:
            suggest = (conds[best][1], counts[best], chips[best][1])

    selects = []  # (name, label, [(value, text)], current value)

    def select(name, label, values, current=None, any_label="any"):
        current = chosen.get(name, "") if current is None else current
        values = [("", any_label)] * bool(any_label) + list(values)
        if current and current not in [v for v, _ in values]:
            values.append((current, current))
        selects.append((name, label, values, current))

    chroms = sorted((summary.get("chrom_tiers", {}).get(chosen["trait"]) or {}), key=_chrom_key) or \
        sorted((c for c, in con.execute("SELECT DISTINCT chrom FROM r").fetchall()), key=_chrom_key)
    if "tier" in types:
        select("tier", "Tier", [(t, t.replace("-", "–")) for t in TIER_FILTERS])
    if "region_class" in types:
        select("region", "Region", [(r, REGION_LABELS[r]) for r in REGIONS])
    select("chrom", "Chromosome", [(c, c) for c in chroms])
    if maf:
        select("min_maf", "Min MAF", [(m, m) for m in MAFS])
    if "assay_status" in types:
        select("assay", "Assay", [(a, a.replace("_", " ")) for a in ASSAY])
    if weights and conditions:
        select("active", "Active in", [(c, condition_label(c)) for c in conditions])
    if weights and "tier_terms" in types:
        select("term", "Evidence", [(t, TERMS.get(t, t)) for t in weights.get("weights", {})])
    select("size", "Rows", [(str(s), str(s)) for s in PAGE_SIZES], str(size), None)
    checks = ([("known", "known loci only", "known" in chosen)] if "known_locus" in types else []) + \
        ([("molqtl", "molQTL lead SNPs", "molqtl" in chosen)] if "molqtl" in types else []) + \
        [(name, f"hide {label}", name in chosen) for name, (label, column, _) in HIDE.items() if column in types]

    groups = []
    for k in shown:
        if groups and groups[-1][0] == COLUMNS[k][0]:
            groups[-1][1] += 1
        else:
            groups.append([COLUMNS[k][0], 1])
    headers = []
    for k in shown:
        group, label, tip, _, sorts = COLUMNS[k]
        if k == "maf" and maf_source:
            tip = f"Minor allele frequency ({'your column' if maf_source == 'yours' else jobs.PUBLIC_AF})"
        here = k == sort
        href = link(sort=k, desc="1" if here and not desc else "", page=None) if sorts else None
        headers.append((k, label, tip, href, ("descending" if desc else "ascending") if here else ""))
    tier_counts = sorted((summary.get("tiers") or {}).get(chosen["trait"], {}).items()) or (
        con.execute("SELECT tier, count(*) FROM v GROUP BY tier ORDER BY tier").fetchall() if "tier" in types else [])
    return {
        "total": total, "matching": matching, "first": (page - 1) * size + 1 if matching else 0,
        "last": min(page * size, matching), "tiers": tier_counts, "chosen": chosen, "query": urlencode(chosen),
        "selects": selects, "checks": checks, "gene": chosen.get("gene", "") if any(c in types for c in ("gene_name", "gene_id")) else None,
        "start": chosen.get("start", ""), "end": chosen.get("end", ""),
        "hidden": [(k, base[k]) for k in ("sort", "desc") if base[k]],
        "columns": [(k, COLUMNS[k][1], k in shown) for k in available if k != "id"], "chips": chips,
        "clear": link(drop=filter_keys, page=None) if conds else None, "suggest": suggest, "groups": groups,
        "headers": headers, "shown": shown, "rows": rows, "page": page, "pages": pages,
        "prev": link(page=page - 1) if page > 1 else None, "next": link(page=page + 1) if page < pages else None,
    }


def _page(con, ids, types, shown, maf, conditions, in_preset, active_states):
    """Display-ready rows for the row numbers `ids`, in that order. Reads only the shown columns."""
    if not ids:
        return []
    wanted = {"file_row_number"} | {c for k in shown for c in COLUMNS[k][3] + EXTRA.get(k, ()) if c in types}
    if "chromatin" in shown:
        wanted |= {f"chromatin_{c}" for c in conditions}
    select = ", ".join(map(ident, sorted(wanted))) + (f", {maf} AS _maf" if maf and "maf" in shown else "")
    cur = con.execute(f"SELECT {select} FROM v WHERE file_row_number IN ({', '.join(str(int(i)) for i in ids)})")
    names = [x[0] for x in cur.description]
    found = {r["file_row_number"]: r for r in (dict(zip(names, x)) for x in cur.fetchall())}
    groups = condition_groups(conditions)
    return [_row(found[i], groups, in_preset, set(active_states)) for i in ids if i in found]


def _row(r, groups, in_preset, active_states):
    """One table row as display values (the template adds the markup)."""
    g = r.get
    distance = g("gene_distance")
    out = {"n": r["file_row_number"], "id": g("id") if g("id") not in (None, ".") else None, "chrom": g("chrom"), "pos": g("pos"),
           "alleles": f"{g('ref')}>{g('alt')}" if g("ref") and g("alt") else (g("ref") or ""),
           "tier": g("tier"), "score": g("tier_score"), "evidence": g("tier_evidence") or "",
           "known": g("known_locus"), "known_dist": g("known_locus_dist"),
           "gene": gene_label(g("gene_name"), g("gene_id"), g("gene_ortholog_human")), "gene_id": g("gene_id") or "",
           "region": CLASS_LABELS.get(g("region_class"), g("region_class")) or "intergenic",
           "distance": "" if distance is None else "in gene" if distance == 0 else
           f"{distance:,} bp" if distance < 1000 else f"{distance / 1000:,.1f} kb",
           "gerp": "" if g("gerp_score") is None else f"{g('gerp_score'):.1f}", "regbuild": g("regbuild_type") or "",
           "maf": "" if g("_maf") is None else f"{g('_maf'):.2f}", "ref_check": g("ref_check") or "",
           "cm": "" if g("cm_female") is None else f"{g('cm_female'):.1f} / {g('cm_male'):.1f}" if g("cm_male") is not None else f"{g('cm_female'):.1f}"}
    if g("molqtl"):  # 'Brain, Gonad (e, ca)', the features as the tooltip
        out["molqtl"] = (f"{(g('molqtl_tissues') or '').replace(',', ', ')} ({(g('molqtl_kinds') or '').replace(',', ', ')})",
                         g("molqtl_features") or "")
    status = g("assay_status") or ("not_checked" if "assay_status" in r else None)
    out["assay"] = (ASSAY.get(status, ("?", "not_checked")) + (status.replace("_", " "), g("assay_reasons") or "")) if status else None
    flags = []
    if g("blacklist"):
        flags.append(("⚠", "blacklisted", "In a blacklisted region: no peak here means 'can't tell'"))
    if g("lore"):
        flags.append(("⚠", "LORe", "Near-identical ohnolog region: probes may cross-hybridise"))
    if g("strand_ambiguous"):
        flags.append(("⇄", "A/T-C/G", "Strand-ambiguous alleles"))
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
    svg = figures.tier_bar(counts, f"SNPs per tier, {c['preset']} preset", desc, c["synthetic"],
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
    svg = figures.ideogram(chroms, bins, c["s"]["chrom_tiers"].get(c["trait"], {}), f"SNPs along the genome, {c['preset']} preset",
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
    svg = figures.heatmap(rows, f"Active chromatin per condition, {c['preset']} preset", desc, c["synthetic"],
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
    svg = figures.hbars(rows, f"Genic region by tier, {c['preset']} preset", desc, c["synthetic"], legend)
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
    svg = figures.hbars(rows, f"Evidence behind the tiers, {c['preset']} preset", desc, c["synthetic"],
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
    source = "your maf/af column" if m["source"] == "yours" else "the 504-fish panel"
    svg = figures.histogram(bars, "Minor allele frequency", desc, c["synthetic"],
                            f"MAF bin (lower edge) from {source}" + ("; black ticks: public background" if bg else ""))
    return svg, ["maf_from", "maf_to", "snps", "background_share"], tsv


def _fig_assay(c, link, desc):
    counts = c["s"].get("assay")
    if not counts:
        return None
    n = sum(counts.values())
    rows = []
    for status in list(ASSAY) + [s for s in counts if s not in ASSAY]:
        if status not in counts:
            continue
        icon, kind = ASSAY.get(status, ("?", "not_checked"))
        k = counts[status]
        rows.append({"label": f"{icon} {status.replace('_', ' ')}", "note": f"{k:,} ({pct(k, n)})",
                     "segments": [(k, palette.STATUS[kind][2], f"{status.replace('_', ' ')}: {k:,} SNPs", link(assay=status) if link else None)]})
    svg = figures.hbars(rows, "Assay design status", desc, c["synthetic"])
    return svg, ["status", "snps"], [(s, counts[s]) for s in counts]


def _fig_reasons(c, link, desc):
    reasons = c["s"].get("assay_reasons")
    if not reasons:
        return None
    n = sum((c["s"].get("assay") or {}).values()) or c["s"].get("n_rows") or 1
    rows, tsv = [], []
    for reason, by in sorted(reasons.items(), key=lambda kv: -sum(kv[1].values()))[:12]:
        k = sum(by.values())
        label = REASONS.get(reason, reason)
        rows.append({"label": label, "note": f"{k:,} ({pct(k, n)})",
                     "segments": [(by[st], palette.STATUS[ASSAY.get(st, ('', 'not_checked'))[1]][2], f"{label}: {by[st]:,} {st.replace('_', ' ')} SNPs",
                                   link(assay=st) if link else None) for st in ("fail", "warn", "not_checked") if by.get(st)]})
        tsv += [(reason, st, by[st]) for st in by]
    legend = [(palette.STATUS[kind][2], st.replace("_", " ")) for st, kind in (("fail", "fail"), ("warn", "warn"), ("not_checked", "not_checked"))
              if any(st in by for by in reasons.values())]
    svg = figures.hbars(rows, "Why SNPs warn or fail the assay checks", desc, c["synthetic"], legend)
    return svg, ["reason", "status", "snps"], tsv


def _fig_gaps(c, link, desc):
    gaps = c["s"].get("gaps")
    if not gaps:
        return None
    sizes = c["manifest"].get("chrom_sizes") or {}
    rows = []
    for chrom, a, b in gaps:
        empty = a == 0 and b == sizes.get(chrom)
        tip = f"Chromosome {chrom}: no SNPs" if empty else f"{chrom}:{a:,}–{b:,}, {(b - a) / 1e6:.2f} Mb without a SNP"
        rows.append({"label": f"chr {chrom}", "note": "no SNPs" if empty else f"{(b - a) / 1e6:.1f} Mb",
                     "segments": [(b - a, palette.GREY[300] if empty else palette.ACCENT, tip,
                                   link(chrom=chrom, start=max(a - 1, 0), end=b) if link else None)]})
    svg = figures.hbars(rows, "Largest gap per chromosome", desc, c["synthetic"])
    return svg, ["chrom", "from", "to", "length"], [(chrom, a, b, b - a) for chrom, a, b in gaps]


FIGURES = {  # name -> (card title, (i) definition, builder(context, link or None, desc) -> (svg, header, rows) or None)
    "tiers": ("SNPs per tier", "Tier 1 = strongest functional evidence for the preset, tier 4 = none. Tier rules are "
              "PROVISIONAL (weights.yaml). Click a tier to list its SNPs.", _fig_tiers),
    "ideogram": ("Where the SNPs are", "Chromosomes to scale (Ssal_v3.1). Each 1 Mb bin is coloured by the best tier among "
                 "its SNPs (grey: tier 4 only); the bar on the right splits each chromosome's SNPs by tier. Click a bin "
                 "to list its SNPs.", _fig_ideogram),
    "conditions": ("Active chromatin per condition", "Share of the SNPs in an active ChromHMM state (PROVISIONAL: "
                   "the weights.yaml active_states) in each of the 21 AQUA-FAANG conditions; × = fold over the public "
                   "background (the release's pool of public sites) when the release has one. Outlined: conditions "
                   "of the preset. Click a cell to list those SNPs.", _fig_conditions),
    "regions": ("Genic region by tier", "SNPs per genic region class (Ensembl 116), split by tier; the black tick is "
                "the share expected from the public background. Click a bar to list those SNPs.", _fig_regions),
    "terms": ("Evidence behind the tiers", "For each evidence term of weights.yaml (PROVISIONAL weights in brackets), "
              "the SNPs it applies to, split by the tier they end in. A SNP can have several terms.", _fig_terms),
    "maf": ("Minor allele frequency", "MAF from your maf or af column when the list has one, else the public allele "
            f"frequency ({jobs.PUBLIC_AF}; European and North American descent, pooled, so population structure is hidden). "
            "Light bars: below 0.05. Black ticks: the count expected from the public background (public AF only). Click a "
            "bar to list those SNPs.", _fig_maf),
    "assay": ("Assay design status", "snpscore's assay QC of the probe flanks (thresholds PROVISIONAL, to confirm with the "
              "genotyping lab). not checked = no local genome sequence for the SNP; left out of the % pass.", _fig_assay),
    "reasons": ("Why SNPs warn or fail", "Each warn or fail SNP counted once per reason it got (a SNP can have several): GC "
                "content, soft-masked repeat share and homopolymers of the probe flanks, public variants in the flanks, "
                "allele and strand checks. Thresholds are the PROVISIONAL weights.yaml assay block. Click a bar to list "
                "the SNPs with that status.", _fig_reasons),
    "gaps": ("Largest gap per chromosome", "The longest stretch of each chromosome without one of the SNPs (chromosome "
             "ends count). Click a bar to list the SNPs on either side.", _fig_gaps),
}


def _figure_context(key, job, trait, summary, d):
    return {"key": key, "job": job, "trait": trait, "preset": trait.replace("_", " "), "s": summary, "weights": jobs.weights(d),
            "manifest": jobs.manifest(d), "background": background(),
            "synthetic": bool(job.get("synthetic_input") or job.get("synthetic_layers")),
            "chip": jobs.read_json(d / "chip.json") if (d / "chip.parquet").exists() else {}}


def _trait(request, summary):
    trait = request.GET.get("trait", "all")
    return trait if trait in summary.get("tiers", {}) else "all"


def table_link(trait):
    """Overview marks link to the Table tab with their filter (plus the preset)."""
    def link(**params):
        return "?" + urlencode({k: v for k, v in {"tab": "table", "trait": trait, **params}.items() if v is not None})
    return link


def figure_card(c, name, svg):
    """Data for the _figure.html partial."""
    url = reverse("snpportal:figure", args=[c["key"], name])
    query = urlencode({"trait": c["trait"]})
    bg = c["background"] if name in ("conditions", "regions", "maf") and c["background"] else None
    sites = (bg or {}).get("n_sites")
    caption = " · ".join(x for x in [
        f"Release {c['job'].get('release')}", f"preset {c['preset']}", "tier rules PROVISIONAL", f"job created {c['job'].get('created_utc')}",
        (f"background: release pool of {sites:,} public sites" if isinstance(sites, int) else "background: release pool") if bg else None,
        "SYNTHETIC test data" if c["synthetic"] else None] if x)
    return {"name": name, "title": FIGURES[name][0], "svg": mark_safe(svg), "svg_url": f"{url}?{query}",
            "tsv_url": f"{url}?{query}&format=tsv", "info": FIGURES[name][1], "caption": caption}


def overview(request, key, job):
    """Context for the Overview tab: KPI tiles, the figures whose data exist, flags and upload QC. Reads summary.json
    and validation.json only, so it is as fast for 1.6M SNPs as for 10."""
    d = jobs.folder(key)
    s = summary_of(d)
    trait = _trait(request, s)
    c = _figure_context(key, job, trait, s, d)
    link = table_link(trait)
    figs = {}
    for name, (_, info, build) in FIGURES.items():
        built = build(c, link, info)
        if built:
            figs[name] = figure_card(c, name, built[0])
    validation = jobs.read_json(d / "validation.json")
    qc_items, qc_warning = qc(validation)
    return {
        "kpis": kpis(s, trait, validation, link),
        "figs": figs,
        "flags": [(FLAGS[k][0], v, pct(v, s.get("n_rows")), link(**{FLAGS[k][1]: "1"})) for k, v in s.get("flags", {}).items() if k in FLAGS],
        "qc_items": qc_items,
        "qc_warning": qc_warning,
        "qc_alias": validation.get("alias_warnings") or [],
        "trait": trait,
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


def kpis(s, trait, validation, link):
    """KPI tiles [{value, label, note, href, provisional, warn}] for the data the summary has."""
    n = s.get("n_rows") or 0
    out = [{"value": f"{n:,}", "label": "SNPs scored"}]
    tiers = s.get("tiers", {}).get(trait)
    if tiers:
        top = int(tiers.get("1", 0)) + int(tiers.get("2", 0))
        out.append({"value": f"{top:,}", "label": "tier 1–2", "note": f"{pct(top, n)} of the SNPs", "href": link(tier="1-2"), "provisional": True})
    if trait in s.get("active", {}):
        k = s["active"][trait]
        out.append({"value": pct(k, n), "label": "in an active element", "note": f"{k:,} SNPs, preset conditions",
                    "href": link(term="active") if s.get("terms") else None, "provisional": True})
    if s.get("region_class"):
        k = sum(s["region_class"].get(x, 0) for x in ("CDS", "splice_region"))
        out.append({"value": pct(k, n), "label": "coding", "note": f"{k:,} in CDS or splice regions", "href": link(region="coding")})
    if s.get("assay"):
        checked = n - s["assay"].get("not_checked", 0)
        out.append({"value": pct(s["assay"].get("pass", 0), checked), "label": "assay pass", "note": f"of {checked:,} checked",
                    "href": link(assay="pass"), "provisional": True})
    if s.get("maf"):
        m = s["maf"]
        known = n - m["missing"]
        common = sum(k for i, k in enumerate(m["bins"]) if i * m["width"] >= 0.05 - 1e-9)
        out.append({"value": pct(common, known), "label": "MAF ≥ 0.05",
                    "note": f"of {known:,} with {'your' if m['source'] == 'yours' else '504-fish panel'} AF", "href": link(min_maf="0.05")})
    if "known" in s.get("counts", {}):
        out.append({"value": f"{s['counts']['known']:,}", "label": "near a known locus", "note": "catalogue window", "href": link(known="1")})
    if "molqtl" in s.get("counts", {}):
        out.append({"value": f"{s['counts']['molqtl']:,}", "label": "molQTL lead SNPs", "note": "nf-RASQUAL, 12 fish; display only",
                    "href": link(molqtl="1")})
    if validation:
        found = warnings_of(validation)
        out.append({"value": f"{len(found)}", "label": "upload warnings", "note": "; ".join(found) or "none", "href": "#qc-h", "warn": bool(found)})
    return out


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
    shown as they are. The warning is snpscore's assembly verdict, so its threshold (PROVISIONAL, 10%) lives in one place."""
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
        "assay": ("Assay status (PROVISIONAL checks)", counts),
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
