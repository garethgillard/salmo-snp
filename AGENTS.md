# salmo-snp: notes for people and their AI assistants

Functional SNP scoring for Atlantic salmon (Ssal_v3.1): public annotation data, a scoring engine and a web portal.
Owner: NMBU; maintainer Gareth Gillard (G). The repository is public on GitHub (G, 2026-11-10); licence: PolyForm Noncommercial
1.0.0 (LICENSE); contributors accept CLA.md (CONTRIBUTING.md).
Each folder has its own AGENTS.md (CLAUDE.md imports it). docs/TRACKER.md says what's next.

## Layout
- `snpdata/`: collects the public sources and builds a versioned release (Parquet tables, manifest.json, tracks.yaml,
  the known-loci catalogue): `snpdata fetch`, `snpdata build`, `snpdata tracks`. Its README's "Release format" is the
  contract with the other two.
- `snpscore/`: scores a SNP list against a release (`snpscore annotate`), plus `rsid`, `pool`, `benchmark` and `gwas`.
  The tier rules (weights.yaml) live here, not in the release.
- `snpportal/`: the Django web portal; reads a release and calls snpscore. `snpportal/lib/` holds its plain-Python
  parts (locus data, panel design, exports, the track registry; `python -m snpportal.lib.cli panel|export|compare`).
- `docs/`: TRACKER (what's next, then what's built), DECISIONS (questions for G, with options and a recommendation),
  ROADMAP (the spec of every roadmap item), LICENSING (the licences, the CLA, commercial permission, third-party
  data and software); for reference: RESEARCH (the source research of 2026-10-06) and SIMPLIFY
  (the simplification plan of 2026-10-07, built).
