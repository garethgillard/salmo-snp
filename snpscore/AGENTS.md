# Notes for Codex

This repo builds the annotation layers behind the salmobase functional SNP portal and annotates SNP lists against them.
The portal lives in `../snpportal` (same repository, salmo-snp) and depends on this package.
Read README.md first: its "Release format" section is the contract with the portal. TRACKER.md says what's next.

## Current phase: local prototype
Everything runs locally on test data: `tests/fixture` and the public inputs from `snpscore fetch`.
No Docker, Apache, server, deployment or hosting work until the prototype works and G says it's time to go online.

## Keep it small
- Minimal files, minimal code. Readable over clever. Don't add tests for every edge case.
- Dependencies: duckdb and pyyaml only. Ask before adding any. No pandas.
- Prefer one DuckDB SQL query over Python loops.
- Must run on Python 3.8 until the portal's Dockerfile sets the version (G, 2026-10-28: own container): no `match`, no `str.removeprefix`, no `X | Y` types; use `from __future__ import annotations`.

## Conventions
- Assembly Ssal_v3.1, chromosomes named "1"-"29" (as AQUA-FAANG and Ensembl).
- Layers use BED coordinates; SNPs use 1-based `pos`; a SNP is inside an interval when start < pos <= end.
- Interval layers must not overlap (annotate uses an ASOF join).
- Output columns: `<layer>` (bool hit, or a number for count layers) and `<layer>_<column>`; then `strand_ambiguous`, `tier`, `tier_score`, `tier_evidence`.
- data/ and release/ are never committed. Never edit files in data/raw by hand.
- Never put breeder data (genotypes, GWAS results, array manifests) in the repo, fixtures or tests.

## Biology decisions belong to G
Don't invent thresholds, weights, "active" state definitions or trait-to-tissue mappings. Ask, then record the answer below.

Decided:
- Primary element set: AQUA-FAANG per-condition ChromHMM states (Ensembl regulatory build may be added as a second layer).

Provisional (chosen by Codex on 2026-10-06 so the prototype works; G to confirm or replace, then move to Decided):
- Active = Active_TSS, Active_enhancer. Weak = primed, poised 1/2, bivalent, flanking up/downstream, accessible chromatin.
  Not counted: repressed polycomb, quiescent, ZNF genes and repeats, Unknown_1.
- Trait presets (condition prefixes): maturation = Brain + Gonad; growth_and_fillet = Muscle + Liver;
  disease_resistance = Liver (the only AQUA-FAANG tissue near immune function); development = the 5 DevMap stages;
  plus one preset per tissue and `all`.
- Weights and tier cut-offs: see weights.yaml (active 3, CDS/splice 3, constrained 2, weak/UTR/active elsewhere/Ensembl
  regulatory 1; tiers at 5, 3, 1). Ensembl regulatory features count only where AQUA-FAANG has no peak (68-86% overlap).
- Benchmark controls matched on distance to the nearest gene only (not MAF or LD).
- Known loci set includes GWAS lead SNPs (six6, bco1l), not only likely-causal missense SNPs (vgll3).

Open (ask G):
- Everything under Provisional.
- Where the nf-rasqual caQTL/eQTL result tables are; ImmunoMap regions; Enhancer-CNE source; public nae1/IPN SNPs.

## Commands
```bash
pip install -e ".[test]"
pytest -q
snpscore fetch && snpscore build --out release/dev
snpscore annotate tests/fixture/snps.vcf --release release/dev --trait maturation -o /tmp/out.tsv
snpscore benchmark --release release/dev -o release/dev/benchmark.tsv
bash prep/make_fixture.sh                     # after changing layers: re-cut tests/fixture from data/raw
```
