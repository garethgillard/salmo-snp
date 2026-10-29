# snpdata

Collects the public Atlantic salmon sources listed in `layers.yaml` and builds a **release**: one Parquet table per
layer plus alias and rs ID tables, the known-loci catalogue, the portal's examples, the signal track registry
(tracks.yaml) and manifest.json. A release holds data only (the tier rules are snpscore's), so it is built once and then
served as static files; snpscore and the portal read it.

## Quick start

```bash
pip install -e ../snpscore -e ".[test]"           # snpdata uses snpscore's motif scoring and file readers
snpdata fetch                                    # download public inputs into data/raw (~1.5 GB kept; about 7 min)
bash prep/make_demo.sh                           # portal demo inputs before build: public_50k, SYNTHETIC chip and GWAS (~20 s)
snpdata build --out release/v0.1                 # standardise every layer in layers.yaml
snpdata tracks                                   # regenerate tracks.yaml from the AQUA-FAANG trackhub (rarely needed)
python prep/make_synthetic.py chip --scale fixture  # SYNTHETIC demo chip for the tests (tests/fixture/synthetic)
python -m pytest -q                              # tests run on the small regions in tests/fixture
```

Then score the public sites once per release and weights change: `snpscore pool --release release/v0.1 --assay
--memory 8GB` (../snpscore/README.md).

`fetch` needs a current CA bundle on old Python/OpenSSL builds: `SSL_CERT_FILE=/path/to/cert.pem snpdata fetch`.
It streams the 975 MB 504-fish VCF and writes only its sites and frequencies (`sites_only` in layers.yaml: CHROM to
INFO with AF, MAF, AC, AN, NS; 88 MB): genotypes and sample names never reach the disk. A source with `count_gt: true`
(the Synchrosmolt parents, whose VCF has no frequencies) gets AC, AN, NS, AF and MAF counted from its genotypes as it
streams, and only those are kept.

## Release format (the contract with snpscore and the portal)

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
  catalog/known_loci.tsv the known-loci catalogue (copy of catalog/known_loci.tsv)
  tracks.yaml            track registry for the locus browser (if tracks.yaml is next to layers.yaml): `snpdata tracks`
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
- `provisional`: the rules G still has to confirm (layers.yaml keys, e.g. `catalog.window`; snpscore's weights.yaml lists its own)
- `genome`: `url`, and `path` of the local copy if the build machine had it (for the sequence checks); on another machine
  `SNPSCORE_GENOME` names its own copy (bgzipped, with `.fai` and `.gzi`), else the URL is read remotely
- `alias`, `rsid` (`file`, `rows`, `left_out`, `source_file`, `urls`, `citation`, `source_sha256`, `sha256`), `catalog`
  (`file`, `window`, `rows`, `sha256`), `files` (sha256 of the copied tracks.yaml), `demo` ([{`file`,
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

## Adding a layer

1. Add an entry to `layers.yaml` (name, type, format, file, url, description, citation). If the input needs heavy processing (VEP, model scores), put the script that makes it in `prep/` and leave out `url`.
2. If the file format is new, add one reader function to `READERS` in `src/snpscore/build.py`.
3. Add a slice of it to `tests/fixture` (see `prep/make_fixture.sh`; the fixture covers the vgll3, six6, bco1l and IPN
   (nae1) loci; catalogue rows on other chromosomes are rejected there as unknown chromosomes) and a check in `tests/`.
   New columns change the golden hash of the fixture annotate output: `pytest -k golden` prints the new value for
   `GOLDEN` in `tests/test_snpscore.py`; update it on purpose and say why in the commit.
4. If it should count towards tiers, add a weight in snpscore's `weights.yaml` (G decides it) and a term in `../snpscore/src/snpscore/score.py`.

Progress and next steps: [docs/TRACKER.md](../docs/TRACKER.md).
