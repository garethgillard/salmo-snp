# Functional SNP portal: tracker

Covers both repos (salmo-snpscore and salmo-snpportal). Work top to bottom; the first unticked box is the next step.
Background and reasoning: the plan doc "Functional SNP portal plan for salmon breeding".

**Current phase: local prototype on test data.** No Docker, Apache, server or hosting work until the prototype works and G says go (steps 7-8).

## Step 0: decisions and contract
- [x] Assembly Ssal_v3.1, chromosomes named 1-29 (same as AQUA-FAANG and Ensembl)
- [x] Coordinates: BED for layers, 1-based `pos` for SNPs
- [x] Release format and layer registry (README, layers.yaml)
- [x] Test fixture: chr21 32-34 Mb (Ensembl "vgll3", the ohnolog), chr25 28.5-29.5 Mb (maturation vgll3, unnamed in Ensembl), chr26 14-16 Mb (nae1, IPN QTL), chr1 110-111 Mb (LORe)

## Step 1: first layers and annotate
- [x] Layers: chromatin (21 conditions), blacklist, LORe, nearest gene
- [x] `snpscore build` and `snpscore annotate`
- [x] Genome-wide check: 45,802 active-TSS and 78,424 active-enhancer peaks, as in the paper
- [x] Speed: 54K SNPs in 3 s, 1.6M SNPs in about 1 min (with all step 3 layers so far: 50K in 4 s, 1.6M in 94 s)

## Step 2: benchmark harness
- [x] Known loci positive set: `benchmark/known_loci.tsv` (vgll3 missense x2, six6 lead x2, bco1l lead x2; published ICSASG_v2 SNPs lifted to Ssal_v3.1)
- [x] Positive set: nf-rasqual caQTL/eQTL lead SNPs (`--positives molqtl:ca molqtl:e --by-tissue` -> release `benchmark_molqtl.tsv`; controls matched on gene distance and public MAF, 95% intervals; Methods figure)
- [x] `snpscore benchmark`: share of positives vs controls matched on gene-distance bins, per layer, region class and tier; output goes in the release folder

## Step 3: remaining layers (one change each)
- [x] Ensembl 116 regulatory build (counts towards tiers only where AQUA-FAANG has no peak)
- [x] Stand-in: genic region class from Ensembl 116 GFF3 (CDS, splice region, UTR, non-coding exon, intron)
- [x] Coding consequences, VEP-lite (P4.5): missense/synonymous/stop/start/splice donor-acceptor from the canonical CDS and the genome; matches Ensembl VEP REST 116 (200/200 random public CDS/splice SNPs; 585/585 terms on an enriched sample incl. codon 1 of non-ATG starts)
- [ ] SIFT4G (or another missense deleteriousness score)
- [x] GERP constrained elements (Ensembl 116 65-fish alignment; `fetch` decodes the bigBed)
- [ ] Enhancer-CNEs
- [ ] Ohnolog pairs and element duplication class (shared / alignable-only / exclusive)
- [x] molQTL from the public nf-RASQUAL lead-SNP tables (Push 2 R4, weight 0)
- [ ] ImmunoMap response regions (source needed from G)
- [ ] TF motif disruption
- [ ] DeepFARM scores (agree redistribution first)
- [x] Assay axis, part 1: variants within 35 bp (public 12-fish VCF), A/T-C/G flag
- [x] Assay axis, part 2a: GC, repeat share, homopolymers, N, TOP/BOT from the genome (P6.2, R2)
- [ ] Assay axis, part 2b: probe-flank uniqueness / paralog cross-hybridisation (P6.8; needs an aligner or k-mer index)

## Step 4: tiers and release v0.1
- [ ] G decides: which states count as active; trait presets (trait -> conditions). Brief with options: DECISIONS.md
- [x] Tier rules and weights in `weights.yaml`, applied by `snpscore annotate --trait` (values provisional)
- [ ] Genome-wide release v0.1; benchmark passes thresholds set in advance

## Step 5: portal MVP (salmo-snpportal)
- [x] Upload -> sortable, paged table -> TSV download
- [x] Trait/tissue selector and tier column (re-tiered per request, no re-annotation)
- [x] Delete old results automatically (on upload and download, after 24 h)

