# A missense effect score: plan (2026-11-24)

G asked for a plan for a missense effect score, to run on Orion (2026-11-24). This is the plan: what the score is
for, the options, what to run, how we would know it works in salmon, and what comes back to salmo-snp. Nothing here
is built yet. The references at the end were checked on PubMed.

## Why

Coding sequence is the one class of evidence that both of our truth sets support: eQTL lead SNPs are in coding
sequence 1.7 times as often as matched SNPs, and the lead SNPs of the age-at-maturity GWAS 2.65 times
([SCORING.md](SCORING.md) section 6). Yet every coding change scores alike today: a missense change, a synonymous
change and a stop gained all weigh 3 (DECISIONS #5). A missense effect score separates the changes a protein
tolerates from the ones it does not, at the single SNP.

What there is to score, in release 2026-11-20 (Ensembl 116 gene models on chromosomes 1 to 29):

| | |
|---|---|
| Protein-coding genes, one canonical protein each | 44,413 (24.8 million residues; median length 523) |
| All protein isoforms | 139,817 (95.0 million residues) |
| Canonical proteins longer than 1,022 residues | 5,201 (the length one pass of the ESM-1b model reads) |
| Missense SNPs among the 7.57 million public sites | 80,820 (38,453 of them with MAF at least 0.05, the public pool) |
| For comparison: synonymous, stop gained, start lost, stop lost | 62,858; 1,825; 405; 230 |
| Every possible missense change by one base, canonical proteins | about 160 million |

## Options

| Method | What it needs | For | Against |
|---|---|---|---|
| **A protein language model, zero-shot** (ESM-1b, as Brandes et al. 2023 did for every possible human missense variant; ESM-1v and ESM-2 are close relatives) | The protein sequences and one GPU. No alignment, no database | Works on any protein of any species, isoform by isoform. In human it classified about 150,000 ClinVar and HGMD missense variants better than the methods it was compared with, and predicted 28 deep mutational scans. One pass of a protein scores all its positions against all 20 amino acids, so every possible change is scored at once. Code and weights have an MIT licence | Trained on proteins of all species with nothing salmon-specific; scores are log-likelihood ratios that need a cut-off chosen on data |
| **SIFT 4G** (Vaser et al. 2016) | A protein database to search (UniRef90, tens of GB) and a GPU | The established score in livestock and fish genomics, so results compare with the literature; a known cut-off (0.05) | The database to download and search; about 2.6 s a protein by the authors' figures; scores depend on how many homologs a protein has, which for salmon includes its Ss4R duplicates |
| AlphaMissense (Cheng et al. 2023) | Its human predictions, carried over by orthology | State of the art in human | Fine-tuned on human and primate variant frequencies and published for human only; carrying scores to salmon through orthology covers conserved 1:1 residues at best. Not proposed |
| A CADD-like score | Many annotation layers and a training set | Scores non-coding variants too | A project of its own, already set after ChromBPNet (AGENTS.md, Variant scores) |

**Recommended: the protein language model first, SIFT 4G on a subset as the cross-check.** The language model is the
smallest piece of work for the widest result: no database, a few GPU hours, every isoform and every possible change.
SIFT 4G on a few thousand proteins then says whether the two methods agree in salmon, which is worth knowing before
either is trusted.

## Questions for G

1. **Which model?** ESM-1b is the one with the published genome-wide workflow (Brandes et al.). ESM-1v (five models,
   averaged) and ESM-2 (650M) cost the same order of compute. Proposed: ESM-1b as the main score, ESM-2 650M run
   beside it on the same proteins, and the better of the two on our checks kept. ProteinGym's leaderboard is the place
   to see how the models rank today before starting.
2. **Which proteins?** Proposed: every isoform (139,817), since it costs hours, with the canonical protein's score as
   the SNP's score. That is the transcript snpscore already names for a coding SNP (`coding_transcript`: the gene's
   Ensembl canonical transcript, else the longest coding sequence), so the score and the consequence describe the
   same protein.
3. **Where does the work live?** One script and one batch job. Proposed: a script in this repository
   (`snpdata/prep/`, like the assembly alignment script), run from a clone on Orion; the alternative is a folder in
   salmo-chrombpnet. A separate repository is more than it needs.
