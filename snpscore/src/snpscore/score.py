"""Tiers from weights.yaml: tier_score = sum of the weights of a SNP's evidence; tiers are tier_score cut-offs.

The rules in use are the shipped weights.yaml, or a copy of it that SNPSCORE_WEIGHTS names (rules_file): an own
rules file kept outside the package, which an update of the package leaves alone. Every file is checked when it is
loaded for scoring (check_weights): a mistyped name or a weight that is not a whole number stops the run with a
message naming it, instead of changing tiers without a word."""
from __future__ import annotations

import hashlib
import os
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
    "Gill_Immature_Female", "Gill_Immature_Male", "Gill_Mature_Male",  # gill ATAC-seq of 2026 (no usable Mature Female)
    "HeadKidney_invivo_pbs", "HeadKidney_invivo_polyIC", "HeadKidney_invivo_vibrio",  # the ImmunoMap (2026)
    "LateBlastulation", "MidGastrulation", "EarlySomitogenesis", "MidSomitogenesis", "LateSomitogenesis")
# The salmon conditions in display order (unified peaks v3; release 2026-11-05 has the first 16 and the stages). Tiers
# count whatever chromatin_<condition> columns a release has.


WEIGHTS = Path(__file__).with_name("weights.yaml")  # the shipped tier rules; a release holds data only

# Every ChromHMM label of the AQUA-FAANG releases, salmon and trout, older models included (the portal's palette.STATES
# has a colour for each). A state in active_states or weak_states must be one of these, so a mistyped name stops the
# run instead of counting nothing; a new label joins here and in the palette when a release brings it.
STATES = ("Active_TSS", "Flanking_upstream", "Flanking_downstream", "Active_enhancer", "Primed_enhancer",
          "Poised_enhancer_1", "Poised_enhancer_2", "Accessible_chromatin", "Bivalent", "Repressed_polycomb",
          "ZNF_genes_and_repeats", "Quiescent", "Unknown_1", "Active_TSS_or_enhancer", "Flanking_TSS_or_poised_enhancer",
          "Bivalent_or_mixed_active/polycomb", "Unknown_2", "Weak_accessible_chromatin")
TERMS = ("active", "active_elsewhere", "weak", "coding", "synonymous", "splice", "utr", "constrained", "regbuild",
         "molqtl", "motif", "pike", "summit")  # the evidence terms scored() knows; a variant score layer adds its own
REQUIRED = ("active", "active_elsewhere", "weak", "coding", "splice", "utr", "constrained", "regbuild")
BLOCKS = ("provisional", "active_states", "weak_states", "weights", "summit", "variant_scores", "tiers", "presets",
          "assay", "design", "finemap", "priors")


class RulesError(InputError):
    """The tier rules (weights.yaml) can't be used: the message names each mistake and the file."""


def rules_file():
    """The tier rules in use: the file SNPSCORE_WEIGHTS names (an own copy of weights.yaml, kept where an update of
    the package leaves it alone; `salmo-snp serve` names the data folder's weights.yaml when there is one), else the
    shipped weights.yaml."""
    own = os.environ.get("SNPSCORE_WEIGHTS")
    return Path(own).expanduser() if own else WEIGHTS


def describe_rules(path=None):
    """What an output says about the rules that made its tiers: {file, sha256, shipped}."""
    path = Path(path) if path else rules_file()
    return {"file": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "shipped": path.resolve() == WEIGHTS.resolve()}


