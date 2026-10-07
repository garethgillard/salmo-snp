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
- Output columns: `<layer>` (bool hit, or a number for count layers) and `<layer>_<column>`; then `strand_ambiguous`, `tier`, `tier_score`, `tier_evidence`.
- data/ and release/ are never committed. Never edit files in data/raw by hand.
- Never put breeder data (genotypes, GWAS results, array manifests) in the repo, fixtures or tests.

## Biology decisions belong to G
Don't invent thresholds, weights, "active" state definitions or trait-to-tissue mappings. Ask, then record the answer below.

Decided:
- Primary element set: AQUA-FAANG per-condition ChromHMM states (Ensembl regulatory build may be added as a second layer).

Provisional (chosen by Claude on 2026-10-06 so the prototype works; G to confirm or replace, then move to Decided):
- Active = Active_TSS, Active_enhancer. Weak = primed, poised 1/2, bivalent, flanking up/downstream, accessible chromatin.
  Not counted: repressed polycomb, quiescent, ZNF genes and repeats, Unknown_1.
- Trait presets (condition prefixes): maturation = Brain + Gonad; growth_and_fillet = Muscle + Liver;
  disease_resistance = Liver (the only AQUA-FAANG tissue near immune function); development = the 5 DevMap stages;
  plus one preset per tissue and `all`.
- Weights and tier cut-offs: see weights.yaml (active 3, CDS/splice 3, constrained 2, weak/UTR/active elsewhere/Ensembl
  regulatory 1; tiers at 5, 3, 1). Ensembl regulatory features count only where AQUA-FAANG has no peak (68-86% overlap).
- Benchmark controls matched on distance to the nearest gene and public MAF (0.05 bins), not LD.
- Known loci set includes GWAS lead SNPs (six6, bco1l), not only likely-causal missense SNPs (vgll3).
- Portal roadmap v2, stage 1 (2026-10-06):
  - Known-locus window 50 kb; effect alleles vgll3 Met54Thr T / Asn323Lys C = early maturation; bco1l direction 'to verify' (strand).
  - Upload QC: assembly warning when (mismatch + strand_flip) / checked > 10%; remote genome checks a 200-SNP sample;
    duplicates = same chrom, pos, ref, alt (first kept); only chromosomes 1-29 are accepted (scaffolds rejected).
  - Locus browser default tracks (tracks.yaml defaults): ATAC, replicate R1, at most 8 rows; preset `all` = first condition
    per tissue incl. Gill and one embryo stage. RNA '.forward' = + strand (to verify).
  - Palette: tier 2 #2171B5 (AA contrast), ChromHMM colours in one dict (palette.STATES) until G picks AQUA-FAANG itemRgb.
  - Portal limits: 3M SNPs, 300 MB upload, 10,000 pasted lines, 24 h retention; privacy statement and citation text need G.
- Portal roadmap v2, stages 2-3 (all in weights.yaml blocks, labelled PROVISIONAL in the UI):
  - Assay QC `assay`: 35 bp flanks, GC 0.30-0.70, repeat share <= 0.5, homopolymer <= 6, no public variant in the flanks (warn);
    LORe/blacklist/A/T-C/G warn; fail on ref mismatch, non-SNP or N. Only ~15% of public SNPs pass (salmon is ~60% repeat): revisit.
  - Panel designer `design`: 384 markers, half backbone (best SNP per genome bin), 20 kb min spacing, MAF >= 0.05, <= 2 per gene,
    <= 1 per AQUA-FAANG element, blacklist excluded; chip comparison window 10 kb, chip gaps > 1 Mb.
  - Fine-mapping `finemap`: Wakefield ABF, prior SD 0.2 (W 0.04), functional prior exp(0.5 x tier_score), 95% credible sets,
    5e-8 / 1e-5, 1 Mb clumping; one causal variant per locus and no LD reference (stated on the page).
  - Locus browser: up to 8 signal rows (R1), ATAC/H3K27ac/H3K4me3, signal and ChromHMM up to 500 kb, lanes up to 2 Mb, 4 s deadline.
  - Vendor layouts (Illumina 60 bp TOP/BOT, Axiom 35 bp, KASP 50 bp) are 'to confirm against the vendor template' (see RESEARCH.md 5).
- Coding consequences, molQTL benchmark, priors (2026-10-07): weights.synonymous = coding (3) until G decides (stop_retained
  counts as synonymous; splice donor/acceptor keep the splice weight); molQTL benchmark positives = leads with BF < 0.1;
  priors category order tier1_2, active, coding, constrained, regulatory (weights.yaml `priors`).
- Ss4R duplicates (2026-10-07): `ss4r` layer from the AQUA-FAANG SalmonTroutOrthologs.tsv on salmobase: the other
  salmon genes of a gene's clade on the paired chromosome of its syntenic quartet (any other chromosome when the quartet
  is unknown); class AORe/LORe from the clade or its neighbours; Ens106 gene ids used as Ens116 ids.

Open (ask G; all collected with options and recommendations in DECISIONS.md):
- Everything under Provisional.
- nf-rasqual tables: found public at github.com/datngu/nf-RASQUAL_paper (lead SNP per feature only; no licence on the repo):
  may we redistribute derived rows, which significance rule (paper: eigenMT BF < 0.1), which allele does pi refer to?
- Public AF: the 504-fish panel is mostly Bertolotti 2020 (PRJEB38061) wild/farmed fish plus the 12 AQUA-FAANG fish; may we host
  derived AF, and how should the population be described? (RESEARCH.md section 4)
- ImmunoMap regions; Enhancer-CNE source; vetting of the 36-row known-loci catalogue (RESEARCH.md section 2).
- Data gap: the public 12-fish VCF (pool, demo list, synthetic GWAS) has only 70 sites on chr10 and stops near 105 Mb on chr1,
  while the 504-fish panel covers both; should the pool and demos use the 504-fish sites instead?
- Assay QC: flank repeat shares are mostly 0 or 1, so ~55% of public SNPs warn on 'repeat' whatever the cut-off; should fully
  soft-masked flanks warn at all? (without it ~46% pass instead of ~20%)

## Commands
```bash
pip install -e ".[test]"
pytest -q
snpscore fetch && snpscore build --out release/dev
snpscore annotate tests/fixture/snps.vcf --release release/dev --trait maturation -o /tmp/out.tsv
snpscore benchmark --release release/dev -o release/dev/benchmark.tsv
bash prep/make_fixture.sh                     # after changing layers: re-cut tests/fixture from data/raw
```
