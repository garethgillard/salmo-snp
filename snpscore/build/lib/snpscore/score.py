"""Tiers from weights.yaml: tier_score = sum of the weights of a SNP's evidence; tiers are tier_score cut-offs."""
from __future__ import annotations

from pathlib import Path

import yaml

from .coding import SYNONYMOUS
from .formats import InputError, lit, q

ADDED = ["tier", "tier_score", "tier_evidence", "tier_terms"]
NOT_CONDITIONS = ("chromatin_summary", "chromatin_id")  # chromatin_* columns that aren't a condition's state

# The 21 conditions with ChromHMM states in AtlanticSalmon_unified_peaks.bed (annotate columns chromatin_<condition>).
# Gill (ATAC and ChIP only), Sperm (ChIP only) and the RNA-only embryo stages have none.
CHROMATIN_CONDITIONS = tuple(f"{t}_{m}_{s}" for t in ("Brain", "Gonad", "Liver", "Muscle")
                             for m in ("Immature", "Mature") for s in ("Female", "Male")) + (
    "LateBlastulation", "MidGastrulation", "EarlySomitogenesis", "MidSomitogenesis", "LateSomitogenesis")


WEIGHTS = Path(__file__).with_name("weights.yaml")  # the tier rules; a release holds data only


def load_weights(path=None):
    """The tier rules: snpscore's weights.yaml, or another copy of it (a portal job's snapshot); None if missing."""
    path = Path(path or WEIGHTS)
    return yaml.safe_load(path.read_text()) if path.exists() else None


def preset_conditions(weights, columns, trait):
    """(conditions in the preset, all conditions), from the chromatin_<condition> columns of an annotated table."""
    if trait not in weights["presets"]:
        raise InputError(f"Unknown trait preset '{trait}'. Choose from: {', '.join(weights['presets'])}")
    every = [c[len("chromatin_"):] for c in columns if c.startswith("chromatin_") and c not in NOT_CONDITIONS]
    prefixes = tuple(weights["presets"][trait])
    return [c for c in every if not prefixes or c.startswith(prefixes)], every


