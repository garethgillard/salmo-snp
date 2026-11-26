# salmo-snp: notes for people and their AI assistants

Functional SNP scoring for Atlantic salmon (Ssal_v3.1) and rainbow trout (USDA_OmykA_1.1; G, 2026-11-12): public
annotation data, a scoring engine and a web portal.
Owner: NMBU; maintainer Gareth Gillard (G). The repository is public on GitHub (G, 2026-11-10); licence: PolyForm Noncommercial
1.0.0 (LICENSE); contributors accept CLA.md (CONTRIBUTING.md).
Each folder has its own AGENTS.md (CLAUDE.md imports it). docs/TRACKER.md says what's next.

## Layout
- `snpdata/`: collects the public sources and builds a versioned release (Parquet tables, manifest.json, tracks.yaml,
  the known-loci catalogue): `snpdata fetch`, `snpdata build`, `snpdata tracks`. Its README's "Release format" is the
  contract with the other two. One layer registry per species: `layers.yaml` (salmon), `rainbow_trout/layers.yaml`.
- `snpscore/`: scores a SNP list against a release (`snpscore annotate`), structural variants by what they overlap
  (`snpscore sv`), plus `rsid`, `pool`, `benchmark` and `gwas`.
  The tier rules (weights.yaml) live here, not in the release.
- `snpportal/`: the Django web portal; reads a release and calls snpscore. `snpportal/lib/` holds its plain-Python
  parts (locus data, panel design, exports, the track registry; `python -m snpportal.lib.cli panel|export|compare`).
- `docs/`: TRACKER (what's next, then what's built), DECISIONS (questions for G, with options and a recommendation),
  ROADMAP (the spec of every roadmap item), LICENSING (the licences, the CLA, commercial permission, third-party
  data and software), SCORING (how other projects score variants, and the options for our starting point), CHROMBPNET
  (the brief of the ChromBPNet repository), MISSENSE (the plan of the missense effect score), ORION (building the
  releases on Orion and hosting them on salmobase: the brief for the chat there, starting with the next build's plan
  and the steps of a build), SALMOBASE (installing and updating the portal on the salmobase server: the same chat's
  brief); for reference: RESEARCH (the source research of 2026-10-06) and SIMPLIFY (the simplification plan of
  2026-10-07, built).
