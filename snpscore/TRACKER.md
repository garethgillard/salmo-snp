# Functional SNP portal: tracker

Covers both repos (salmo-snpscore and salmo-snpportal). Work top to bottom; the first unticked box is the next step.
Background and reasoning: the plan doc "Functional SNP portal plan for salmon breeding".

**Current phase: local prototype on test data.** No Docker, Apache, server or hosting work until the prototype works and G says go (steps 7-8).

## Step 0: decisions and contract
- [x] Assembly Ssal_v3.1, chromosomes named 1-29 (same as AQUA-FAANG and Ensembl)
- [x] Coordinates: BED for layers, 1-based `pos` for SNPs
- [x] Release format and layer registry (README, layers.yaml)
- [x] Test fixture: chr21 32-34 Mb (vgll3), chr26 14-16 Mb (nae1, IPN QTL), chr1 110-111 Mb (LORe)

## Step 1: first layers and annotate
- [x] Layers: chromatin (21 conditions), blacklist, LORe, nearest gene
- [x] `snpscore build` and `snpscore annotate`
- [x] Genome-wide check: 45,802 active-TSS and 78,424 active-enhancer peaks, as in the paper
- [x] Speed: 54K SNPs in 3 s, 1.6M SNPs in about 1 min

## Step 2: benchmark harness
- [ ] Positive sets: nf-rasqual caQTL/eQTL lead SNPs (result tables needed from G), known loci list
- [ ] `benchmark/` script: share of positives vs matched controls per layer and tier; run on every release

## Step 3: remaining layers (one change each)
- [ ] Ensembl 116 regulatory build
- [ ] VEP consequences, then SIFT4G
- [ ] GERP / constrained elements (Ensembl fish alignment)
- [ ] Enhancer-CNEs
- [ ] Ohnolog pairs and element duplication class (shared / alignable-only / exclusive)
- [ ] molQTL (nf-rasqual) and ImmunoMap response regions
- [ ] TF motif disruption
- [ ] DeepFARM scores (agree redistribution first)
- [ ] Assay axis: probe-flank uniqueness, flanking variants, GC, A/T-C/G

## Step 4: tiers and release v0.1
- [ ] G decides: which states count as active; trait presets (trait -> conditions)
- [ ] Tier rules and weights in `weights.yaml`, applied by `snpscore annotate`
- [ ] Genome-wide release v0.1; benchmark passes thresholds set in advance

## Step 5: portal MVP (salmo-snpportal)
- [x] Upload -> sortable, paged table -> TSV download
- [ ] Trait/tissue selector and tier column
- [ ] Delete old results automatically (cron or on upload)

## Step 6: evidence card, genome view, filters, vendor export
- [ ] Evidence card per SNP (21-condition state strip, gene, flags)
- [ ] Genome view using salmobase's jbrowse_react bundle
- [ ] Filters (tier, tissue, element class, flags)
- [ ] Axiom/Illumina flank export

## Step 7: going online (later, once the prototype works)
- [ ] Decide where the repos live: GitLab elixir-nmbu (like salmobase) or GitHub
- [ ] Release folder under /datafiles on the salmobase server
- [ ] Staging deploy; CIGENE colleagues test it

## Step 8: merge into salmobase (later)
- [ ] Copy `snpportal/` into the salmobase repo (steps in salmo-snpportal/README.md)
- [ ] Plan the move of salmobase's Docker image off Python 3.8 (end of life; caps DuckDB at 1.2.2, Django at 4.2)