def scored(table, weights, columns, trait, synthetic=()):
    """SQL selecting `table` (annotate output with `columns`) plus tier, tier_score, tier_evidence and tier_terms
    (LIST(STRUCT(term, weight)): the weights.yaml terms that fired) for a preset. Terms from the layers named in
    `synthetic` (manifest layers with synthetic: true) never count."""
    chosen, every = preset_conditions(weights, columns, trait)
    w = dict(weights["weights"])
    if "coding" in w:  # releases made before the coding consequence: synonymous CDS changes weigh as any CDS change
        w.setdefault("synonymous", w["coding"])

    def having(conditions, states):  # SQL list of the conditions whose state is one of `states`
        quoted = ", ".join(lit(s) for s in states)
        items = ", ".join(f"CASE WHEN {q('chromatin_' + c)} IN ({quoted}) THEN {lit(c)} END" for c in conditions)
        return f"list_filter([{items}], x -> x IS NOT NULL)" if conditions else "[]::VARCHAR[]"

    def tissues(lst):  # Brain_Mature_Male, Brain_Immature_Female -> "Brain"
        return f"array_to_string(list_sort(list_distinct(list_transform({lst}, x -> split_part(x, '_', 1)))), ',')"

    # (layer, term, condition, evidence text) per kind of evidence; the weight of a term is weights[term].
    terms = [
        ("chromatin", "active", "len(_active) > 0", f"'active: ' || {tissues('_active')}"),
        ("chromatin", "active_elsewhere", "len(_active) = 0 AND len(_active_any) > 0",
         f"'active elsewhere: ' || {tissues('_active_any')}"),
        ("chromatin", "weak", "len(_active) = 0 AND len(_weak) > 0", f"'weak: ' || {tissues('_weak')}"),
    ]
    if "region_class" in columns and "coding_consequence" in columns:
        # 'missense p.Thr46Met', 'synonymous p.Thr46=', 'splice donor'; 'CDS' when not computed (alleles unknown)
        named = ("replace(replace(coding_consequence, '_variant', ''), '_', ' ') || coalesce(' ' || coding_hgvsp, '')")
        text = f"CASE WHEN coalesce(coding_consequence, 'coding_sequence_variant') = 'coding_sequence_variant' THEN 'CDS' ELSE {named} END"
        syn = f"coalesce(coding_consequence IN ({', '.join(lit(c) for c in SYNONYMOUS)}), false)"
        terms += [("region", "coding", f"region_class = 'CDS' AND NOT {syn}", text),
                  ("region", "synonymous", f"region_class = 'CDS' AND {syn}", text),
                  ("region", "splice", "region_class = 'splice_region'",
                   f"CASE WHEN coding_consequence LIKE 'splice_%' THEN {named} ELSE 'splice region' END")]
    elif "region_class" in columns:
        terms += [("region", "coding", "region_class = 'CDS'", "'CDS'"),
                  ("region", "splice", "region_class = 'splice_region'", "'splice region'")]
    if "region_class" in columns:
        terms.append(("region", "utr", "region_class IN ('five_prime_UTR', 'three_prime_UTR')", "'UTR'"))
    if "gerp" in columns:
        terms.append(("gerp", "constrained", "gerp", "'constrained'"))
    if "regbuild" in columns:  # mostly the same elements as the AQUA-FAANG peaks, so only counted where there is no peak
        no_peak = " AND NOT chromatin" if "chromatin" in columns else ""
        terms.append(("regbuild", "regbuild", f"regbuild{no_peak}", "'Ensembl ' || regbuild_type"))
    if "motif_changed" in columns and "motif" in w:  # a JASPAR motif match changed by the alleles, inside a robust peak
        in_peak = " AND coalesce(chromatin, false)" if "chromatin" in columns else ""
        terms.append(("motif", "motif", f"coalesce(motif_changed, false){in_peak}", "'motif: ' || motif_tfs"))
    if "molqtl" in columns and "molqtl" in w:  # nf-RASQUAL lead SNP: display only while its weight is 0
        terms.append(("molqtl", "molqtl", "molqtl", "'molQTL lead: ' || molqtl_tissues"))
    terms = [t for t in terms if t[0] not in synthetic]

    def weight(term):  # whole numbers, so tier_score and tier_terms keep their INTEGER type in every release
        value = w[term]
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"weights.yaml: weight '{term}' must be a whole number")
        return f"{value}::INTEGER"

    score = " + ".join(f"CASE WHEN {cond} THEN {weight(term)} ELSE 0 END" for _, term, cond, _ in terms) or "0"
    evidence = ", ".join(f"CASE WHEN {cond} THEN {text} END" for _, _, cond, text in terms) or "NULL"
    fired = ", ".join(f"CASE WHEN {cond} THEN {{'term': {lit(term)}, 'weight': {weight(term)}}} END"
                      for _, term, cond, _ in terms)
    tier_terms = (f"list_filter([{fired}], x -> x IS NOT NULL)" if terms
                  else "[]::STRUCT(term VARCHAR, weight INTEGER)[]")
    t1, t2, t3 = weights["tiers"]
    added = [c for c in ADDED if c in columns]
    source = f"(SELECT * EXCLUDE ({', '.join(added)}) FROM {table})" if added else table
    return f"""
        SELECT * EXCLUDE (_active, _active_any, _weak, tier_score, tier_evidence, tier_terms),
               CASE WHEN tier_score >= {t1} THEN 1 WHEN tier_score >= {t2} THEN 2 WHEN tier_score >= {t3} THEN 3 ELSE 4 END AS tier,
               tier_score, tier_evidence, tier_terms
        FROM (SELECT *, {score} AS tier_score, concat_ws('; ', {evidence}) AS tier_evidence, {tier_terms} AS tier_terms
              FROM (SELECT *, {having(chosen, weights['active_states'])} AS _active,
                              {having(every, weights['active_states'])} AS _active_any,
                              {having(chosen, weights['weak_states'])} AS _weak
                    FROM {source}))"""