- `tools/`: check.sh (what CI runs), user_install_test.sh (a new user's install), get_data.sh (the data for real use),
  smoke.sh (one test of a running portal: its health page, and every example scored through the job queue),
  cloud_setup.sh (cloud sessions).

## Plan (G, 2026-10-28)
1. One repository, three folders. snpdata builds a release once; it is published as static files on Apache, beside
   salmobase in its own folder. snpscore only scores and can change without touching the rest. snpportal is the website.
2. Dependencies point one way: snpdata -> snpscore <- snpportal (snpscore's tests build their fixture release with snpdata).
3. Scoring rules stay out of the release: weights.yaml lives in snpscore, and whatever depends on the weights (the
   public pool's tiers, `snpscore pool`) is a cache built from the release, rebuilt after a weight changes.
4. The local install is the main product (G, 2026-11-03): users install from this GitHub repository and run the
   portal on their own computer, safe for industry SNPs. `pip install` snpscore and snpportal (the `salmo-snp`
   package), `salmo-snp download` (a release snapshot and the genome, every file checked), `salmo-snp serve`
   (127.0.0.1 only; `SNPPORTAL_LOCAL`: results kept in the platform data folder until deleted, never expired, pages say
   so), `salmo-snp info`. snpscore installs alone for pipelines; snpdata is only for whoever builds releases. The
   README's "Run it on your own computer" is the user guide; tools/user_install_test.sh is that path as a test (CI).
   Where it runs:
   - development: clone, `conda env create -f environment.yml` (conda-forge only), editable installs;
   - NREC (demo and staging until salmobase): git checkout, updated only when G says so (the manual `deploy`
     workflow, a batch of tested changes at a time; G, 2026-11-06), never by a merge;
   - salmobase (the live installation, being prepared: G, 2026-11-25): the portal behind salmobase's Apache at
     /snp/ (not merged into its Django), as a container of its own on salmobase's Docker network, reading the
     published data where it is on the server (`SNPSCORE_SALMOBASE`: its datafiles folder); installed and updated
     by the chat on Orion (docs/SALMOBASE.md);
   - breeding companies and everyone else: the local install.
   Docker and bioconda only wrap the package. Nothing depends on Docker-only features.
5. The data is hosted online (salmobase or any static web server) as one folder: releases/<version>/ (the snapshot
   `salmo-snp download` fetches, with SHA256SUMS), releases/latest.json, and with `snpdata publish --raw` raw/ (the
   input files, genome included, that `snpdata fetch --mirror` rebuilds from). Since 2026-11-25 it is
   https://salmobase.org/datafiles/datasets/salmo-snp (serve.py DATA_URL; docs/ORION.md "Hosting on salmobase").
   Releases are versioned apart from the code; each salmo-snp version names the one it expects (serve.py RELEASE). A
   copy of the folder on a disk works the same (`--from <folder>`), for computers without internet. Fetching public
   data at given locations (AQUA-FAANG signal for a viewed region) is
   fine; users' SNPs and results are never sent or stored online. Never edit a release by hand: rebuild it
   (snpscore.release.check refuses damaged ones).
6. GitHub: branches and pull requests; tests on every pull request and push to main; G reviews biology files
   (CODEOWNERS); a merge to main deploys nothing: the NREC demo is updated when G asks (the `deploy` workflow);
   a vX.Y.Z tag builds the wheels (and later the image) as a GitHub Release.

7. Species (G, 2026-11-12): a release is for one species and assembly. Salmon releases are named by their date
   (2026-11-05), another species' with the species first (trout-2026-11-13), and the manifest's `species` block
   (layers.yaml: key, name, latin, prefix, the browser's example locus, the pages' wording, samples, searches) says
   which. The portal's species bar (top right; a cookie, so it works on a server too) picks the species: new lists are
   scored against that species' release (serve.py RELEASES names one per species), while results, panels and saved
   projects keep the release they were made with. The pages are written for salmon; `jobs.wording` is the one place
   that turns them into another release's (assembly, older assembly, number of conditions, chromosome names, and the
   release's own pairs). Adding a species: a folder with layers.yaml and tracks.yaml, a fixture, an entry in RELEASES.
   The data build is per species, the serving is one thing (G, 2026-11-14): `snpdata fetch` and `build` run once for
   each species and make that species' release files; one portal (one install, one NREC demo, one deploy) serves
   every release it holds, and the species bar switches between them.

## Rules
- Never commit breeder data (genotypes, GWAS results, array manifests): not in fixtures, tests or docs either.
  `data/`, `release/` and results folders are never committed. Never edit files in snpdata/data/raw by hand.
- Keep it small: few files, little code, readable over clever. Don't add tests for every edge case.
- Dependencies: duckdb and pyyaml (plus Django for the portal). Ask G before adding any. No pandas. Optional, for
  the SNP card's Predict button only (G asked for it, 2026-11-25): numpy and onnxruntime, the `chrombpnet` extra of
  salmo-snp. The base install and everything else run and are tested without them.
- Versions (G, 2026-11-04: the newest that suit): Python 3.11 or newer (`requires-python`; 3.10 reached its end of
  life on 2026-10-01; CI, the NREC demo and cloud sessions run 3.12), Django 5.2 LTS (fixes to 2028-04-30; 6.x needs
  Python 3.12), DuckDB 2 (`duckdb>=2.0,<3`). The pyproject.toml files are the one place they are set: CI, deploys
  and cloud sessions install the newest versions those allow. DuckDB 2: SQL list lambdas are `lambda x: ...` (not
  `x -> ...`), and a half-read result blocks its connection: on a shared connection (`duckdb.sql`, `duckdb.execute`)
  use `fetchall()`, not `fetchone()`.
- Assembly Ssal_v3.1, chromosomes named "1"-"29" (as AQUA-FAANG and Ensembl); rainbow trout USDA_OmykA_1.1, "1"-"28",
  "30"-"32" and "Y" (the Arlee line has no 29; layers.yaml `chromosome_names`). Layers use BED coordinates; SNPs use
  1-based `pos`; a SNP is inside an interval when start < pos <= end.
- Changes go through pull requests. Anything touching the biology files (CODEOWNERS lists them) needs G's OK in the
  chat before it is merged.

## Biology decisions belong to G
Don't invent thresholds, weights, "active" state definitions or trait-to-tissue mappings. Ask, then record the answer below (and in docs/DECISIONS.md).

Decided:
- Repository and deployment (2026-10-28): see Plan above. Licence: PolyForm Noncommercial 1.0.0 (commercial use only
  with permission). Ownership and contributions (G, 2026-11-09): copyright NMBU (LICENSE); invited collaborators
  contribute by pull request and accept CLA.md once (a licence grant: they keep their copyright, NMBU may license the
  project with their work on any terms), checked by the `cla` workflow; CONTRIBUTING.md says how. CLA.md in force
  (G, 2026-11-10).
- Primary element set: AQUA-FAANG per-condition ChromHMM states (Ensembl regulatory build may be added as a second layer).
- RNA-seq strands (2026-10-08): the trackhub's '.forward' files are the + strand (checked at vgll3: 16x the reverse
  files' reads over the gene).
- Sperm ChIP is ignored (2026-10-08; salmobase answers 403 for its files).
- No Bgee expression in the locus browser (2026-10-08); the release keeps bgee.parquet (Bgee 16.0, bgee.org, Ssal_v3.1
  ids; salmobase's copy is 15.2 on ICSASG_v2) for a gene card later.
- No phenotypic traits in the portal (2026-10-09): it names sample conditions only (tissues, maturity, sex, embryo
  stages), never maturation, growth and so on; users map conditions to traits themselves. weights.yaml presets stay as
  snpscore's CLI names and the portal's cache of precomputed condition sets (to rename to tissue names later).
- All conditions (2026-10-11, replaces 'Trait = Active in'): the portal's tiers always count all 27 conditions (21 until
  release 2026-11-20: see the AQUA-FAANG 2026 entry below) (Table,
  card, Overview, GWAS functional prior, gene page, variant page); there is no Active in and no condition picker. The
  Table only filters after scoring: its Chromatin column filter keeps SNPs in a robust ATAC peak (or an active state) in
  at least one chosen condition (tissues, maturity, sex) and changes no tier, Overview or card. One SNP's card opens in
  the Table's drawer.
- Public demo (2026-10-12): the portal runs openly (no password) on an NREC VM, so the molQTL rows and the 504-fish
  allele frequencies are shown publicly. Redistribution of both (the releases, the test fixture, the public
  repository) is agreed with their authors, G's colleagues (G, 2026-11-10).
- TF motifs (2026-10-19): JASPAR 2024 CORE vertebrates non-redundant (879 motifs, the set SalMotifDB v2 uses), scored
  ourselves in pure Python (no FIMO). +1 (weights.motif) when, inside a robust ATAC peak, one allele matches a motif at
  p < 1e-5 and the other doesn't, with at least 4 bits between them (about 15% of in-peak public SNPs; at FIMO's
  p < 1e-4 76% would score). SalMotifDB data (promoter hits, TOBIAS footprints) only with the authors' files and
  permission: its robots.txt disallows the API.
- Hubsmolt known loci (2026-10-20, G asked): the chromosome 14 hub SNP ssa14_50815335 and its two high-LD cis-eQTL SNPs
  (ssa14_50820817, ssa14_50852463) from the Synchrosmolt preprint (Saitou et al. 2025, Fig. 4) under smoltification;
  the paper gives no alleles, so the hub SNP's effect allele (A) is the Synchrosmolt parents' minor allele (caveat says so).
- Synchrosmolt (2026-10-19): the parents' frequencies only (the offspring were imputed from them). From the next
  release (G, 2026-11-24) the parents' whole-genome set, 112 fish and 3,993,949 SNPs, replaces ENA PRJEB114348's 108
  fish and 411,908 SNPs; it isn't online, so layers.yaml reads it as `local` (snpdata/README.md), and its frequencies
  may be published (G, 2026-11-24). The CGD Axiom VCF (PRJEB107807) waits: its positions are not Ssal_v3.1
  (snpdata/README.md "Not added").
- Industry users (2026-11-04): the plan is ROADMAP.md "Push 3" (I1-I20; boxes in TRACKER step 9), in G's order: ready
  to hand over (I1-I6), chip design (I7-I14), variant scores (I15-I16, G's DeepFARM and CADD-like data), genomes later
  (I17-I20). One user per install, who shares results as files: no accounts, no shared server (on hold). Chip tools
  serve Thermo Fisher Axiom first (G's guess for Norwegian aquaculture; to confirm), then Illumina and KASP. Genome
  comparison is on hold until G has asked the users.
- NREC deploys (G, 2026-11-06): the demo is updated only when G says so in a chat, after enough merged and tested
  changes for a larger update; merging a pull request no longer deploys (how: "Deploying the NREC demo",
  under Cloud sessions; it applies to every session).
- Chip placement by flank (I18; G, 2026-11-05: Claude's recommendations for now, on the safe side; DECISIONS #34, #36
  stay open, under Open below): flank keys from the 504-fish panel's sites; a placement's whole flank must match the
  genome exactly (IUPAC and N skipped), else it is not placed, not by its rs ID either, and a row its rs ID places
  must agree the same way at the rs ID's site when it has a flank (either strand); where the flank and the rs ID
  disagree, the flank's position is kept (the only one checked against the genome), and the rs ID's is named
  (position_source) and counted.

- Rainbow trout (G, 2026-11-12: add it as a second species, on the assembly of the AQUA-FAANG trout data, with the
  AQUA-FAANG data as the highlight and whatever public data of the salmon kinds exists; a species-specific release,
  and a species bar at the top right that picks the release). How it was done: Plan 7; what Claude chose on the way
  is under Provisional below and in docs/DECISIONS.md #38-#45.

- Your own tracks (G, 2026-11-15): a user's BED file (coordinates; the name as hover text; its own colours only when
  the file has them) is shown near the top of the Locus browser and offered as a Table filter, and is never scored:
  no tier, Overview or card changes. Global in a local install, private to the browser and expiring like results on
  a server. The limits (50 MB, 1,000,000 intervals) are in snpportal/AGENTS.md "Provisional".

- Rainbow trout chromosome Y is kept (G, 2026-11-14): scored, shown and in the ideogram (sdY and 3,928 AQUA-FAANG
  peaks are on it).

- New AQUA-FAANG salmon data (G, 2026-11-20): the gill ATAC-seq re-made in 2026 (gill states and peaks) and the
  ImmunoMap (head kidney after PBS, poly I:C or Vibrio) are Locus browser tracks ("integrated into the app now as new
  tracks to see") and are scored ("include gill and immunomap in the scoring"): the chromatin layer is the unified
  peaks v3, 27 conditions (gill: immature female and male, mature male; head kidney: three in vivo treatments), from
  release 2026-11-20. The ImmunoMap's new label Bivalent_or_mixed_active/polycomb counts as weak, like Bivalent; the
  disease_resistance preset is head kidney, gill and liver, and gill and head_kidney presets were added. The release
  is built and published by the `species-data` workflow (G chose it over his Mac). Claude's display choices:
  DECISIONS #48. Release 2026-11-20 was built from the unified peaks v3; salmobase has had v5 since 2026-11-23 (gill
  and head kidney states from retrained models, the same peaks), which the next release takes.
- NCBI RefSeq is the Locus browser's default gene lane (G, 2026-11-20), one isoform per gene (the most CDS bases);
  Ensembl genes (their gene pages and Ss4R duplicates) and every isoform of both are one click away. Thin lines
  separate the tissues, the ImmunoMap and the DevMap in the Chromatin states and Regulatory elements drop-downs (G,
  2026-11-20).
- Variant scores (I16; G, 2026-11-21): ChromBPNet first, one model per AQUA-FAANG condition trained on the ATAC-seq
  read alignments (bigWigs can't be used), in its own repository run on Orion, where the data are; DeepFARM retraining
  and a CADD-like score later. The starting brief, with the data, plan and hand-back format: docs/CHROMBPNET.md.
- The public pool (DECISIONS #15; G, 2026-11-21): the Overview's public background, the benchmark's controls, the panel
  designer's and chip comparison's public candidates and the gene pages' public variants all come from the 504-fish
  panel's common sites (public MAF >= the designer's design.min_maf, 0.05): 3,436,671 sites on all 29 chromosomes in
  release 2026-11-20, instead of the 1.6M sites of the 12 AQUA-FAANG fish's VCF (70 on chromosome 10). G chose the
  common sites over a sample of all 7.6M, which are half rare. snpscore.pool.SITES; the README's "Public background pool".
- Scoring first (G, 2026-11-21): after the data to visualise, the scoring of the SNPs is the most important thing. It
  will be customisable but needs a good starting point, either real basic or learned from other functional genomics
  projects (ENCODE, GTEx, GTEx for animals). The research and the options are docs/SCORING.md, its questions for G
  DECISIONS #49-#53, the order of work TRACKER "Next" (S0-S8). The weights stay G's: the research gives an order of
  evidence, not numbers. G, 2026-11-22: long research runs one thing at a time, the most important first, so that the
  usage allowance doesn't run out mid-way; no large multi-agent runs unless G asks.

- Structural variants (G, 2026-11-24): users can score structural variants (any list of regions: an SV VCF, BED, a
  table, or pasted chrom:start-end lines) instead of SNPs, "scored in the same way, except ignoring anything that would
  require a specific base position"; "any functional data that overlaps the SV region counts towards evidence of
  function impact"; the results stay as close to the SNPs' as they can; published SVs join the known loci, with an
  example set. Built as `snpscore sv` (sv.py) and the Score page's Structural variants tab; Claude's choices are under
  Provisional and in docs/DECISIONS.md #55-#57.
- More layers of evidence (G, 2026-11-24: "Add the pike layer, and do any testing to improve this data layer. Add a
  layer of scoring based on ATAC summit distance and signal strength. Add a plan for Missense effect score (run on
  orion?)"; the weights are settled after more data is gathered): `pike` and `summit` are release layers of both
  species and terms in weights.yaml with weight 0, shown and never counted until G sets them (DECISIONS #54, #58;
  what Claude chose in building them is under Provisional); the missense plan is docs/MISSENSE.md (DECISIONS #59).
  ChromBPNet allele effects are expected from the Orion repository at the end of that week.

- Builds on Orion, releases on salmobase (G, 2026-11-24): releases are built on Orion from now on ("faster as we can
  run slurm jobs, have access to salmobase data there"), the built snapshots are uploaded to salmobase's data files,
  and the live app and installs retrieve them from there; the work continues in a chat on Orion over SSH. The brief,
  with what the next build contains and what has to be found out there: docs/ORION.md. Publishing (G, 2026-11-25:
  "We need only to make links and then rsync to salmobase server. Do a test and then if it passes upload the data"):
  `snpdata/prep/orion_publish.sh`; releases 2026-11-24 and trout-2026-11-24 are there since 2026-11-25, and serve.py
  DATA_URL, tools/get_data.sh and the demo's species.sh read them from there.
  The same day G set the build's contents (docs/ORION.md has the list): the ChromBPNet scores wait for a later
  build; the AQUA-FAANG citation becomes the published paper; a snapshot holds "only data used in the portal or
  package tool" (no benchmark files); no pool with coding consequences, no fSalSal1 tables and no missense score
  yet; the place on salmobase is `datafiles/datasets/salmo-snp/`. Asked to choose where to start it, Claude chose
  Orion over `ssh orion` from G's Mac (attached to the cloud session), with the Mac giving only the inputs that are
  not online. G's rule for all Orion work (2026-11-20): never set a SLURM time limit.

- The build after those (G, 2026-11-25): "plan the next build using the new gill salmo-chrombpnet model available,
  and the new trout immunomap data on salmobase". Built on Orion and published the same day as releases 2026-11-25
  and trout-2026-11-25, which serve.py names (docs/ORION.md "The latest build" has the plan, the checks and the
  result). G's answers that day (DECISIONS #60-#64: "go with your recommendations for all five, except the full 9+
  million public snps. We'll do it, but just not at this point"):
  - Salmon gains the layer `chrombpnet_gill`, the gill ChromBPNet model's score per SNP (the absolute log2 fold
    change of predicted accessibility, each SNP by the fold that held its chromosome out), shown and not counted.
    Every public and Synchrosmolt site (9,288,186) is to be scored later, not now. Which smaller set comes first
    is Claude's choice (Provisional below).
  - "Can we make sure we have that useful track from chrombpnet to show effects": the Locus browser's score rows
    show the direction of each effect as the scorer's own browser track does (up and red: the alt allele predicted
    more accessible; down and blue: less). A score file may carry `effect` (signed) and `percentile` columns for it.
  - A user's own SNPs outside the scored set show 'not scored' in the Table. Their cards can run the model for
    one SNP at a time (Predictions on demand, below).
  - Trout head kidney (the ImmunoMap's PBS and Vibrio) counts in the tiers, as salmon's does: the trout release is
    built from the unified peaks v6 (19 conditions).
  - `Weak_accessible_chromatin` (the trout PBS model's ATAC-only state with weak emission) is a weak state, as
    Accessible_chromatin.
  - Vibrio's summits: from a MACS2 call on its four good fish's merged reads if that is quick to make with the
    AQUA-FAANG files, else the build goes without them.

- Predictions on demand (G, 2026-11-25: "we do have the gill model online. Can we add the feature to see the effect
  with a button in the snp card? on demand from the server?"): the SNP card's 'Predict with ChromBPNet Gill' button
  runs the gill model for that one SNP where the portal runs (the demo's server, or the user's computer) and shows
  what it predicts with each allele: the direction, the log2 fold change, its rank among the model's 100,000 random
  public SNPs and the two predicted profiles. Shown, never counted. It needs numpy and onnxruntime, an optional
  extra, installed on the demo, in the container, in CI and in cloud sessions; the model's files are fetched from
  salmobase when first needed and checked. The models are listed in snpportal/lib/models.yaml, apart from the data
  releases, so it works with any salmon release. How: snpportal/README.md "Predictions on demand". Also that day: a
  release builds without a score file that is not published yet ("It might not include chrombpnet scores").

- Faster and simpler builds, tests and deploys (G, 2026-11-25: "Yes if it's changed you can fetch again. Yes reuse
  where you can to save time between releases"; then "Look for ways for in the next releases to speed up and simply
  the building, testing and deploying. From now, the builds will run on orion in a separate orion ssh chat, using a
  build plan it pulls from the repo and serve the data by syncing it to salmobase. For now we deploy to NREC, but
  soon we'll move the app to the salmobase server. There we can use the same data that's deployed on salmobase").
  Built: `snpdata fetch` downloads a salmobase file again when the server's copy has changed; a build copies the
  layers that did not change from the release before, only from one built by the same code, and writes layers in a
  full row order, so the same input gives the same bytes; the plan and the steps of a build are the first section
  of docs/ORION.md, which the Orion chat pulls; `tools/check.sh` runs the suites side by side; `salmo-snp
  download` and the demo's species.sh fetch only the files that changed; the demo's update.sh runs the new commit's
  own steps. Proposed and not built, for G to choose (DECISIONS #67, #68; docs/ORION.md "Faster and simpler builds,
  tests and deploys"): who says which release is current, and how the build chat hands back.
- Who does what, and the salmobase server (G, 2026-11-25: "we should prepare to setup the deployment option to
  salmobase server. Then we can work on feature development in this chat, and then hand off building and deploying
  releases to salmobase in the orion ssh chat"). Feature development is the cloud chat's, by pull request; the chat
  on Orion builds the data releases, publishes them, and installs and updates the portal on the salmobase server,
  each when G says. Its briefs are docs/ORION.md and docs/SALMOBASE.md: keep them complete, as that chat has
  nothing else. Prepared, and tried on a mock of the server's folders (nothing has run on the server yet): with
  `SNPSCORE_SALMOBASE` naming the server's datafiles folder the portal reads the releases, the genomes, the
  AQUA-FAANG tracks and the models' files where they are published and writes nothing there; `deploy/server.sh`
  starts it in a container or from a virtual environment; `deploy/survey.sh` reads what the server offers;
  `tools/smoke.sh` tests a running portal, `prep/release_test.sh` built releases before they are published.
  Claude's choices, PROVISIONAL (DECISIONS #65): the portal shows the releases its version names, not a newer one
  in the folder; the server builds no pool (they come from Orion with the release). The NREC demo stays until G
  says otherwise.
  How salmobase itself runs (its repository, https://gitlab.com/elixir-nmbu/salmobase, public; G pointed to it,
  2026-11-25; docs/SALMOBASE.md has it): a Docker Compose project (app, db, docs) with Apache inside the `app`
  container, its configuration copied into the image, `/docs` sent to the docs container by name, and `/snp` free.
  So the portal is a container of its own in a compose project of its own (`deploy/compose.salmobase.yml`) on
  salmobase's network, named `snp`, and one block in salmobase's Apache file sends `/snp` to it: the one change in
  salmobase's repository, kept here as `deploy/salmobase-snp.patch` for a merge request there, which G accepts (G,
  2026-11-25: "I have access to the repo and can accept the pull"; a cloud session has no GitLab login, so the
  branch is pushed from a clone that has: G's, or Orion's). Being a second Django on one host name, its cookies have names of their own and the path
  `/snp/`. Tried with salmobase's real Apache file and a stand-in for its Django. The server itself cannot be
  reached from a cloud session: what is still unknown is a table in docs/SALMOBASE.md, filled in by the survey.
  Navigation between salmobase's pages and the portal is left for later (G, 2026-11-25: "Don't worry about
  navigation to and from salmobase for now"): the portal is an address.

- Your own tier rules (G, 2026-11-26: "the option to upload a custom weights yaml (with a link to download the latest
  one to modify), and also a large pop-up box in the middle of the screen that has all the scoring factors listed with
  sliders and a text box ... to adjust like a sound mixer. Then this custom weights will be in their browser to score
  the snps or change the scored results on the fly"): the Tier rules mixer on the Score page and on every finished
  result (snpportal/snpportal/rules.py, `_mixer.html`, portal.js): a fader and a number box per evidence term, the
  tier cut-offs and the chromatin states; upload a weights.yaml, download the standard one or these. A user's rules
  live in the browser (localStorage) and go with each new list; on a results page the mixer shows the tiers the faders
  would give and Apply tiers the job again (jobs.retier). Claude's choices: DECISIONS #69-#72 (Provisional below).
  Then (G, 2026-11-26): "Make the sliders horizontal, and grouped logically" (chromatin and regulatory elements,
  genes and proteins, conservation, allele effects, tier cut-offs); and "make it able to focus the type of elements,
  like choosing certain tissues extra or to just focus on elements from a give tissue, we need that option": the
  mixer's Focus (the tissues ticked are the job's presets.all; active and weak states count there, activity only
  elsewhere as 'Active, other tissues', active_elsewhere). This amends 'All conditions' (2026-10-11) for a user's own
  rules only: the standard rules, and so the portal's default tiers, still count every condition, and a focused
  result says its focus (its header, the Overview's 'Tier for your focus: ...', its downloads).
- ChromBPNet liver, and effects first (G, 2026-11-26: "We have now a chrombpnet model for liver online, add that to
  the prediction. Reduce the prediction test, and give the result for gill and liver when the button is pressed";
  then "The ChromBPNet needs to focus on effect too, make it obvious the size difference in the atac peak, not just
  p-value significance of it"): lib/models.yaml has the liver model (salmobase datafiles chrombpnet/AtlanticSalmon/
  v1/Liver/); the card's one Predict button runs every model of the assembly, a row each: the predicted ATAC signal
  with each allele as bars on one scale, the change in percent and log2, then the rank and how peak-like the place
  is; the text is shorter. Everywhere a ChromBPNet score shows, the size of the change comes first: the Table's
  Scores column and the card ('↓ 14% · top 1%'), and the Locus browser's ticks, whose height is now the size of the
  change (|log2 fold change|, square-root scaled, full at 0.5: browser.EFFECT_FULL), not the rank. Own rules can
  count a score layer from a least change as well as a rank (variant_scores {percentile, min_score}).
- Usage documents wait for 1.0 (G, 2026-11-26: "don't update usage document yet, like the tour. Let's wait till a
  first official release to make the tour and help docs final for version 1.0"): no new tour screenshots or Help and
  README user-guide rewrites for each change until the first official release; a statement a change makes false
  (how long results are kept, say) is still corrected where it stands.

Provisional (chosen by Claude on 2026-10-06 so the prototype works; G to confirm or replace, then move to Decided):
- Active = Active_TSS, Active_enhancer. Weak = primed, poised 1/2, bivalent, flanking up/downstream, accessible chromatin,
  the ImmunoMap's bivalent or mixed active/polycomb (G, 2026-11-20) and the trout ImmunoMap's weak accessible
  chromatin (G, 2026-11-25). Not counted: repressed polycomb, quiescent, ZNF
  genes and repeats, Unknown_1 (the published models') and Unknown_2 (the first gill model's; gone from the unified
  peaks since their v4 of 2026-11-23).
- Trait presets (condition prefixes): maturation = Brain + Gonad; growth_and_fillet = Muscle + Liver;
  disease_resistance = HeadKidney + Gill + Liver (G, 2026-11-20; Liver alone before the ImmunoMap); development = the
  5 DevMap stages; plus one preset per tissue (gill and head_kidney too) and `all`.
- Weights and tier cut-offs: see weights.yaml (active 3, CDS/splice 3, constrained 2, weak/UTR/active elsewhere/Ensembl
  regulatory 1; tiers at 5, 3, 1). Ensembl regulatory features count only where AQUA-FAANG has no peak (68-86% overlap).
- Benchmark controls matched on distance to the nearest gene and public MAF (0.05 bins), not LD.
- Known loci set includes GWAS lead SNPs (six6, bco1l), not only likely-causal missense SNPs (vgll3).
- Portal roadmap v2, stage 1 (2026-10-06):
  - Known-locus window 50 kb; effect alleles vgll3 Met54Thr T / Asn323Lys C = early maturation; bco1l direction 'to verify' (strand).
  - Upload QC: assembly warning when (mismatch + strand_flip) / checked > 10%; remote genome checks a 200-SNP sample;
    duplicates = same chrom, pos, ref, alt (first kept); only chromosomes 1-29 are accepted (scaffolds rejected).
  - Locus browser default tracks (tracks.yaml defaults): ATAC, replicate R1, at most 8 rows; preset `all` = first condition
    per tissue incl. Gill and one embryo stage.
  - Palette: tier 2 #2171B5 (AA contrast), ChromHMM colours in one dict (palette.STATES) until G picks AQUA-FAANG itemRgb.
  - Portal limits: 3M SNPs, 300 MB upload, 10,000 pasted lines; results kept 30 days on a server (G, 2026-11-26: "for
    now, for a month"; 24 h before), until deleted on a local install (G, 2026-11-03); privacy statement and
    citation text need G.
- Portal roadmap v2, stages 2-3 (all in weights.yaml blocks, labelled PROVISIONAL in the UI):
  - Assay QC `assay`: 35 bp flanks, GC 0.30-0.70, repeat share <= 0.5, homopolymer <= 6, no public variant in the flanks (warn);
    LORe/blacklist/A/T-C/G warn; fail on ref mismatch, non-SNP or N. Only ~15% of public SNPs pass (salmon is ~60% repeat): revisit.
  - Panel designer `design`: 384 markers, half backbone (best SNP per genome bin), 20 kb min spacing, MAF >= 0.05, <= 2 per gene,
    <= 1 per AQUA-FAANG element, blacklist excluded; chip comparison window 10 kb, chip gaps > 1 Mb.
  - Fine-mapping `finemap`: Wakefield ABF, prior SD 0.2 (W 0.04), functional prior exp(0.5 x tier_score), 95% credible sets,
    5e-8 / 1e-5, 1 Mb clumping; one causal variant per locus and no LD reference (stated on the page).
  - Locus browser: up to 8 signal rows (R1), ATAC/H3K27ac/H3K4me3, signal and ChromHMM up to 500 kb, lanes up to 2 Mb, 4 s deadline.
  - Vendor layouts (Illumina 60 bp TOP/BOT, Axiom 35 bp, KASP 50 bp) are 'to confirm against the vendor template' (see docs/RESEARCH.md 5).
- Push 3 (2026-11-04, DECISIONS #30-#33, #35, #37): panel purposes, mixes and target sizes (weights.yaml design.presets,
  target_sizes); the chip upgrade's QC (call rate 0.95, HWE p 1e-6); probe uniqueness shown, never flagged
  (assay.max_paralog_identity: null); variant scores shown, never counted (variant_scores: {}); the data-handling
  sheet's wording; Primer3 (70-120 bp products,
  150 bp flanks) and Agena (100 bp flanks, layout unverified) files; ICSASG_v2 converted only inside blocks of EVA rs
  IDs with one offset (layers.yaml liftover); fSalSal1 from same-chromosome minimap2 asm5 alignments, mapq >= 5,
  overlapping blocks dropped (DECISIONS #37; the alignment postponed, G 2026-11-06: no fSalSal1
  tables in a release until I20).
- The gill ChromBPNet scores' first set (2026-11-25, DECISIONS #60): until every site is scored, the public and
  Synchrosmolt SNPs inside the model's own training peaks (216,592 SNPs in the gill MACS2 peaks; 216,586 scored in
  release 2026-11-25, on CPU in about an hour), where its predictions mean the most. The layer's percentile is the scorer's, among 100,000 random public
  SNPs, so 'top 1%' reads the same whichever set is scored.
- The pike and summit layers (2026-11-24, DECISIONS #54, #58; docs/SCORING.md section 6 has the tests):
  - `pike`: the bases with alignment depth to northern pike in AQUA-FAANG's salmon-trout-pike alignment, alignment
    gaps of up to 50 bp closed (layers.yaml `max_gap`; chosen from the eQTL test: SNPs in gaps of up to 50 bp are
    lead SNPs as often as aligned ones, in longer gaps not). Trout: the same rule, untested there.
  - `summit`: the summits of each condition's nf-core MACS2 peaks (merged replicates) that lie inside a robust peak;
    summits within 25 bp of each other count as one, with the values of the highest-ranked (`window`); none is
    reported beyond 500 bp (`max_distance`); strength is the rank among the condition's own peaks, because fold
    enrichment differs between conditions (median 3.1 to 6.5).
  - The summit rule (weights.yaml `summit`): within 50 bp of a summit in the strongest quarter of its condition.
    Weights: pike 0, summit 0. Recommended to G: pike 1; summit 0 until allelic imbalance or ChromBPNet can test it.
- Rainbow trout release (2026-11-12, DECISIONS #38-#45; the tier rules are salmon's weights.yaml, unchanged):
  - Layers: AQUA-FAANG unified peaks and ChromHMM states (17 conditions: brain, liver, muscle by maturity and sex, five
    embryo stages; no gonad states; from the release after trout-2026-11-24 also the ImmunoMap's head kidney after
    PBS and Vibrio, 19 conditions: Decided, 2026-11-25), blacklist, LORe regions, Ss4R duplicates (the same salmon-trout table, its Omyk
    rows) and synteny; Ensembl 116 genes, regulatory build and GERP; NCBI RefSeq models; JASPAR motifs (G's salmon
    rule); EVA release 9 rs IDs (USDA_OmykA_1.1, and Omyk_1.0 as the older assembly). No molQTL, expression, Bgee,
    genetic map or position conversion (EVA has too few rs IDs on Omyk_1.0 for blocks).
  - Public allele frequencies: the only public genome-wide set found on USDA_OmykA_1.1, the University of Maryland
    low-pass study (ENA PRJEB109732: 462 farmed fish at about 1x, imputed by Gencove, genotypes with posterior >= 0.9).
    Counted from the genotypes of its three cohorts (all 462 fish), biallelic SNPs on chromosomes with MAF
    >= 0.01 and a genotype in at least half of the fish. ENA open data; frequencies only.
  - Unplaced scaffolds are not kept, as for salmon (chromosome Y is: Decided).
  - Known loci (G asked for a catalogue from the publications, 2026-11-13; `rainbow_trout/catalog/known_loci.tsv`, 11
    rows, to vet: #38): gene regions where the published markers are not placed on USDA_OmykA_1.1 (greb1l and rock1,
    migration timing; six6, age at maturity; sdY) and QTL windows published on this assembly (BCWD resistance, 3; IHNV
    resistance, 4: those with a false-positive probability under 0.1). No SNP rows and no effect alleles yet, so
    uploads get a badge only near the four gene-region rows. The Locus browser opens at greb1l and rock1.
  - The public pool: since 2026-11-21 the salmon rule (Decided), so an even sample of at most 4,000,000 (MAX_SITES) of
    the public sites with MAF >= 0.05: 3.37M of 13.5M (before: 2,000,000 of all 18.8M).
- The tier rules in use (2026-11-26, TRACKER S7: G asked for the audit's gaps to be fixed first): the shipped
  weights.yaml, or an own copy that SNPSCORE_WEIGHTS names (`salmo-snp` sets it to the data folder's weights.yaml,
  which `salmo-snp rules --copy` makes and a package update leaves alone; snpscore's commands also take
  `--weights`). A file with a mistake is refused, each one named by its key (snpscore.check_weights; the portal's
  design and priors blocks in lib/export.check_rules): the portal does not start (system check E004) and makes no
  job. Results compare only with a public pool scored with their own rules (jobs.pool_file; otherwise the Overview
  says why it leaves the background out). A Design panel takes the rules of its first source and refuses a list
  scored with others; saved versions keep them and download with their stored tiers. Outputs name the rules
  (validation.json `rules`, Parquet key-value metadata, the pool's stamp, the benchmark's head, gwas.json).
- A user's own tier rules (2026-11-26, DECISIONS #69-#71): only the scoring blocks (weights, tiers, the state lists,
  summit, variant_scores) are theirs, the other blocks stay the portal's; a weight is at most 100, a cut-off at most
  1000, a file at most 100 KB without YAML anchors; faders 0-10 and 1-20 (rules.py). Kept in the browser only; a job
  keeps the rules it was scored with, and Apply re-tiers it through the job queue. Results with own rules compare
  with the public pool tiered again with their rules (jobs.own_background, cached in the results folder).
- Structural variants (2026-11-24, DECISIONS #55-#57): each evidence term counts once however many elements an SV
  overlaps (a 1-bp SV scores as a SNP at that base); per condition the strongest state of the peaks it overlaps; the
  most severe gene region; Ensembl regulatory only without an AQUA-FAANG peak; insertions and breakends are their
  junction's two bases; inversions and translocations count over their whole span. SV jobs have no panels, vendor
  files, priors or public-SNP comparison. Catalogue rows of `type` sv (`start`, `end` 1-based, `svtype`): salmon 6
  (Stenløkk 2022 chr18 and chr9 inversions, `local_adaptation`; Bertolotti 2020 farmed-vs-wild outliers,
  `domestication`), trout 2 (Omy05, `anadromy`; Omy17, `fillet_yield`). Examples: Known SVs, and 300 SYNTHETIC SVs
  that build makes (layers.yaml `demo_svs`).
- Coding consequences, molQTL benchmark, priors (2026-10-07): weights.synonymous = coding (3) until G decides (stop_retained
  counts as synonymous; splice donor/acceptor keep the splice weight); molQTL benchmark positives = leads with BF < 0.1;
  priors category order tier1_2, active, coding, constrained, regulatory (weights.yaml `priors`).
- Ss4R duplicates (2026-10-07): `ss4r` layer from the AQUA-FAANG SalmonTroutOrthologs.tsv on salmobase: the other
  salmon genes of a gene's clade on the paired chromosome of its syntenic quartet (any other chromosome when the quartet
  is unknown); class AORe/LORe from the clade or its neighbours; Ens106 gene ids used as Ens116 ids.
- Locus browser redesign (2026-10-08): no trait on the browser; signal tracks are the mean over a condition's replicates;
  combined tracks stack the tissue means; RNA-seq per-condition rows on a shared log scale.

Open (ask G; all collected with options and recommendations in docs/DECISIONS.md):
- Everything under Provisional.
- nf-rasqual tables: found public at github.com/datngu/nf-RASQUAL_paper (lead SNP per feature only; no licence on the repo;
  redistribution agreed, G 2026-11-10): which significance rule (paper: eigenMT BF < 0.1), which allele does pi refer to?
- Public AF: the 504-fish panel is mostly Bertolotti 2020 (PRJEB38061) wild/farmed fish plus the 12 AQUA-FAANG fish (hosting
  derived AF agreed, G 2026-11-10): how should the population be described? (docs/RESEARCH.md section 4)
- Enhancer-CNE source; vetting of the 40-row known-loci catalogue (docs/RESEARCH.md section 2).
- Data gap: the public 12-fish VCF (demo list, synthetic GWAS) has only 70 sites on chr10 and stops near 105 Mb on chr1,
  while the 504-fish panel covers both; should the demos use the 504-fish sites too? (The pool does: Decided.)
- Assay QC: flank repeat shares are mostly 0 or 1, so ~55% of public SNPs warn on 'repeat' whatever the cut-off; should fully
  soft-masked flanks warn at all? (without it ~46% pass instead of ~20%)
- Chip placement by flank (DECISIONS #34, #36): decided for now (see Decided); revisit with the first real ICSASG_v2
  manifest's counts: zero mismatches or some, and which position wins where the flank and the rs ID disagree.
- Not biology, still G's: the PyPI names, the systems the install is promised on, the Axiom assumption, what
  'genome comparison' means and the data-handling sheet's wording (DECISIONS.md #25-#30).

## Development
Tests use the small fixture in `snpdata/tests/fixture`, so they need no downloads.

```bash
conda env create -f environment.yml && conda activate salmo-snp   # conda-forge only; installs the three folders editable
bash tools/check.sh                                    # what CI runs: pyflakes, then the four suites side by side (~2 min)
(cd snpscore && python -m pytest -q)                   # or one suite at a time
(cd snpdata && python -m pytest -q)
(cd snpportal && python -m pytest -q tests && SNPPORTAL_WORKERS=0 python manage.py test snpportal --parallel)
salmo-snp serve                                        # the portal on http://127.0.0.1:8000/snp/, with the data below
salmo-snp serve --release snpdata/release/dev          # or a release you built
```
Rainbow trout (not needed for the tests: `snpdata/tests/fixture/rainbow_trout` is its fixture; `python
prep/make_fixture_trout.py` in snpdata/ re-cuts it):
```bash
cd snpdata && snpdata fetch --layers rainbow_trout/layers.yaml --data data/rainbow_trout/raw   # ~80 GB streamed, 2 GB kept
snpdata build --layers rainbow_trout/layers.yaml --data data/rainbow_trout/raw --out release/trout-2026-11-13   # ~1.5 h (motifs)
bash tools/get_data.sh trout-2026-11-25   # the published release (salmobase); a build: salmo-snp serve --release
```
Without conda: a Python 3.12 venv and `pip install -e "snpscore[test]" -e snpdata -e snpportal`, as CI. `bash tools/user_install_test.sh [python]` checks a new user's install (wheels, the
newest dependencies allowed, publish -> download -> annotate -> serve); run it after changing packaging,
dependencies or serve.py.

The data for real use (not needed for the tests): `bash tools/get_data.sh` (`salmo-snp download`: the release
serve.py RELEASE names and its genome, from salmobase), checked and copied into the salmo-snp data folder (`salmo-snp
info` says where); then `salmo-snp serve`. A new release is built and published on Orion (docs/ORION.md:
`prep/orion_build.sbatch`, then `prep/orion_publish.sh`).

## Cloud sessions (Claude Code on the web)
- Setup: `.claude/settings.json` runs `tools/cloud_setup.sh` at session start (only when CLAUDE_CODE_REMOTE=true): it
  makes `.venv` with CI's Python (3.12) and the three folders editable, with the newest versions they allow, and puts
  it on PATH. The commands above then work as written, and `bash tools/check.sh` tests what CI tests; the tests need
  no network and no data. A new user's install on other Pythons: `bash tools/user_install_test.sh python3.13` (uv
  fetches others: `uv python install 3.11`, then `$(uv python find 3.11)`). Local auto-memory doesn't reach the cloud: these
  AGENTS.md files are the memory, so record decisions and how-tos here.
- The container is reclaimed when the session ends: push before stopping. `tools/get_data.sh` (a minute or two)
  puts the release and the genome in ~/.local/share/salmo-snp, from salmobase; rerun it in each new session that
  needs them.
- Network: the default (Trusted) allows GitHub and PyPI, so the tests work. `tools/get_data.sh` (the data), the
  locus browser's AQUA-FAANG tracks and the genome URL need `salmobase.org`; rebuilding
  the data (`snpdata fetch`) needs salmobase.org, ftp.ensembl.org, jun2026.archive.ensembl.org, ftp.ebi.ac.uk,
  ftp.sra.ebi.ac.uk, ftp.ncbi.nlm.nih.gov, jaspar.elixir.no, www.bgee.org and www.biorxiv.org: in the environment's
  settings (the cloud environment menu in the session's title bar, then Edit), Network access, add them under Allowed
  domains (the Limited level; Custom in older apps) with Allow package managers left ticked, or choose a broader level
  (https://code.claude.com/docs/en/cloud-environments#network-access). This environment reached all of them on
  2026-11-04, so check before changing anything.
- GitHub: the cloud proxy refuses GitHub's GraphQL API, so `gh` works only through `gh api` (REST): no
  `gh release download` or `gh pr create`. Pull requests, their checks and comments go through the GitHub MCP tools.
- The NREC demo: https://158.39.75.9/snp/ for people (test.salmobase.org/snp/ redirected there from 2026-11-10 but
  answered 404 on 2026-11-16: use the IP until salmobase's Apache line is back); sessions use
  https://158-39-75-9.sslip.io/snp/ (the bare IP didn't connect through the session's proxy on 2026-11-04).
- EBI's FTP hosts (ftp.ebi.ac.uk, ftp.sra.ebi.ac.uk) reset about half of the connections through the session's proxy
  and serve about 1.5 MB/s per connection (2026-11-12): `snpdata fetch` asks again from where a download stopped
  (build.Resuming), but the trout cohort VCFs (7, 16 and 55 GB) took parallel ranged downloads here, processed in
  parts that are kept when done: a session's background processes die when its worker restarts or the session is
  paused, so make long steps resumable, run them with `setsid nohup`, and push often.
- Building and showing a feature (G, 2026-11-04: G sees changes before they are merged):
  1. Work on the session's branch, one feature at a time, with a test in the right suite (pytest for snpscore,
     snpdata and snpportal/lib; `snpportal/snpportal/tests*.py` for pages); `bash tools/check.sh` before each push.
  2. Try it on the real data: `bash tools/get_data.sh` once per session, then
     `DJANGO_ALLOWED_HOSTS='*' salmo-snp serve &` (still 127.0.0.1 only; the host list lets the Claude app's preview
     pane reach it) and report port 8000 to the app, so G can open the pages from the chat.
  3. Show it: `(cd snpportal && python manage.py screenshots /snp/... --out <scratchpad>/shots)` takes full-page PNGs
     of any pages (and says whether htmx and Bootstrap loaded); send them to the chat, before and after when a page
     changes. Score an example first when the page needs a job (`/snp/` POST `example=known_loci`, as
     tour_images does).
  4. Push and open (or update) the pull request; CI runs. NREC runs main only, and only what G has had deployed:
     it is public, so branches never go there.
- A ChromBPNet model's scorer runs in a cloud session (2026-11-25, for the fixture's gill scores): a scratch venv
  with numpy and onnxruntime (not project dependencies), the model's `scorer/` files and
  `training_peaks.narrowPeak.gz` from salmobase laid out as in its release, and an uncompressed FASTA of the
  chromosomes needed, cut from the bgzipped genome (`zcat` and a filter on the record names; the scorer accepts a
  subset). Run one chromosome per process: 0.3 to 0.5 s a SNP on 4 cores, about 1 GB. Its scores of the model's
  test SNPs matched the published ones to 0.00001. The portal's own predictor (snpportal/lib/predict.py, the card's
  Predict button) is checked the same way: `SNPPORTAL_MODEL_TEST=<a folder for the model's files>
  SNPPORTAL_MODEL_GENOME=<the Ssal_v3.1 fa.gz> python -m pytest -q tests/test_predict.py` in snpportal/ (it fetches
  what the folder lacks). cloud_setup.sh installs numpy and onnxruntime, so the button works in a session's portal.
- Checking pages without a browser: fetch them with curl from a `salmo-snp serve` in the background;
  `bash tools/user_install_test.sh` checks the whole user path.
- Merging (G, 2026-11-04): features collect on the session's branch and its pull request, and go live only when G
  says so in the chat, usually several at a time (no auto-merge). Claude then merges the PR with the GitHub tools,
  once CI is green; the merge deploys nothing. Before merging, say whether the PR touches the CODEOWNERS
  files (the biology) and wait for G's OK. main's protection asks for a PR and the `tests` check, not approvals (the
  PRs are under G's account, and GitHub doesn't let an author approve). After a merge, the branch restarts from main
  for the next PR. `deploy/nrec.sh` needs G's Mac (SSH key); new data releases are built and published on Orion
  (docs/ORION.md).
- The releases on the NREC demo (from salmobase since 2026-11-25): `deploy/update.sh` ends with `deploy/species.sh`,
  which fetches a release named in serve.py RELEASE or RELEASES that the VM lacks from where the data is published
  (serve.py DATA_URL: the files of its SHA256SUMS, the genome from the manifest's address, the pool from
  releases/<version>/pool/), checks it and puts it in place: a salmon release becomes /srv/snpportal/release (the one
  it replaces moving to releases/<version> for the results made with it), another species' goes in
  /srv/snpportal/releases/, which settings.py finds beside the default release. Only what changed is fetched: a
  file a release on the VM already holds with the same sha256 is copied from it, and a genome with the manifest's
  sha256 is kept. update.sh runs the steps of the commit it has just checked out (since 2026-11-25: a change to them
  takes effect in the deploy that brings it, not one deploy later). A stale pool of any species is the deploy workflow's
  (update.sh names each stale release; the job builds its pool from the release on salmobase and sends it,
  `update.sh pool <version>`). A new release, in short: build and publish it on Orion, name it in serve.py RELEASE or
  RELEASES, merge, deploy. Until 2026-11-24 the releases were GitHub data releases (data-<version>:
  `prep/github_release.sh`, `prep/release_from_demo.sh`); the `species-data` workflow still builds a release on
  GitHub's runner and sends it to the VM (`update.sh` `release <version>` -> `species.sh stdin`), but salmon can't
  build there (its Synchrosmolt input is not online).
- Deploying the NREC demo (G, 2026-11-06): only when G asks in the chat ("deploy to NREC"), usually after several
  merged pull requests; never on your own initiative, and never a branch. Run the `deploy` workflow on main:
  `gh workflow run deploy.yml --ref main` (cloud sessions, REST only: `gh api -X POST
  repos/garethgillard/salmo-snp/actions/workflows/deploy.yml/dispatches -f ref=main`), or G uses Actions > deploy >
  Run workflow. It runs the tests, then `deploy/update.sh` on the VM (~20 s), then `tools/smoke.sh` against the live
  demo (its health page, and the known-loci example scored for each species): a red last step means the demo needs
  a look. Then tell G what went live (the merges since the last deploy run), with the smoke test's lines. A new
  data release is built and published on Orion (docs/ORION.md) and the deploy installs it; a stale public pool (after a weights.yaml or snpscore
  change) is built on GitHub's runner and sent by the same workflow run (snpportal/README.md "Deploying the demo").
