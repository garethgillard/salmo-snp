"""The Scoring page, /snp/about/scoring/ (G, 2026-11-27: "Make the scoring doc and the reasoning, choices, and research
behind the scoring decisions available and quick to access. This should be doc like with sections and an index, so
that users can see the different metrics that go into a score, what the literature says on how to weight it, and what
the testing results we have so far on it. Be clear on the testing data we've used up front."): docs/SCORING.md and the
scoring rows of docs/DECISIONS.md, for users. The numbers are docs/SCORING.md's, measured on Atlantic salmon (release
2026-11-20, and the layers and the GWAS of 2026-11-24): change them there first. The weights and the band cut-offs
come from the installed weights.yaml, so the page always names the ones that score."""
from __future__ import annotations

from django.shortcuts import render

from . import about, figures, jobs

RELEASE_TESTED = "2026-11-20"
DOCS = "https://github.com/garethgillard/salmo-snp/blob/main/docs/"  # the research note and the decisions, in full

TESTS = [  # (name, what it is, what it can test, its limits): the truth sets and the controls, said first
    ("eQTL lead SNPs", "The SNP most associated with each gene's expression in the 12 AQUA-FAANG fish (nf-RASQUAL; "
     "Nguyen et al. 2025): 1,606 leads.", "Every kind of evidence: the fairest test we have.",
     "Lead SNPs are tags, not the causal SNPs (167 lie inside their own gene). From 12 fish, a SNP common in them is "
     "eight times likelier to be a lead, and 65% of public sites could not have been leads at all."),
    ("caQTL lead SNPs", "The SNP most associated with each ATAC peak's accessibility in the same 12 fish: 1,057 leads.",
     "Evidence other than chromatin.", "They were found by testing ATAC peaks, so they lie in peaks by construction: "
     "circular for chromatin evidence."),
    ("Age-at-maturity GWAS", "Sinclair-Waters et al. 2020: 11,166 males of one aquaculture strain, 512,397 SNPs and 116 "
     "independent signals; 112 of the lead SNPs placed on Ssal_v3.1 (2026-11-24). Not in the portal's data.",
     "The one independent test: a trait, not a molecular phenotype.",
     "The leads are 50K-array tags whose neighbours were imputed (21 to 24% discordance): a regulatory causal SNP is "
     "unlikely to be on an array, a coding one may be. One trait, one strain."),
    ("Known loci", "The portal's catalogue of 40 published loci.", "A sanity check.",
     "Partly chosen because they are missense, so coding evidence is expected: not a validation."),
    ("Controls", "Public SNPs from the 3,436,671 common sites of the 504-fish panel (the public background), matched to "
     "each lead. Design S: every site in the same gene-distance and allele-frequency bin. Design T (QTL leads): every "
     "site the QTL study could have reported (1,361,114), matched on gene distance and on the allele count in the 12 "
     "fish.", "Odds ratios with 95% intervals: how much more often leads have a kind of evidence than their controls.",
     "Matching decides the answer: against random controls one published classifier scored AUC 0.95, against controls "
     "from the same 1 kb region 0.64 (GWAVA). LD is not matched here."),
]

GLANCE = {  # term -> (eQTL leads: design S, design T, leads with it; GWAS leads): docs/SCORING.md section 6
    "active": ("1.51 (1.22–1.84)", "1.37 (1.13–1.66)", "104", "0.81 (0.39–1.50)"),
    "weak": ("1.07 (0.81–1.39)", "1.02 (0.78–1.31)", "58", ""),
    "coding": ("1.86 (1.28–2.62)", "1.82 (1.27–2.52)", "34", "2.65 (1.50–4.42), any CDS"),
    "synonymous": ("1.83 (1.24–2.61)", "1.74 (1.20–2.44)", "31", ""),
    "splice": ("0.43 (0.05–1.56)", "0.43 (0.05–1.56)", "2", ""),
    "utr": ("2.13 (1.75–2.56)", "1.95 (1.61–2.34)", "123", "1.35 (0.69–2.41)"),
    "constrained": ("2.89 (1.44–5.18)", "2.12 (1.06–3.81)", "11", "1.80 (0.21–6.64)"),
    "regbuild": ("1.15 (0.81–1.58)", "1.36 (0.97–1.87)", "39", ""),
    "motif": ("0.87 (0.49–1.45)", "0.86 (0.50–1.38)", "15", ""),
    "summit": ("1.07 (0.62–1.71)", "1.07 (0.64–1.67)", "", ""),
    "pike": ("1.92 (1.72–2.14)", "1.61 (1.45–1.79)", "", "0.98 (0.67–1.46)"),
}
GLANCE_ROWS = [  # rows beside the terms: (label, eQTL S, eQTL T, leads with it, GWAS)
    ("In a robust ATAC peak (for comparison)", "1.31 (1.11–1.55)", "1.24 (1.05–1.45)", "", "0.92 (0.53–1.50)"),
    ("Score 3 or more (bands 5+ and 3–4)", "1.56 (1.32–1.83)", "1.47 (1.25–1.71)", "167", "1.51 (0.95–2.33)"),
]

