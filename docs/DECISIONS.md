# Decisions for G

Everything the prototype currently does by a provisional rule, in one place, with the options and a recommendation.
Each answer goes into ../AGENTS.md under "Decided" and, where it is a number, into snpscore's `weights.yaml` (then
rebuild the pool with `snpscore pool`: the release holds no weights; a layer setting in layers.yaml needs a new release).
Evidence sources: RESEARCH.md (section numbers below), the reviews of 2026-10-07 and 2026-11-04 and the benchmark in
`release/dev`.

## Scoring (changes tiers)

| # | Question | Now (provisional) | Options | Recommendation |
|---|---|---|---|---|
| 1 | Which ChromHMM states count as **active**? | Active_TSS, Active_enhancer | add Primed_enhancer; add Flanking_upstream | Keep as is; revisit with the eQTL benchmark (caQTLs are circular with ATAC) |
| 2 | How do primed, poised, bivalent, flanking and accessible states count? | 'weak', weight 1, only if not active in the preset | weight 0; weight 1; split primed (1) from poised/bivalent (0) | Split: primed/flanking 1, poised/bivalent/accessible 0 |
| 3 | Trait presets (which conditions each trait uses) | maturation = Brain + Gonad; growth_and_fillet = Muscle + Liver; disease_resistance = Liver; development = 5 embryo stages | add a gill preset from ATAC peaks only (no ChromHMM for gill); immature-only conditions for maturation | Keep; add gill as display-only until gill chromatin states exist |
| 4 | Weights and tier cut-offs | active 3, coding 3, splice 3, constrained 2, weak/UTR/active elsewhere/regbuild 1; tiers at 5/3/1 | as is; calibrate on the eQTL benchmark | Calibrate on eQTL leads (enrichment per term) before v0.1 |
| 5 | Should **synonymous** CDS SNPs score lower than missense? | same as missense (weights.yaml `synonymous`, new) | 3 (as now); 1; 0 | 1 (counted like UTR) |
| 6 | Should molQTL lead SNPs score? | weight 0 (shown, not scored) | 0; 1-2 once significance and permission are settled | 0 until #12 and #13 are answered |
| 7 | Top-N tie-break when SNPs share a score | tier, score, then known locus, assay pass, MAF; ties are counted on the page | as is; MAF first; GERP first | As is |

**Benchmark evidence for #1-#5** (`snpscore benchmark --positives molqtl --by-tissue`, release/dev, 10 controls per positive matched on gene distance and MAF, 95% intervals):
eQTL lead SNPs (n = 1,606, the fair test) are enriched in tier 1-2 1.48x (1.27-1.72), active state 1.40x (1.15-1.71), 3'UTR 2.03x, CDS 1.62x and
GERP constrained 2.29x (1.19-4.40); tier 1 alone is not significant (1.35x, 0.70-2.61). Gonad eQTLs show no active-state enrichment (0.99x).
caQTL leads (n = 1,057) give 3-4x, but they are called on the same ATAC data, so this is partly circular. Known loci (n = 37) are biased by selection.

| # | Question | Now | Recommendation |
|---|---|---|---|
| 4a | Use eQTL-lead enrichment (gene distance + MAF matched) to calibrate weights? | not used | Yes, with caQTLs reported but not used for calibration |
| 4b | The v0.1 'benchmark passes thresholds set in advance': which threshold? | none | Lower 95% bound > 1 for tier <= 2 on eQTL leads (met today: 1.27) |
| 4c | Score a one-tissue molQTL set with that tissue's preset, or always 'all'? | the tissue's preset | Tissue preset |

## Assay and panel design (changes what goes on a chip)

| # | Question | Now (provisional) | Options | Recommendation |
|---|---|---|---|---|
| 8 | Should fully repeat-masked probe flanks **warn**? | warn above 90% soft-masked; ~55% of public SNPs warn on this alone, ~20% pass overall | keep; drop the repeat warning (~46% pass); warn only when both flanks are fully masked | Ask the genotyping lab; meanwhile warn only when both flanks are fully masked |
| 9 | Other assay thresholds | GC 0.30-0.70, homopolymer > 6, flank variants on both sides, LORe/blacklist/A-T-C-G warn | confirm with the CIGENE genotyping lab | Confirm; add per-base runs (G/C > 4, A/T > 6) as in the carp array |
| 10 | Exclude A/T and C/G SNPs from panels by default? | warn only | exclude by default (Illumina bin rule, two Axiom probesets) | Exclude by default for Illumina panels |
| 11 | Panel defaults | 384 markers, half backbone, 20 kb spacing, MAF >= 0.05, <= 2 per gene, <= 1 per element, blacklist excluded | breeders' own defaults; cM spacing (Brekke map) | Ask a breeding partner; offer cM spacing as the default once #3 of RESEARCH.md 1 (male map on chr 2, 8, 17) is settled |
| 12 | Locus names in vendor files | Ssa<chrom>p<pos>, e.g. Ssa25p28996360 | as is; partner naming scheme | As is |

