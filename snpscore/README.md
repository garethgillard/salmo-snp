# salmo-snpscore

Builds the annotation tables behind the salmobase SNP portal, and annotates any Atlantic salmon SNP list against them.
Layers so far: AQUA-FAANG chromatin states (21 conditions), genic region class, Ensembl regulatory build, GERP constrained
elements, blacklist, late-rediploidized (LORe) regions, nearest gene (with description, expression per tissue and human
and zebrafish ortholog names), known variants within 35 bp (probe flank), allele frequency in the public 504-fish panel,
nf-RASQUAL caQTL/eQTL lead SNPs, genetic map position (cM), and the known-loci catalogue. rs IDs (EVA release 9) place
SNP lists that have only rs IDs or ICSASG_v2 positions. Each SNP also gets a tier for a trait preset (rules in `weights.yaml`; provisional until agreed).
On top of that: assay designability QC, a panel designer, chip comparison, vendor exports, and GWAS summary statistics
(loci and fine-mapping with a functional prior).

## Quick start

```bash
pip install -e ".[test]"                         # the test extra adds pytest
snpscore fetch                                   # download public inputs into data/raw (~1.5 GB kept; about 7 min)
bash prep/make_demo.sh                           # portal demo inputs before build: public_50k, SYNTHETIC chip and GWAS (~20 s)
snpscore build --out release/v0.1                # standardise every layer in layers.yaml, copy weights.yaml
snpscore annotate my_snps.vcf.gz --release release/v0.1 --trait maturation -o my_snps_annotated.parquet  # or .tsv
snpscore rsid rs863754587 --release release/v0.1  # Ssal_v3.1 and ICSASG_v2 position of an rs ID
snpscore pool --release release/v0.1 --assay --memory 8GB  # public background pool: release/v0.1/pool/ (about 100 s)
snpscore benchmark --release release/v0.1 -o release/v0.1/benchmark.tsv   # known loci; controls from the pool
snpscore benchmark --release release/v0.1 --positives molqtl:ca molqtl:e --by-tissue -o release/v0.1/benchmark_molqtl.tsv
snpscore panel my_snps_annotated.parquet --release release/v0.1 --preset maturation --n 384 -o panel.parquet
snpscore export panel.parquet --release release/v0.1 --preset maturation --format illumina  # or axiom, kasp, bed, priors, ...
snpscore compare my_snps_annotated.parquet --chip my_chip.csv --release release/v0.1 --pool
python prep/make_synthetic.py chip --scale fixture  # SYNTHETIC demo chip for the tests (tests/fixture/synthetic)
snpscore gwas sumstats.tsv --release release/v0.1 --trait maturation -o gwas_out/   # loci.tsv, finemap.tsv
pytest -q                                        # tests run on the small regions in tests/fixture
```

`fetch` needs a current CA bundle on old Python/OpenSSL builds: `SSL_CERT_FILE=/path/to/cert.pem snpscore fetch`.
It streams the 975 MB 504-fish VCF and writes only its sites and frequencies (`sites_only` in layers.yaml: CHROM to
INFO with AF, MAF, AC, AN, NS; 88 MB): genotypes and sample names never reach the disk. A source with `count_gt: true`
(the Synchrosmolt parents, whose VCF has no frequencies) gets AC, AN, NS, AF and MAF counted from its genotypes as it
streams, and only those are kept.

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

## Release format (the contract with the portal)

A release is one folder, named by its version:

```
release/v0.1/
  manifest.json          see below
  <layer>.parquet        one file per layer in layers.yaml
  alias.parquet          alias (lower case), chrom, warning: every chromosome name annotate accepts (warning: shown
                         in the validation report, e.g. for HG993277.1)
  rsid.parquet           rs (BIGINT, the number), chrom, pos, ref, alt (Ssal_v3.1), v2_chrom, v2_pos, v2_ref, v2_alt
                         (ICSASG_v2; NULL unless on exactly one ICSASG_v2 line) from EVA release 9, sorted by rs, zstd;
                         rs IDs on several Ssal_v3.1 lines are left out. `snpscore.rsid(release, rs)` looks one up
  synteny.parquet        Ss4R homeologous blocks (salmobase synteny 2021-11), each block once from each side: chrom,
                         start, end (BED), partner, partner_start, partner_end, pairs, aore, lore; not annotated
  bgee.parquet           Bgee 16.0 RNA-seq per gene_id and tissue (anatomical entity): libraries, present (libraries
                         calling the gene present), median_tpm, studies; not annotated
  catalog/known_loci.tsv the known-loci catalogue (copy of benchmark/known_loci.tsv)
  weights.yaml           tier rules and trait presets; PROVISIONAL `assay`, `design` and `finemap` blocks
  tracks.yaml            track registry for the locus browser (if tracks.yaml is next to layers.yaml): `tracks`
                         (bigWigs), `chromhmm` and `peaks` (one bigBed per condition: ChromHMM segmentation, robust
                         ATAC peaks; the name field is the state)
  benchmark.tsv          optional: `snpscore benchmark` output for this release (known loci)
  benchmark_molqtl.tsv   optional: `snpscore benchmark --positives molqtl:ca molqtl:e --by-tissue` (nf-RASQUAL leads
                         vs matched controls); same columns as benchmark.tsv (see "Benchmark")
  demo/                  example inputs for the portal's buttons (layers.yaml `demo`): known_loci.tsv, public_50k.vcf
                         (dev only), chip_demo_SYNTHETIC.tsv and gwas_maturation_SYNTHETIC.tsv (dev only; made by
                         prep/make_demo.sh, the last two through prep/make_synthetic.py)
  pool/pool.parquet      optional: `snpscore pool` (see "Public background pool"); annotate never reads it
  pool/background.json   optional: the pool's shares, for the dashboard
```

`manifest.json`:
- `version`, `assembly`, `chromosomes`, `created`, `snpscore_version`, `duckdb_version`
- `chrom_sizes`: {chrom: length} of the numbered chromosomes, from the genome `.fai` (or the layers' largest end where
  that is larger, or the `.fai` lacks the chromosome, as in the test fixture). annotate's known chromosomes.
- `provisional`: the rules G still has to confirm (keys of weights.yaml and layers.yaml, e.g. `weights`, `catalog.window`)
- `genome`: `url`, and `path` of the local copy if the build machine had it (for the sequence checks); on another machine
  `SNPSCORE_GENOME` names its own copy (bgzipped, with `.fai` and `.gzi`), else the URL is read remotely
- `alias`, `rsid` (`file`, `rows`, `left_out`, `source_file`, `urls`, `citation`, `source_sha256`, `sha256`), `catalog`
  (`file`, `window`, `rows`, `sha256`), `files` (sha256 of the copied weights.yaml and tracks.yaml), `demo` ([{`file`,
  `sha256`, `synthetic`}])
- `layers`: per layer its layers.yaml settings (type, format, url, description, `licence`, `population`, ...), `urls`
  (layers with several inputs), `synthetic` (true = test or stand-in data: label it, it never counts in tiers),
  `citation`, `source_file`, `md5` and `source_sha256` of the inputs, `file` and `sha256` of the parquet, `rows`,
  `columns` (the value columns)

Every positional `<layer>.parquet` has `chrom`, `start`, `end` in BED coordinates (0-based start, end exclusive), sorted
by chrom and start, followed by the layer's value columns. `gene` layers are keyed by `gene_id` instead. Layer
parquets are zstd-compressed.

