# Scoring SNPs: what other projects do, and our starting point

G, 2026-11-21: "The most important thing after having the data to visualise is the scoring of the SNPs. It will be
customisable, but we need a good starting point. Either we do it real basic, or we try to learn from other functional
genomics projects" (ENCODE, GTEx, and GTEx for animals). This note is that research and what it means for salmo-snp.
The questions it raises for G are in [DECISIONS.md](DECISIONS.md) (#1-#5 and #49-#53); the order of work is in
[TRACKER.md](TRACKER.md) "Next".

How it was made: six literature reviews (84 findings) by AI researchers on 2026-11-21 and -22, from papers retrieved
through PubMed and Europe PMC. On 2026-11-22 Claude re-checked the 51 papers cited here against their PubMed records
(title, authors, journal, year, and the number where the abstract gives it). A number followed by † appears only in
the paper's full text, as the reviewer read it, and was not re-checked. References with DOI links are at the end.
Our own measurements on release 2026-11-20 are in section 6 (added 2026-11-22).

## 1. The short answer

- **Nobody has a proven set of weights we could copy.** The transparent human schemes (RegulomeDB ranks, FORGEdb
  points) were validated only by enrichment, never shown to rank variants accurately. The learned human scores (CADD
  and its relatives) work for rare, damaging variants and do hardly better than chance on our task: common variants
  inside one LD block. The livestock scores that work (FAETH, FAEMI) were learned from trait records of 44,000 to
  103,000 cattle. No aquaculture species has a trained or validated score.
- **So the answer to "real basic, or learn from others" is both.** Keep the form basic: a transparent additive rule.
  That is the form of both published livestock scores and of the standard fine-mapping priors, and at our data size a
  transparent expert rule is not obviously worse than a learned one. Take the *order* of the evidence from the
  literature, and take the *scale* from our own benchmark.
- **The literature orders the evidence differently from our provisional weights** in three places (section 3):
  a protein change and evolutionary constraint carry more per SNP than a regulatory element; an active promoter
  carries more than an active enhancer; a synonymous change is not a protein change. These are questions for G.
- **What orders SNPs inside one locus is evidence at the base**, not the region: a predicted allele effect (the
  ChromBPNet scores to come), allelic imbalance, a protein change. Chromatin states separate regions from the
  background and then tie. The tier is best presented as a region-level filter with honest ties.
- **Where a functional score has paid off:** narrowing the candidates inside a GWAS locus, and choosing chip
  markers when it is combined with trait data and applied per genome segment. Inside one breeding population the
  gain in genomic prediction is small or nil. The tool should say so.
- **Customisable means learnable from the company's own data.** Every scheme that worked estimated the value of each
  evidence class from trait data. We can offer that as an optional report on a user's own GWAS, with a fixed,
  transparent default for everyone else.
- **Our own benchmark confirms that the tiers carry signal, and cannot do more yet** (section 6). eQTL lead SNPs sit
  in tiers 1 and 2 about 1.5 times as often as matched controls under every design. But there is no gradient across
  tiers or scores, the score ranks the leads no better than distance to the nearest gene start, and no option of the
  open decisions changes the result measurably. Calibration has to wait for a better truth set.
- **The one public salmon GWAS agrees on size and disagrees on the prior** (section 6). The lead SNPs of 116
  age-at-maturity signals are in tiers 1 and 2 1.5 times as often as matched SNPs, carried by coding sequence and not
  by chromatin state, and the prior slope the GWAS itself supports is 0.05 to 0.15 per score point, not 0.5.
- **Conservation can do much more than it does.** The GERP layer has the highest odds of any term but touches 0.2%
  of SNPs. Sequence that still aligns to pike covers 16% of SNPs and is enriched at eQTL leads more strongly than an
  active chromatin state (1.6 to 1.9 times; section 6). It is a layer since 2026-11-24, shown and not yet counted.
- **Two more layers, 2026-11-24.** The distance to the nearest ATAC summit and its signal strength are a layer too;
  at eQTL leads they add nothing to the peak itself so far. A missense effect score is planned for Orion
  ([MISSENSE.md](MISSENSE.md)).

## 2. What other projects do

| Scheme | How it scores | Data it needed | What was shown |
|---|---|---|---|
| RegulomeDB ranks (human, 2012) | Nested classes 1a to 6: eQTL evidence first, then how specifically the data show a factor bound at the base (ChIP-seq peak, matching motif, footprint, DNase peak). Histone marks are not in the rank | ENCODE data from over 100 cell types† | Enrichment of GWAS-linked SNPs only. Classes 1 and 2 hold about 2% of variants†. Its authors later added a trained probability (TURF) because the eQTL-led top class discriminated poorly |
| FORGEdb score (human, 2024) | 0 to 10 points: DNase hotspot 2, histone peak 2, TF motif 1, allele-specific occupancy 1, enhancer-gene link 2, eQTL 2† | ENCODE, Roadmap, GTEx | Enrichment only. Equal points per evidence line, chosen for transparency, not fitted |
| ENCODE registry, HaploReg | No score: the evidence itself is shown | | |
| CADD, Eigen, LINSIGHT, GWAVA and relatives (human) | Trained or evolutionary genome-wide scores, driven largely by conservation | Disease mutations, or alignments | Good for rare, damaging variants. In a comparison of 24 such scores the AUROC was 0.45 to 0.80 for rare disease variants and lower for common regulatory variants. On saturation mutagenesis of 20 regulatory elements none predicted single-base effects well (best mean correlation 0.22†) |
| Expression modifier score, EMS (human, 2021) | A classifier trained on 14,807 fine-mapped eQTL variants with 6,121 features | GTEx | Distance to the gene start was by far the most informative feature; the trained score barely beat distance alone (AUPRC 0.884 against 0.856†); yes/no histone peaks added under 2%† |
| Open Targets (human, 2021) | First a hand-weighted evidence score; replaced by a trained model once 445 gold-standard loci existed | Hundreds of curated loci | The trained model beat distance alone; sparse evidence types (QTL colocalisation) contributed little† |
| PolyFun (human, 2020) | Prior for fine-mapping estimated from the GWAS itself over 187 annotations, re-calibrated in 20 bins† | 49 traits, about 318,000 people each | Over 32% more confidently fine-mapped variants |
| FarmGTEx: cattle 2022, pig 2024, later chicken and sheep† | No per-variant score. Molecular QTL catalogues used to explain GWAS loci at gene level (colocalisation, TWAS) | Thousands of RNA-seq samples; the target is 50 tissues from 1,000 animals per species | GWAS signal was enriched only about 1.4 to 1.6-fold in molecular QTL in pigs†. In cattle, expression and splicing QTL variants from 16 tissues explained 69% of heritability; far less with fewer samples† |
| FAETH (cattle, 2019) | A variant's score is the mean, over 13 annotation partitions, of the trait heritability per variant of the class it falls in†. Additive | 34 traits in 44,270 cattle, 17.7 million variants | Conserved sites and metabolite QTL ranked highest, then expression QTL, young variants, histone-mark peaks. High-ranking variants predicted better in 7,551 further cattle |
| FAEMI (cattle, 2025) | Linear regression of each variant's fine-mapping probability on about 50 annotations fitted jointly† | 16 traits in 103,000 cattle | About 11% better prediction of heat tolerance in 45,000 new cattle. Weights shrank under joint fitting, and the linear model beat a random forest† |
| XT-50K cattle chip (2021) | GWAS p-value divided by the FAETH score, the best few variants per 50 kb segment, then assay design filters† | 34 traits in 44,000 cattle | Better prediction than the standard chip across countries and breeds (8 to 11% relative†), tested in over 90,000 cattle |
| Salmon sequence-model score (Nguyen 2025) | A deep-learning model's predicted allele effect; the top SNP per 250 kb | AQUA-FAANG chromatin profiles | 9,073 SNPs predicted late maturation about as well as the 70k array and 0.01 to 0.045 better than random subsets†. The same kind of score separated fine-mapped pig eQTL only modestly (AUROC 0.57†) |
| Aquaculture GWAS follow-up | Locus by locus, by plain intersection: linked to the lead SNP, in open or active chromatin of a relevant tissue, or coding, or allele-specific expression | A QTL and a few experiments | Sea bass: two SNPs in active regulatory regions proposed at a disease-resistance QTL. Salmon pancreas disease: candidates narrowed with immune-stimulated head kidney data (the ImmunoMap)†. Neither reports confirmation by genome editing† |

Genomic prediction, where annotation was used to choose or weight markers:

| Study | Result |
|---|---|
| US dairy evaluation (VanRaden 2017) | Selected sequence variants added 2.7 points of reliability; adding all candidates added 0.6. They were chosen by effect size, with annotation only as a pre-filter† |
| Seven commercial pig lines (Ros-Freixedes 2022) | Preselected sequence variants: +0.025 accuracy on average with about 80,000 animals; not robust across traits and lines |
| Two pig nucleus lines (Kjetså 2024) | Markers chosen by a pig CADD score alone lowered accuracy against high-density genotypes |
| 91,215 dairy cows (Alemu 2025) | GWAS and RNA-seq QTL variants helped slightly†; the contributions of ChIP-seq, ATAC-seq and coding sets varied |
| Chicken (Kang 2026); pig (Tang 2026) | Expression-QTL features gave no significant gain; annotation alone gave marginal gains, 4 to 5% only once the trait's own GWAS hits were a class† |
| Dairy breeds (Fang 2017); sheep (Moghaddar 2019) | Much more gain between breeds or in little-related animals (+0.161 against +0.020 within a breed) |
| Human polygenic scores (SBayesRC 2024) | 96 annotations with learned weights: +14% within and up to +34% across ancestries |
| Salmon lice resistance (Onabanjo 2024) | Whole-genome sequence predicted no better than the 50k array |
| Four aquaculture species (Song 2022) | Weighted GBLUP +1.5% on average; genomic-feature BLUP with GWAS-derived features lost accuracy† |
| Pacific white shrimp (Shi 2026) | SNPs in a muscle-specific bivalent chromatin state raised accuracy across populations from 0.21 to 0.31 against random subsets. One study, 972 animals |

## 3. Which evidence carries information, against our provisional weights

| Evidence | What the literature found | In salmo-snp today | Difference |
|---|---|---|---|
| Protein change | The largest enrichment per SNP among confidently fine-mapped human trait variants (nonsynonymous 51-fold†). Pig GWAS lead SNPs: 20-fold in coding sequence†. In salmon, the coding candidate at the IPN locus was not supported by genome editing, and the gene that was (nae1) has its strongest variants between genes† | Coding 3, splice 3, and synonymous also 3 | A synonymous change is not what was enriched. Coding suits "candidate causal variant" better than "marker for prediction" |
| Evolutionary constraint | Ranked first in the cattle score. 16-fold among fine-mapped human variants†. But pig GWAS lead SNPs were less conserved than background†, and it stayed significant in the later cattle score only for the deepest alignment† | GERP element from 65 fish: 2 | The literature puts constraint at or above a regulatory element. Ours is below. Ours also reaches only 0.23% of SNPs; alignment to pike reaches 14% and is enriched at eQTL leads (section 6) |
| Active promoter | Pig lead SNPs 12-fold in active promoters†. Pig molecular QTL most enriched in active promoters† | "Active" 3: active TSS and active enhancer alike | The literature separates the two. Our eQTL leads do not: with controls matched on gene distance an active TSS state shows 1.17 (0.84 to 1.60) and an active enhancer without one 1.85 (1.41 to 2.38) (section 6) |
| Active enhancer | Pig lead SNPs 2-fold in active enhancers†; more in the matching tissue† | "Active" 3 | Lower than a promoter, and where the tissue matters most. Part of the promoter excess is detection bias towards large effects near genes |
| Weak, poised, bivalent, accessible | Low weight per SNP. Open chromatin still matters in total because it covers many SNPs. In shrimp the best state for prediction was bivalent | 1 | Agrees. Do not set to zero on present evidence |
| Matching tissue | eQTL evidence pooled over all tissues generally did best across 41 traits; tissue-specific evidence was stronger for blood and brain traits (Hormozdiari 2018). Immune stimulation revealed effects the resting state lacks (Alasoo 2018) | All 27 conditions by default | Agrees. The head kidney treatments earn their place for disease traits |
| TF motif disrupted inside a peak | Supporting evidence only: 10 to 20% of candidate causal non-coding variants changed a known motif†. At the salmon accessibility-QTL leads the excess was slight† | +1 | Agrees. A missing motif must never count against a SNP |
| Molecular-QTL lead SNP | Weak per variant. Fine-mapped eQTL variants were enriched 5.8-fold for trait heritability; all significant eQTL variants 1.8-fold. GTEx resolved about one eQTL in eleven to a single variant†. 12 fish is below the sample sizes these studies tested† | 0: shown, not scored | Agrees. Keep at 0 |
| Predicted allele effect (sequence models) | The best predictors of which variant in a molecular-QTL signal is causal†. But as annotations they added almost nothing once coding, conserved and regulatory annotations were accounted for (Dey 2020) | Coming (ChromBPNet): shown, not counted | Test what it adds to the existing layers before it counts; use the top of the distribution |
| Allelic imbalance in ATAC reads | Variant-level evidence from 20 cell lines†, enriched for variants associated with brain disorders (Zhang 2020) | Not computed | The better use of the 12 fish. It speaks only for SNPs heterozygous in them |
| Distance to the gene start | The strongest single predictor of fine-mapped eQTL variants†. But GWAS hits, unlike eQTL, do not cluster at gene starts (Mostafavi 2023) | Not a term. The benchmark matches on gene distance | Use it as a control and a baseline, not as evidence |

Two more points on form:
- **Overlap breaks an additive score.** Marginal enrichments of overlapping layers do not add: two annotations with
  enrichments of 2.5 and 4.8 alone gave 2.4 together in fgwas†. A SNP in an active promoter is usually also in a
  robust peak, often in a UTR and in an Ensembl feature. Our rule already guards the worst cases (one chromatin term
  for the best state over conditions; the Ensembl point only where AQUA-FAANG has no peak). Every new layer should
  earn points only for what it adds given the others.
- **Reliability is not function.** In salmonid sequence data 22 to 62% of SNPs show deviant heterozygosity,
  concentrated in repeats and recently rediploidised regions (Dallaire 2023), and 35 to 39% of a trout array's SNPs
  failed or were monomorphic in two other populations (Bernard 2022). The same regions hold conserved duplicated
  enhancers, so a function-only score favours the least reliable SNPs. Keep the caution flags separate and visible.

## 4. What our benchmark must get right

- **Controls decide the answer.** One classifier scored AUC 0.95 against random controls, 0.82 against controls
  matched on distance to the gene start and 0.64 against controls from the same 1 kb region† (GWAVA). Enrichment tests
  that ignore LD gave three times the nominal false-positive rate† (GARFIELD). Ours matches on gene distance and
  allele frequency; the literature adds distance to the gene start, LD and gene density, and reports the tightest
  control set as the headline.
- **caQTL leads cannot test chromatin weights.** They are tested on ATAC peaks, so they lie in or near peaks by
  construction (841 of 2,707 leads inside the tested peak† in the original RASQUAL study).
- **A lead SNP is seldom the causal SNP** (about 5% on average for GWAS index SNPs†), so also score loci: is the
  best-scoring SNP near the lead better than in matched control regions?
- **eQTL and GWAS hits are different kinds of variant** (Mostafavi 2023): tuning on eQTL leads alone rewards
  promoter-proximal variants. Salmon has one public GWAS with full summary statistics† that could serve as an
  independent test: age at maturity in 11,166 males, 512,397 SNPs, 116 independent signals, on assembly ICSASG_v2
  (Sinclair-Waters 2020), which our conversion table can move to Ssal_v3.1.
- **Few positives.** About a thousand noisy leads can support four tier enrichments or one slope, not a fitted weight
  for every layer. Class estimates were imprecise even with 14,762 cows (Yuan 2024).
- **The prior's scale.** exp(0.5 x tier_score) means 4.5-fold prior odds at score 3, 12-fold at 5 and 55-fold at 8.
  Our earlier benchmark measured 1.48-fold (1.27 to 1.72) enrichment of eQTL leads in tiers 1 and 2. Lead SNPs
  dilute that figure, but the assumed prior is steeper than anything we have measured, and steeper than the 18-fold
  top bin of the best human eQTL score†. The validated practice is to estimate the enrichment per score bin and to
  show a flat prior beside it.

## 5. Options for the starting point

| | What it is | For | Against |
|---|---|---|---|
| A | Today's rule, unchanged | Transparent; nothing to do | Its order disagrees with the literature in three places; the prior's scale is unmeasured |
| B | Still basic: whole-number weights that G sets, re-ordered where G agrees with the literature (#5 synonymous, #49 promoter against enhancer, #50 constraint) | Transparent; defensible by citation; a day of work once decided | Borrowed orderings are hypotheses for salmon until our benchmark supports them |
| C | The same additive form, with the scale measured: enrichment per tier on our benchmark (tighter controls, held-out chromosomes, the maturity GWAS) sets the GWAS prior and checks the order | What the literature does at our data size; the numbers come with intervals | Our molecular-QTL leads cannot do it (section 6): it needs the maturity GWAS or allelic imbalance as the truth set first |
| D | A learned score beside the tier, as RegulomeDB added TURF | The route to within-locus ranking | Needs labels we do not have yet: allelic imbalance in the 12 fish, ChromBPNet effects, a company's own GWAS |

Claude's recommendation, after our own measurements (section 6): **B now, by judgement; C when a better truth set
exists; D later.** Our molecular-QTL leads confirm that the tiers carry signal but cannot choose between options, so
the order of the weights is G's judgement of the literature and the biology. Our data do say two things: nothing
supports weighting an active promoter above an active enhancer once distance to the gene is controlled (#49), and
nothing supports a prior as steep as exp(0.5 x tier_score) (#51). The ChromBPNet scores and allelic imbalance enter
as a bonus only after they pass a test of what they add inside peaks. The numbers stay G's.

For customisation, the literature supports three levels, in this order: the evidence always shown beside the tier
(every project does this); a documented way to run with one's own weights and named profiles; and an optional report
that estimates the enrichment per tier from the user's own GWAS, with a flat prior for comparison. Fitting weights to
one GWAS is a laptop job in the fgwas form but needs tens of independent loci, which few aquaculture traits have, so
it should be a report, not the default.

What to tell users:
- The tier says a SNP lies in a region with functional evidence. It does not say the SNP is causal, and SNPs in the
  same element tie.
- For a GWAS locus, read the tier among the SNPs linked to the lead SNP.
- For a chip, use the tier as a preference inside genome bins, after reliability, spacing and allele frequency. The
  panel designer already works this way. Combined with the company's own GWAS it follows the one design with a
  documented gain.
- For genomic prediction in one population, expect little. Estimate any benefit in fish that took no part in
  choosing the markers.

## 6. What our own data say (release 2026-11-20)

How it was measured. Positives: the lead SNPs of molecular QTL mapped in 12 fish (1,606 eQTL leads, the fairer test;
1,057 caQTL leads, circular for chromatin evidence) and the 40 catalogue loci. Controls, in two designs. S: every
other pool site in the same gene-distance bin and allele-frequency bin, which is the shipped benchmark's rule with all
controls instead of 10 drawn. T: every site the QTL study could have reported (1,361,114 sites), matched on gene
distance and on the allele count in the 12 fish. One analyst agent computed it, a second wrote it up and re-derived
the main numbers with its own queries, and Claude re-checked the counts against the release (2026-11-22). The scripts
and tables are kept outside the repository.

Odds ratios for eQTL lead SNPs, with 95% intervals:

| Evidence (weight today) | Design S | Design T | Leads with it |
|---|---|---|---|
| Tiers 1 and 2 | 1.56 (1.32-1.83) | 1.47 (1.25-1.71) | 167 of 1,475 |
| Tier 1 | 1.76 (0.91-3.09) | 1.40 (0.72-2.46) | 12 |
| Active state (3) | 1.51 (1.22-1.84) | 1.37 (1.13-1.66) | 104 |
| - an active TSS state | 1.17 (0.84-1.60) | 1.07 (0.77-1.43) | 41 |
| - an active enhancer state, no active TSS state | 1.85 (1.41-2.38) | 1.70 (1.31-2.16) | 63 |
| Weak state (1) | 1.07 (0.81-1.39) | 1.02 (0.78-1.31) | 58 |
| Any coding-sequence SNP (3) | 1.73 (1.32-2.21) | 1.68 (1.30-2.13) | 65 |
| - protein-changing | 1.86 (1.28-2.62) | 1.82 (1.27-2.52) | 34 |
| - synonymous | 1.83 (1.24-2.61) | 1.74 (1.20-2.44) | 31 |
| Splice region (3) | 0.43 (0.05-1.56) | 0.43 (0.05-1.56) | 2 |
| UTR (1) | 2.13 (1.75-2.56) | 1.95 (1.61-2.34) | 123 |
| GERP constrained (2) | 2.89 (1.44-5.18) | 2.12 (1.06-3.81) | 11 |
| Ensembl regulatory feature, no peak (1) | 1.15 (0.81-1.58) | 1.36 (0.97-1.87) | 39 |
| Motif changed inside a peak (1) | 0.87 (0.49-1.45) | 0.86 (0.50-1.38) | 15 |

The state rows compare with SNPs outside peaks; the other rows with SNPs that lack that evidence.

What the data support:
- **The tiers carry signal, robustly and modestly.** eQTL leads are in tiers 1 and 2 about 1.5 times as often as
  matched controls under both designs. Known loci: 5.2 (2.9 to 9.3; 13 of 40 against 25 of 400), from few loci, a
  quarter of them in coding sequence. caQTL leads: 3.2 (2.8 to 3.6), circular.
- **There is no gradient.** Against tier 4, tier 3 is as enriched as tier 2 (1.60 against 1.64). Score by score the
  odds are flat (1.66 at score 1, 1.64 at 3, 1.69 at 4). A plain "any evidence, yes or no" ranks the leads as well as
  the score. The score's AUC is 0.539 (0.528 to 0.550).
- **The score does not beat distance.** Distance to the nearest protein-coding gene start alone has AUC 0.562, which
  is 0.023 above the score (0.006 to 0.040). This is the eQTL bias the literature describes, in our own data.
- **What carries the eQTL signal:** UTR, coding sequence, active enhancers and, from 11 leads, constraint. What shows
  none: an active TSS state once gene distance is matched, weak states, the Ensembl feature, a motif change, the
  splice region (2 leads).
- **Synonymous and protein-changing leads are equally enriched** (ratio 0.97, 0.58 to 1.63). So the coding and UTR
  signal is about lying in the transcript, where the method measures allele-specific expression, not about protein
  function. These leads cannot inform DECISIONS #5.
- **No listed option of DECISIONS #1, #2 or #5 changes the benchmark measurably.** The odds ratio of tiers 1 and 2
  stays between 1.44 and 1.58 and the AUC moves by at most 0.004. The options do move SNPs: 100,933 fall a tier if
  weak states count 0, and 49,417 rise if primed enhancers count as active.
- **The prior is steeper than anything measured.** exp(0.5 x score) assumes 1.6, 2.7, 4.5, 7.4, 12 and 20-fold for
  scores 1 to 6; the measured odds stay near 1.7. Lead SNPs are tags, which dilutes the measured figures, so the true
  slope is unknown, not shown to be flat.

What the data cannot support: the size of any weight, a choice between the options, graded chromatin evidence (no
trend with the number of conditions in which a SNP is active) or the prior's slope. The reasons:
- The leads come from 12 fish and are tags: 167 of the 1,606 eQTL leads lie inside their own gene.
- The chance of being a lead rises eight-fold with the allele count in the 12 fish, from 2.7 to 22 per 10,000 sites,
  and 65% of pool sites could not have been leads at all (chromosomes 10 and 15 almost entirely).
- eQTL leads are 1.4 times as frequent in late-rediploidised regions (1.24 to 1.56), which points to a reliability
  problem in the truth set, not to biology.

Found on the way:
- **The public pool carries no coding consequence**, because it is built without the genome. All 73,579
  coding-sequence sites in it count as coding and the synonymous weight never applies there, while it does apply to a
  user's list scored with the genome. If DECISIONS #5 changes that weight, uploads and the public background would be
  scored by different rules.
- **The benchmark is cheap:** 5 to 38 seconds and at most 38 kB per run. It can be built with the pool in every
  install; today no release has it, so the Methods page shows none.
- Tiers in the pool of 3,436,671 sites: tier 1 13,045 (0.38%), tier 2 211,438 (6.15%), tier 3 291,820 (8.49%),
  tier 4 2,920,368 (84.98%).

### The age-at-maturity GWAS: an independent test (2026-11-24)

According to PubMed, Sinclair-Waters et al. 2020
([doi:10.1186/s12711-020-0529-8](https://doi.org/10.1186/s12711-020-0529-8)) mapped age at maturity in 11,166 males
of one aquaculture strain: 512,397 SNPs (a 50K array imputed to a 930K panel)
on assembly ICSASG_v2, with 116 independent signals. Its supplementary Table S3 gives the statistics of every SNP.
`snpscore annotate --from-assembly ICSASG_v2` moved 481,585 SNPs (94.0%) to Ssal_v3.1, all but five of them agreeing
with the reference base there, and 112 of the 116 lead SNPs. The data are not in the repository.

Lead SNPs against all other GWAS SNPs of the same allele-frequency bin and gene-distance bin:

| Evidence | Leads with it | Matched SNPs | Odds ratio (95%) |
|---|---|---|---|
| Tiers 1 and 2 | 29 of 112 (25.9%) | 18.8% | 1.51 (0.95-2.33) |
| Tier 1 | 4 | 1.5% | 2.43 (0.65-6.41) |
| Coding sequence | 18 | 6.7% | 2.65 (1.50-4.42) |
| UTR | 13 | 8.9% | 1.35 (0.69-2.41) |
| Active state | 11 | 11.9% | 0.81 (0.39-1.50) |
| In a peak | 20 | 19.2% | 0.92 (0.53-1.50) |
| GERP constrained | 2 | 1.0% | 1.80 (0.21-6.64) |

- **The same 1.5-fold as at eQTL leads, with a different carrier:** coding sequence, not chromatin state.
- **The prior's slope, fitted to the GWAS** (the fgwas form: one causal SNP per locus, prior proportional to
  exp(slope x tier_score), 100 loci of 250 kb either side of a lead): 0.05 (-0.15 to 0.20). With 100 kb windows 0.10
  (-0.10 to 0.25); without chromosomes 9 and 25, which hold the six6 and vgll3 signals, 0.15 (-0.10 to 0.35). The
  portal's 0.5 lies outside every interval and fits worse than a flat prior (log-likelihood lower by 19, 14 and 6).
  As a yes-or-no prior term, coding sequence is supported at 2.0 (0.9 to 4.1), and at 3.3 (1.3 to 6.7) without the
  two large loci.
- **Inside loci the posterior does not sit on high-tier SNPs:** the share of posterior on tier 1-2 SNPs is 1.01
  times their share of the locus' SNPs (0.67 to 1.41). The 95% credible set is one SNP at the median under either
  prior; the functional prior changes the top SNP in about one locus in ten.
- Genome-wide, at the same allele frequency and gene distance, tier 1 SNPs have 1.08 times the mean chi-square of
  tier 4 SNPs (1.00 to 1.15); tiers 2 and 3 show nothing.

Limits. The leads are array tags. Each is almost always a genotyped 50K SNP whose neighbours were imputed with 21 to
24% discordance, so the posterior concentrates on the tag whatever its function, and tests inside loci lean towards no
enrichment. A regulatory causal variant is unlikely to be on an array at all, while a coding one may be, which favours
coding here. The array is itself rich in evidence (18.6% of its SNPs are in tiers 1 and 2, against 6.5% of the public
pool). One trait, one strain. So this GWAS supports a flatter prior and the coding weight; it does not test the
chromatin weights.

### Conservation: what would make it count for more (2026-11-24)

Today's layer is membership of a GERP constrained element from Ensembl's 65-fish alignment: 180,364 elements of 32 bp
at the median, 11.5 Mb or 0.4% of the genome. It applies to 8,058 of the 3,436,671 pool SNPs (0.23%), 37% of them in
coding sequence. It has the highest odds ratio of any term at eQTL leads and the fewest leads (11).

- **Per-base scores from the same alignment do not help.** Ensembl publishes them (a 448 MB bigWig). Only 22% of
  the genome has a score at all (the vgll3 missense site has none), and most scored bases are aligned too shallowly
  to score above 0.4. A score of 2 or more gives 2.15 (0.79 to 4.69) at eQTL leads from 6 leads, and 1 or more gives
  1.61 (0.80 to 2.89): no better than the element flag. The alignment is the limit, not how it is scored.
- **Sequence that still aligns to pike is the layer that helps.** AQUA-FAANG's whole-genome alignment of salmon,
  trout and pike is on salmobase with an alignment-depth track (90 MB). Pike split from salmonids before their genome
  duplication, so this is sequence retained for over 100 million years. It covers 13.8% of the 7.57 million public
  SNPs: 65% of those in coding sequence, 41% of those in peaks, 10% of intergenic ones. At eQTL leads:

| Lead SNPs | Design S | Design T | T, also matched on imputation quality |
|---|---|---|---|
| All (433 of 1,606 aligned to pike) | 1.74 (1.55-1.95) | 1.46 (1.30-1.63) | 1.47 (1.32-1.65) |
| With no tier evidence today (tier 4) | 1.64 (1.41-1.91) | 1.38 (1.19-1.60) | |
| More than 10 kb from a protein-coding gene start | 1.83 (1.56-2.13) | 1.44 (1.24-1.67) | |
| Aligned to pike, outside peaks and coding sequence | 1.63 (1.43-1.86) | 1.38 (1.21-1.57) | |

  For comparison in the strictest design, being in a peak gives 1.24 (1.05 to 1.45) and a constrained element 2.17
  (1.08 to 3.88). The result holds with imputation quality of 0.95 or more outside blacklisted regions (1.47, 1.31 to
  1.64) and outside late-rediploidised regions (1.37, 1.19 to 1.59). So conservation with pike is as informative per
  SNP as an active chromatin state at these leads, applies to SNPs the score ignores today, and reaches 2.4 times as
  many leads as tiers 1 and 2 do.
- **The GWAS does not confirm it and cannot refute it:** 62 of 112 lead SNPs align to pike, against 55.8% of matched
  array SNPs (0.98, 0.67 to 1.46). The array is already four times richer in pike-aligned sequence than the public
  sites, which also shows that the flag goes with sequence that is easy to genotype.
- Whether and how it counts is G's decision (DECISIONS #54). The layer is in the code since 2026-11-24 (`pike`,
  weight 0: shown, not counted); the tests that shaped it follow.

### The pike layer: what improves it (2026-11-24)

G asked for the layer and for tests to improve it. All on the 7.57 million public sites and the eQTL leads, designs S
and T as above (T also matched on imputation quality). The alignment's MAF files give the aligned base in pike, in
the trout ortholog and in the salmon and trout duplicate copies.

| Version of the flag | Share of public SNPs | Design S | Design T |
|---|---|---|---|
| The SNP's base aligns to pike (the depth track) | 13.8% | 1.74 (1.55-1.95) | 1.47 (1.32-1.65) |
| ... and the pike base is the salmon reference base | 7.7% | 1.69 (1.45-1.97) | 1.37 (1.18-1.58) |
| ... and the pike base differs | 5.3% | 1.54 (1.31-1.81) | 1.39 (1.19-1.61) |
| 90 to 100% of the 50 flanking bases identical in pike | 0.7% | 2.10 (1.39-3.05) | 1.64 (1.10-2.37) |
| 70 to 79% identical | 3.1% | 1.38 (1.09-1.73) | 1.15 (0.92-1.43) |
| Aligned, under 50% identical | 6.1% | 1.57 (1.32-1.84) | 1.46 (1.24-1.72) |
| Aligned to the trout ortholog but not to pike | 37% | 1.14 | 1.03 (0.93-1.14) |
| The salmon duplicate copy 70% identical or more, pike not aligned | 10.0% | 1.12 (0.94-1.32) | 1.10 (0.93-1.28) |
| Aligned to none of the four | 42% | 0.58 | 0.72 (0.64-0.81) |
| In an alignment gap of 1 to 20 bp | 1.6% | 2.01 (1.52-2.61) | 1.80 (1.37-2.32) |
| In a gap of 21 to 50 bp | 0.6% | 2.38 (1.56-3.48) | 2.10 (1.38-3.07) |
| In a gap of 51 to 100 bp | 0.7% | 0.86 (0.41-1.58) | 0.95 (0.47-1.71) |
| Within 25 bp of aligned sequence, in a gap of over 50 bp | 2.6% | 1.04 (0.75-1.39) | 1.05 (0.78-1.40) |
| **The layer as built: aligned, gaps of up to 50 bp closed** | **16.0%** | **1.92 (1.72-2.14)** | **1.61 (1.45-1.79)** |

- **Depth of conservation is what matters.** Sequence shared with trout alone carries nothing; neither does the
  salmon duplicate copy without pike. Pike is the layer.
- **The base itself adds nothing, and identity little.** A SNP whose reference base is the pike base is no likelier
  to be a lead than one where they differ. Windows 90 to 100% identical do better, but they are 0.7% of SNPs and 56%
  of them coding; outside coding sequence, high identity gives no more than plain alignment (SNPs with no tier
  evidence: 1.16, 0.90 to 1.47, for windows 70% identical or more, against 1.44 for aligned windows under 50%).
  So the release needs the 90 MB depth track, not the 2 GB of alignments.
- **Short alignment gaps belong to the conserved stretch.** SNPs in gaps of up to 50 bp are leads at least as often
  as aligned SNPs; in longer gaps and just outside the edges they are not. Closing gaps of up to 50 bp is the one
  change that improved the layer, and it is `max_gap: 50` in layers.yaml (PROVISIONAL).
- **As built:** 563 Mb in 1,226,940 stretches, 16.0% of public SNPs and 18.5% of the pool's: 71% of its coding
  SNPs, 54% of those in splice regions, 42 to 44% in UTRs, 18% of intronic and 13.5% of intergenic ones. Outside
  coding sequence, UTRs and splice regions the leads are still enriched (1.83 and 1.54), as among SNPs with no tier
  evidence (1.84 and 1.55); 79% of the pool SNPs in the layer are outside robust peaks. Rainbow trout gets the same
  layer from the same alignment (547 Mb), untested: trout has no eQTL set.
- **A check that does not use the eQTL leads:** in unique sequence the 504 fish have 2.37 public SNPs per kb where no
  flanking base is identical in pike, then 2.19, 2.07 and 1.77 as identity rises, and 1.24 where 90 to 100% are
  identical. Fewer variants where conservation is higher is what selection against changes would leave (the share of
  rare variants changes little, 46.0 to 48.5%).

### ATAC summits: distance and signal strength (2026-11-24)

G asked for a layer of scoring from the distance to the ATAC summit and the signal strength. The nf-core MACS2 peak
files of the 27 conditions on salmobase give 4.6 million significant summits, 3.0 million of them inside robust
peaks. A robust peak holds several: its summits span 151 bp at the median. Fold enrichment differs between
conditions (median 3.1 to 6.5, 90th percentile 5.9 to 18.6), so the layer also gives each summit's rank among its own
condition's peaks.

| SNPs | Share of pool | Design S | Design T |
|---|---|---|---|
| In a robust peak (for comparison) | 7.96% | 1.31 (1.11-1.55) | 1.24 (1.05-1.45) |
| Within 50 bp of a summit | 3.53% | 1.39 (1.09-1.75) | 1.38 (1.10-1.71) |
| Within 50 bp of a summit in the strongest quarter of its condition (the rule) | 1.04% | 1.07 (0.62-1.71) | 1.07 (0.64-1.67) |
| Within 50 bp of a summit in the weaker half | 1.48% | 1.58 (1.10-2.18) | 1.54 (1.11-2.09) |
| Inside robust peaks only: within 50 bp of a summit against the rest of the peak | | 1.08 (0.78-1.49) | 1.18 (0.86-1.59) |
| Inside robust peaks only: the rule | | 0.77 (0.43-1.29) | 0.83 (0.48-1.36) |
| caQTL leads, inside robust peaks only: the rule | | 1.68 (1.24-2.25) | 1.71 (1.27-2.27) |
| caQTL leads, inside robust peaks only: within 50 bp of any summit | | 1.07 (0.84-1.35) | 1.11 (0.88-1.39) |

- **Distance to a summit says about what the peak says.** Being within 50 bp of a summit is no better at eQTL leads
  than being in the peak, and inside peaks the difference from the rest of the peak is within noise (163 to 178 leads).
- **Strength is not supported by the eQTL leads.** Leads are not more often at strong summits; if anything at weak
  ones. Strong peaks are often shared, promoter-like elements, where a lead found in 12 fish is less likely.
- **The caQTL leads do support it,** 1.7 times, but a strong peak is also where a caQTL is easiest to detect in 12
  fish, so this cannot be told from detection.
- Summits outside robust peaks carried nothing in the first test (0.84 and 0.98), so the layer keeps those inside.
- **As built:** `summit` gives every SNP within 500 bp of a summit its distance, the signal, the rank and the
  condition; 98.7% of pool SNPs in a robust peak get them. The rule (weights.yaml `summit`: within 50 bp, rank 0.75
  or more) has weight 0. It needs evidence at the base to be judged: allelic imbalance in the 12 fish, and the
  ChromBPNet effects. DECISIONS #55.

### What a user can customise today

From an audit of the code and demonstrations on a copy of the release (2026-11-22):
- **One set of rules:** weights.yaml inside the installed snpscore package. There are two ways to change the
  scoring: choose one of 11 named condition presets on the command line (`--trait`), or edit the installed file by
  hand. No option names another weights file, and no portal page has a control for weights, cut-offs, state lists or
  conditions.
- **Re-tiering needs no new annotation:** a tier is SQL over stored evidence columns. Applying other rules to a list
  of 40 to 209,327 SNPs took 0.09 to 0.64 seconds, against 7 to 28 seconds to annotate again; on the whole pool, 2 to
  3 seconds for tier counts and 31 to 35 seconds for a new pool file.
- **Editing the file works for new runs,** and every job keeps a copy of its rules with their hash. But the audit
  demonstrated gaps:
  - a running portal keeps comparing new results with the old public background, without notice;
  - the Design panel and saved projects state the installed file's hash whatever rules made their tiers, and a saved
    version's download was silently re-tiered (18 of 40 SNPs) while its report showed the stored tiers;
  - of seven deliberate mistakes in the file, three changed tiers with no message and four gave a Python error;
  - the README's update command puts the shipped file back;
  - snpscore's own output files do not say which rules made them.
- **Effort to each level** (estimates): an own-weights file as a supported option, a day to a few days; named
  profiles in the portal, a few days plus a public background per profile; editing rules for one job with immediate
  re-tiering, a week or more; a profile saved with a design project and stated in every export, a few days; learning
  weights from the user's own data, a week or more and decisions by G.

## 7. Next layers of evidence

In the order of expected value for the effort (2026-11-24). Each has to pass the same test before it counts: what it
adds given the layers already there.

| Layer | What it adds | Effort | Status |
|---|---|---|---|
| ChromBPNet allele effects, per condition | Evidence at the base: the kind that orders SNPs inside a peak or locus | Running on Orion (docs/CHROMBPNET.md) | Good test results so far (G, 2026-11-24) |
| Allelic imbalance in the 12 fish's ATAC and RNA reads | Measured, variant-level evidence, and a truth set for everything else | A by-product of the ChromBPNet evaluation on Orion | To ask of the Orion repository |
| Conservation with pike (salmon-trout-pike alignment) | Broad conservation for 16% of SNPs; 1.6 to 1.9 at eQTL leads | Small: one 90 MB track on salmobase | Built 2026-11-24 (layer `pike`, salmon and trout; weight 0); in the data with the next release; DECISIONS #54 |
| A missense effect score for coding SNPs | Separates damaging from harmless protein changes; coding is the one class both truth sets support, and all of it scores alike today | A protein language model on one GPU on Orion for a few hours, SIFT 4G as the cross-check | Planned: [MISSENSE.md](MISSENSE.md); DECISIONS #56 |
| Distance to the ATAC summit, and signal strength | Graded accessibility in place of a yes-or-no state | Small: the nf-core peak files on salmobase | Built 2026-11-24 (layer `summit`, salmon and trout; weight 0); no gain at eQTL leads (section 6); DECISIONS #55 |
| A large fine-mapped eQTL set (the gill study of about 3,000 fish) | The strongest regulatory truth set in salmon | Depends on the authors' data | To ask |

Tested and set aside: per-base GERP scores (section 6). Looked at and not a per-SNP layer: salmobase's TFBS folder,
which holds motif activity per condition, not binding sites.

## References

According to PubMed, with each DOI as a link.

Human schemes and benchmarks
- Boyle AP et al. 2012. Annotation of functional variation in personal genomes using RegulomeDB. Genome Res.
  [doi:10.1101/gr.137323.112](https://doi.org/10.1101/gr.137323.112)
- Dong S, Boyle AP. 2022. Prioritization of regulatory variants with tissue-specific function (TURF). Nucleic Acids
  Res. [doi:10.1093/nar/gkab924](https://doi.org/10.1093/nar/gkab924)
- Breeze CE et al. 2024. FORGEdb. Genome Biol.
  [doi:10.1186/s13059-023-03126-1](https://doi.org/10.1186/s13059-023-03126-1)
- Kircher M et al. 2019. Saturation mutagenesis of twenty disease-associated regulatory elements. Nat Commun.
  [doi:10.1038/s41467-019-11526-w](https://doi.org/10.1038/s41467-019-11526-w)
- Wang Z et al. 2023. Performance comparison of computational methods for non-coding variants. Genomics Proteomics
  Bioinformatics. [doi:10.1016/j.gpb.2022.02.002](https://doi.org/10.1016/j.gpb.2022.02.002)
- Ritchie GRS et al. 2014. Functional annotation of noncoding sequence variants (GWAVA). Nat Methods.
  [doi:10.1038/nmeth.2832](https://doi.org/10.1038/nmeth.2832)
- Wang QS et al. 2021. Supervised learning for functionally informed fine-mapping of cis-eQTLs (EMS). Nat Commun.
  [doi:10.1038/s41467-021-23134-8](https://doi.org/10.1038/s41467-021-23134-8)
- Mountjoy E et al. 2021. An open approach to prioritize causal variants and genes at GWAS loci (Open Targets). Nat
  Genet. [doi:10.1038/s41588-021-00945-5](https://doi.org/10.1038/s41588-021-00945-5)
- Dey KK et al. 2020. Evaluating the informativeness of deep learning annotations for human complex diseases. Nat
  Commun. [doi:10.1038/s41467-020-18515-4](https://doi.org/10.1038/s41467-020-18515-4)
- Avsec Ž et al. 2026. Advancing regulatory variant effect prediction with AlphaGenome. Nature.
  [doi:10.1038/s41586-025-10014-0](https://doi.org/10.1038/s41586-025-10014-0)

GTEx, molecular QTL and fine-mapping
- GTEx Consortium. 2020. The GTEx Consortium atlas of genetic regulatory effects across human tissues. Science.
  [doi:10.1126/science.aaz1776](https://doi.org/10.1126/science.aaz1776)
- Hormozdiari F et al. 2018. Leveraging molecular quantitative trait loci to understand the genetic architecture of
  diseases and complex traits. Nat Genet.
  [doi:10.1038/s41588-018-0148-2](https://doi.org/10.1038/s41588-018-0148-2)
- Weissbrod O et al. 2020. Functionally informed fine-mapping and polygenic localization (PolyFun). Nat Genet.
  [doi:10.1038/s41588-020-00735-5](https://doi.org/10.1038/s41588-020-00735-5)
- Mostafavi H et al. 2023. Systematic differences in discovery of genetic effects on gene expression and complex
  traits. Nat Genet. [doi:10.1038/s41588-023-01529-1](https://doi.org/10.1038/s41588-023-01529-1)
- Kumasaka N et al. 2016. Fine-mapping cellular QTLs with RASQUAL and ATAC-seq. Nat Genet.
  [doi:10.1038/ng.3467](https://doi.org/10.1038/ng.3467)
- Zhang S et al. 2020. Allele-specific open chromatin in human iPSC neurons. Science.
  [doi:10.1126/science.aay3983](https://doi.org/10.1126/science.aay3983)
- Alasoo K et al. 2018. Shared genetic effects on chromatin and gene expression indicate a role for enhancer priming
  in immune response. Nat Genet. [doi:10.1038/s41588-018-0046-7](https://doi.org/10.1038/s41588-018-0046-7)
- Farh KK et al. 2015. Genetic and epigenetic fine mapping of causal autoimmune disease variants. Nature.
  [doi:10.1038/nature13835](https://doi.org/10.1038/nature13835)
- Pickrell JK. 2014. Joint analysis of functional genomic data and GWAS of 18 human traits (fgwas). Am J Hum Genet.
  [doi:10.1016/j.ajhg.2014.03.004](https://doi.org/10.1016/j.ajhg.2014.03.004)
- Iotchkova V et al. 2019. GARFIELD classifies disease-relevant genomic features. Nat Genet.
  [doi:10.1038/s41588-018-0322-6](https://doi.org/10.1038/s41588-018-0322-6)

Farm animals
- Liu S et al. 2022. A multi-tissue atlas of regulatory variants in cattle (CattleGTEx). Nat Genet.
  [doi:10.1038/s41588-022-01153-5](https://doi.org/10.1038/s41588-022-01153-5)
- Teng J et al. 2024. A compendium of genetic regulatory effects across pig tissues (PigGTEx). Nat Genet.
  [doi:10.1038/s41588-023-01585-7](https://doi.org/10.1038/s41588-023-01585-7)
- Fang L et al. 2025. The Farm Animal Genotype-Tissue Expression (FarmGTEx) Project. Nat Genet.
  [doi:10.1038/s41588-025-02121-5](https://doi.org/10.1038/s41588-025-02121-5)
- Xu Z et al. 2025. Integrating large-scale meta-GWAS and PigGTEx resources. Natl Sci Rev.
  [doi:10.1093/nsr/nwaf048](https://doi.org/10.1093/nsr/nwaf048)
- Xiang R et al. 2019. Quantifying the contribution of sequence variants with regulatory and evolutionary
  significance to 34 bovine complex traits (FAETH). PNAS.
  [doi:10.1073/pnas.1904159116](https://doi.org/10.1073/pnas.1904159116)
- Xiang R et al. 2021. Genome-wide fine-mapping identifies pleiotropic and functional variants that predict many
  traits across global cattle populations (XT-50K). Nat Commun.
  [doi:10.1038/s41467-021-21001-0](https://doi.org/10.1038/s41467-021-21001-0)
- Xiang R et al. 2023. Gene expression and RNA splicing explain large proportions of the heritability for complex
  traits in cattle. Cell Genomics. [doi:10.1016/j.xgen.2023.100385](https://doi.org/10.1016/j.xgen.2023.100385)
- Xiang R et al. 2025. Integrating extensive functional annotations and multiomics of cattle enhances climate
  resilience prediction and mapping (FAEMI). PNAS.
  [doi:10.1073/pnas.2514736122](https://doi.org/10.1073/pnas.2514736122)
- VanRaden PM et al. 2017. Selecting sequence variants to improve genomic predictions for dairy cattle. Genet Sel
  Evol. [doi:10.1186/s12711-017-0307-4](https://doi.org/10.1186/s12711-017-0307-4)
- Ros-Freixedes R et al. 2022. Genomic prediction with whole-genome sequence data in intensely selected pig lines.
  Genet Sel Evol. [doi:10.1186/s12711-022-00756-0](https://doi.org/10.1186/s12711-022-00756-0)
- Kjetså MV et al. 2024. Effects of reference population size and structure on genomic prediction of maternal traits
  in two pig lines. J Anim Breed Genet. [doi:10.1111/jbg.12865](https://doi.org/10.1111/jbg.12865)
- Alemu SW et al. 2025. Comparison of genomic prediction accuracies in dairy cattle lactation traits using five
  classes of functional variants. Genet Sel Evol.
  [doi:10.1186/s12711-025-00966-2](https://doi.org/10.1186/s12711-025-00966-2)
- Kang H et al. 2026. Integrating predicted gene expression into genomic selection: an evaluation in partridge
  chickens. Genet Sel Evol. [doi:10.1186/s12711-026-01099-w](https://doi.org/10.1186/s12711-026-01099-w)
- Tang Z et al. 2026. Improving genomic prediction accuracy of complex traits by integrating massive types of
  functional annotations (IFAM). Nat Commun.
  [doi:10.1038/s41467-026-72470-0](https://doi.org/10.1038/s41467-026-72470-0)
- Moghaddar N et al. 2019. Genomic prediction based on selected variants from imputed whole-genome sequence data in
  Australian sheep populations. Genet Sel Evol.
  [doi:10.1186/s12711-019-0514-2](https://doi.org/10.1186/s12711-019-0514-2)
- Fang L et al. 2017. Use of biological priors enhances understanding of genetic architecture and genomic prediction
  within and between dairy cattle breeds. BMC Genomics.
  [doi:10.1186/s12864-017-4004-z](https://doi.org/10.1186/s12864-017-4004-z)
- Zheng Z et al. 2024. Leveraging functional genomic annotations and genome coverage to improve polygenic prediction
  (SBayesRC). Nat Genet. [doi:10.1038/s41588-024-01704-y](https://doi.org/10.1038/s41588-024-01704-y)
- Yuan C et al. 2024. Evaluation of heritability partitioning approaches in livestock populations. BMC Genomics.
  [doi:10.1186/s12864-024-10600-y](https://doi.org/10.1186/s12864-024-10600-y)

Aquaculture
- Baudement MO, Morata DP, Gillard GB et al. 2026. Developmental contexts of gene-regulatory evolution following
  whole genome duplication in salmonids. Nat Ecol Evol.
  [doi:10.1038/s41559-026-03171-6](https://doi.org/10.1038/s41559-026-03171-6). The AQUA-FAANG salmonid atlas,
  now published; the release's layers still cite the 2025 preprint.
- Nguyen DT et al. 2025. A Nextflow pipeline for molecular QTL mapping in small sample size datasets with an
  application in Atlantic salmon. BMC Genomics.
  [doi:10.1186/s12864-025-12302-5](https://doi.org/10.1186/s12864-025-12302-5)
- Nguyen DT et al. 2025. Sequence-based chromatin activity modeling and regulatory impact prediction of genetic
  variants in farmed animals using deep learning. NAR Genom Bioinform.
  [doi:10.1093/nargab/lqaf139](https://doi.org/10.1093/nargab/lqaf139)
- Mukiibi R et al. 2025. Integrated functional genomic analysis identifies regulatory variants underlying a major QTL
  for disease resistance in European sea bass. BMC Biol.
  [doi:10.1186/s12915-025-02180-4](https://doi.org/10.1186/s12915-025-02180-4)
- Manousi D et al. 2025. Dissecting the genetic basis of response to salmonid alphavirus in Atlantic salmon. BMC
  Genomics. [doi:10.1186/s12864-025-11735-2](https://doi.org/10.1186/s12864-025-11735-2)
- Pavelin J et al. 2021. The nedd-8 activating enzyme gene underlies genetic resistance to infectious pancreatic
  necrosis virus in Atlantic salmon. Genomics.
  [doi:10.1016/j.ygeno.2021.09.012](https://doi.org/10.1016/j.ygeno.2021.09.012)
- Verta JP et al. 2020. Cis-regulatory differences in isoform expression associate with life history strategy
  variation in Atlantic salmon. PLoS Genet.
  [doi:10.1371/journal.pgen.1009055](https://doi.org/10.1371/journal.pgen.1009055)
- Sinclair-Waters M et al. 2020. Beyond large-effect loci: large-scale GWAS reveals a mixed large-effect and
  polygenic architecture for age at maturity of Atlantic salmon. Genet Sel Evol.
  [doi:10.1186/s12711-020-0529-8](https://doi.org/10.1186/s12711-020-0529-8)
- Onabanjo O et al. 2024. Use of whole-genome sequence data for fine mapping and genomic prediction of sea louse
  resistance in Atlantic salmon. Front Genet.
  [doi:10.3389/fgene.2024.1381333](https://doi.org/10.3389/fgene.2024.1381333)
- Song H, Hu H. 2022. Strategies to improve the accuracy and reduce costs of genomic prediction in aquaculture
  species. Evol Appl. [doi:10.1111/eva.13262](https://doi.org/10.1111/eva.13262)
- Shi JL et al. 2026. Epigenome-informed prioritization of bivalent chromatin SNPs enhances genomic prediction
  robustness in Pacific white shrimp. Zool Res.
  [doi:10.24272/j.issn.2095-8137.2026.110](https://doi.org/10.24272/j.issn.2095-8137.2026.110)
- Dallaire X et al. 2023. Widespread deviant patterns of heterozygosity in whole-genome sequencing due to
  autopolyploidy, repeated elements, and duplication. Genome Biol Evol.
  [doi:10.1093/gbe/evad229](https://doi.org/10.1093/gbe/evad229)
- Bernard M et al. 2022. Development of a high-density 665 K SNP array for rainbow trout genome-wide genotyping.
  Front Genet. [doi:10.3389/fgene.2022.941340](https://doi.org/10.3389/fgene.2022.941340)

The six reviews in full (84 findings and 76 scheme descriptions, each with its source and a quoted passage) are kept
outside the repository; ask Claude for any of them.