EVIDENCE = [  # (term, its name, what the literature says, what our tests say); '†': only in the paper's full text
    ("active", "Active chromatin state",
     "In pigs, GWAS lead SNPs were 12-fold enriched in active promoters and 2-fold in active enhancers†, and molecular "
     "QTL were most enriched in active promoters†; part of the promoter excess is detection bias towards large effects "
     "near genes. Enhancers count most in the matching tissue†, and immune stimulation revealed effects the resting "
     "state lacks (Alasoo 2018).",
     "eQTL leads are in an active state 1.51 (1.22–1.84) times as often as matched SNPs outside peaks. Split, the order "
     "is the reverse of the literature's once gene distance is matched: an active TSS state 1.17 (0.84–1.60), an active "
     "enhancer without one 1.85 (1.41–2.38). There is no trend with the number of conditions a SNP is active in. The "
     "GWAS leads show none (0.81, 0.39–1.50; 11 leads), but array tags are a poor test of chromatin."),
    ("weak", "Weak state, active in none",
     "Low weight per SNP, but open chromatin counts in total because it covers many SNPs. In shrimp, SNPs in a bivalent "
     "state raised the accuracy of genomic prediction across populations from 0.21 to 0.31 (one study of 972 animals; "
     "Shi 2026). Advice: do not set them all to zero on present evidence.",
     "No signal at eQTL leads: 1.07 (0.81–1.39). Counting weak states as 0 would move 100,933 public SNPs down a band "
     "without changing the benchmark measurably."),
    ("coding", "CDS: protein change or unknown",
     "The largest enrichment per SNP among confidently fine-mapped human trait variants (nonsynonymous 51-fold†); pig "
     "GWAS lead SNPs were 20-fold enriched in coding sequence†. In salmon, the coding candidate at the IPN resistance "
     "locus was not supported by genome editing, and the gene that was (nae1) has its strongest variants between genes "
     "(Pavelin 2021).",
     "Protein-changing eQTL leads: 1.86 (1.28–2.62). GWAS leads in coding sequence: 2.65 (1.50–4.42), 18 of 112; as a "
     "prior term the GWAS supports 2.0 (0.9–4.1). Coding is the one class both truth sets support. Every protein change "
     "weighs the same today; a missense effect score is planned (DECISIONS #59)."),
    ("synonymous", "CDS: synonymous",
     "A synonymous change is not what was enriched in the human fine-mapping studies: the enrichment is for changes to "
     "the protein.",
     "Weighs as a protein change until the maintainer decides (DECISIONS #5; recommended: 1, as a UTR). eQTL leads cannot "
     "decide it: synonymous and protein-changing leads are equally enriched (1.83 against 1.86), because QTL mapping "
     "measures expression, so lying in the transcript is what counts there. The public background is built without the "
     "genome and has no coding consequences: all its CDS sites count as protein changes."),
    ("splice", "Splice region", "Not reviewed separately: it weighs as a protein change.",
     "Too few to test: 2 eQTL leads in a splice region (0.43, 0.05–1.56)."),
    ("utr", "UTR", "Not reviewed separately.",
     "Among the strongest signals at eQTL leads: 2.13 (1.75–2.56), 123 leads; GWAS leads 1.35 (0.69–2.41). Like the "
     "synonymous result, probably about lying in the transcript, where QTL mapping measures expression."),
    ("constrained", "GERP constrained",
     "Ranked first in a cattle score built from 34 traits in 44,270 cattle (FAETH; Xiang 2019) and 16-fold enriched among "
     "fine-mapped human variants†; but pig GWAS lead SNPs were less conserved than background†, and in a later cattle "
     "score only the deepest alignment stayed significant†. The literature puts constraint at or above a regulatory "
     "element; the default weights put it below an active state (DECISIONS #50).",
     "The highest odds of any term at eQTL leads, 2.89 (1.44–5.18), but from 11 leads: it reaches only 0.23% of the "
     "public SNPs (8,058 of 3,436,671). Per-base GERP scores from the same alignment do not help (only 22% of the genome "
     "has one). Conservation with pike reaches far more SNPs (below)."),
    ("regbuild", "Ensembl regulatory, no peak",
     "Human schemes count such elements as one line of evidence among several; FORGEdb gives each line equal points, "
     "chosen for transparency and not fitted (Breeze 2024).",
     "No clear signal: 1.15 (0.81–1.58), design T 1.36 (0.97–1.87). It counts only where AQUA-FAANG has no peak, as 68 "
     "to 86% of Ensembl's features overlap one."),
    ("motif", "TF motif change in a peak",
     "Supporting evidence only: 10 to 20% of candidate causal non-coding variants changed a known motif†, and at the "
     "salmon caQTL leads the excess was slight†. A missing motif must never count against a SNP.",
     "No signal at eQTL leads: 0.87 (0.49–1.45), 15 leads. The rule (+1) is the maintainer's (2026-10-19); about 15% of "
     "public SNPs in peaks have it."),
    ("summit", "Near a strong ATAC summit", "Not reviewed separately: graded accessibility in place of a yes-or-no state.",
     "Being within 50 bp of a summit says about what being in the peak says (1.39 against 1.31 at eQTL leads), and the "
     "rule, a summit in the strongest quarter of its condition, adds nothing: 1.07 (0.62–1.71). caQTL leads favour "
     "strong summits 1.7-fold, but a strong peak is also where a caQTL is easiest to detect. Shown, not counted, until "
     "allelic imbalance or the ChromBPNet effects can test it (DECISIONS #58)."),
    ("pike", "Aligns to pike",
     "Conservation, as above. Pike split from the salmonids before their genome duplication, so this is sequence kept "
     "for over 100 million years.",
     "The strongest broad signal found: eQTL leads are in it 1.92 (1.72–2.14) times as often as matched SNPs (design T "
     "1.61), as much per SNP as an active state, for 16% of public SNPs: 2.4 times as many leads as score 3 or more. It "
     "holds outside coding sequence and UTRs (1.83) and among SNPs with no other evidence (1.84). The GWAS neither "
     "confirms nor refutes it (0.98, 0.67–1.46). Closing alignment gaps of up to 50 bp was the one change that "
     "improved it. Shown, not counted, until the maintainer decides; recommended: 1 (DECISIONS #54)."),
    ("molqtl", "molQTL lead",
     "Weak per variant: fine-mapped eQTL variants were enriched 5.8-fold for trait heritability, all significant eQTL "
     "variants 1.8-fold (Hormozdiari 2018); GTEx resolved about one eQTL in eleven to a single variant†. 12 fish is below "
     "the sample sizes these studies tested†.",
     "Shown, not counted. These leads are the truth set of the tests on this page, so they cannot be tested against "
     "themselves."),
]
CHROMBPNET = ("ChromBPNet allele effects (gill)",
              "Predicted allele effects are the best predictors of which variant in a molecular-QTL signal is causal†, "
              "but as annotations they added almost nothing once coding, conserved and regulatory annotations were "
              "accounted for (Dey 2020). A salmon sequence-model score chose 9,073 SNPs that predicted late maturation "
              "about as well as the 70K array (Nguyen 2025).",
              "Not tested yet. Shown, never counted: in the Table, on the card and with the card's Predict button, for "
              "the 216,586 public and Synchrosmolt SNPs in the gill model's training peaks (release 2026-11-25). It "
              "counts only after a test of what it adds inside peaks (DECISIONS #53).")