## Step 6: evidence card, genome view, filters, vendor export
- [x] Evidence card per SNP (21-condition state strip, gene, flags)
- [x] Genome view: server-rendered locus browser with live salmobase tracks, plus deep links to salmobase JBrowse and Ensembl
- [ ] Optional: embed salmobase's jbrowse_react bundle once merged into salmobase
- [x] Filters (tier, trait preset, region class, flags)
- [x] Axiom/Illumina/KASP flank export with TOP/BOT, sidecar provenance and vendor rules (P6.4, R2)

## Step 7: going online (later, once the prototype works)
- [ ] Decide where the repos live: GitLab elixir-nmbu (like salmobase) or GitHub
- [ ] Release folder under /datafiles on the salmobase server
- [ ] Staging deploy; CIGENE colleagues test it

## Step 8: merge into salmobase (later)
- [ ] Copy `snpportal/` into the salmobase repo (steps in salmo-snpportal/README.md)
- [ ] Plan the move of salmobase's Docker image off Python 3.8 (end of life; caps DuckDB at 1.2.2, Django at 4.2)

## Portal roadmap v2 (full specs in [ROADMAP.md](ROADMAP.md))

First push = waves A-C (items marked **now**); wave D (GWAS) is next. Ticked when built and tested.

### M1 Foundations: safe, traceable, testable, consistent
- [x] P1.1 Sanitise user columns and sandbox DuckDB (confirmed SQL-injection path) (S, must, **now**)
- [x] P1.2 Remote bigWig/BGZF reader core: one read per tree node, keep-alive, deadline (M, must, **now**)
- [x] P1.3 Job folders, background annotation, precomputed tiers with tier_terms, jobs from rows (M, must, **now**)
- [x] P1.4 Release pinning, weights snapshot, provenance headers and methods text (M, must, **now**)
- [x] P1.5 Design system (minimal): palette, partials, stylesheet, accessibility (S, must, **now**)
- [x] P1.6a Offline test kit: synthetic bigWig writer, range server, golden hash, test markers (S, must, **now**)
- [x] P1.6b Synthetic GWAS generator (make_synthetic.py gwas): Wave D (S, must)
- [x] P1.7 Extend the fixture to all known loci (S, should)

### M2 Trustworthy upload
- [x] P2.1 Chromosome aliases, validation report and assembly/strand check (M, must, **now**)
- [x] P2.2 Upload page redesign with examples, paste box and safe limits (S, must, **now**)
- [x] P2.3 Privacy and data-lifecycle hardening (S, must, **now**)
- [ ] P2.4 Optional in-browser genotype stripping before upload (S, should)
- [ ] P2.5 ICSASG_v2 -> Ssal_v3.1 offline position table (L, should)
- [x] P2.6 Chip manifests, PLINK files and header aliases (S, should, **now**)

### M3 Results overview and table
- [x] P3.1 Public background pool and background summary (S, must, **now**) (1.6M public sites in 30 s)
- [x] P3.2 Overview dashboard (server-rendered SVG, linked to the table) (M, must, **now**)
- [x] P3.3 Results table that scans quickly (M, must, **now**)
- [ ] P3.4 Custom condition presets and preset comparison matrix (S, should)
- [x] P3.5 One-page report (print to PDF) (S, should)
- [ ] P3.6 Tissue-pattern UpSet plot (M, could)

### M4 Locus browser and evidence card with salmobase tracks
- [x] P4.1 Track registry (tracks.yaml) from the AQUA-FAANG trackhubs (S, must, **now**)
- [x] P4.2 Gene-model features layer and gene descriptions (S, must, **now**)
- [x] P4.3a Server-rendered SVG locus browser: local annotation lanes (no network) (M, must, **now**)
- [x] P4.3b Live AQUA-FAANG ATAC signal lanes from salmobase (M, must, **now**) (live salmobase ATAC: 1.4 s cold, 0.1 s warm)
- [x] P4.3c Per-condition ChromHMM lanes (genome-wide segmentation) and ChIP/RNA rows (M, should) (ChromHMM toggle + H3K27ac/H3K4me3 rows; RNA rows not shown)
- [x] P4.4a Evidence card core and permanent variant page (M, must, **now**)
- [x] P4.5 Coding consequence (VEP-lite) from the canonical CDS and the genome (M, should) (weights.synonymous PROVISIONAL = coding)
- [x] P4.6 molQTL evidence contract (minimal, synthetic until nf-rasqual tables arrive) (S, could) (real public tables instead: R4)
- [ ] P4.7 Condition x assay signal matrix at the SNP (M, should)
- [ ] P4.8 Genome-wide ChromHMM state layer (not only inside robust peaks) (M, should)
- [ ] P4.9 Build-time per-peak signal layer (M, should)
- [ ] P4.10 Per-base GERP RS lane and value (S, could)
- [ ] P4.11 Allele-specific accessibility in AQUA-FAANG fish (L, could)
- [ ] P4.12 Rainbow trout functional conservation (L, could)
- [ ] P4.13 Gill ATAC peak display layer (sea lice, AGD) (S, should)