4. **Rainbow trout too?** The same script with the trout proteins. Proposed: yes, in the same run.
5. **How will it count?** A decision for later, with the data in hand (DECISIONS #59). Until then it is shown and
   counts nothing, like every variant score (weights.yaml `variant_scores: {}`).

## What to run

1. **Inputs.** The Ensembl 116 protein sequences and gene models, already sources of the release:
   `https://ftp.ensembl.org/pub/release-116/fasta/salmo_salar/pep/Salmo_salar.Ssal_v3.1.pep.all.fa.gz` and the GFF3
   that layers.yaml names (trout: `oncorhynchus_mykiss`, USDA_OmykA_1.1). The model weights are downloaded once
   (`fair-esm`, or the same models from Hugging Face); Orion's compute nodes may need them copied in.
2. **Score.** For each protein, one pass of the model on the unchanged sequence gives, at every position, the
   log-likelihood of each of the 20 amino acids. A change's score is the log-likelihood ratio of the new amino acid
   to the reference one: negative when the model finds the new one less likely there. Proteins longer than 1,022
   residues are read in overlapping windows and the windows combined, as Brandes et al. describe. Output: one table
   per species of protein, position, reference amino acid and the 20 scores. About 95 million residues for salmon:
   a few GPU hours on one card with 16 GB or more.
3. **Map to SNPs.** For every possible single-base change in a coding sequence, the amino-acid change and its score,
   keyed by chromosome, position, reference and alternative allele, for the canonical protein. snpscore's coding
   module (`snpscore.coding`) already turns a SNP into its protein change, so the mapping is a join; its output for
   the public sites is the check that both agree.
4. **Cross-check.** SIFT 4G on a subset (for example the 838 protein-coding genes of chromosome 25), and the rank
   correlation of the two scores.

## How we would know it works in salmon

In the order of how much each can show:

1. **Rare variants.** Changes that harm a protein are kept rare by selection. Of the public missense SNPs 52.4% are
   rare (MAF under 0.05), against 46.0% of the synonymous ones and 55.1% of the stops gained. A score that works
   splits the missense SNPs: the share that is rare should rise step by step from the tenth it calls most tolerated to
   the tenth it calls most damaging, from near the synonymous figure to the stop-gained one or above. 80,820 SNPs
   make this a well-powered test, and it uses nothing the model was trained on.
2. **Missing variants.** Of all possible missense changes, the share seen among the 504 fish should fall as the
   predicted damage rises.
3. **Agreement with SIFT 4G** on the subset.
4. **Known cases**, as a look and not a test: the vgll3 missense SNPs (Met54Thr, Asn323Lys) and the other missense
   SNPs of the known-loci catalogue. Variants selected for a trait need not look damaging, so a tolerated call
   there is no failure.

A score that fails the first check is not handed over.

## What comes back to salmo-snp

1. **The score for the public missense SNPs**, as a variant-score file, the format the release already reads
   (snpdata/README.md, "A per-variant score"): tab-separated, header `chrom pos ref alt score`. The score is the
   log-likelihood ratio with its sign turned, so that higher means more damaging, as the format expects (the layer's
   percentile is the share of scored variants with a lower score). One layers.yaml entry adds it:

   ```yaml
     - name: missense
       type: point
       format: variant_scores
       file: missense_esm1b.tsv.gz
       label: Missense effect
       description: Predicted effect of the amino-acid change on the protein (ESM-1b log-likelihood ratio, sign turned; higher = less tolerated), for missense SNPs in the canonical protein
       citation: ...
       licence: ...
   ```

   The portal then shows it in the Table's Scores column, on the card and in the Locus browser, with no new code.
2. **The full tables** (every position of every protein), kept on Orion and on salmobase. From them a second file
   can hold every possible missense change (about 160 million rows, an optional download of several hundred MB), so
   that a breeder's own coding SNPs are scored too. Whether to ship that is a later choice.
3. **A short report**: the model and its version, the commands, the run time, and the four checks above with their
   numbers.

Hosting follows the ChromBPNet scores: the file on salmobase, its address in layers.yaml, so that the release build
on GitHub's runners can fetch it.

## What it does not do

- It says how well a protein tolerates a change, not what the change does to a trait, and nothing about direction.
- It scores amino-acid changes only: not synonymous changes, stops, splice sites or anything outside coding sequence.
- It is not calibrated on salmon. The checks above show whether it ranks variants sensibly; a cut-off for "damaging"
  is G's to set on those results (the cut-off Brandes et al. propose was set on human clinical variants).

## References

According to PubMed:

- Brandes N, Goldman G, Wang CH, Ye CJ, Ntranos V. Genome-wide prediction of disease variant effects with a deep
  protein language model. Nat Genet 2023;55:1512-1522. [doi:10.1038/s41588-023-01465-0](https://doi.org/10.1038/s41588-023-01465-0)
- Rives A, Meier J, Sercu T, et al. Biological structure and function emerge from scaling unsupervised learning to
  250 million protein sequences. Proc Natl Acad Sci USA 2021;118(15). [doi:10.1073/pnas.2016239118](https://doi.org/10.1073/pnas.2016239118) (ESM-1b)
- Vaser R, Adusumalli S, Leng SN, Sikic M, Ng PC. SIFT missense predictions for genomes. Nat Protoc 2016;11:1-9.
  [doi:10.1038/nprot.2015.123](https://doi.org/10.1038/nprot.2015.123)
- Cheng J, Novati G, Pan J, et al. Accurate proteome-wide missense variant effect prediction with AlphaMissense.
  Science 2023;381:eadg7492. [doi:10.1126/science.adg7492](https://doi.org/10.1126/science.adg7492)

Not checked on PubMed (named for orientation): ESM-1v (Meier et al. 2021), ESM-2 (Lin et al. 2023), ProteinGym
(Notin et al. 2023).