OTHERS = [  # (scheme, how it scores, what was shown): docs/SCORING.md section 2, shortened
    ("RegulomeDB (human, 2012)", "Nested classes: eQTL evidence first, then how specifically the data show a factor "
     "bound at the base", "Enrichment only; its authors later added a trained probability (TURF), as the top class "
     "discriminated poorly"),
    ("FORGEdb (human, 2024)", "0 to 10 points: equal points per line of evidence, chosen for transparency, not fitted",
     "Enrichment only"),
    ("CADD and relatives (human)", "Trained or evolutionary genome-wide scores, driven largely by conservation",
     "Good for rare, damaging variants; for common regulatory variants close to chance (AUROC 0.45 to 0.80 for rare "
     "disease variants, lower for common regulatory ones)"),
    ("Expression modifier score (human, 2021)", "A classifier trained on 14,807 fine-mapped eQTL variants",
     "Distance to the gene start was by far the most informative feature; the score barely beat distance alone"),
    ("PolyFun (human, 2020)", "A fine-mapping prior estimated from the GWAS itself over 187 annotations",
     "Over 32% more confidently fine-mapped variants"),
    ("FAETH (cattle, 2019)", "Additive: each variant scores the trait heritability per variant of its annotation classes; "
     "34 traits in 44,270 cattle", "Conserved sites and metabolite QTL ranked highest; high-ranking variants predicted "
     "better in 7,551 further cattle"),
    ("FAEMI (cattle, 2025)", "A variant's fine-mapping probability regressed on about 50 annotations; 16 traits in 103,000 "
     "cattle", "About 11% better prediction of heat tolerance in 45,000 new cattle"),
    ("XT-50K chip (cattle, 2021)", "GWAS p-value divided by the FAETH score, the best few variants per 50 kb, then assay "
     "filters", "8 to 11% better prediction than the standard chip across countries and breeds†"),
    ("FarmGTEx (cattle, pig and others)", "No per-variant score: molecular-QTL catalogues explain GWAS loci at gene level",
     "GWAS signal enriched 1.4 to 1.6-fold in molecular QTL in pigs†"),
    ("Salmon sequence-model score (Nguyen 2025)", "A deep-learning model's predicted allele effect; the top SNP per 250 kb",
     "9,073 SNPs predicted late maturation about as well as the 70K array"),
]

