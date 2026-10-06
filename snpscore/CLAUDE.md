# Notes for Claude

This repo builds the annotation layers behind the salmobase functional SNP portal and annotates SNP lists against them.
The portal lives in the sibling repo `salmo-snpportal` and depends on this package.
Read README.md first: its "Release format" section is the contract with the portal. TRACKER.md says what's next.

## Current phase: local prototype
Everything runs locally on test data: `tests/fixture` and the public inputs from `snpscore fetch`.
No Docker, Apache, server, deployment or hosting work until the prototype works and G says it's time to go online.

## Keep it small
- Minimal files, minimal code. Readable over clever. Don't add tests for every edge case.
- Dependencies: duckdb and pyyaml only. Ask before adding any. No pandas.
- Prefer one DuckDB SQL query over Python loops.
- Must run on Python 3.8 (salmobase's Docker image): no `match`, no `str.removeprefix`, no `X | Y` types; use `from __future__ import annotations`.

## Conventions
- Assembly Ssal_v3.1, chromosomes named "1"-"29" (as AQUA-FAANG and Ensembl).
- Layers use BED coordinates; SNPs use 1-based `pos`; a SNP is inside an interval when start < pos <= end.
- Interval layers must not overlap (annotate uses an ASOF join).
- Output columns: `<layer>` (bool hit) and `<layer>_<column>`.
- data/ and release/ are never committed. Never edit files in data/raw by hand.
- Never put breeder data (genotypes, GWAS results, array manifests) in the repo, fixtures or tests.

## Biology decisions belong to G
Don't invent thresholds, weights, "active" state definitions or trait-to-tissue mappings. Ask, then record the answer below.

Decided:
- Primary element set: AQUA-FAANG per-condition ChromHMM states (Ensembl regulatory build may be added as a second layer).

Open (ask G):
- Which states count as "active" (proposed: Active_TSS, Active_enhancer) and how primed/poised/bivalent are treated.
- Trait presets: which conditions each trait uses.
- Tier rules and weights.

## Commands
```bash
pip install -e ".[test]"
pytest -q
snpscore fetch && snpscore build --out release/dev
snpscore annotate tests/fixture/snps.vcf --release release/dev -o /tmp/out.tsv
```
