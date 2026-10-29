# salmo-snp: notes for people and their AI assistants

Functional SNP scoring for Atlantic salmon (Ssal_v3.1): public annotation data, a scoring engine and a web portal.
Owner: Gareth Gillard (G). The repository is private (invite only); licence: PolyForm Noncommercial 1.0.0 (LICENSE).
Each folder has its own AGENTS.md (CLAUDE.md imports it). docs/TRACKER.md says what's next.

## Layout
- `snpdata/`: collects the public sources and builds a versioned release (Parquet tables, manifest.json, tracks.yaml,
  the known-loci catalogue): `snpdata fetch`, `snpdata build`, `snpdata tracks`. Its README's "Release format" is the
  contract with the other two.
- `snpscore/`: scores a SNP list against a release (`snpscore annotate`), plus `rsid`, `pool`, `benchmark` and `gwas`.
  The tier rules (weights.yaml) live here, not in the release.
- `snpportal/`: the Django web portal; reads a release and calls snpscore. `snpportal/lib/` holds its plain-Python
  parts (locus data, panel design, exports, the track registry; `python -m snpportal.lib.cli panel|export|compare`).
- `docs/`: TRACKER (next steps), DECISIONS (open questions for G with options), ROADMAP, RESEARCH, SIMPLIFY.

## Plan (G, 2026-10-28)
1. One repository, three folders. snpdata builds a release once; it is published as static files on Apache, beside
   salmobase in its own folder. snpscore only scores and can change without touching the rest. snpportal is the website.