OPEN = [  # (decision, today, what the evidence says, the recommendation): docs/DECISIONS.md, the maintainer's to decide
    ("Which states count as active (#1)", "Active TSS and Active enhancer", "Adding primed enhancers would move 49,417 "
     "public SNPs up a band and change no test measurably", "Keep; revisit with a better truth set"),
    ("How weak states count (#2)", "Weight 1, only where no condition is active", "No signal at eQTL leads; 100,933 "
     "public SNPs fall a band at weight 0", "Split: primed and flanking 1, poised, bivalent and accessible 0"),
    ("Synonymous changes (#5)", "Weight 3, as a protein change", "The literature's enrichment is for protein changes; "
     "our eQTL leads cannot decide it", "1, as a UTR"),
    ("Active promoter against active enhancer (#49)", "Both 'active', weight 3", "Literature: promoter higher. Our eQTL "
     "leads: enhancer higher once gene distance is matched", "Keep them equal until a GWAS-based test says otherwise"),
    ("Constraint against an active state (#50)", "2 against 3", "Literature: constraint at or above; ours: the highest "
     "odds, from 11 leads", "Keep 2; conservation counts through pike instead (#54)"),
    ("The GWAS prior's slope (#51)", "exp(0.5 × score): 4.5-fold prior odds at score 3, 12-fold at 5", "The maturity GWAS "
     "supports 0.05 to 0.15 per point; 0.5 fits worse than a flat prior", "Lower it (0 to about 0.3) and show a flat "
     "prior beside it"),
    ("Distance to the gene start (#52)", "Not a term; the tests match on it", "The strongest single predictor of eQTL "
     "leads, but GWAS hits do not cluster at gene starts", "No: a matching variable, and the baseline to beat"),
    ("ChromBPNet effects and allelic imbalance (#53)", "Shown, weight 0", "Evidence at the base orders SNPs inside a "
     "locus; as annotations such scores added little in human studies", "0 until each passes a test inside peaks"),
    ("Sequence that aligns to pike (#54)", "Shown, weight 0", "1.6 to 1.9 at eQTL leads, 16% of public SNPs",
     "1, as a weak chromatin state"),
    ("ATAC summits (#58)", "Shown, weight 0", "No gain over the peak at eQTL leads", "0 until tested on evidence at the base"),
]