### M5 Explore without an upload
- [x] P5.1 Landing page with one search box and resolver (S, must, **now**)
- [x] P5.2 Gene page, and gene or interval lists to candidate jobs (M, must, **now**)
- [x] P5.3 Known-loci catalogue with effect alleles (S, should, **now**)
- [x] P5.4 Data, methods, glossary, help and 'Run it locally' pages generated from the release (S, must, **now**)
- [ ] P5.5 Element pages and element tissue specificity (M, should)
- [ ] P5.6 Candidate target genes beyond the nearest gene (M, should)
- [ ] P5.7 Gene expression per tissue x condition with tau (M, should)
- [ ] P5.8 Ss4R ohnolog context (S, should) (ss4r layer from the AQUA-FAANG salmon-trout table, Known loci column and gene page links done; mirrored expression bars to do)
- [ ] P5.9 TF motif disruption (ref vs alt) (M, should)
- [x] P5.10 Ortholog names for unnamed salmon genes (S, should, **now**)
- [x] P5.11 Guided 'vgll3 and maturation' tour (S, should, **now**)
- [x] P5.12 rsID support (S, could) (EVA rs bridge: R6)

### M6 Breeding toolkit: assayable markers, panels, chip comparison and exports
- [x] P6.1 Public allele frequency 'point' layer and peak ids (Wave A) (S, must, **now**)
- [x] P6.2 Assay designability QC from the Ssal_v3.1 genome (M, must, **now**) (thresholds provisional; revisited in push 2)
- [x] P6.3 Panel designer (backbone + functional fill under constraints) (M, must, **now**)
- [x] P6.4 Vendor submission exports (Illumina-style, Axiom-style, KASP) and the zip bundle (M, must, **now**)
- [x] P6.5 Genomic-prediction priors bundle (BayesRC, GFBLUP/MultiBLUP, LDAK, annot) (S, must) (`--format priors`; portal: default categories under 'More formats', no category checkboxes yet)
- [x] P6.6 Compare with an existing chip (overlap, gaps, new functional coverage) (S, should, **now**)
- [ ] P6.7 Saved, versioned panels with diff (opt-in retention) (M, could)
- [ ] P6.8 Ohnolog cross-hybridisation risk for probes (L, could)
- [x] P6.9 Genetic map (cM) layer and cM-based spacing (M, should) (Brekke 2023: R5)
- [ ] P6.10 Multi-population allele frequencies (M, could)

### M7 GWAS summary statistics and functional fine-mapping (next push, Wave D)
- [x] P7.1 Sumstats upload mode with format detection and harmonisation (M, must)
- [x] P7.2 Manhattan plot, tier-stratified QQ plot and loci table (M, must)
- [x] P7.3 LocusZoom-style regional association plot on the locus browser (S, must)
- [x] P7.4 Wakefield ABF fine-mapping with uniform vs functional priors (M, must) (synthetic GWAS; planted vgll3 Met54Thr rises under the functional prior)
- [ ] P7.5 Enrichment vs matched background and 21-condition relevance heatmap (M, should)
- [ ] P7.6 Public LD reference from the 504-fish phased panel (L, should)
- [ ] P7.7 Functional proxy finder for array lead SNPs (M, should)
- [ ] P7.8 Colocalisation with caQTL/eQTL and between two traits (L, should)
- [ ] P7.9 Heritability enrichment helper (S, could)

### M8 Scale, API and going-online readiness
- [x] P8.1 Speed up annotate (nearest gene by ASOF joins, narrow table) (M, should) (nearest gene 79.5 s -> 2.1 s on 1.6M SNPs)
- [ ] P8.2 Versioned JSON API v1 (M, should)
- [ ] P8.3 Offline CLI parity for confidential data (M, should)
- [ ] P8.4 Observability without content and a health endpoint (S, should)
- [ ] P8.5 Release integrity: verify, diff and Django system checks (S, should)
- [ ] P8.6 Fair-use limits and queue fairness (S, could)
- [ ] P8.7 Genome-wide annotated public catalogue and per-category downloads (M, could)
- [ ] P8.8 Remote reader extras deferred from P1.2 (S, should)

