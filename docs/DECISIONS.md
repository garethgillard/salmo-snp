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
| 24 | Python, Django and DuckDB versions. Python 3.8 is end of life since 2024-10-07 and Django 4.2 since 2026-04-07 (no security fixes), and the public demo runs on both; 3.8 was for salmobase's container, and the portal now gets its own | Python 3.8, Django 4.2, DuckDB 1.2.2 on the server and in CI; users get Django 4.2 and DuckDB 1.5 | Python >= 3.10 (3.12 on the server), Django 5.2 LTS (fixes to 2028-04), DuckDB 1.5; DuckDB 2 later. Measured 2026-11-04: all tests pass on that set but one, which needs a small fix (TRACKER step 8) |
| 25 | The package names on PyPI. salmo-snp depends on `snpscore` by name, and none of snpscore, snpdata or salmo-snp is registered there, so a stranger's package of that name could be installed by a user who installs salmo-snp alone or upgrades snpscore by name | names unregistered; the README installs both packages in one command from GitHub | Register the three names now (empty placeholders are allowed), and publish there when the repository goes public |
| 26 | Which systems the user-install check runs on | Linux only (CI, Python 3.12); Python 3.13 and 3.14 checked by hand on 2026-11-04 | Add macOS (a private repository's macOS minutes count 10x: run it weekly and on tags, not on every pull request); Windows once the test script handles `Scripts\`, as breeders often use Windows |