- `tools/`: check.sh (what CI runs), user_install_test.sh (a new user's install), get_data.sh (the data for real use),
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
   - salmobase (the live installation, later): a container installing a tagged version behind salmobase's Apache at
     /snp/, linked from salmobase with a button (not merged into its Django), the release folder mounted;
   - breeding companies and everyone else: the local install.
   Docker and bioconda only wrap the package. Nothing depends on Docker-only features.
5. The data is hosted online (salmobase or any static web server) as one folder made by `snpdata publish --raw`:
   releases/<version>/ (the snapshot `salmo-snp download` fetches, with SHA256SUMS), releases/latest.json, and raw/
   (the input files, genome included, that `snpdata fetch --mirror` rebuilds from). Releases are versioned apart from
   the code; each salmo-snp version names the one it expects (serve.py RELEASE), and serve.py DATA_URL gets the
   folder's address once it is hosted. A copy of the folder on a disk works the same (`--from <folder>`), for
   computers without internet. Fetching public data at given locations (AQUA-FAANG signal for a viewed region) is
   fine; users' SNPs and results are never sent or stored online. Never edit a release by hand: rebuild it
   (snpscore.release.check refuses damaged ones).
6. GitHub: branches and pull requests; tests on every pull request and push to main; G reviews biology files
   (CODEOWNERS); a merge to main deploys nothing: the NREC demo is updated when G asks (the `deploy` workflow);
   a vX.Y.Z tag builds the wheels (and later the image) as a GitHub Release.

## Rules
- Never commit breeder data (genotypes, GWAS results, array manifests): not in fixtures, tests or docs either.
  `data/`, `release/` and results folders are never committed. Never edit files in snpdata/data/raw by hand.
- Keep it small: few files, little code, readable over clever. Don't add tests for every edge case.
- Dependencies: duckdb and pyyaml (plus Django for the portal). Ask G before adding any. No pandas.
- Versions (G, 2026-11-04: the newest that suit): Python 3.11 or newer (`requires-python`; 3.10 reached its end of
  life on 2026-10-01; CI, the NREC demo and cloud sessions run 3.12), Django 5.2 LTS (fixes to 2028-04-30; 6.x needs
  Python 3.12), DuckDB 2 (`duckdb>=2.0,<3`). The pyproject.toml files are the one place they are set: CI, deploys
  and cloud sessions install the newest versions those allow. DuckDB 2: SQL list lambdas are `lambda x: ...` (not
  `x -> ...`), and a half-read result blocks its connection: on a shared connection (`duckdb.sql`, `duckdb.execute`)
  use `fetchall()`, not `fetchone()`.
- Assembly Ssal_v3.1, chromosomes named "1"-"29" (as AQUA-FAANG and Ensembl). Layers use BED coordinates; SNPs use
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
- All conditions (2026-10-11, replaces 'Trait = Active in'): the portal's tiers always count all 21 conditions (Table,
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
- Synchrosmolt (2026-10-19): the 108 parents' frequencies only (the offspring were imputed from them). The CGD Axiom
  VCF (PRJEB107807) waits: its positions are not Ssal_v3.1 (snpdata/README.md "Not added").
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
    per tissue incl. Gill and one embryo stage.
  - Palette: tier 2 #2171B5 (AA contrast), ChromHMM colours in one dict (palette.STATES) until G picks AQUA-FAANG itemRgb.
  - Portal limits: 3M SNPs, 300 MB upload, 10,000 pasted lines, 24 h retention on a server (a local install keeps
    results until deleted, G 2026-11-03); privacy statement and citation text need G.
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
- ImmunoMap regions; Enhancer-CNE source; vetting of the 40-row known-loci catalogue (docs/RESEARCH.md section 2).
- Data gap: the public 12-fish VCF (pool, demo list, synthetic GWAS) has only 70 sites on chr10 and stops near 105 Mb on chr1,
  while the 504-fish panel covers both; should the pool and demos use the 504-fish sites instead?
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
bash tools/check.sh                                    # what CI runs: pyflakes, then the four suites (~4 min)
(cd snpscore && python -m pytest -q)                   # or one suite at a time
(cd snpdata && python -m pytest -q)
(cd snpportal && python -m pytest -q tests && SNPPORTAL_WORKERS=0 python manage.py test snpportal)
salmo-snp serve                                        # the portal on http://127.0.0.1:8000/snp/, with the data below
salmo-snp serve --release snpdata/release/dev          # or a release you built
```
Without conda: a Python 3.12 venv and `pip install -e "snpscore[test]" -e snpdata -e snpportal`, as CI. `bash tools/user_install_test.sh [python]` checks a new user's install (wheels, the
newest dependencies allowed, publish -> download -> annotate -> serve); run it after changing packaging,
dependencies or serve.py.

The data for real use (not needed for the tests): `bash tools/get_data.sh`, the GitHub data release named after
serve.py RELEASE (temporary hosting until salmobase), checked and copied into the salmo-snp data folder (`salmo-snp
info` says where); then `salmo-snp serve`. A new release goes up from G's Mac: `snpdata build`, then
`bash prep/github_release.sh <release>`.

## Cloud sessions (Claude Code on the web)
- Setup: `.claude/settings.json` runs `tools/cloud_setup.sh` at session start (only when CLAUDE_CODE_REMOTE=true): it
  makes `.venv` with CI's Python (3.12) and the three folders editable, with the newest versions they allow, and puts
  it on PATH. The commands above then work as written, and `bash tools/check.sh` tests what CI tests; the tests need
  no network and no data. A new user's install on other Pythons: `bash tools/user_install_test.sh python3.13` (uv
  fetches others: `uv python install 3.11`, then `$(uv python find 3.11)`). Local auto-memory doesn't reach the cloud: these
  AGENTS.md files are the memory, so record decisions and how-tos here.
- The container is reclaimed when the session ends: push before stopping. `tools/get_data.sh` (about 20 s) puts the
  release and the genome in ~/.local/share/salmo-snp; rerun it in each new session that needs them.
- Network: the default (Trusted) allows GitHub, its release downloads and PyPI, so the tests and
  `tools/get_data.sh` work. The locus browser's AQUA-FAANG tracks and the genome URL need `salmobase.org`; rebuilding
  the data (`snpdata fetch`) needs salmobase.org, ftp.ensembl.org, jun2026.archive.ensembl.org, ftp.ebi.ac.uk,
  ftp.sra.ebi.ac.uk, ftp.ncbi.nlm.nih.gov, jaspar.elixir.no, www.bgee.org and www.biorxiv.org: in the environment's
  settings (the cloud environment menu in the session's title bar, then Edit), Network access, add them under Allowed
  domains (the Limited level; Custom in older apps) with Allow package managers left ticked, or choose a broader level
  (https://code.claude.com/docs/en/cloud-environments#network-access). This environment reached all of them on
  2026-11-04, so check before changing anything.
- GitHub: the cloud proxy refuses GitHub's GraphQL API, so `gh` works only through `gh api` (REST): no
  `gh release download` or `gh pr create`. Pull requests, their checks and comments go through the GitHub MCP tools.
- The NREC demo: https://test.salmobase.org/snp/ for people (salmobase's Apache redirects it to https://158.39.75.9/snp/;
  G, 2026-11-10); sessions use https://158-39-75-9.sslip.io/snp/ (the bare IP didn't connect through the session's
  proxy on 2026-11-04).
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
- Checking pages without a browser: fetch them with curl from a `salmo-snp serve` in the background;
  `bash tools/user_install_test.sh` checks the whole user path.
- Merging (G, 2026-11-04): features collect on the session's branch and its pull request, and go live only when G
  says so in the chat, usually several at a time (no auto-merge). Claude then merges the PR with the GitHub tools,
  once CI is green; the merge deploys nothing. Before merging, say whether the PR touches the CODEOWNERS
  files (the biology) and wait for G's OK. main's protection asks for a PR and the `tests` check, not approvals (the
  PRs are under G's account, and GitHub doesn't let an author approve). After a merge, the branch restarts from main
  for the next PR. `deploy/nrec.sh` and new data releases need G's Mac (SSH key, data/raw).
- Deploying the NREC demo (G, 2026-11-06): only when G asks in the chat ("deploy to NREC"), usually after several
  merged pull requests; never on your own initiative, and never a branch. Run the `deploy` workflow on main:
  `gh workflow run deploy.yml --ref main` (cloud sessions, REST only: `gh api -X POST
  repos/garethgillard/salmo-snp/actions/workflows/deploy.yml/dispatches -f ref=main`), or G uses Actions > deploy >
  Run workflow. It runs the tests, then `deploy/update.sh` on the VM (~20 s). Then check
  https://158-39-75-9.sslip.io/snp/health/ and tell G what went live (the merges since the last deploy run). A new
  data release still needs `deploy/nrec.sh` from G's Mac; a stale public pool (after a weights.yaml or snpscore
  change) is built on GitHub's runner and sent by the same workflow run (snpportal/README.md "Deploying the demo").