### Push 2: research-driven (specs in RESEARCH.md)
- [x] R1 Public AF from the 504-fish panel (not the 12-fish INFO AF); relabel the population; keep frequencies only (S, must)
- [x] R2 Vendor export corrections: sidecar provenance, numeric build, uppercase IUPAC, TOP/BOT 'cannot determine', locus names, chr 0, flank lengths, panel bin/spacing warnings; TOP/BOT oracle test (S, must)
- [x] R3 Known-loci catalogue 6 -> 36 verified rows across 8 traits; published-associations lane and card callout; bco1l A (+) = red (S, must)
- [x] R4 Real molQTL lead-SNP layer from the public nf-RASQUAL tables (brain, gonad, liver, muscle ATAC + 5 RNA; weight 0; licence to confirm) (M, should)
- [x] R5 Genetic map layer (Brekke 2023, native Ssal_v3.1, male/female cM) and cM spacing in the panel designer (S, should)
- [x] R6 rsID search and ICSASG_v2 -> Ssal_v3.1 for known variants via the EVA release 9 rs bridge (S, should)
- [x] R7 Alias table: accept .2 GenBank versions (chr 9, 11, 18, 26); warn on HG993277.1 (S, should)
- [x] R8 AQUA-FAANG itemRgb palette option, citation block, ENA/FAANG metadata on the Data page; SalmoBase gene deep links; NCBI LOC search (S, should)
- [x] R9 P4.5 note: vgll3 Met54Thr is T46M on ENSSSAT00000230965 (offset 8 to the published numbering) (S, could)

### Simplification pass (plan in [SIMPLIFY.md](SIMPLIFY.md); cuts are reversible from git)
- [x] S1 One caveat line per page (synthetic prefix), qualifiers next to numbers, no per-figure provenance captions, slim footer
- [x] S2 Overview: top-10 SNPs first, 4 tiles, 3 open figures; the rest behind one click
- [x] S3 Table: one row of filters + 'More filters', default columns, drawer
- [x] S4 Panel and Export: panel first, 1 figure, 25 rows; whole-list downloads only on Export
- [x] S5 Association and regional plot: Manhattan and loci first, settings under 'Advanced settings', QC as one line
- [x] S6 Evidence card and variant page: tier and why first, word budget
- [x] S7 Score, GWAS page and landing: one trait select, one primary action, short search help
- [x] S8 Gene and known loci pages: word budgets, 10/25-row lists
- [x] S9 Help, Methods, Data, Tour (5 steps) and Report: definitions in one place

### Results refresh (to 2026-10-11)
- [x] Tiers count all 21 conditions everywhere (no Active in); the Table filters on its columns (Chromatin: a peak or an active state in the picked conditions, a filter only) and takes single SNPs out with +/-
- [x] Evidence card in the Table's drawer: score blocks against the tier cut-offs, a mini locus browser (+-10 kb) with chromatin tiles, the marker section; 'Open locus browser' widens the drawer over the page
- [x] Score page lists this browser's results; Design panel page (Add to panel from the Table, chip comparison, problems-first SNP list with drops by hand, vendor files; this browser only, 24 h)
- [x] Guided tour (8 slides, new screenshots), Help, Methods, Run locally, report, READMEs and methods text match the above

### Review pass (2026-10-07)
- [x] Six-lens review (correctness, security/privacy, Python 3.8 + performance, UI/UX, science, tests/docs): 49 findings, 48 confirmed by two skeptics, fixed (commits e246d89 / 59c27b0)
- [x] Final check: snpscore 100 + portal 57 tests, dev and live suites, 953-URL smoke test on release/dev
- [x] Cross-package leftovers (chip cap, trait SD check, spill dirs, allele note, MAF bins, demo script, GWAS methods text, export panel list) (commits 5abd2a2 / b5ed092)

### Manual QA (not automatable)
- [x] Evidence card prints on one A4 page; report on two (49 cards and 5 reports, headless Chrome A4; not Safari/Firefox print)
- [x] Locus browser readable at 1280 px and on a tablet (768/1024/1280 px in headless Chrome; below 992 px wide figures scroll in their card; no real tablet)
- [x] Colour-blind check of tier and ChromHMM palettes (Machado 2009 simulation, CIEDE2000; 'Ensembl regulatory' moved to sky blue; AQUA-FAANG palette's Bivalent vs Repressed_polycomb is close under deuteranopia: labels on cells, tooltips only on lanes)
