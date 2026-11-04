# salmo-snp: tracker

What's next for the whole repository (snpdata/, snpscore/ and snpportal/). **Next** is the order of work; the
sections after it record what was built (ticked when built and tested), and their open boxes are the backlog.
Specs: [ROADMAP.md](ROADMAP.md). Questions only G can answer: [DECISIONS.md](DECISIONS.md) (ask, don't decide).
Background and reasoning: the plan doc "Functional SNP portal plan for salmon breeding".

## Where things stand (2026-11-04)
- Phase: feature work on the local install, the main product (AGENTS.md plan 4, G 2026-11-03); the live site moves
  to salmobase later.
- main is green on GitHub (tests, user-install, deploy). The NREC demo https://158.39.75.9/snp/ runs the latest main
  with release 2026-11-03 (cloud sessions use https://158-39-75-9.sslip.io/snp/: the bare IP didn't connect through their proxy).
- The data for real use: the private GitHub Release data-2026-11-03 (`bash tools/get_data.sh`); not on salmobase yet.
- Work happens in cloud sessions, on a branch with a pull request (AGENTS.md "Cloud sessions"); G merges.

## Next
1. **G's feature requests** (G, 2026-11-04: coming next). Each becomes a box in step 9 below, in G's order, with a
   spec in ROADMAP.md when it needs more than a line.
2. ~~Off end-of-life versions~~: done 2026-11-04 (step 8).
3. **A public background pool for every install** (step 8): no release in use has one, so the Overview's
   comparisons with public sites are never drawn.
4. **Before the local install is shared beyond collaborators** (step 8, and step 7's open boxes): Bootstrap and htmx
   shipped with the package (the pages need cdn.jsdelivr.net today), a v0.1.0 tag, the package names on PyPI, the data
   on salmobase, the citation and privacy text, macOS and Windows checks.
5. **Backlog**: the other open boxes below, in the order G picks, and the questions in DECISIONS.md (the tier rules,
   #1-#5, come before the genome-wide release v0.1 of step 4).

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

## Step 5: portal MVP (snpportal/)
- [x] Upload -> sortable, paged table -> TSV download
- [x] Trait/tissue selector and tier column (re-tiered per request, no re-annotation)
- [x] Delete old results automatically (on upload and download, after 24 h)

## Step 6: evidence card, genome view, filters, vendor export
- [x] Evidence card per SNP (21-condition state strip, gene, flags)
- [x] Genome view: server-rendered locus browser with live salmobase tracks, plus deep links to salmobase JBrowse and Ensembl
- [ ] Optional: embed salmobase's jbrowse_react bundle once merged into salmobase
- [x] Filters (tier, trait preset, region class, flags)
- [x] Axiom/Illumina/KASP flank export with TOP/BOT, sidecar provenance and vendor rules (P6.4, R2)

## Step 7: one repository, a static data release and a container (G, 2026-10-28; plan in ../AGENTS.md)
- [x] One private GitHub repository, salmo-snp, with both histories in snpscore/ and snpportal/; PolyForm Noncommercial licence
- [x] Move the release build (fetch, build, layers.yaml, tracks.yaml, prep/, the known-loci catalogue) to snpdata/;
      snpdata imports snpscore for the motif scoring and file readers, never the other way round
- [x] Weights out of the release: the public pool's tiers and background summaries become a cache built from the release
- [x] Portal-only code (locus browser data, Design panel, exports, the track registry reader) moves to snpportal/lib/
      (the bigWig reader stays in snpscore: the genome reader is built on it; GWAS fine-mapping stays too, with `snpscore gwas`)
- [x] One AGENTS.md per folder (CLAUDE.md imports it) instead of the duplicated notes; CI runs both test suites and
      rejects data files outside tests/fixture
- [x] Automatic deploys to NREC from main (update.sh, GitHub Actions deploy job; both keys set up 2026-10-29)
- [x] Gene models: a representative Ensembl isoform, expandable to every Ensembl and NCBI RefSeq isoform
      (transcripts_ncbi layer, in release 2026-11-03)
- [x] environment.yml (conda-forge, python 3.8) for development
- [x] The salmo-snp package (snpportal/pyproject.toml): `salmo-snp download` (SHA256SUMS, written by snpdata build) and
      `salmo-snp serve` (127.0.0.1). The public site keeps gunicorn behind Caddy (no `--public` mode needed yet)
- [x] Local install hardened after a newcomer test (2026-11-03): duckdb<2; snpscore.release.check (serve, annotate,
      download and publish refuse a damaged release); genome downloaded with the release (no positions sent for
      sequence checks); platform data folder, results kept until deleted (SNPPORTAL_LOCAL); salmo-snp info; download
      from a URL or a folder; snpdata publish (releases/ + raw/ mirror) and fetch --mirror; CI user-install job
- [x] release/2026-11-03 rebuilt cleanly (with transcripts_ncbi); serve.py RELEASE names it
- [x] Temporary data hosting: GitHub Release data-2026-11-03 (snpdata/prep/github_release.sh; tools/get_data.sh);
      delete it once the data is on salmobase
- [x] Cloud sessions: tools/cloud_setup.sh (SessionStart hook in .claude/settings.json), AGENTS.md "Cloud sessions"
- [ ] Host the published folder (`snpdata publish --raw`: releases/, latest.json, raw/) on salmobase's Apache and set
      serve.py DATA_URL; the nf-RASQUAL and 504-fish layers only once their owners agree to redistribution
- [ ] v0.1.0 tag (G decides when): .github/workflows/release.yml builds the three wheels into a GitHub Release
- [ ] Dockerfile for salmobase (installs a tagged version; release folder mounted); salmobase links to it with a button
- [ ] Before the repository goes public: synthetic stand-ins for the fixture cuts of licence-pending data

## Step 8: platform, pool and sharing (review of 2026-11-04)
- [x] Off end-of-life versions (G, 2026-11-04: the newest that suit). Python 3.8 had had no fixes since 2024-10-07
      and Django 4.2 none since 2026-04-07, and the public demo ran on them. Now: Python >= 3.11 (3.10's end of life
      was 2026-10-01; CI, NREC and cloud sessions on 3.12), Django 5.2 LTS (fixes to 2028-04-30), DuckDB 2, PyYAML 6,
      setuptools >= 77 (SPDX licence in every package), pyflakes 4.1, htmx 2.0.11, actions/checkout and setup-python
      v7. The ranges are set only in the pyproject.toml files: CI, deploys (update.sh now upgrades the packages) and
      cloud sessions install the newest they allow. The palette cookie moved from `request_started` to a middleware
      (under ASGI, Django 5 sends the signal in another context); the SQL lambdas are written `lambda x: ...`. DuckDB
      2.0.0 gives the same annotate output (golden hash) and the 220-page crawl of the real release finds no errors
- [x] DuckDB 2 (2.0.0 of 2026-10-21): the lambdas, and two tests that left a half-read result on DuckDB's shared
      connection (`fetchall()` instead of `fetchone()`); the product code was already fine
- [ ] Public background pool for every install. `salmo-snp download` leaves `pool/` out (a cache of the current
      weights), `snpscore pool` needs the 12-fish VCF in data/raw (a release builder's), and the demo's release has
      none either. So the Overview's thin bars and ticks for public sites, and the '×' fold of 'Active chromatin per
      condition', are never drawn, though their (i) texts describe them, and gene-page candidates are annotated on the
      fly. Proposal: `snpscore pool` takes its sites from the release's public_af (the 12 AQUA-FAANG fish's sites, as
      now, or the 504-fish panel: DECISIONS.md #15); `salmo-snp download` and nrec.sh build it (~40 s for 1.6M sites)
- [ ] Bootstrap 5.1.3 and htmx 2.0.4 shipped with the package (static files, MIT and BSD licences; G to OK) instead of
      cdn.jsdelivr.net, which every page loads them from: offline, or where a company network blocks the CDN, a local
      install's pages lose their layout and the job progress panel never refreshes (its `<noscript>` fallback needs
      JavaScript off). salmobase's own base template brings Bootstrap there. Then the README's and Help's 'fetches
      public data only' are complete
- [ ] Install by tag once v0.1.0 exists (README: `...salmo-snp@v0.1.0#subdirectory=...`), so a reinstall needs no
      `--force-reinstall` and users can say which version they ran
- [ ] The package names on PyPI (DECISIONS.md #25): snpscore, snpdata and salmo-snp are unregistered, and salmo-snp
      depends on `snpscore` by name
- [ ] The user-install check on macOS and Windows (DECISIONS.md #26); Windows also needs tools/user_install_test.sh
      to find `Scripts\` instead of `bin/`

## Step 9: G's feature requests (2026-11-04)
G sends these next; one box each, in G's order.

## Portal roadmap v2 (full specs in [ROADMAP.md](ROADMAP.md))

First push = waves A-C (items marked **now**), then wave D (GWAS, M7). Ticked when built and tested.

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

### M7 GWAS summary statistics and functional fine-mapping (Wave D)
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

### More public data (2026-10-19/20)
- [x] Synchrosmolt parents' allele frequencies (`synchrosmolt_af`, ENA PRJEB114348; 108 WGS fish) and the locus browser's Public SNPs group (combined row, a row per dataset)
- [x] TF motif evidence: JASPAR 2024 motif changes at SNPs in robust peaks (+1, G's rule), the card's TF motifs section (logos, both alleles' scores) and the browser's TF motifs group
- [x] Known loci: the three chromosome 14 hubsmolt SNPs (Saitou et al. 2025 preprint, Fig. 4)
- [x] Public demo at https://158.39.75.9/snp/ (deploy/nrec.sh with the IP and the sslip.io name)
- [ ] CGD Axiom array positions (ENA PRJEB107807): need Ssal_v3.1 positions from the submitters (README "Not added")
- [ ] Synchrosmolt gill eQTL table (45,543 SNP-gene pairs): ask the Sandve lab; would join the molQTL lane
- [ ] DeepFARM salmon scores: ask D. T. Nguyen for the model weights or precomputed scores for the 504-panel SNPs
- [ ] LD reference (Synchrosmolt parents or the 504-fish panel, r2 pairs only): G to choose the population
- [ ] Motif hits in repeats (low-complexity motifs such as EWSR1-FLI1 and ZSCAN4 fire most): G to decide whether to skip soft-masked windows

### Review pass (2026-10-07)
- [x] Six-lens review (correctness, security/privacy, Python 3.8 + performance, UI/UX, science, tests/docs): 49 findings, 48 confirmed by two skeptics, fixed (commits e246d89 / 59c27b0)
- [x] Final check: snpscore 100 + portal 57 tests, dev and live suites, 953-URL smoke test on release/dev
- [x] Cross-package leftovers (chip cap, trait SD check, spill dirs, allele note, MAF bins, demo script, GWAS methods text, export panel list) (commits 5abd2a2 / b5ed092)

### Review 2026-11-04 (cloud session; what is still to do is in step 8)
- [x] Real release 2026-11-03 through `salmo-snp serve` in the cloud: the four examples and a pasted list scored, then
      220 pages crawled with their links and every export of each job: no server errors (the 400s are the 50,000-SNP
      vendor-file cap, whose message pointed to the unlinked Panel tab: fixed)
- [x] A new user's install (tools/user_install_test.sh) on Python 3.13 and 3.14 (Django 4.2.30, DuckDB 1.5.6): passes
- [x] Django 5.2.19 + DuckDB 1.5.6 on Python 3.12: one test fails (step 8); Django's system check is clean
- [x] tools/check.sh runs what CI runs, and CI calls it; pyflakes now covers the Django app too (one unused variable
      removed); the leftover 'AGENT' build comments are gone
- [x] Cloud sessions on CI's Python and versions (tools/cloud_setup.sh, uv's Python 3.8); get_data.sh over REST;
      user_install_test.sh no longer leaves build/ folders in the source tree
- [x] `salmo-snp serve` says when the release this version expects isn't downloaded
- [x] Docs: README rewritten as the user guide; stale names and paths fixed in the folder READMEs and AGENTS.md files
      (snpportal.lib, src/snpdata/build.py, dated release folders, AGENTS.md for CLAUDE.md); status notes on ROADMAP,
      RESEARCH and SIMPLIFY; DECISIONS #22-#26 brought up to date; this tracker's Next

### Manual QA (not automatable)
- [x] Evidence card prints on one A4 page; report on two (49 cards and 5 reports, headless Chrome A4; not Safari/Firefox print)
- [x] Locus browser readable at 1280 px and on a tablet (768/1024/1280 px in headless Chrome; below 992 px wide figures scroll in their card; no real tablet)
- [x] Colour-blind check of tier and ChromHMM palettes (Machado 2009 simulation, CIEDE2000; 'Ensembl regulatory' moved to sky blue; AQUA-FAANG palette's Bivalent vs Repressed_polycomb is close under deuteranopia: labels on cells, tooltips only on lanes)
