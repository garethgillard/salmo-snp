# snpscore

Annotates any Atlantic salmon SNP list against a release built by ../snpdata, and gives each SNP a tier.
Layers so far: AQUA-FAANG chromatin states (21 conditions), genic region class and the coding consequence (VEP-lite),
Ensembl regulatory build, GERP constrained elements, blacklist, late-rediploidized (LORe) regions, nearest gene (with
description, expression per tissue, human and zebrafish ortholog names and its Ss4R duplicate), known variants within
35 bp (probe flank), allele frequencies (the public 504-fish panel, the Synchrosmolt parents), TF motif changes
(JASPAR 2024, in robust ATAC peaks), nf-RASQUAL caQTL/eQTL lead SNPs, genetic map position (cM), and the known-loci
catalogue. rs IDs (EVA release 9) place SNP lists that have only rs IDs or ICSASG_v2 positions. Each SNP gets a tier
from the rules in `src/snpscore/weights.yaml` (provisional until G agrees them): for all 21 conditions by default, as
the portal always counts them, or for a trait preset (`--trait`).
On top of that: assay designability QC, the public background pool, a benchmark against known loci, and GWAS summary
statistics (loci and fine-mapping with a functional prior). The panel designer, chip comparison and vendor exports are
the portal's (../snpportal/README.md).

## Quick start

```bash
pip install -e ".[test]"                         # the test extra adds pytest; the tests also need ../snpdata
R=~/.local/share/salmo-snp/releases/2026-11-03  # a downloaded release (`salmo-snp info`), or one built with snpdata
snpscore annotate my_snps.vcf.gz --release $R --trait maturation -o my_snps_annotated.parquet  # or .tsv
snpscore rsid rs863754587 --release $R           # Ssal_v3.1 and ICSASG_v2 position of an rs ID
snpscore pool --release $R --if-stale           # public background pool, a cache of the current weights: $R/pool/
snpscore benchmark --release $R -o $R/benchmark.tsv   # known loci; controls from the pool
snpscore benchmark --release $R --positives molqtl:ca molqtl:e --by-tissue -o $R/benchmark_molqtl.tsv
snpscore gwas sumstats.tsv --release $R --trait maturation -o gwas_out/   # loci.tsv, finemap.tsv
python -m pytest -q                              # tests run on the small regions in ../snpdata/tests/fixture
```

The tier rules ship with the package (`snpscore.WEIGHTS`), so changing a weight needs no new release: rebuild the
pool (`snpscore pool`) and rescore.

## Input SNPs

`snpscore.formats.detect()` recognises the layout; `validation.json` records which one it found (`format`).

| Input | Read as |
| --- | --- |
| VCF (`.vcf`, `.vcf.gz`, a `##fileformat=VCF` line, or a `#CHROM POS ID REF ALT` header) | first 5 columns only; genotypes are never read |
| TSV/CSV/space-separated table with a header | header aliases: `CHR`/`Chromosome` -> `chrom`; `BP`/`Position`/`MapInfo`/`Physical Position` -> `pos`; `SNP`/`Name`/`Marker`/`rsid`/`Probe Set ID` -> `id`; `REF`/`A2`/`Allele A` -> `ref`; `ALT`/`A1`/`Allele B` -> `alt` |
| lines of `chrom pos [ref alt]` without a header | 2 columns = chrom pos, 3 = + id, 4 = + ref alt |
| PLINK `.bim` / `.map` | chrom, id, pos (and A1 -> alt, A2 -> ref) |
| BED (`.bed`, `.bed.gz`) | chrom, end -> pos, name -> id; only 1-bp intervals (others are rejected as `bad_pos`); `track`, `browser` and `#` lines skipped |
| Illumina-style manifest CSV | the `[Assay]` section: `Name`, `Chr`, `MapInfo`, and `SNP` `[A/G]` -> ref/alt |
| Axiom-style annotation CSV | `#%` lines skipped; `Probe Set ID`, `Chromosome`, `Physical Position`, `Allele A`, `Allele B` |
| a list of rs IDs (one per line, or a table whose id column holds rs IDs and that has no chrom and pos) | id; annotate places each through the release's `rsid.parquet` |