| Layer type | In the parquet | Columns annotate adds |
| --- | --- | --- |
| `interval` | non-overlapping intervals (`build` checks) | `<layer>` (true if inside an interval), `<layer>_<column>`; with `id: true` also `<layer>_id` = `chrom:start-end` of the interval (BED coordinates); with `interpolate: true` the parquet has `<column>` (value at start) and `<column>_next` (value at end) and `<layer>_<column>` is interpolated linearly at pos (3 decimals) |
| `nearest` | features, may overlap | `<layer>_<column>` of the nearest feature within `max_distance` and `<layer>_distance` (0 = inside; ties go to the lower start) |
| `count` | 1-bp features, one per position (`build` checks) | `<layer>`: number of features within `window` bp either side, not counting the SNP's own position |
| `point` | 1-bp features with `ref`, `alt`, one per position and allele pair (`build` checks) | `<layer>` (true if a feature with the SNP's alleles is at its position), `<layer>_<column>` for the columns other than ref/alt; with input alleles `<layer>_alleles` (`same`, `swapped`, `strand_flip`, `strand_flip_swapped`, `other`), and `af` and `*_af` (as 1 - af) and `ac` (as an - ac) turned to the input's alt. `other` = a different variant at the position: `<layer>` is false and every `<layer>_<column>` NULL. Without input alleles a feature at the position is a hit |
| `gene` | one row per `gene_id` (`build` checks) | `<layer>_<column>` for the SNP's nearest gene |
| `features` | overlapping features for the viewers | nothing (never annotated) |

Layers today: `chromatin` (interval with `chromatin_id`), `region`, `regbuild`, `gerp`, `blacklist`, `lore` (interval),
`gene` (nearest: strand, id, name, biotype, description), `transcripts` (features), `gene_ortholog` (gene: human,
zebrafish), `ss4r` (gene: ohnolog, ohnolog_chrom, class; AQUA-FAANG Ss4R duplicates), `flank_variants` (count, 504-fish panel sites), `public_af` (point: af, maf, ac, an, ns, aquafaang12_af,
aquafaang12_dr2), `synchrosmolt_af` (point: af, maf, ac, an, ns), `molqtl` (point: n, tissues, kinds, best_bf, features), `cm` (interval, interpolate: male, female),
`expression` (gene: one column per tissue).

- `public_af`: the nf-rasqual 504-fish reference panel (Beagle-phased; sites with HWE p < 1e-6 removed; MAF > 0.01;
  7,572,808 SNPs; NS = 504 and AN = 1008 at every site): 479 wild and farmed fish of European and North American descent
  from Bertolotti et al. 2020 (ENA PRJEB38061), the 12 AQUA-FAANG BodyMap fish and 13 others. Pooled frequencies
  hide population structure, and the 12 AQUA-FAANG fish are among the 504.
  `aquafaang12_af` and `aquafaang12_dr2` are the 12-fish VCF's INFO AF and DR2 (frequency in those 12 fish and their
  imputation quality); every 12-fish site is a panel site. vgll3 Met54Thr (25:28996360 C/T): af 0.480159 (504 fish),
  aquafaang12_af 0.67. layers.yaml records the `population` and `licence: to confirm`.
- `synchrosmolt_af`: the 108 whole-genome sequenced parents of the Synchrosmolt family experiment (NMBU; ENA
  PRJEB114348, 411,908 SNPs, Beagle-phased; chromosomes ssa01-ssa29, mapped to 1-29 with `rename_chrom` through the
  alias table). The ENA analysis also has 2,730 offspring imputed from these parents: 99.97% of their sites are
  parent sites and their frequencies follow the crosses (100 full-sib families), so only the parents are used.
  247,196 sites are also 504-fish panel sites.
- Not added: the CGD Axiom array VCF (ENA PRJEB107807) says Ssal_v3.1 but its contig lengths are Ssal_v3's (chr1
  158,978,050 bp, chr2 72,924,950 bp), EVA files it under Ssal_v3, and its 63,809 positions hit WGS panel sites at
  chance level (0.26%); its reference alleles were set from a genome, so they look right anyway. It needs a lift
  from Ssal_v3 to Ssal_v3.1 (or a v3.1 file from the submitters) first; layers.yaml takes it back with
  `id_as: probe` and `rename_chrom: true`.
- `molqtl`: nf-RASQUAL (Nguyen et al. 2025) eigenMT tables from github.com/datngu/nf-RASQUAL_paper: caQTL for Brain,
  Gonad, Liver and Muscle ATAC (Gill ATAC left out: the assay was discarded) and eQTL for Brain, Gill, Gonad, Liver and
  Muscle RNA. The tables hold one lead SNP per feature (12 fish), so this is not fine-mapping and coloc can't run on it.
  A lead counts when its eigenMT-adjusted p (`BF`) is below `max_bf` 0.1 (the paper's rule, PROVISIONAL; it gives the
  paper's counts, e.g. Liver 276 eGenes and 308 caPeaks): 2,656 SNPs, 3,585 features. `kinds` = `ca` and/or `e`;
  `features` = '; '-separated `<tissue> <kind> <feature> (BF <bf>, pi <pi>)`, best first, with genes as Ensembl 106
  IDs (all 1,175 significant ones are in Ensembl 116) and peaks as `chrom:start-end` (BED; the table's 1-based
  `Interval_N:chrom:start:end` minus 1 at the start, unverified). pi is RASQUAL's effect size; which allele it refers
  to is not confirmed. The tables' `FDR` column is a copy of `pvalue` and is not read. Weight 0 (display only);
  `licence: to confirm with the authors`.
- `cm`: Brekke et al. 2023 linkage map (AquaGen, 34,842 markers, native Ssal_v3.1, CC BY 4.0; bioRxiv supplement
  media-1.txt, whose `Mb` column holds base pairs): `cm_male` and `cm_female` interpolated between the flanking
  markers; `cm` false and NULL values before a chromosome's first and after its last marker (unmarked ends up to 12 Mb,
  e.g. the right end of chr17). The male map misses crossovers on chromosomes 2, 8 and 17 (19.5, 2.0 and 3.8 cM).