REFERENCES = [  # (citation, DOI): the papers this page names, as docs/SCORING.md lists them
    ("Alasoo K et al. 2018. Shared genetic effects on chromatin and gene expression indicate a role for enhancer priming "
     "in immune response. Nat Genet.", "10.1038/s41588-018-0046-7"),
    ("Boyle AP et al. 2012. Annotation of functional variation in personal genomes using RegulomeDB. Genome Res.",
     "10.1101/gr.137323.112"),
    ("Breeze CE et al. 2024. FORGEdb. Genome Biol.", "10.1186/s13059-023-03126-1"),
    ("Dey KK et al. 2020. Evaluating the informativeness of deep learning annotations for human complex diseases. Nat "
     "Commun.", "10.1038/s41467-020-18515-4"),
    ("Dong S, Boyle AP. 2022. Prioritization of regulatory variants with tissue-specific function (TURF). Nucleic Acids "
     "Res.", "10.1093/nar/gkab924"),
    ("Hormozdiari F et al. 2018. Leveraging molecular quantitative trait loci to understand the genetic architecture of "
     "diseases and complex traits. Nat Genet.", "10.1038/s41588-018-0148-2"),
    ("Mostafavi H et al. 2023. Systematic differences in discovery of genetic effects on gene expression and complex "
     "traits. Nat Genet.", "10.1038/s41588-023-01529-1"),
    ("Nguyen DT et al. 2025. A Nextflow pipeline for molecular QTL mapping in small sample size datasets with an "
     "application in Atlantic salmon. BMC Genomics.", "10.1186/s12864-025-12302-5"),
    ("Nguyen DT et al. 2025. Sequence-based chromatin activity modeling and regulatory impact prediction of genetic "
     "variants in farmed animals using deep learning. NAR Genom Bioinform.", "10.1093/nargab/lqaf139"),
    ("Pavelin J et al. 2021. The nedd-8 activating enzyme gene underlies genetic resistance to infectious pancreatic "
     "necrosis virus in Atlantic salmon. Genomics.", "10.1016/j.ygeno.2021.09.012"),
    ("Ritchie GRS et al. 2014. Functional annotation of noncoding sequence variants (GWAVA). Nat Methods.",
     "10.1038/nmeth.2832"),
    ("Shi JL et al. 2026. Epigenome-informed prioritization of bivalent chromatin SNPs enhances genomic prediction "
     "robustness in Pacific white shrimp. Zool Res.", "10.24272/j.issn.2095-8137.2026.110"),
    ("Sinclair-Waters M et al. 2020. Beyond large-effect loci: large-scale GWAS reveals a mixed large-effect and "
     "polygenic architecture for age at maturity of Atlantic salmon. Genet Sel Evol.", "10.1186/s12711-020-0529-8"),
    ("Wang QS et al. 2021. Supervised learning for functionally informed fine-mapping of cis-eQTLs (EMS). Nat Commun.",
     "10.1038/s41467-021-23134-8"),
    ("Wang Z et al. 2023. Performance comparison of computational methods for non-coding variants. Genomics "
     "Proteomics Bioinformatics.", "10.1016/j.gpb.2022.02.002"),
    ("Weissbrod O et al. 2020. Functionally informed fine-mapping and polygenic localization (PolyFun). Nat Genet.",
     "10.1038/s41588-020-00735-5"),
    ("Xiang R et al. 2019. Quantifying the contribution of sequence variants with regulatory and evolutionary "
     "significance to 34 bovine complex traits (FAETH). PNAS.", "10.1073/pnas.1904159116"),
    ("Xiang R et al. 2021. Genome-wide fine-mapping identifies pleiotropic and functional variants that predict many "
     "traits across global cattle populations (XT-50K). Nat Commun.", "10.1038/s41467-021-21001-0"),
    ("Xiang R et al. 2025. Integrating extensive functional annotations and multiomics of cattle enhances climate "
     "resilience prediction and mapping (FAEMI). PNAS.", "10.1073/pnas.2514736122"),
    ("Fang L et al. 2025. The Farm Animal Genotype-Tissue Expression (FarmGTEx) Project. Nat Genet.",
     "10.1038/s41588-025-02121-5"),
]


def scoring(request):
    """/snp/about/scoring/: the test data first, then how a score is made, the evidence one by one (its weight now, what
    fires it, the literature, our tests), whether the score works, what other projects do, the score bands, what is
    still open and the references. Written for salmon: the species bar's wording is not applied (jobs.middleware)."""
    w = jobs.weights() or {}
    weights = w.get("weights") or {}
    cuts = list(w.get("tiers") or figures.default_cuts())
    terms = [{"term": t, "name": name, "weight": weights.get(t), "counts": about.TERM_TEXT.get(t, ""), "literature": lit,
              "ours": ours, "glance": GLANCE.get(t)} for t, name, lit, ours in EVIDENCE if t in weights]
    return render(request, "snpportal/scoring.html", {
        "nav": "about", "title": "How scores are made", "tests": TESTS, "tested": RELEASE_TESTED, "terms": terms,
        "glance_rows": GLANCE_ROWS, "chrombpnet": CHROMBPNET, "others": OTHERS, "open": OPEN,
        "references": sorted(REFERENCES), "cuts": cuts, "bands": figures.bands(cuts), "shares": about.shares_text(),
        "conditions": len(jobs.CONDITIONS), "lambda": (w.get("finemap") or {}).get("functional_lambda"),
        "note_url": DOCS + "SCORING.md", "decisions_url": DOCS + "DECISIONS.md"})