Columns named like `snpscore.RESERVED` (chrom, pos, id, ref, alt, p, log10p, beta, se, z, af, maf, n, a1, a2) keep their
name. Every other input column is kept as `in_<name>` (characters other than letters, digits and `_` become `_`; at most
50 such columns, the rest are dropped and listed in the report). `pos` must be a whole number (`100.5` or `2.9e7` are
rejected as `bad_pos`, not rounded). Manifest ref/alt are often not the genome's ref/alt and
manifest positions are often ICSASG_v2: the reference check below catches both.

Chromosomes may be named `25`, `chr25`, `ssa25` (any case) or by the chromosome's GenBank or RefSeq accession
(`HG993284.1`, `NC_059466.1`, with or without version; chromosomes 9, 11, 18 and 26 are `.2` versions in Ssal_v3.1:
HG993268.2, HG993270.2, HG993277.2, HG993285.2). `HG993277.1` is an older chromosome 18 sequence of another length
(84,482,589 bp, against 84,084,598): it is read as 18 with a warning in the validation report (layers.yaml
`aliases.extra`). Coordinates must be Ssal_v3.1, except that a row whose id is an rs ID is placed from EVA release 9:
- no chrom or pos: placed at the rs ID's Ssal_v3.1 position (`position_source` = `rsid`); not in the table, or on
  several Ssal_v3.1 lines: rejected as `unknown_rsid`
- pos equal to the rs ID's ICSASG_v2 position (and chrom its v2 chromosome, or a name the release doesn't know, e.g.
  `CM003303.1`) but not its Ssal_v3.1 one: moved to Ssal_v3.1 (`position_source` = `ICSASG_v2 <chrom>:<pos>` as
  given), alleles complemented where EVA's two placements are on opposite strands. EVA's Ssal_v3.1 positions are
  EVA's remaps of the older submissions.

With `--from-assembly ICSASG_v2` (`annotate(..., lift_from="icsasg_v2")`, ROADMAP I19), the positions are taken to be
ICSASG_v2 ones (chromosomes 1-29, ssaNN, chrNN, or the v2 GenBank and RefSeq accessions CM003279.1-CM003307.1 and
NC_027300.1-NC_027328.1) and converted through the release's `liftover_icsasg_v2.parquet`: collinear blocks of EVA's rs
IDs placed on both assemblies, so a position between two rs IDs that keep the same offset converts exactly
(`position_source` = `ICSASG_v2 <chrom>:<pos>`, alleles complemented on blocks of the other strand); a position outside
them is placed by its rs ID if it has one, else rejected as `liftover_unmapped`. The validation report's `liftover`
counts them.

With `--place-by-flank` (`annotate(..., place_by_flank=True)`, ROADMAP I18), the positions are taken to be on another
assembly, as in an ICSASG_v2 chip manifest: each row is placed by its flank sequence (a column `Flank`, `SourceSeq` or
`TopGenomicSeq` holding `LEFT[A/B]RIGHT`) where the 16 bases either side match a known variant site of the release's
`flank_keys.parquet` exactly, on either strand (alleles complemented when given on the other one; `position_source` =
`flank`); else by its rs ID as above; else it is rejected as `flank_not_found`. The validation report's `flank` counts
them.

Checking releases: `snpscore verify <release>` re-hashes every file against its SHA256SUMS (a damaged or edited file
is named); `snpscore diff <old> <new>` lists what changed between two releases, for a changelog.

## Annotate output

