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
snpdata build --out release/2026-11-03           # standardise every layer in layers.yaml (versions are dates)
snpdata tracks                                   # regenerate tracks.yaml from the AQUA-FAANG trackhub (rarely needed)
python prep/make_synthetic.py chip --scale fixture  # SYNTHETIC demo chip for the tests (tests/fixture/synthetic)
python -m pytest -q                              # tests run on the small regions in tests/fixture
```

Then score the public sites once per release and weights change: `snpscore pool --release release/2026-11-03
--assay --memory 8GB` (../snpscore/README.md). A published release leaves the pool out (a cache of the current
weights): `salmo-snp download` and `serve` build it from the release's own sites.

`fetch` needs a current CA bundle on old Python/OpenSSL builds: `SSL_CERT_FILE=/path/to/cert.pem snpdata fetch`.
It streams the 975 MB 504-fish VCF and writes only its sites and frequencies (`sites_only` in layers.yaml: CHROM to
INFO with AF, MAF, AC, AN, NS; 88 MB): genotypes and sample names never reach the disk. A source with `count_gt: true`
(the Synchrosmolt parents, whose VCF has no frequencies) gets AC, AN, NS, AF and MAF counted from its genotypes as it
streams, and only those are kept.

## Rainbow trout

A release is for one species. `rainbow_trout/layers.yaml` is the registry of the rainbow trout release, on
USDA_OmykA_1.1 (the assembly of the AQUA-FAANG trout data; chromosomes 1-28, 30-32 and Y), with its `tracks.yaml`
beside it (`snpdata tracks --hub .../trackhub/RainbowTrout/ -o rainbow_trout/tracks.yaml`):

```bash
snpdata fetch --layers rainbow_trout/layers.yaml --data data/rainbow_trout/raw
snpdata build --layers rainbow_trout/layers.yaml --data data/rainbow_trout/raw --out release/trout-2026-11-13
python prep/make_fixture_trout.py       # re-cut tests/fixture_trout (chromosome 28 12.00-12.22 Mb, Y 5.95-6.05 Mb)
```

Its version carries the species (`trout-<date>`), so two species' releases never share a version. What layers.yaml
adds for a species other than salmon: `species` (key, name, latin, the chromosome `prefix` users may write, the Locus
browser's `example`, the pages' `wording`, `samples` and `searches`: the manifest carries it and the portal reads it),
`chromosome_names` (when the chromosomes are not all numbers), `rsid.older` (the older assembly of EVA's second file)
and `demo_sample` (an example list cut from a built layer). The layers are the salmon ones where the same source
exists for trout: AQUA-FAANG peaks and states (17 conditions), blacklist, LORe, Ss4R (`species: Omyk` rows of the
salmon-trout table) and synteny; Ensembl 116 genes, regulatory build and GERP; NCBI models; orthologs; JASPAR motifs;
EVA rs IDs. No molQTL, expression, Bgee, genetic map, liftover or known-loci catalogue.

`public_af` and `flank_variants` come from the one public genome-wide variant set on this assembly, ENA PRJEB109732
(University of Maryland): 462 farmed fish in three cohorts (35, 92 and 335 fish; 7, 16 and 55 GB), sequenced at about
1x and imputed by Gencove, genotypes with a posterior below 0.9 set to missing. `fetch` streams each cohort, counts AC,
AN and NS from the genotypes and keeps those only, for SNPs (`count_gt`, `snps_only`); with `pool: true`, `build`
sums the cohorts per site and keeps biallelic SNPs on chromosomes with `min_maf` and `min_an`. `flank_variants`
counts every SNP site of the first cohort's file (the imputation panel's sites, whatever their frequency).

## The fSalSal1 conversion

The conversion between Ssal_v3.1 and fSalSal1 (GCA_965601325.1, NCBI's RefSeq reference for Atlantic salmon) comes
from an alignment made once, before `snpdata build`; minimap2 (through its Python binding, mappy) is needed for this
step only. Postponed (G, 2026-11-06): releases are built without it until the data tracks move to fSalSal1 (I20);
`snpdata build` leaves the two fSalSal1 tables out while the PAF is missing. About 5 hours on 4 cores and 7 GB of
memory; less with more cores:

```bash
pip install mappy
B=https://ftp.ncbi.nlm.nih.gov/genomes/all/GCA/965/601/325/GCA_965601325.1_fSalSal1
curl -o data/raw/GCA_965601325.1_fSalSal1_genomic.fna.gz $B/GCA_965601325.1_fSalSal1_genomic.fna.gz
curl -o data/raw/GCA_965601325.1_fSalSal1_assembly_report.txt $B/GCA_965601325.1_fSalSal1_assembly_report.txt
python prep/align_assemblies.py data/raw/Salmo_salar.Ssal_v3.1.dna_sm.toplevel.fa.gz \
    data/raw/GCA_965601325.1_fSalSal1_genomic.fna.gz data/raw/GCA_965601325.1_fSalSal1_assembly_report.txt \
    data/raw/ssal31_to_fsalsal1.paf.gz data/raw/fsalsal1_names.tsv --threads 8