## Data, permissions and wording

| # | Question | Now | Recommendation |
|---|---|---|---|
| 13 | May we redistribute rows derived from the nf-RASQUAL tables (no licence on the repo)? Which significance rule (paper: eigenMT BF < 0.1)? Which allele does pi refer to? | used locally, BF < 0.1, no direction shown | Ask the authors (Nguyen, Sandve, Lien, Grønvold); also ask for full per-SNP outputs (needed for colocalisation) |
| 14 | How to describe the 504-fish AF panel; may we host derived frequencies? | "504-fish panel: mostly wild and farmed fish from Bertolotti et al. 2020 plus the 12 AQUA-FAANG fish" | Confirm wording and permission; consider a European / North American split from the Bertolotti metadata |
| 15 | Public SNP list for the background pool, demos and default panels: the 12-fish VCF has 70 sites on chr10 and stops near 105 Mb on chr1 | 12-fish VCF; no install has a pool today (TRACKER step 8), so the answer also sets what `salmo-snp download` builds from the release | Switch to the 504-fish panel sites (7.57M, frequencies only); the pool then takes longer to build than the 1.6M 12-fish sites' ~40 s (not measured) |
| 16 | Known-loci catalogue: vet the 40 rows and effect alleles | 40 rows (incl. the 3 hubsmolt SNPs), 13 with an effect allele; bco1l A (+ strand) = red flesh | Vet; add QTL intervals for IPN and sea lice |
| 17 | Fine-mapping defaults | prior SD 0.2, functional lambda 0.5, 95% sets, 5e-8 / 1e-5, 1 Mb clumping | Keep as labelled defaults; add the LD reference (#19) before using credible sets for decisions |
| 18 | Chromatin colours | portal palette by default, AQUA-FAANG itemRgb as a viewer option | Make itemRgb the default (matches the papers and JBrowse), but note: with deuteranopia its Bivalent (counted) and Repressed_polycomb (not counted) look alike (CIEDE2000 5.4); cells carry 'Biv'/'Pc' text, browser lanes rely on colour and tooltips |
| 19 | LD reference: may we derive packed haplotypes or r2 from the 504-fish phased VCF? | none | Yes if permitted; it fixes the biggest fine-mapping caveat |
| 20 | Portal name, how to cite, contact, privacy statement, footer credit for AQUA-FAANG and salmobase | placeholders marked 'under review' | Write once with the AQUA-FAANG consortium |
| 21 | Gene labels for genes unnamed in Ensembl | '~VGLL3' (human ortholog) | As is, or NCBI RefSeq names as a second source |
| 21a | Ss4R duplicate of a gene (Known loci column, `ss4r_*` columns) | other salmon gene(s) of its AQUA-FAANG salmon-trout clade on the paired chromosome of the syntenic quartet; none when the clade has one salmon copy (six6a: its chr1 namesake is in another clade) | Keep; ask the table's authors whether 1:1 clades next to a split clade (six6a) should be joined |

## Platform and sharing

| # | Question | Now | Recommendation |
|---|---|---|---|
| 22 | Where the repository lives | Decided (G, 2026-10-28): one private GitHub repository, salmo-snp | - |
| 23 | A copy for colleagues to try | Done: the public NREC demo (G, 2026-10-12) and the local install (2026-11-03) | - |
| 24 | Python, Django and DuckDB versions | Decided (G, 2026-11-04: the newest that suit): Python >= 3.11, Django 5.2 LTS, DuckDB 2; ../AGENTS.md "Rules" | - |
| 25 | The package names on PyPI. salmo-snp depends on `snpscore` by name, and none of snpscore, snpdata or salmo-snp is registered there, so a stranger's package of that name could be installed by a user who installs salmo-snp alone or upgrades snpscore by name | names unregistered; the README installs both packages in one command from GitHub | Register the three names now (empty placeholders are allowed), and publish there when the repository goes public |
| 26 | Which systems the install is promised on | The user-install check runs on Linux (every pull request), and on macOS and Windows (.github/workflows/platforms.yml: tags, weekly, by hand, and pull requests that touch packaging; both passed on 2026-11-04) | Promise Linux, macOS and Windows with Python 3.11-3.14; say so in the README |
| 27 | Which genotyping vendor the chip tools serve first (ROADMAP Push 3, I8 and I13) | G, 2026-11-04: probably Thermo Fisher Axiom (Affymetrix), as Norwegian aquaculture genotyping uses; Illumina and KASP second | Confirm with a breeding partner or the CIGENE lab, and get a current Axiom submission template and a design-results file from them (Thermo's columns are not public) |
| 28 | What 'genome comparison' means for the industry users | On hold: G is asking them | Options: positions between assemblies (I18-I19), a SNP and its Ss4R duplicate (partly there: ss4r layer, card, browser), salmon against rainbow trout (P4.12) |
| 29 | User accounts or a shared company server | Decided (G, 2026-11-04): one user per install, who shares results as files; a shared server is on hold | If a partner asks: their own login in front (SSO or a reverse proxy) before any accounts in the portal |
| 30 | The data-handling sheet (I2): README "What is stored, and what goes over the network" and its short form on a local install's Help page | a draft by Claude, from the code | Read it as a breeder's IT department would; then it is the text we hand out |
| 31 | Panel purposes and the chip upgrade (I8, I11; weights.yaml design) | genomic selection 5,000 markers, 100 kb, MAF 0.05, backbone 0.9; parentage 200, 2 Mb, MAF 0.3, backbone 1, 1 per gene, assay pass only; trait panel 96, 1 kb, MAF 0.01, no backbone, 4 per gene; sizes 96, 192, 384, 1,536, 5,000, 50,000; upgrade drops markers below call rate 0.95 or HWE p 1e-6 | Ask a breeding partner which purposes and sizes they order (and the vendor's current formats); parentage panels usually want MAF >= 0.3 and unlinked markers, which the cM spacing (Brekke map) would give better than 2 Mb |
| 32 | Probe uniqueness (I10): above which identity to the Ss4R duplicate should a SNP warn? | shown, never flagged (weights.yaml assay.max_paralog_identity: null); of 2,000 SNPs, 20% of LORe and 3.4% of others have >= 97% on both flanks | 0.97 on the cleaner flank as a warning, not a fail, once the genotyping lab confirms that Axiom cross-hybridises at that level |
| 33 | Variant scores (I15): from which percentile does a DeepFARM or CADD-like score count, and with what weight? | shown, never counted (weights.yaml variant_scores: {}) | Decide when the data is in: e.g. the top 10% (benchmark rows show its enrichment) with weight 1 |
| 34 | Flank keys for placing chips by sequence (I18; layers.yaml flank_keys) | the 504-fish panel's sites (7,572,808; 5,582,506 unique keys, 65 MB), in release 2026-11-05. Not yet checked against a real ICSASG_v2 Axiom manifest: none was on G's Mac on 2026-11-05 | Keep these sites, add EVA's rs sites if an ICSASG_v2 chip places too few; check it against a real ICSASG_v2 Axiom manifest (one from a partner) and the rs bridge before telling users |
| 35 | Primer3, Agena and the ICSASG_v2 conversion (I14, I19) | Primer3 products 70-120 bp and 150 bp flanks; Agena flanks 100 bp, layout unverified; ICSASG_v2 positions convert only inside blocks of rs IDs with one offset (positions between them are rejected) | Ask the genotyping lab for its GT-seq and Agena settings; keep the conversion strict (an inferred position between blocks could be off by an indel) |
| 36 | The Ssal_v3.1 <-> fSalSal1 conversion (I19) and the assembly for I20 | each Ssal_v3.1 chromosome aligned to the same fSalSal1 chromosome only (minimap2 asm5), primary alignments with mapq >= 5, overlapping blocks dropped; chromosome 25: 94.5% of public sites convert, 99.97% of those land on one of the SNP's alleles. Newer: a telomere-to-telomere assembly, MGB-Salmon-T2T-v1.0 (GCA_059053775, July 2026) | Keep fSalSal1 for I20 as NCBI's RefSeq reference unless AQUA-FAANG's re-run picks the T2T one; the conversion code takes either (one alignment each) |