`transcripts.parquet`: `chrom, start, end, transcript_id, gene_id, gene_name, strand, part` (exon, CDS,
five_prime_UTR, three_prime_UTR), `phase, canonical` (Ensembl_canonical tag), `biotype`.

`catalog/known_loci.tsv`: `chrom, pos, id, ref, alt, locus, ensembl_gene, trait, evidence, effect, effect_allele,
effect_direction, icsasg_v2, source` (DOIs), `rsid`, `caveat`, `note`. `effect_allele` is on the Ssal_v3.1 forward
strand and filled only where the paper is unambiguous (12 rows). `trait` is one of age_at_maturity, ipn_resistance,
pd_resistance, cms_resistance, sea_lice_resistance, flesh_colour, smoltification, sex_determination. `icsasg_v2` is
the published ICSASG_v2 position, or EVA release 9's for natively Ssal_v3.1 rows. `caveat` says why a row needs care
(farmed strain only, suggestive, inferred position, not a SNP, ...).

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
see "Biology decisions" in CLAUDE.md and `provisional` in the manifest.

## Public background pool

`snpscore pool --release R [--background VCF] [--assay]` (`snpscore.pool.build_pool`) annotates every public 12-fish
site (the 1.6M sites of the 12 AQUA-FAANG fish, all of them 504-panel sites) (sequence and assay checks only with
`--assay`, which needs `--memory 8GB` for the 1.6M sites and takes about 100 s; the default run takes about 40 s with
4 threads and 4 GB) and writes, under `R/pool/`:
- `pool.parquet`: the annotate columns (tiers for the `all` preset), then `tier__<preset>` and `tier_score__<preset>`
  for every preset in weights.yaml (wide, one row per site, in genome order).
- `background.json`: `n_sites`, `rows_read`, `rejected`, `release`, `created`, `source`, `assay_checked`, `seconds`;
  categories as {key: {`n`, `share`}} whose shares sum to 1: `tiers` {preset: {tier}}, `region_class` (NULL =
  `intergenic`), `maf_histogram` (public MAF in bins of 0.05, `0.00-0.05` ... `0.45-0.50`), `assay_status` (with
  `--assay`); independent shares (share of sites): `active_by_condition` {condition: share with an active state},
  `flags` {chromatin, regbuild, gerp, blacklist, lore, public_af, strand_ambiguous}; `assay_reasons` (with `--assay`)
  {reason: {`n`, `share`}}: warn and fail reasons by name as in validation.json, share = of all sites.

## Breeder tools: assay QC, panel designer, chip comparison, exports

All defaults are PROVISIONAL and live in weights.yaml (`assay` and `design` blocks, listed in manifest `provisional`).

