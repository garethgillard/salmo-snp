# salmo-chrombpnet: starting brief (2026-11-21)

This brief starts a new repository and a new chat on Orion, NMBU's HPC cluster. Copy it into the new repository as
`AGENTS.md`, and add a `CLAUDE.md` containing the single line `@AGENTS.md`, as salmo-snp does. It holds everything
known when the work started: the goal, the decisions made, the data and where it is, the plan, and what to hand back
to salmo-snp. Keep it up to date as the work goes on: this file is the project's memory, because a new chat knows
nothing else.

Owner: NMBU. Maintainer and decision-maker: Gareth Gillard (G). Main project:
[garethgillard/salmo-snp](https://github.com/garethgillard/salmo-snp), which scores salmon SNPs and runs the web
portal. This repository only makes the scores; salmo-snp shows them.

## Goal

Score every public Atlantic salmon SNP (assembly Ssal_v3.1) for its predicted effect on chromatin accessibility in
each of the 27 AQUA-FAANG conditions. The scores come from ChromBPNet models, one per condition, trained on the
AQUA-FAANG ATAC-seq. salmo-snp then shows them as a variant-score layer (its ROADMAP I15 and I16). They feed SNP chip
and panel design, fine-mapping priors and breeding work: they rank which SNPs are likely to change regulation, and in
which tissue.

Why ChromBPNet (G, 2026-11-21, after comparing it with retraining DeepFARM and with a CADD-like score):
- It models ATAC read counts at single-base resolution.
- It removes the Tn5 enzyme's sequence bias with a separate bias model, so a variant's effect reflects the TF binding
  sites it breaks rather than the enzyme.
- It is small, yet competitive with much larger models at predicting variant effects on accessibility, including
  caQTLs.
- Its contribution scores show which base of which motif a SNP hits.
- Models transfer poorly between cell types, so one model per condition is the right design, and AQUA-FAANG has 27.

Done means:
1. Each condition's model passes ChromBPNet's own QC on held-out chromosomes. Its bias model shows no TF motifs.
2. The scores enrich for caQTL lead SNPs and agree with allelic imbalance, measurably better than salmo-snp's current
   evidence (chromatin states and the JASPAR motif rule). Details are under "Evaluation" below.
3. The score files are handed back in salmo-snp's format, with a method note, a citation and a licence (see "What to
   hand back to salmo-snp").

Not part of this work:
- No breeder data is used here: no company genotypes and no GWAS results. Those stay with G.
- salmo-snp never runs TensorFlow. All scores are precomputed here and loaded as files.
- DeepFARM retraining and a CADD-like score come later. The CADD-like score may then use these scores as features.

## Decided (G, 2026-11-21)

- ChromBPNet first; retrained DeepFARM and a CADD-like score later.
- The work runs on Orion, in its own git repository, with its own chat. The data are on Orion.
- Assembly Ssal_v3.1 with chromosomes named "1" to "29" (Ensembl naming), the same as the AQUA-FAANG data and
  salmo-snp.
- ChromBPNet needs read alignments: BAM files, fragment files or tagAlign files. The salmobase bigWigs will not work.
  - nf-core's bigWigs are fragment coverage scaled to a million reads. Each fragment is spread over its whole length
    and the counts are no longer whole numbers.
  - ChromBPNet learns from the exact Tn5 cut sites (the read ends, shifted) and their integer counts. Its bias model
    and its profile output depend on both.
  - Its training commands accept only `-ibam`, `-ifrag` or `-itag`. A bigWig is only used as the observed data for its
    QC.

## Questions for G

Each has a recommendation. Ask G before acting on any of them, and record the answer here under Decided.

1. **Repository.** Recommended: `garethgillard/salmo-chrombpnet`, private until the results are checked. Later, the
   same licence as salmo-snp: PolyForm Noncommercial 1.0.0, copyright NMBU, with CLA.md. ChromBPNet and variant-scorer
   are MIT licensed, so they can be used.
2. **Bias models.** Recommended: one bias model per lab and protocol, each checked by its QC, rather than one for all
   data. The groups are:
   - BodyMap 2020 (NMBU);
   - the re-made gill libraries of 2026 (a new protocol);
   - DevMap (Roslin);
   - ImmunoMap (Aberdeen).

   If a group's own bias model fails QC, use the BodyMap one or a pretrained ENCODE ATAC bias model, and say so.
3. **Gill.** The 2026 gill libraries are weak: median TSS enrichment 1.3, against 1.8 to 3.8 in the other tissues.
   Recommended: train them, flag them, and drop a gill model that fails QC.
4. **Which variants to score.** Recommended: the 7,572,808 public sites in salmo-snp release 2026-11-20
   (`public_af.parquet`: biallelic SNPs of the 504-fish panel, MAF at least 0.01). EVA rs IDs could be added later.
   If the scoring speed measured in the pilot makes this too slow, score only the sites within 1 kb of a unified peak.
   The scored set must be stated, because salmo-snp shows variants outside it as "not scored".
5. **Turning 27 conditions into salmo-snp layers.** salmo-snp's score format holds one score per variant per layer.
   Recommended:
   - Hand back the full table (every condition's logFC, JSD and active-allele quantile).
   - Add one layer `chrombpnet` whose score is the largest |logFC| across the 27 conditions, averaged over folds.
   - Optionally add one layer per tissue.

   G decides which layers go into a release.
6. **Weights.** The scores are shown but don't count towards tiers until G sets a weight from the benchmark
   (salmo-snp DECISIONS #33).

## Biology decisions belong to G

Don't invent thresholds, cut-offs, condition groupings or trait links: ask G, then record the answer here. ChromBPNet's
own defaults are fine to use when stated, for example its bias threshold factor or its input and output lengths
(2114 and 1000 bp).

## Data

All of it should be on Orion. The AQUA-FAANG nf-core runs were made under `/mnt/project/Aqua-Faang/` (the paths in
salmobase's design files say so). Check what is still there before downloading anything.

### Genome

- **Sequence:** Ensembl Ssal_v3.1, soft-masked:
  `https://salmobase.org/datafiles/genomes/AtlanticSalmon/Ssal_v3.1/sequence_Ensembl/Salmo_salar.Ssal_v3.1.dna_sm.toplevel.fa.gz`.
  It is also in salmo-snp's genome download: `salmo-snp-genome-Ssal_v3.1.tar` in the GitHub release `data-2026-11-20`.
  - nf-core used "the Ensembl genome of each species". Check which file the BAMs were aligned to (their `@SQ`
    header).
  - Use only chromosomes "1" to "29" in the chromosome sizes file. Leave out the unplaced scaffolds and MT.
- **Duplicated genome:** salmon had a whole-genome duplication (Ss4R), and its paired chromosome arms are still
  similar. The LORe regions (late rediploidized) are near-identical between their two copies.
  - Short reads map poorly in LORe regions, and nf-core removed multi-mapping reads.
  - Homeologous arms can leak between training and test chromosomes; see "Folds" under the plan.
  - The data: salmo-snp release tables `synteny.parquet` (174 homeologous blocks: chrom, start, end, partner, aore,
    lore) and `lore.parquet` (16 regions).

### ATAC-seq: the 27 conditions

- **Processing:** nf-core/atacseq 1.2.1, bwa, paired-end.
- **BAM files:** one per replicate, named
  `results/bwa/mergedLibrary/<group>_R<n>.mLb.clN.sorted.bam`, where `<group>` is
  `AtlanticSalmon_ATAC_<condition>`. They are filtered already ("clN": duplicates, mitochondrial and blacklisted
  reads, multi-mappers and improper pairs removed); check the pipeline's documentation for the exact filters.
- **Merged BAMs:** `results/bwa/mergedReplicate/<group>.mRp.clN.sorted.bam` has all replicates of a condition.
- **Peaks:** MACS2 narrowPeak files with summits, per condition, in `results/bwa/mergedReplicate/macs/narrowPeak/`.
- **Expected folders**, mirroring salmobase's
  [nfcore folder](https://salmobase.org/datafiles/datasets/Aqua-Faang/nfcore/AtlanticSalmon/):
  - `nfcore/AtlanticSalmon/BodyMap/ATAC/<Tissue>/results/`
  - `nfcore/AtlanticSalmon/DevMap/ATAC/results/`
  - `nfcore/AtlanticSalmon/ImmunoMap/ATAC/results/`
- **BAMs on salmobase:** salmobase still has the BodyMap and DevMap BAMs (about 2.7 GB each), but not those of the
  ImmunoMap or the 2026 gill run.
- **Raw reads in ENA:** BodyMap PRJEB47408, DevMap PRJEB51854, ImmunoMap PRJEB50077. The 2026 gill reads are not in
  ENA yet. Their FASTQs were read from `/mnt/labfiles/LiceRESIST/coho_tissue_panel/atac/fastq/`.

The condition names are salmo-snp's, and so are the output column names. The read counts are of filtered reads, both
mates, with all of a condition's replicates merged, taken from salmobase's flagstat files. Divide by two for
fragments.

| Condition (salmo-snp) | Dataset, lab | Replicates to use | Filtered reads, all replicates merged |
|---|---|---|---|
| Brain_Immature_Female | BodyMap, NMBU | R1-R3 | 160 M |
| Brain_Immature_Male | BodyMap | R1-R3 | 177 M |
| Brain_Mature_Female | BodyMap | R1-R3 | 153 M |
| Brain_Mature_Male | BodyMap | R1-R3 | 151 M |
| Gonad_Immature_Female | BodyMap | R1-R3 | 138 M |
| Gonad_Immature_Male | BodyMap | R1-R3 | 116 M |
| Gonad_Mature_Female | BodyMap | R1-R3 | 138 M |
| Gonad_Mature_Male | BodyMap | R1-R3 | 126 M |
| Liver_Immature_Female | BodyMap | R1-R3 | 139 M |
| Liver_Immature_Male | BodyMap | R1-R3 | 141 M |
| Liver_Mature_Female | BodyMap | R1-R3 | 164 M |
| Liver_Mature_Male | BodyMap | R1-R3 | 133 M |
| Muscle_Immature_Female | BodyMap | R1-R3 | 121 M |
| Muscle_Immature_Male | BodyMap | R1-R3 | 117 M |
| Muscle_Mature_Female | BodyMap | R1-R3 | 133 M |
| Muscle_Mature_Male | BodyMap | R1-R3 | 158 M |
| Gill_Immature_Female | BodyMap gill, re-made 2026 | **R2, R3 only** | 100 M (all three) |
| Gill_Immature_Male | BodyMap gill 2026 | R1-R3 | 120 M |
| Gill_Mature_Male | BodyMap gill 2026 | **R3 only** | 96 M (all three) |
| HeadKidney_invivo_pbs | ImmunoMap, Aberdeen | R1-R6 (6 fish) | 238 M |
| HeadKidney_invivo_polyIC | ImmunoMap | R1-R6 | 251 M |
| HeadKidney_invivo_vibrio | ImmunoMap | R1-R6 | 220 M |
| LateBlastulation | DevMap, Roslin | R1-R3 (embryo pools) | 80 M |
| MidGastrulation | DevMap | R1-R3 | 86 M |
| EarlySomitogenesis | DevMap | R1-R3 | 64 M |
| MidSomitogenesis | DevMap | R1-R3 | 57 M |
| LateSomitogenesis | DevMap | R1-R3 | 52 M |

Notes on the table:
- **Gill replicates:** the replicates were chosen by quality (AQUA-FAANG README, note 2). The gill merged BAMs hold
  all replicates, so merge the chosen replicate BAMs yourself.
- **Not used:**
  - gill Mature Female, which has no usable library;
  - the original 2022 gill run, which was discarded;
  - the 18 in vitro head kidney leukocyte samples, 15 of which failed QC.
- **BodyMap fish:** 12 fish, AquaGen commercial strain, sampled in September 2020 (BioSamples SAMEA9253105 to
  SAMEA9253116). The replicate numbers are these fish: Immature Female R1-R3 = J8, J9, J10; Immature Male = J15, J16,
  J18; Mature Female = A14, A15, A24; Mature Male = A19, A20, A22. The gill libraries are from the same fish.
- **ImmunoMap fish:** juvenile parr. The replicate numbers are fish numbers, the same fish in the ImmunoMap's ATAC-,
  ChIP- and RNA-seq.
- **DevMap samples:** pools of embryos, so they cannot be used for allelic imbalance.
- **Description of all of it:** the [AQUA-FAANG README](https://salmobase.org/datafiles/datasets/Aqua-Faang/README.html)
  on salmobase (updated 2026-11-20).
- **Citation:** Baudement M-O, Perojil Morata D, Gillard GB, ..., Kent MP, Lien S, Macqueen DJ. *Salmonids reveal
  principles of regulatory evolution following autotetraploidization.* bioRxiv 2025, doi:10.64898/2025.12.18.695160.

### Peaks, background and blacklist

- **Training peaks:** use the per-condition MACS2 narrowPeak files (they have summits in column 10, as ChromBPNet
  requires), with blacklisted regions removed. ChromBPNet's examples use relaxed peaks (its Preprocessing wiki says
  how). Calling them again from the merged BAMs is an option; compare the counts first.
- **Gill:** call the gill peaks again from only the chosen replicates.
- **Background regions:** make them with `chrombpnet prep nonpeaks` (GC-matched).
- **Blacklist:** the AQUA-FAANG blacklist (4,365 regions):
  `https://salmobase.org/datafiles/datasets/Aqua-Faang/blacklist/AtlanticSalmon_blacklist.bed`. It is also
  `blacklist.parquet` in the release.
- **Unified robust peaks v3:** 328,894 peaks, each with its ChromHMM state in every condition. salmo-snp scores with
  these; they are `chromatin.parquet` in the release. Use them for evaluation and for choosing variants, not for
  training.

### Variants to score

- `public_af.parquet` in salmo-snp release 2026-11-20 has the 7,572,808 sites, with columns chrom, start, end (= the
  1-based position), ref, alt, af and maf.
  - ref is the Ssal_v3.1 reference base, and salmo-snp joins on (chrom, position, ref, alt). Keep the alleles exactly
    as they are: variant-scorer's allele1 = ref and allele2 = alt, so a positive logFC means alt is more accessible.
- To get the release, download `salmo-snp-data-2026-11-20.tar` from the GitHub release `data-2026-11-20` of
  salmo-snp. salmo-snp's `tools/get_data.sh` does this through `gh api`. Or install salmo-snp and run
  `salmo-snp download`.
- The release is about 400 MB of Parquet tables. Python reads them with duckdb (`duckdb.sql("select ... from
  'public_af.parquet'")`) or pyarrow.

### Evaluation data

- **caQTL lead SNPs:** `molqtl.parquet` in the release, from nf-RASQUAL on the 12 BodyMap fish.
  - 1,057 caQTL leads (kinds 'ca') with eigenMT-adjusted p (BF) below 0.1, in brain, gonad, liver and muscle. There is
    no gill ATAC caQTL.
  - The `features` column gives the tissue, the peak and RASQUAL's pi; pi's allele direction is not confirmed.
  - The source is [datngu/nf-RASQUAL_paper](https://github.com/datngu/nf-RASQUAL_paper): Nguyen DT, Sandve SR, Lien S,
    Grønvold L. BMC Genomics 2025;26:1070.
  - Lead SNPs only, from 12 fish: low power and a winner's curse, so expect wide confidence intervals.
- **Genotypes of the 12 BodyMap fish**, for allelic imbalance:
  `https://salmobase.org/datafiles/datasets/nf-rasqual-data/12_samples_genotype_filtered_on_504.vcf.gz`.
  - They are imputed against the 504-fish panel; the DR2 INFO field gives imputation quality. The chromosomes are
    named ssa01 to ssa29, so rename them to 1 to 29.
  - Check how the VCF's sample names match J8 ... A22.
  - The ImmunoMap fish have no public genotypes. They could be called from their own reads later, as nf-RASQUAL did.
- **Known loci:** `catalog/known_loci.tsv` in the release (vgll3, six6 and others), as a sanity check, not a
  benchmark.
- **Baselines** to compare against:
  - salmo-snp's tiers and evidence: annotate the same variants with `snpscore annotate`;
  - the JASPAR motif rule (`motif.parquet`);
  - optionally DeepFARM's pretrained salmon DanQ model (github.com/datngu/DeepFARM), if it is on Ssal_v3.1.

## Plan

Work in steps. Report to G after steps 1, 4 and 6, and don't start the full run (step 5) before G has seen the pilot.

0. **Set up Orion.**
   - Find the GPU partition and its GPUs (`sinfo`, `scontrol show partition`) and the CUDA driver.
   - ChromBPNet pins TensorFlow 2.8, which needs CUDA 11.2 and cuDNN 8.1. Its README installs it with Python 3.8.
   - Use the Docker image `kundajelab/chrombpnet` through Apptainer or Singularity (with `--nv`), pinned to a digest.
     Or use a conda environment as the README says. Check that TensorFlow 2.8 runs on Orion's GPUs: very new GPUs
     may need a newer build.
   - Put large outputs on Orion's scratch or project storage, never in the git repository.
   - Never run heavy jobs on a login node: use SLURM (`sbatch`).
1. **Inventory.**
   - Find each condition's BAMs on Orion and check their reference (`@SQ` lines, chromosome names).
   - Collect QC per replicate: TSS enrichment and FRiP from nf-core's MultiQC.
   - Merge the chosen replicates per condition (`samtools merge`).
   - Write `samples.tsv`: condition, dataset, lab, BAMs used, reads and peaks. Report it to G.
2. **Inputs.**
   - Make the chromosome sizes file (1 to 29), the peaks (blacklist removed) and the background regions.
   - **Folds:** five folds of whole chromosomes (`chrombpnet prep splits`). Watch for Ss4R leakage: a test
     chromosome's homeologous arm may be in training. Use `synteny.parquet` to measure it: compare test metrics in
     LORe blocks, AORe blocks and non-duplicated sequence. If LORe test regions score clearly better, keep the
     homeologous partners of a fold's test chromosomes out of its training set.
3. **Bias models**, one per group (question 2 for G).
   - Use `chrombpnet bias pipeline` on background regions.
   - Check the QC report: the bias model should learn the Tn5 motif and no TF motifs. Look at `bw_shift_qc.png`: the
     pipeline assumes unshifted reads, which nf-core/atacseq 1.2.1 should give.
4. **Pilot.** Fold 0 for four conditions: Liver_Immature_Female, HeadKidney_invivo_pbs, Gill_Immature_Male and
   MidGastrulation.
   - Check the counts Pearson r and profile JSD on test peaks, and the motifs and footprints.
   - Score the caQTL leads and matched controls, and the allelic-imbalance sites of liver.
   - Measure training time and variant-scoring speed, and estimate the full run in GPU-hours.
   - Report to G before step 5.
5. **Full run.**
   - Train 27 conditions × 5 folds.
   - Score the variant set with variant-scorer for each fold (`variant_scoring.per_chrom.py`, `--no_hdf5`), then
     average over folds (`variant_summary_across_folds.py`).
   - Make every step resumable: one SLURM job per condition and fold, outputs kept when done.
6. **Benchmark** (see below) and **hand back to salmo-snp**.

## Evaluation

- **Model quality:** ChromBPNet's metrics on held-out chromosomes, per condition and fold: counts Pearson r and profile
  JSD in peaks, and the bias model's QC. Report them as a table.
- **caQTL enrichment:**
  - Compare the top 10% and top 1% of scores among caQTL leads with matched control SNPs. salmo-snp matches controls
    on distance to the nearest gene and on MAF bins (`snpscore benchmark`).
  - Use the model of the caQTL's own tissue, and also the largest score across conditions.
  - Compare with salmo-snp's current evidence over the same SNPs.
- **Allelic imbalance:** this is the strongest test, because it is within the same fish and the same assay, and has
  far more sites than the caQTLs.
  - At heterozygous sites of the BodyMap fish, count each allele's reads in each condition's ATAC BAMs.
  - Control for reference mapping bias, for example by remapping with WASP or by checking that both alleles map
    equally.
  - Test whether the sign of the predicted logFC agrees with the observed allelic ratio at significant sites, and how
    the two correlate.
  - Keep the test chromosomes held out: score with the fold whose test set holds the site.
- **Rules:** never tune on the caQTL or allelic-imbalance sets; they are tests. State every choice in the report.

## What to hand back to salmo-snp

1. **Score files** in salmo-snp's format (its `snpdata/README.md`, "A per-variant score"):
   - a tab-separated file, gzipped, with the header `chrom pos ref alt score`;
   - pos is 1-based, Ssal_v3.1, chromosomes "1" to "29", one row per variant;
   - alleles exactly as in `public_af.parquet`;
   - a bigger score means a stronger predicted effect, because salmo-snp ranks scores into percentiles. Use |logFC|,
     or the integrative score (`abs_logfc_x_jsd_x_active_allele_quantile`) if the benchmark favours it;
   - variants that weren't scored are left out.
2. **A layers.yaml entry** for each file, written for G to add:
   ```yaml
     - name: chrombpnet
       type: point
       format: variant_scores
       file: chrombpnet_scores.tsv.gz
       label: ChromBPNet
       description: predicted effect of the alt allele on ATAC accessibility, largest |logFC| over the 27 AQUA-FAANG conditions (mean of 5 folds); scored set = ...
       citation: ...
       licence: ...
   ```
   ROADMAP I15 also names `model`, `version` and `scored_set`; put them in the description if the build doesn't
   read them yet.
3. **The full per-condition table** (Parquet: chrom, pos, ref, alt, and per condition logfc, jsd and active-allele
   quantile), for G to choose further layers from.
4. **A method note:**
   - software and versions, image digest, peaks, folds, bias models, QC table, benchmark results, the scored set,
     and known caveats (gill quality, LORe mappability, 12-fish caQTLs);
   - citations: ChromBPNet (Pampari A, et al., bioRxiv 2024, doi:10.1101/2024.12.25.630221; check whether it is
     published by now), variant-scorer (github.com/kundajelab/variant-scorer), AQUA-FAANG (above) and nf-RASQUAL
     (above).
5. **Where the files go:** G puts them where salmo-snp's `snpdata build` reads raw data, and they go into the next
   salmo-snp release. In salmo-snp, scores are shown and never counted until G sets a weight (`weights.yaml`
   `variant_scores: {}`, DECISIONS #33).

## Rules for this repository

- **Never commit data:** no BAMs, FASTQs, genotypes, model weights or score tables. Commit code, configuration,
  `samples.tsv` and small reports (QC tables, plots). Add `.gitignore` entries for the work folders on the first day.
- **No breeder data,** not even for testing.
- **Keep it small:**
  - plain bash and `sbatch` scripts, one per step, driven by `samples.tsv` and one `config.yaml`;
  - add a workflow manager only if G agrees;
  - log each SLURM job's ID and outcome in the step's report.
- **Pin versions:** the ChromBPNet image digest or package version, variant-scorer's commit, and the genome file's
  checksum.
- **Record decisions:** put each of G's answers under Decided in this file, with the date.

## Links

- ChromBPNet: [repository](https://github.com/kundajelab/chrombpnet) (MIT),
  [wiki](https://github.com/kundajelab/chrombpnet/wiki) (preprocessing, training, output format, FAQ),
  [preprint](https://www.biorxiv.org/content/10.1101/2024.12.25.630221v1)
- variant-scorer: [repository](https://github.com/kundajelab/variant-scorer) (MIT)
- AQUA-FAANG on salmobase: [README](https://salmobase.org/datafiles/datasets/Aqua-Faang/README.html) and the
  [nf-core results](https://salmobase.org/datafiles/datasets/Aqua-Faang/nfcore/)
- DeepFARM: [preprint](https://www.biorxiv.org/content/10.1101/2025.02.21.639224) (a possible baseline)
- salmo-snp: `snpdata/README.md` ("Release format", "A per-variant score"), `docs/ROADMAP.md` (I15, I16) and
  `docs/DECISIONS.md` (#33)
