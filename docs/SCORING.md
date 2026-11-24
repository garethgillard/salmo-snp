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
Our own measurements on release 2026-11-20 are computed but not yet written up and re-checked (section 6).

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
| Evolutionary constraint | Ranked first in the cattle score. 16-fold among fine-mapped human variants†. But pig GWAS lead SNPs were less conserved than background†, and it stayed significant in the later cattle score only for the deepest alignment† | GERP element from 65 fish: 2 | The literature puts constraint at or above a regulatory element. Ours is below. GERP from 65 fish of a duplicated genome is untested |
| Active promoter | Pig lead SNPs 12-fold in active promoters†. Pig molecular QTL most enriched in active promoters† | "Active" 3: active TSS and active enhancer alike | The literature separates the two |
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
| C | The same additive form, with the scale measured: enrichment per tier on our benchmark (tighter controls, held-out chromosomes, the maturity GWAS) sets the GWAS prior and checks the order | What the literature does at our data size; the numbers come with intervals | Needs the benchmark upgrades first; with about a thousand positives it can calibrate tiers, not every weight |
| D | A learned score beside the tier, as RegulomeDB added TURF | The route to within-locus ranking | Needs labels we do not have yet: allelic imbalance in the 12 fish, ChromBPNet effects, a company's own GWAS |

Claude's recommendation: **B and C together now, D as the upgrade path.** G decides the order questions with our own
measurements beside the literature; the prior is calibrated per tier; the ChromBPNet scores and allelic imbalance
enter as a bonus only after they pass a test of what they add inside peaks. The numbers stay G's.

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

## 6. What our own data say

Already recorded (DECISIONS.md, benchmark on an earlier release): eQTL lead SNPs are enriched in tiers 1 and 2
1.48-fold (1.27 to 1.72), in an active state 1.40-fold (1.15 to 1.71) and in GERP elements 2.29-fold (1.19 to 4.40);
tier 1 alone is not significant.

Computed on release 2026-11-20 on 2026-11-22, not yet written up or independently re-checked: odds ratios for every
evidence term against two control designs, a joint model, the score against single features and against distance to
the gene start, and what each option of DECISIONS #1, #2 and #5 would change. A separate audit established what a
user can customise today: named condition presets on the command line, and editing the installed weights file; no
portal control; re-tiering needs no new annotation and takes under a second for a list. Both go into this section
and into DECISIONS when the write-up is checked.

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