`snpscore.panel.design(source, preset='all', n_target, min_spacing_bp, min_maf, backbone_fraction, max_per_gene,
max_per_element, require_assay_pass, exclude_flags, must_include, weights=, chrom_sizes=, table='v', out=None,
coordinate=None)`: `source` is an annotate/pool parquet (or TSV) path, or a DuckDB connection with a table or view
`table`. Parameters left None come from `weights['design']`. Steps: must-include ids first; a backbone of
round(n_target x backbone_fraction) SNPs, the best per genome-length-proportional bin; then the rest by
`design_score` = score.tier x tier_score / max + score.assay x (pass 1, warn 0.5) + score.maf x MAF / 0.5. Every pick
keeps `min_spacing_bp` (bisect per chromosome; `coordinate(chrom, pos)` can map bp to cM later), at most
`max_per_gene` per `gene_id` and `max_per_element` per `chromatin_id`. Filters: MAF (your `maf`/`af` column, else
`public_af_maf`; unknown passes), assay (`fail` dropped, or all but `pass` with require_assay_pass), and
`exclude_flags` (columns true or > 0, e.g. blacklist, lore, strand_ambiguous, flank_variants, near_chip). Tiers come
from `tier__<preset>` when present (pool, the portal's tiers.parquet); a parquet/TSV path without them holds the
tiers of the preset it was annotated with, so its tier columns are recomputed for `preset` with `weights` (the CLI
passes the release's; `synthetic=` names the layers that never count), and a connection's `tier` is used as it is. A
TSV/CSV source reads `chrom`, `id`, `ref`, `alt` and `genome_base` as text. Ties go to the lower row number.
Returns {`params`, `hash` (same input and params -> same hash and parquet sha256), `summary`, `selected`}; `out` gets
the source columns plus `source_row` (0-based row in the source), `selection_reason` (`must_include`, `backbone`,
`functional` = tier 1-3, `fill` = tier 4), `panel_rank` and `design_score`, ordered by panel_rank. `summary`:
`n_target`, `n_selected`, `n_rows`, `n_candidates`, `reasons`, `tiers`, `per_chromosome` [{chrom, n, length}],
`spacing` {min, median, max}, `largest_gaps` [{chrom, start, end, size}] (chromosome ends included),
`region_class`, `assay_status`, `missing_must_include`, and `binding` (why fewer than n_target were found).
`snpscore panel` also writes `<out stem>.summary.json`.

`snpscore.panel.compare_sql(rel, chip, window_bp, tier='tier')` adds `on_chip`, `dist_to_chip` (bp to the nearest
chip SNP on the chromosome), `near_chip` (<= window_bp) and `novel_functional` (tier 1-2 and not near_chip).
`compare(source, chip, preset, window_bp, gap_bp, pool=, weights=, chrom_sizes=)` returns `summary` {total, shared,
novel_functional, other (the three add up to total), chip_snps, window_bp, gap_bp, gaps} and `gaps` [{chrom, start,
end, size, filler: {chrom, pos, id, tier, source: list | pool} or None}] for chip gaps over gap_bp (design
`chip_window` 10 kb and `chip_gap` 1 Mb). `read_chip(path, release, out, max_snps=CHIP_MAX)` reads any input layout
through the aliases into chrom, pos, id, and stops with InputError past `max_snps` rows (3,000,000).

`snpscore.export`: `provenance(manifest, weights, meta)` -> '# ' lines (release, manifest and weights sha256,
versions, preset, filters, panel, PROVISIONAL rules, SYNTHETIC when synthetic data contributes, the equivalent
command); `methods_text(manifest, weights, preset, release_dir, finemap=None)` -> methods paragraphs and references
(layer citations, each '; '-separated part once and 'DOI to add' where it has no doi:, GERP++, the catalogue's DOIs;
with `finemap`, the GWAS settings used, a loci and fine-mapping paragraph and Wakefield 2009); `export(source, fmt, out,
release_dir, preset, meta, include_failed, plain, flank=, template=, sidecars=True)` for tsv, parquet (provenance in
the KV metadata), bed, and the vendor layouts (`illumina`, `axiom`, `kasp`; columns per template version in
`TEMPLATES`, each 'layout to confirm against the vendor's current template'). A path source's tiers are recomputed
for `preset` as in design(). Rows keep the source's order (a connection's view is written in sorted `_row` ranges).
- Vendor files hold one row per SNP and no comment lines. `Sequence` is `<flank>[REF/ALT]<flank>` on the forward (+)
  strand, upper case, neighbouring public variants as IUPAC codes (N for indels); REF/ALT are the input's alleles
  (complemented for `strand_flip`), else the public site's. Flanks: illumina 60 bp (60-200), axiom 35 bp, kasp 50 bp
  (50-100). Columns: illumina (designstudio-2026) `Locus_Name, Target_Type, Sequence, Chromosome, Coordinate,
  Genome_Build_Version, Source, Source_Version, Sequence_Orientation, Plus_Minus, Species, Force_Infinium_I,
  Replication_Count` (iselect-2016 also available); axiom `SNP_ID, Chromosome, Position, Strand, Sequence`; kasp
  `SNP ID, Sequence, Position`. Locus names are `Ssa<chromosome>p<position>` (chromosome 0 off 1-29).
- Next to each vendor file: `<file>.provenance.txt` (the '# ' provenance, template, flank, left-out counts and panel
  warnings) and `<file>.lookup.tsv` (`locus_name, id, chrom, pos, ref, alt, topbot, allele_a, allele_b, two_probes,
  assay_status, assay_reasons, export_notes`: TOP/BOT by Illumina's rules incl. the sequence walk for A/T and C/G,
  with Illumina's A/B alleles).
- Left out: SNPs without known biallelic alleles or a full flank, and unless include_failed (then kept, with the
  reason in `export_notes`) assay fail and not_checked SNPs and, for illumina, SNPs whose TOP/BOT strand cannot be
  determined (code 103).

`--format priors` (`export.priors(source, out, release_dir, preset, meta, categories=None)`) writes a zip of
genomic-prediction prior files: `bayesrc_classes.txt` (SNP<TAB>class, no header, input order), `sets/<category>.txt`
(GFBLUP/MultiBLUP sets, which overlap), `ldak_partitions/partition1..K` (disjoint, covering every SNP), `annot.tsv`
(CHR, BP, SNP, a 0/1 column per category, tier_score, `active_<condition>` for the 21 conditions), `snp_lookup.tsv`
(only when some ids are missing: names `Ssa<chrom>p<pos>`), `README.txt` (provenance, category definitions and counts,
a methods paragraph, references) and `methods.txt`. Categories: tier1_2, active, coding (non-synonymous
`coding_consequence`, else region_class CDS), constrained, regulatory, none; a SNP's class is the first category it is
in, in the PROVISIONAL weights.yaml `priors: order`.

`bundle_zip(out, source, release_dir, preset, meta, formats, svgs)` zips the exports, manifest.json,
weights.yaml, methods.txt, provenance.txt, README.txt and figures/*.svg. `filename(fmt, release, preset, tag)` names
files `snpscore_<release>_<preset>[_<tag>][_<vendor>].<ext>`.

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

## Locus views and remote tracks

`snpscore.locus` serves the portal's locus browser, card and variant page from the release (BED coordinates; SNP `pos`
1-based): `locus(release, chrom, start, end)` returns every lane of a window up to 2 Mb (gene models, peaks with their
21 states, regbuild, GERP, blacklist, LORe, public variants, known loci); `parse_region(text, release)` reads
`25:28,980,000-29,010,000`, `ssa25:28.98-29.01Mb` or `25:28996360` (aliases through alias.parquet);
`signal(tracks, chrom, start, end, cache=)` and `segments(...)` read bigWig/bigBed tracks from `tracks.yaml` on a fixed
public tile grid (cache keys never hold a user's position; a track that misses the 4 s deadline is None);
`annotate_position(release, chrom, pos, ref, alt, trait)` annotates one position on the fly (same row as a full
annotate). Remote files are read with HTTP range requests by `snpscore.bbi` and `snpscore.fasta`, https only and
only on allowlisted hosts (`SNPSCORE_ALLOWED_HOSTS`, default salmobase.org and ftp.ensembl.org); set
`SNPSCORE_CA_FILE` when Python lacks CA certificates. `python -m snpscore.tracks` regenerates `tracks.yaml` from the
salmobase track hubs.

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
- `benchmark/known_loci.tsv` (also the release catalogue): 37 rows (36 published SNPs and the sdY gene region) across 8 traits, from
  the verified 2026-10 research catalogue (36 rows; RESEARCH.md section 2) plus the earlier six6_lead_2022. Positions
  are Ssal_v3.1 through EVA release 9 rs IDs, flank matches (`prep/lift_icsasg_v2.py`) or the paper; `caveat` flags
  the inferred ones. bco1l rs863785818: A on the + strand = red flesh (the paper's T, other strand). vgll3 Met54Thr is
  T46M on Ensembl's ENSSSAT00000230965 (aCg/aTg): the published residue numbers are Ensembl's + 8 (Asn323Lys is
  N315K there); labels keep the published numbering. Rows are still to be vetted by G.
- nf-rasqual caQTL/eQTL lead SNPs (`molqtl`, `molqtl:ca`, `molqtl:e`, `molqtl:e:Gill`, ...): the release `molqtl` layer
  (BF < `max_bf` 0.1, PROVISIONAL); the molqtl row itself is left out (true for every positive).

## Adding a layer

1. Add an entry to `layers.yaml` (name, type, format, file, url, description, citation). If the input needs heavy processing (VEP, model scores), put the script that makes it in `prep/` and leave out `url`.
2. If the file format is new, add one reader function to `READERS` in `src/snpscore/build.py`.
3. Add a slice of it to `tests/fixture` (see `prep/make_fixture.sh`; the fixture covers the vgll3, six6, bco1l and IPN
   (nae1) loci; catalogue rows on other chromosomes are rejected there as unknown chromosomes) and a check in `tests/`.
   New columns change the golden hash of the fixture annotate output: `pytest -k golden` prints the new value for
   `GOLDEN` in `tests/test_snpscore.py`; update it on purpose and say why in the commit.
4. If it should count towards tiers, add a weight in `weights.yaml` and a term in `src/snpscore/score.py`.

Progress and next steps: [TRACKER.md](TRACKER.md).