def check_weights(w):
    """The mistakes in a set of rules, as plain messages that name the key ([] when it can be used): a block, state,
    term or preset condition that is mistyped, a weight that is not a whole number of 0 or more, tier cut-offs out of
    order, an entry the scoring needs that was left out. These are the edits that otherwise change tiers silently or
    stop with a Python error."""
    if not isinstance(w, dict):
        return ["the file holds no rules: it should be named blocks, as the shipped weights.yaml"]
    out = [f"unknown block '{k}' (mistyped? the blocks are {', '.join(BLOCKS)})" for k in w if k not in BLOCKS]
    out += [f"'{k}' is missing" for k in ("active_states", "weak_states", "weights", "tiers", "presets") if k not in w]
    seen = {}
    for key in ("active_states", "weak_states"):
        states = w.get(key)
        if key in w and not (isinstance(states, list) and all(isinstance(x, str) for x in states)):
            out.append(f"{key}: a list of chromatin state names, e.g. [Active_TSS, Active_enhancer]")
            continue
        for state in states or []:
            if state not in STATES:
                out.append(f"{key}: '{state}' is not a chromatin state of the releases (they are {', '.join(STATES)})")
            elif state in seen:
                out.append(f"'{state}' is in both {seen[state]} and {key}")
            seen.setdefault(state, key)
    scores = w.get("variant_scores") or {}
    if not isinstance(scores, dict):
        out.append("variant_scores: score layer names with the percentile from which each counts, e.g. {chrombpnet_gill: 0.99}")
        scores = {}
    weights = w.get("weights")
    if "weights" in w and not isinstance(weights, dict):
        out.append("weights: 'term: whole number' lines, as in the shipped file")
    elif isinstance(weights, dict):
        for term, value in weights.items():
            if term not in TERMS and term not in scores:
                out.append(f"weights: unknown term '{term}' (mistyped? the terms are {', '.join(TERMS)}, and the score "
                           "layers named under variant_scores)")
            elif isinstance(value, bool) or not isinstance(value, int) or value < 0:
                out.append(f"weights: '{term}' is {value!r}; a weight is a whole number, 0 or more (0 shows it without counting it)")
        out += [f"weights: '{t}' is missing (a whole number; 0 counts nothing)" for t in REQUIRED if t not in weights]
        if weights.get("summit") and not isinstance(w.get("summit"), dict):
            out.append("weights: 'summit' counts, but the summit block (max_distance, min_rank) is missing")
        out += [f"variant_scores: '{name}' has no weight under weights (add one; 0 shows it without counting it)"
                for name in scores if name not in weights]
    for name, cutoff in scores.items():
        if isinstance(cutoff, bool) or not isinstance(cutoff, (int, float)) or not 0 <= cutoff <= 1:
            out.append(f"variant_scores: '{name}' is {cutoff!r}; it is the percentile from which the score counts, 0 to 1")
    tiers = w.get("tiers")
    if "tiers" in w and not (isinstance(tiers, list) and len(tiers) == 3
                             and all(isinstance(t, int) and not isinstance(t, bool) for t in tiers)
                             and tiers[0] > tiers[1] > tiers[2] >= 1):
        out.append(f"tiers: {tiers!r}; the minimum tier_score of tiers 1, 2 and 3, three whole numbers from high to low, "
                   "the last 1 or more, e.g. [5, 3, 1]")
    presets = w.get("presets")
    if "presets" in w and not isinstance(presets, dict):
        out.append("presets: 'name: [condition names or their beginnings]' lines ([] for all conditions)")
    elif isinstance(presets, dict):
        if "all" not in presets:
            out.append("presets: 'all' is missing (the portal's tiers and snpscore's default)")
        for name, prefixes in presets.items():
            if not (isinstance(prefixes, list) and all(isinstance(x, str) for x in prefixes)):
                out.append(f"presets: '{name}' is a list of condition names or their beginnings ([] for all), e.g. [Brain, Gonad]")
                continue
            out += [f"presets: '{x}' in '{name}' begins no condition's name (they begin with "
                    f"{', '.join(sorted({c.split('_')[0] for c in CHROMATIN_CONDITIONS}))})"
                    for x in prefixes if not any(c.startswith(x) for c in CHROMATIN_CONDITIONS)]
    rule = w.get("summit")
    if rule is not None and not (isinstance(rule, dict) and isinstance(rule.get("max_distance"), int)
                                 and not isinstance(rule.get("max_distance"), bool) and rule["max_distance"] >= 0
                                 and isinstance(rule.get("min_rank"), (int, float)) and 0 <= rule["min_rank"] <= 1):
        out.append("summit: max_distance (whole bp, 0 or more) and min_rank (0 to 1), e.g. {max_distance: 50, min_rank: 0.75}")
    from . import assay, gwas  # their own defaults say which keys their blocks take
    for block, known in (("assay", {*assay.DEFAULTS, "max_paralog_identity"}), ("finemap", gwas.DEFAULTS)):
        given = w.get(block)
        if given is not None and not isinstance(given, dict):
            out.append(f"{block}: 'key: value' lines, as in the shipped file")
        elif isinstance(given, dict):
            out += [f"{block}: unknown key '{k}' (mistyped? the keys are {', '.join(sorted(known))})" for k in given if k not in known]
    return out