```

Each Ssal_v3.1 chromosome is aligned to the same fSalSal1 chromosome only (asm5 preset), so the Ss4R duplicate of a
region can't take its place; build keeps primary alignments with mapq >= 5 and drops blocks that overlap. Checked on
chromosome 25 (2026-11-06): 93.7% of Ssal_v3.1 and 92.0% of fSalSal1 in blocks; 94.5% of the public sites convert, the
fSalSal1 base is one of the two alleles at 99.97% of them, 99.66% come back to the same position.

## Publishing the data

```bash
snpdata publish release/2026-11-03 --to site --raw    # then copy site/ to the web server (e.g. rsync to salmobase)
```

`site/` is what goes online, in one folder on any static web server (Apache beside salmobase):

```
site/releases/<version>/     the snapshot `salmo-snp download` fetches (no pool/: a cache of the current weights)
site/releases/<version>/SHA256SUMS   one line per file; download checks every file against it
site/releases/latest.json    {"version": ...}: `salmo-snp download latest`
site/raw/                    with --raw: every input file of data/raw that layers.yaml names, the genome and its
                             indexes included, with SHA256SUMS: `snpdata fetch --mirror <site URL>` rebuilds from it,
                             and `salmo-snp download` takes the genome from here
```

A published version never changes: build a new version folder instead. `publish` refuses a release that
`snpscore.release.check` finds damaged (a layer missing from the manifest, a missing file), the check `serve` and
`annotate` make too; never edit a release by hand. `build` writes SHA256SUMS and the genome's sha256 into the
manifest. Before publishing, the licence of each layer must allow redistribution (layers.yaml `licence`; for the nf-RASQUAL
and 504-fish layers the authors agreed, G 2026-11-10): `--raw` redistributes the inputs as
well as the derived tables. Each salmo-snp version names the release it expects (`snpportal/snpportal/serve.py`
`RELEASE`), and `DATA_URL` there gets the site's address once it is hosted.

## Release format (the contract with snpscore and the portal)

A release is one folder, named by its version (the date it was built):

```
release/2026-11-03/
  manifest.json          see below
  <layer>.parquet        one file per layer in layers.yaml
  alias.parquet          alias (lower case), chrom, warning: every chromosome name annotate accepts (warning: shown
                         in the validation report, e.g. for HG993277.1)
  rsid.parquet           rs (BIGINT, the number), chrom, pos, ref, alt (Ssal_v3.1), v2_chrom, v2_pos, v2_ref, v2_alt
                         (ICSASG_v2; NULL unless on exactly one ICSASG_v2 line) from EVA release 9, sorted by rs, zstd;
                         rs IDs on several Ssal_v3.1 lines are left out. `snpscore.rsid(release, rs)` looks one up
  liftover_<name>.parquet  chrom, start, end (BED, on the assembly converted from), to_chrom, shift, strand (pairs for
                         EVA's): collinear blocks (a position p goes to p + shift on '+', shift - p on '-'); layers.yaml
                         `liftover`: icsasg_v2 from EVA's rs IDs on both assemblies, fsalsal1 from an alignment ("The
                         fSalSal1 conversion"). snpscore.liftover converts input positions with it (I19); optional
  liftover_to_<name>.parquet  the same, from this release's assembly to <name> (from an alignment): the exports'
                         <label>_chrom and <label>_pos columns. The manifest's `liftover` entries give each table's
                         label, direction and the chromosome names users may give (aliases)
  flank_keys.parquet     key (UBIGINT: the 16 bases either side of a site, packed 2 bits each, on the strand that sorts
                         first), chrom, pos, canonical (the genome's forward strand is the one keyed): every site of the
                         layers layers.yaml `flank_keys.sites` names, read from the genome; keys at more than one site
                         left out. snpscore.placement places manifests by their flank sequences with it (I18); optional
  synteny.parquet        Ss4R homeologous blocks (salmobase synteny 2021-11), each block once from each side: chrom,
                         start, end (BED), partner, partner_start, partner_end, pairs, aore, lore; not annotated
  bgee.parquet           Bgee 16.0 RNA-seq per gene_id and tissue (anatomical entity): libraries, present (libraries
                         calling the gene present), median_tpm, studies; not annotated
  catalog/known_loci.tsv the known-loci catalogue (copy of catalog/known_loci.tsv)
  motif.meme             the JASPAR motifs the motif layer was scored with (the evidence card redraws hits from it)
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
  SHA256SUMS             'sha256  path' of every file but pool/ (what `salmo-snp download` checks)
```

`manifest.json`:
- `version`, `assembly`, `chromosomes`, `created`, `snpscore_version`, `duckdb_version`
- `chrom_sizes`: {chrom: length} of the numbered chromosomes, from the genome `.fai` (or the layers' largest end where
  that is larger, or the `.fai` lacks the chromosome, as in the test fixture). annotate's known chromosomes.
- `provisional`: the rules G still has to confirm (layers.yaml keys, e.g. `catalog.window`; snpscore's weights.yaml lists its own)
- `genome`: `url`, `file`, `sha256` ({"fa.gz", ".fai", ".gzi"}: what `salmo-snp download` checks its copy against) and `path` of
  the local copy if the build machine had it (for the sequence checks); on another machine
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
`gene` (nearest: strand, id, name, biotype, description), `transcripts` and `transcripts_ncbi` (features),
`gene_ortholog` (gene: human, zebrafish), `ss4r` (gene: ohnolog, ohnolog_chrom, class; AQUA-FAANG Ss4R duplicates), `flank_variants` (count, 504-fish panel sites), `public_af` (point: af, maf, ac, an, ns, aquafaang12_af,
aquafaang12_dr2), `synchrosmolt_af` (point: af, maf, ac, an, ns), `motif` (point: changed, n, tfs, delta; JASPAR 2024 motif changes at
public sites in robust peaks, scored by snpscore.motif), `molqtl` (point: n, tissues, kinds, best_bf, features), `cm`
(interval, interpolate: male, female),
`expression` (gene: one column per tissue).

- `public_af`: the nf-rasqual 504-fish reference panel (Beagle-phased; sites with HWE p < 1e-6 removed; MAF > 0.01;
  7,572,808 SNPs; NS = 504 and AN = 1008 at every site): 479 wild and farmed fish of European and North American descent
  from Bertolotti et al. 2020 (ENA PRJEB38061), the 12 AQUA-FAANG BodyMap fish and 13 others. Pooled frequencies
  hide population structure, and the 12 AQUA-FAANG fish are among the 504.
  `aquafaang12_af` and `aquafaang12_dr2` are the 12-fish VCF's INFO AF and DR2 (frequency in those 12 fish and their
  imputation quality); every 12-fish site is a panel site. vgll3 Met54Thr (25:28996360 C/T): af 0.480159 (504 fish),
  aquafaang12_af 0.67. layers.yaml records the `population` and the `licence` (redistribution agreed with the authors).
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
  redistribution agreed with the authors (G, 2026-11-10).
- `cm`: Brekke et al. 2023 linkage map (AquaGen, 34,842 markers, native Ssal_v3.1, CC BY 4.0; bioRxiv supplement
  media-1.txt, whose `Mb` column holds base pairs): `cm_male` and `cm_female` interpolated between the flanking
  markers; `cm` false and NULL values before a chromosome's first and after its last marker (unmarked ends up to 12 Mb,
  e.g. the right end of chr17). The male map misses crossovers on chromosomes 2, 8 and 17 (19.5, 2.0 and 3.8 cM).

`transcripts.parquet`: `chrom, start, end, transcript_id, gene_id, gene_name, strand, part` (exon, CDS,
five_prime_UTR, three_prime_UTR), `phase, canonical` (Ensembl_canonical tag), `biotype`.
`transcripts_ncbi.parquet`: the same columns for the NCBI RefSeq models (annotation GCF_905237065.1-RS_2025_05):
`gene_id` is the NCBI GeneID, `part` exon or CDS (NCBI writes no UTR rows), `canonical` the RefSeq Select tag (none in
this annotation), `biotype` the transcript's feature type (mRNA, lnc_RNA, ...); chromosomes renamed from RefSeq accessions.

`catalog/known_loci.tsv`: `chrom, pos, id, ref, alt, locus, ensembl_gene, trait, evidence, effect, effect_allele,
effect_direction, icsasg_v2, source` (DOIs), `rsid`, `caveat`, `note`. `effect_allele` is on the Ssal_v3.1 forward
strand and filled only where the paper is unambiguous (12 rows). `trait` is one of age_at_maturity, ipn_resistance,
pd_resistance, cms_resistance, sea_lice_resistance, flesh_colour, smoltification, sex_determination. `icsasg_v2` is
the published ICSASG_v2 position, or EVA release 9's for natively Ssal_v3.1 rows. `caveat` says why a row needs care
(farmed strain only, suggestive, inferred position, not a SNP, ...).

## Adding a layer

1. Add an entry to `layers.yaml` (name, type, format, file, url, description, citation). If the input needs heavy processing (VEP, model scores), put the script that makes it in `prep/` and leave out `url`.
2. If the file format is new, add one reader function to `READERS` in `src/snpdata/build.py`.
3. Add a slice of it to `tests/fixture` (see `prep/make_fixture.sh`; the fixture covers the vgll3, six6, bco1l and IPN
   (nae1) loci; catalogue rows on other chromosomes are rejected there as unknown chromosomes) and a check in `tests/`.
   New columns change the golden hash of the fixture annotate output: `pytest -k golden` in ../snpscore prints the new
   value for `GOLDEN` in `../snpscore/tests/test_snpscore.py`; update it on purpose and say why in the commit.
4. If it should count towards tiers, add a weight in snpscore's `weights.yaml` (G decides it) and a term in `../snpscore/src/snpscore/score.py`.

**A per-variant score** (ROADMAP I15: DeepFARM, a CADD-like score) needs no code: a tab-separated file (gzip optional)
with the header `chrom pos ref alt score` (pos 1-based, Ssal_v3.1, chromosomes 1-29) and one layers.yaml entry:

```yaml
  - name: deepfarm
    type: point
    format: variant_scores
    file: deepfarm_scores.tsv.gz
    label: DeepFARM                 # how the portal names it
    description: DeepFARM regulatory-effect score of the alt allele (what the model scored, e.g. public sites in peaks)
    citation: ...
    licence: ...
```

`build` adds `percentile` (the share of the scored set with a lower score). annotate gives `deepfarm` (true when the
variant was scored), `deepfarm_score` and `deepfarm_percentile`; the portal shows them in the Table's Scores column, the
card and a locus-browser row, and the benchmark compares the top 10% and 1% with matched controls. It counts in tiers only
once G sets `variant_scores: {deepfarm: <percentile>}` and a `deepfarm` weight in snpscore's weights.yaml.

Progress and next steps: [docs/TRACKER.md](../docs/TRACKER.md).