`snpscore annotate` (and `snpscore.annotate()`) writes one row per kept input SNP, in input order (TSV, or Parquet/CSV
by file extension): `chrom` (after aliases), `pos`, the other input columns, `position_source` (only when rows were
placed through rs IDs: `rsid`, `ICSASG_v2 <chrom>:<pos>` or NULL = as given), then the layer columns in layers.yaml
order, then:
- `known_locus` (id of the nearest catalogue SNP within `catalog.window` bp), `known_locus_dist`, and at its exact
  position `known_effect_allele` (in the input's alleles: complemented when only its complement is one of them) and
  `known_effect_note` (`alt`, `ref`, `alt, other strand`, `ref, other strand`, `not one of the input alleles`)
- with a genome: `genome_base`, `flank_gc`, `flank_repeat` (soft-masked share of the 35 bp either side) and `ref_check`
  (`ok`, `swapped`, `strand_flip`, `mismatch`, `not_snp`, `not_checked`: chromosome not in the genome, an N base, no
  alleles, or not in the sample of 200 SNPs checked when the genome is read remotely)
- with a genome, the assay designability QC (`snpscore.assay`, rules in the weights.yaml `assay` block, PROVISIONAL):
  `assay_flank` (35 bp + `[REF/ALT]` + 35 bp on the forward strand, all upper case: genome bases, neighbouring public
  variants as IUPAC codes (N for indels; KASP reads lower case as 'uncertain'), N past a chromosome end; alleles
  complemented for `strand_flip`, the public alleles when the input has none), `assay_gc`, `assay_repeat`
  (soft-masked share), `assay_homopolymer` (longest single-base run in either flank), `assay_n` (N bases in the
  71-mer), `assay_status` (`pass`, `warn`, `fail`, `not_checked`) and `assay_reasons` ('; '-separated, each a name
  then any numbers, NULL for pass). fail = a `fail_ref_check` value (mismatch, not_snp) or any N; warn = alleles on
  the other strand or unknown, GC outside `gc`, repeat share above `max_repeat` (0.9), a run longer than
  `max_homopolymer`, more than `max_flank_variants` public variants on both sides (one clean side is enough for Axiom;
  `flank_variants_per_side: false` counts both sides together), an A/T or C/G SNP whose flanks give no TOP/BOT strand
  (Illumina code 103), or a true `warn_flags` column (lore, blacklist, strand_ambiguous). not_checked = chromosome
  not in the genome, or a remote genome and more than 2,000 SNPs (`assay.REMOTE_MAX`; the reference check then uses
  the 200-SNP sample)
- with a genome and a `gff3_transcripts` features layer (genome local, or at most `assay.REMOTE_MAX` SNPs), the coding
  consequence (`snpscore.coding`, VEP-lite): `coding_consequence` (Sequence Ontology term as VEP writes it:
  `missense_variant`, `synonymous_variant`, `stop_gained`, `stop_lost`, `start_lost`, `stop_retained_variant`,
  `incomplete_terminal_codon_variant`, `coding_sequence_variant` (effect unknown), `splice_donor_variant`,
  `splice_acceptor_variant`; NULL outside CDS and splice sites), `coding_hgvsp` (3-letter: `p.Thr46Met`, `p.Thr46=`,
  `p.Lys352Ter`, `p.Met1?`, `p.Pro1?`, `p.Ter357ArgextTer?`), `coding_aa_pos` (Ensembl residue number),
  `coding_codons` (VEP style, `aCg/aTg`), `coding_transcript` (canonical, else longest CDS, else lowest id) and
  `coding_note` (`first of several alt alleles`, `alt allele from the public panel`, `alleles from the public panel` (a
  position only), `alleles unknown`, `alleles do not match the genome`, `not a SNP`, `genome base unknown`). Only SNPs whose `region_class` is CDS or splice_region are looked up; codons can span
  introns; swapped or strand-flipped alleles are turned to the reference first; splice donor/acceptor = the 2 intronic
  bases at internal exon ends, for SNPs in no CDS (a CDS hit on another transcript wins); any change to codon 1 is
  `start_lost`, also where the first codon is not ATG (as VEP). Checked against Ensembl VEP REST (release 116, same
  transcripts and canonical flags): 200/200 random public CDS/splice SNPs identical; 585/585 terms on an enriched sample
  (stop/start/splice, codons spanning exons, both strands, codon 1 of non-ATG starts, synthetic allele probes). VEP
  writes `extTerN` for stop_lost and `p.TerN=` for an incomplete terminal codon (here NULL). Ensembl numbers vgll3
  Met54Thr as Thr46Met (published residue numbers are Ensembl's + 8).
- `strand_ambiguous` (A/T or C/G; if the input has `ref` and `alt`)
- `tier` (1 best to 4), `tier_score`, `tier_evidence`, and `tier_terms`
  (`LIST(STRUCT(term VARCHAR, weight INTEGER))`: the weights.yaml terms that fired) for the `--trait` preset (default
  `all`). `snpscore.scored()` recomputes the tier columns for another preset.

Next to the output, `<stem>.validation.json` and `<stem>.rejects.tsv`:
- validation.json: `format`, `rows_read`, `snps_kept`, `rejected` ({reason: rows}), `unknown_chromosomes` (top 10
  names and rows), `aliases_applied` (from, to, rows), `alias_warnings` (from, to, rows, message; only when any),
  `rsid` (`placed`, `moved_from_icsasg_v2`, `alleles_complemented`, `unknown`; only when the input has rs IDs and the
  release has rsid.parquet), `duplicates_merged`, `indels`, `multiallelic`, `columns_renamed`,
  `columns_dropped`, `ref_check` ({value: rows}), `ref_check_sampled`, `assembly` (`verdict` ok / warning / not_checked,
  `checked`, `mismatch_or_flip_share`, and a `message` when (mismatch + strand_flip) / checked > 10%: probably
  ICSASG_v2 coordinates or the other strand), `assay` ({assay_status: rows}), `assay_reasons` ({reason: SNPs} over
  the warn and fail SNPs, by name without the numbers (`assay.breakdown`), most frequent first; a SNP counts once per
  reason), `coding` ({consequence: SNPs}) and `coding_notes` ({note: SNPs}).
- rejects.tsv: `row` (1 = first SNP row of the input), `chrom`, `pos`, (`id`, `ref`, `alt`), `reason`
  (`missing_chrom`, `unknown_rsid`, `bad_pos`, `unknown_chrom`, `duplicate`: same chrom, pos, ref, alt as an earlier
  row, after rs placement).

Problems with the input raise `snpscore.InputError` (a ValueError) with a message that is safe to show: no SQL, file
paths or input lines. DuckDB runs in a sandbox (`snpscore.connect(read_dirs, write_dir, threads=2,
memory_limit='2GB')`): it can read only the input's folder, the release and the output folder, write only the output
folder (which is also where it spills; a connection without write_dir never spills, so a query over memory_limit
fails rather than writing rows to DuckDB's default `.tmp`), and has no network or extension loading. Lists over
250,000 SNPs are written in input order through sorted Parquet parts in the output folder (hidden, removed
afterwards), so the 1.6M public sites annotate within the 2 GB.

A SNP at 1-based `pos` is inside an interval when `start < pos <= end`.

## Tiers

`tier_score` adds up the weights in `weights.yaml` for each kind of evidence a SNP has: an active chromatin state in a
condition of the preset, active only elsewhere, a weak state, a CDS change to the protein or of unknown effect
(`coding`), a synonymous CDS change or stop retained (`synonymous`; PROVISIONAL, weighted as `coding` until G decides; a
weights.yaml without the key falls back to the coding weight), splice region, UTR, GERP constrained element, and an
Ensembl regulatory feature where AQUA-FAANG has no peak, and an nf-RASQUAL molQTL lead (`molqtl`, weight 0: listed in
`tier_terms` and `tier_evidence`, never scored until G decides). `tier_evidence` names the coding consequence
('missense p.Thr46Met', 'synonymous p.Thr46=', 'splice donor'), or 'CDS' / 'splice region' when it was not computed.
Tiers are score cut-offs. A preset is a list of condition
prefixes (e.g. `maturation: [Brain, Gonad]`). Weights are whole numbers, so `tier_score` is always an integer. Layers
marked `synthetic: true` never count. All of this is provisional:
see "Biology decisions" in ../AGENTS.md and `provisional` in the manifest.

## Public background pool

`snpscore pool --release R [--sites aquafaang12|panel] [--background VCF] [--assay] [--if-stale]`
(`snpscore.pool.build_pool`) annotates public sites taken from the release itself: by default every site of the 12
AQUA-FAANG fish (`public_af` rows with `aquafaang12_af`, the 1.6M sites of their VCF, all of them 504-panel sites;
`--sites panel`: all 7.6M panel sites; `snpscore.pool.SITES`, DECISIONS #15), or the sites of a VCF. Sequence and assay
checks run only with `--assay`, which needs `--memory 8GB` for the 1.6M sites and takes about 100 s; the default run
takes about 35-40 s with 4 threads and 4 GB. It writes, under `R/pool/`:
- `pool.parquet`: the annotate columns (tiers for the `all` preset), then `tier__<preset>` and `tier_score__<preset>`
  for every preset in weights.yaml (wide, one row per site, in genome order).
- `background.json`: `n_sites`, `rows_read`, `rejected`, `release`, `created`, `source`, `assay_checked`, `seconds`,
  `weights_sha256` and `snpscore_version` (`stale()`: no pool, or one made for another release version, other weights
  or another snpscore; `--if-stale` builds only then, as `salmo-snp download` and `serve` and the NREC deploys do);
  categories as {key: {`n`, `share`}} whose shares sum to 1: `tiers` {preset: {tier}}, `region_class` (NULL =
  `intergenic`), `maf_histogram` (public MAF in bins of 0.05, `0.00-0.05` ... `0.45-0.50`), `assay_status` (with
  `--assay`); independent shares (share of sites): `active_by_condition` {condition: share with an active state},
  `flags` {chromatin, regbuild, gerp, blacklist, lore, public_af, strand_ambiguous}; `assay_reasons` (with `--assay`)
  {reason: {`n`, `share`}}: warn and fail reasons by name as in validation.json, share = of all sites.

## GWAS summary statistics and fine-mapping

`snpscore gwas SUMSTATS --release R --trait T -o OUT` (`snpscore.gwas.run`) reads GCTA-fastGWA, PLINK2 `.glm`, regenie,
BOLT-LMM, GEMMA or any table with a chromosome, a position and p (or LOG10P, z, or beta and se), annotates the SNPs
like any list, and writes into OUT: `sumstats.parquet` (as read), `gwas.parquet`, `gwas.json`, `result.parquet`,
`loci.tsv` and `finemap.tsv`.
- Reading (`detect`, `read`, `prepare`): one SQL pass derives `z` and `neglog10p` (-log10 p, parsed as text so
  `1e-400` gives 400), recovers z from p for p-only rows (`z_from_p`), keeps only additive tests, drops unplaced
  scaffolds and duplicates (counted in `gwas.json` `dropped`). A `# SYNTHETIC` first line marks the file synthetic.
- Harmonisation (`attach`): the statistics join annotate's rows by the sumstats row (`in_row`, written by `prepare` and
  dropped from result.parquet afterwards), so rows annotate moved from ICSASG_v2 by their rs ID keep their statistics
  at the Ssal_v3.1 position; alleles (as annotated) are turned to the Ssal_v3.1 reference (genome base, else the public
  12-fish site); a swap flips beta, z and af. `gwas.parquet`: `file_row_number, row, chrom, pos, id, ref, alt, beta,
  se, z, z_from_p, neglog10p, af, n, harmonised` (`ok`, `swapped`, `strand_flip`, `strand_flip_swapped`,
  `unchecked`, `mismatch`, `not_snp`, `no_alleles`) and `harmonised_by` (`genome`, `public sites`).
- `gwas.json`: `format`, `rows_read`, `kept`, `dropped`, `unknown_chromosomes`, `with_beta_se`, `z_from_p`,
  `lambda_gc`, `max_neglog10p`, `n_significant`, `trait_sd_estimate` (median se x sqrt(2 N af (1 - af)), as coloc
  estimates sdY; NULL without se, N and af), `synthetic`, `harmonised`, `annotated`; after `run`, `finemap` (the
  settings used, with `trait_sd_source`) and `warnings`.
- Analysis on any table with those columns plus the tiers: `lambda_gc`, `manhattan` (thinned below p 0.01), `qq` (by
  tier, region or active state), `clump` (greedy distance clumping into loci) and `finemap`: Wakefield approximate
  Bayes factors with V from se (or 1/(2N af(1-af))) and W = prior_sd^2, under a uniform prior and a functional prior
  proportional to exp(functional_lambda x tier_score); posterior inclusion probabilities per locus window and 95%
  credible sets. No LD is used.
- Defaults (`snpscore.gwas.DEFAULTS`, overridden by the weights.yaml `finemap` block, PROVISIONAL): prior_sd 0.2,
  functional_lambda 0.5, coverage 0.95, significant 5e-8, suggestive 1e-5, window 1 Mb, trait_sd 1.
  `settings(weights, report, **changes)` replaces trait_sd with the report's `trait_sd_estimate` when there is one (W is
  on the SD scale: betas in phenotype units with trait_sd 1 make every Bayes factor about 1) and records where it came
  from (`trait_sd_source`); `trait_sd_implied(report, cfg)` gives the estimate when the trait SD used differs more than
  2x (`TRAIT_SD_RATIO`) from it (else None), `trait_sd_warning(report, cfg)` the same as a sentence. Pass the settings
  to `export.methods_text(..., finemap=cfg)` (or `bundle_zip` meta `finemap`) for the fine-mapping paragraph.
- `python prep/make_synthetic.py gwas [--scale fixture|dev]` writes `gwas_maturation_SYNTHETIC.tsv` (+ `.fastGWA`,
  `.glm.linear`, `_ponly.tsv`, `_truth.tsv` with the planted causal SNPs and lambda) over public sites; the same seed
  gives the same files.

## Benchmark

`snpscore benchmark --release R [--positives FILE|molqtl[:ca|e][:Tissue] ...] [--by-tissue] [--background FILE]`
(`benchmark.benchmark_sets`) draws 10 controls per positive from the background (default `R/pool/pool.parquet`, else the
public 12-fish VCF), matched on distance to the nearest gene (6 bins) and public MAF (0.05 bins; positives without a
public MAF on distance only), seeded, never at a positive's position. Tiers and evidence terms are recomputed for the
trait (a one-tissue molQTL set uses that tissue's preset). Rows: every shared boolean layer, each weights.yaml evidence
term (`evidence = <term>`), `region_class = <class>`, `<*_consequence> = <value>` (when the background has it: pool
`--assay`) and `tier <= N`, with the share of positives and controls, enrichment, and 95% intervals (Wilson for shares,
Katz log for the enrichment; approximate, as controls are stratified). Columns: set, trait, feature, positives,
controls, share_pos, share_ctrl, enrichment, hits_pos, hits_ctrl, share_pos_low/high, share_ctrl_low/high,
enrichment_low/high, after '#' provenance lines. caQTLs share the AQUA-FAANG ATAC data with the chromatin layer, so
their chromatin enrichment is partly circular; eQTLs are the fairer test; leads come from 12 fish (winner's curse).

Positive sets:
- `../snpdata/catalog/known_loci.tsv` (the release catalogue): 40 rows (39 published SNPs and the sdY gene region) across 8 traits, from
  the verified 2026-10 research catalogue (36 rows; docs/RESEARCH.md section 2), the earlier six6_lead_2022, and the three
  chromosome 14 'hubsmolt' SNPs of the Synchrosmolt preprint (Saitou et al. 2025, Fig. 4; added 2026-10-20). Positions
  are Ssal_v3.1 through EVA release 9 rs IDs, flank matches (`prep/lift_icsasg_v2.py`) or the paper; `caveat` flags
  the inferred ones. bco1l rs863785818: A on the + strand = red flesh (the paper's T, other strand). vgll3 Met54Thr is
  T46M on Ensembl's ENSSSAT00000230965 (aCg/aTg): the published residue numbers are Ensembl's + 8 (Asn323Lys is
  N315K there); labels keep the published numbering. Rows are still to be vetted by G.
- nf-rasqual caQTL/eQTL lead SNPs (`molqtl`, `molqtl:ca`, `molqtl:e`, `molqtl:e:Gill`, ...): the release `molqtl` layer
  (BF < `max_bf` 0.1, PROVISIONAL); the molqtl row itself is left out (true for every positive).