2. Dependencies point one way: snpdata -> snpscore <- snpportal (snpscore's tests build their fixture release with snpdata).
3. Scoring rules stay out of the release: weights.yaml lives in snpscore, and whatever depends on the weights (the
   public pool's tiers, `snpscore pool`) is a cache built from the release, rebuilt after a weight changes.
4. One package, one entry point (G, 2026-10-29, replacing 'Docker first'): `pip install salmo-snp` brings the portal
   and snpscore (snpscore also installs alone for pipelines; snpdata is only for whoever builds releases), and
   `salmo-snp serve` runs it: `--local` (default) on 127.0.0.1 for one user, so a SNP list never leaves the computer;
   `--public` behind a web server with 24 h deletion. Where it runs:
   - development: clone, `conda env create -f environment.yml` (conda-forge only), editable installs; tests use the
     fixture, real use downloads the published release;
   - NREC (demo and staging): git checkout, deployed automatically after the tests pass on main (update.sh);
   - salmobase (production): a container installing a tagged version, behind salmobase's Apache at /snp/, linked from
     salmobase with a button (not merged into its Django), the release folder mounted from the same server;
   - breeding companies: the package (wheel from GitHub Releases for licensees, PyPI later), release downloaded once.
   Docker and bioconda only wrap the package. Nothing depends on Docker-only features.
5. Data releases are versioned apart from the code and published once as static files (Apache, beside salmobase);
   each package version names the release it expects. Fetching public data at given locations (genome bases,
   AQUA-FAANG signal) is fine; users' SNPs and results are never stored online.
6. GitHub: branches and pull requests; tests on every pull request; G reviews biology files (CODEOWNERS); a merge to
   main deploys to NREC; a vX.Y.Z tag builds the wheels (and later the image) as a GitHub Release, which salmobase and
   company users take.

## Rules
- Never commit breeder data (genotypes, GWAS results, array manifests): not in fixtures, tests or docs either.
  `data/`, `release/` and results folders are never committed. Never edit files in snpdata/data/raw by hand.
- Keep it small: few files, little code, readable over clever. Don't add tests for every edge case.
- Dependencies: duckdb and pyyaml (plus Django for the portal). Ask G before adding any. No pandas.
- Python 3.8 until the portal's Dockerfile sets the version: no `match`, no `str.removeprefix`, no `X | Y` types; use
  `from __future__ import annotations`.
- Assembly Ssal_v3.1, chromosomes named "1"-"29" (as AQUA-FAANG and Ensembl). Layers use BED coordinates; SNPs use
  1-based `pos`; a SNP is inside an interval when start < pos <= end.
- Changes go through pull requests; G reviews anything touching the biology (CODEOWNERS).

## Biology decisions belong to G
Don't invent thresholds, weights, "active" state definitions or trait-to-tissue mappings. Ask, then record the answer below (and in docs/DECISIONS.md).

Decided:
- Repository and deployment (2026-10-28): see Plan above. Licence: PolyForm Noncommercial 1.0.0 (commercial use only
  with G's permission).
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
  allele frequencies are shown publicly; the licence questions under Open are still to confirm with their owners.
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
  - Portal limits: 3M SNPs, 300 MB upload, 10,000 pasted lines, 24 h retention; privacy statement and citation text need G.
- Portal roadmap v2, stages 2-3 (all in weights.yaml blocks, labelled PROVISIONAL in the UI):
  - Assay QC `assay`: 35 bp flanks, GC 0.30-0.70, repeat share <= 0.5, homopolymer <= 6, no public variant in the flanks (warn);
    LORe/blacklist/A/T-C/G warn; fail on ref mismatch, non-SNP or N. Only ~15% of public SNPs pass (salmon is ~60% repeat): revisit.
  - Panel designer `design`: 384 markers, half backbone (best SNP per genome bin), 20 kb min spacing, MAF >= 0.05, <= 2 per gene,
    <= 1 per AQUA-FAANG element, blacklist excluded; chip comparison window 10 kb, chip gaps > 1 Mb.
  - Fine-mapping `finemap`: Wakefield ABF, prior SD 0.2 (W 0.04), functional prior exp(0.5 x tier_score), 95% credible sets,
    5e-8 / 1e-5, 1 Mb clumping; one causal variant per locus and no LD reference (stated on the page).
  - Locus browser: up to 8 signal rows (R1), ATAC/H3K27ac/H3K4me3, signal and ChromHMM up to 500 kb, lanes up to 2 Mb, 4 s deadline.
  - Vendor layouts (Illumina 60 bp TOP/BOT, Axiom 35 bp, KASP 50 bp) are 'to confirm against the vendor template' (see docs/RESEARCH.md 5).
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
- nf-rasqual tables: found public at github.com/datngu/nf-RASQUAL_paper (lead SNP per feature only; no licence on the repo):
  may we redistribute derived rows, which significance rule (paper: eigenMT BF < 0.1), which allele does pi refer to?
- Public AF: the 504-fish panel is mostly Bertolotti 2020 (PRJEB38061) wild/farmed fish plus the 12 AQUA-FAANG fish; may we host
  derived AF, and how should the population be described? (docs/RESEARCH.md section 4)
- ImmunoMap regions; Enhancer-CNE source; vetting of the 40-row known-loci catalogue (docs/RESEARCH.md section 2).
- Data gap: the public 12-fish VCF (pool, demo list, synthetic GWAS) has only 70 sites on chr10 and stops near 105 Mb on chr1,
  while the 504-fish panel covers both; should the pool and demos use the 504-fish sites instead?
- Assay QC: flank repeat shares are mostly 0 or 1, so ~55% of public SNPs warn on 'repeat' whatever the cut-off; should fully
  soft-masked flanks warn at all? (without it ~46% pass instead of ~20%)

## Development
Tests use the small fixture in `snpdata/tests/fixture`, so they need no downloads.

```bash
python3 -m venv .venv
.venv/bin/pip install -e "snpscore[test]" -e snpdata "django>=4.2,<5" "duckdb==1.2.2"
(cd snpscore && ../.venv/bin/python -m pytest -q)
(cd snpdata && ../.venv/bin/python -m pytest -q)
(cd snpportal && ../.venv/bin/python -m pytest -q tests && SNPPORTAL_WORKERS=0 ../.venv/bin/python manage.py test snpportal)
```