def scoring_rules(weights=None, trait="all"):
    """(rules, described) for annotate's `weights` argument: the rules file it names (default: the rules in use),
    checked, and what the outputs say about it ({file, sha256, shipped, trait, snpscore_version}); (None, None) when
    the default file is missing (then nothing is tiered)."""
    path = Path(weights) if weights else rules_file()
    if weights and not path.is_file():
        raise RulesError(f"No tier rules at {path}")
    rules = load_weights(path)
    if not rules:
        return None, None
    if trait not in rules["presets"]:
        raise InputError(f"Unknown trait preset '{trait}'. Choose from: {', '.join(rules['presets'])}")
    try:
        from importlib.metadata import version
        snpscore_version = version("snpscore")
    except Exception:  # not installed, e.g. run from a source tree
        snpscore_version = "unknown"
    return rules, {**describe_rules(path), "trait": trait, "snpscore_version": snpscore_version}


def output_options(out, described):
    """COPY options for an annotated output: a Parquet file also names its rules in its key-value metadata
    (snpscore_rules_sha256, snpscore_trait, snpscore_version); None for the default by suffix."""
    if Path(out).suffix != ".parquet" or not described:
        return None
    meta = {"snpscore_rules_sha256": described["sha256"], "snpscore_trait": described["trait"],
            "snpscore_version": described["snpscore_version"]}
    return "FORMAT parquet, KV_METADATA {" + ", ".join(f"{k}: {lit(str(v))}" for k, v in meta.items()) + "}"


def load_weights(path=None, check=True):
    """The tier rules: the rules in use (rules_file()), or another copy of them (a portal job's snapshot); None if
    that file is missing. With `check` a file with mistakes raises RulesError naming each one (check_weights): a job's
    snapshot is read without, since it was checked when the job was scored."""
    path = Path(path) if path else rules_file()
    if not path.exists():
        if os.environ.get("SNPSCORE_WEIGHTS") and path == rules_file():
            raise RulesError(f"SNPSCORE_WEIGHTS names {path}, which does not exist")
        return None
    try:
        w = yaml.safe_load(path.read_text())
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f" at line {mark.line + 1}" if mark else ""
        raise RulesError(f"The tier rules in {path} can't be read{where}: {getattr(e, 'problem', None) or e}") from None
    if check:
        problems = check_weights(w)
        if problems:
            raise RulesError(f"The tier rules in {path} can't be used:\n  " + "\n  ".join(problems))
    return w


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
        return f"list_filter([{items}], lambda x: x IS NOT NULL)" if conditions else "[]::VARCHAR[]"

    def tissues(lst):  # Brain_Mature_Male, Brain_Immature_Female -> "Brain"
        return f"array_to_string(list_sort(list_distinct(list_transform({lst}, lambda x: split_part(x, '_', 1)))), ',')"

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
    if "pike" in columns and "pike" in w:  # sequence that aligns to northern pike: display only while its weight is 0
        terms.append(("pike", "pike", "coalesce(pike, false)", "'aligns to pike'"))
    rule = weights.get("summit") or {}
    if {"summit_distance", "summit_rank"} <= set(columns) and "summit" in w and rule:  # near a strong ATAC summit
        terms.append(("summit", "summit", f"coalesce(summit_distance <= {int(rule['max_distance'])} "
                                          f"AND summit_rank >= {float(rule['min_rank'])}, false)",
                      "'ATAC summit ' || summit_distance || ' bp: ' || summit_condition"))
    for name, cutoff in (weights.get("variant_scores") or {}).items():  # I15: a score layer counts from G's percentile
        if f"{name}_percentile" in columns and name in w:
            terms.append((name, name, f"coalesce({q(name + '_percentile')} >= {float(cutoff)}, false)",
                          f"{lit(name + ' ')} || printf('%.2f', {q(name + '_score')})"))
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
    tier_terms = (f"list_filter([{fired}], lambda x: x IS NOT NULL)" if terms
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
