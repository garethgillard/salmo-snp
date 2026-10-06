# Simplification plan: salmobase functional SNP portal

Content and ease-of-use review of the local prototype (http://localhost:8000/snp/), revised after a critique on 2026-10-07. The goal is less text and fewer features on screen, keeping what users value. Simplifying must not make the evidence look stronger than it is. Each change lands as a small 'simplify: <page>' commit, so any cut can be reverted on its own.

Read-only review: no repo files were changed.

## Principles

1. Answer first. Each page opens with what the visitor came for: on SNP-list results, the top SNPs; on Association, the Manhattan plot and loci; on Panel, the panel; on the card, the tier and why. Everything else goes below it or behind one click.
2. Cut repetition, not meaning. When a short qualifier (15 words or fewer) changes how a number is read, it stays next to that number. Tier 4 = 'no evidence found (not evidence of no effect)'. 'No peak' names the conditions sampled. CDS says 'amino-acid effect not computed'. PIPs say 'one causal variant, no LD'. Known-locus rows keep their catalogue caveat. MAF says 'pooled; your strain can differ'. Cut anything else that repeats.
3. Word budgets count the visible words before any click, without nav or footer. Landing ≤120. Score ≤160. Overview ≤150 words of prose, with 4 tiles, a top-10 table and 3 open figures. Table: one row of filters. Panel ≤140, with 1 figure and 25 rows. Export ≤150. Association ≤160, with the Manhattan plot above the fold at 1440x900. Card and Variant ≤180, or ≤220 when a known locus with a catalogue caveat is shown. Gene ≤300. Known loci ≤100 before the first table. Help ≤600. Methods ≤700. Data ≤450. Tour: 5 steps of ≤80 words. Footer ≤28. If a page goes over, cut layout text before qualifiers.
4. One caveat line per page. Pages that show tiers get one line under the header: 'Prototype: tiers rank annotated evidence, not proven effects; rules are provisional. Methods →'. On a synthetic job, that same line starts with 'SYNTHETIC data ·', so there is one line, not two. The shared results header partial renders it, so every tab, card, regional plot, drawer and report of that job gets it. No PROVISIONAL or SYNTHETIC badges in headings, tiles, captions, table cells or tooltips. Figures keep the synthetic watermark. Downloads, exported figures and the report keep the full caveat.
5. No internal language on screen. No 'G'. No file names (weights.yaml, tracks.yaml, catalog/known_loci.tsv). No config keys, internal column names (gc, n, chromatin_id), sha256 values or hash-named objects. Where a decision is pending, write 'under review'.
6. Provenance lives in files: exported SVG/PNG/TSV headers, the zip bundle, the report (12-character hashes) and the Data and Methods pages. It does not go under every figure. The footer keeps only a data credit of 8 words or fewer.
7. Defaults over knobs. Show the 3-5 controls most visits use. Put the rest under one 'More filters' or 'Advanced settings' disclosure. It shows '(n active)', counted on the server, and opens by itself when any hidden control is not at its default. Apply on change where possible. Exception: a control that changes what ends up on a chip stays visible. That is the Assay select (All · Pass + warn · Pass + warn, no LORe · Pass only), the same on the Table and the Panel.
8. Show what carries signal, and never hide a finding. Replace an empty figure or section with one line. A tile that reads 0 stays when 0 is a result (Tier 1–2, Near a known locus). Only alert tiles, such as upload warnings, hide at 0. QC collapses to one line that opens by itself on any problem.
9. Say it once, in one place. Definitions and the colour key go in Methods. Formats, search syntax, privacy detail and vendor-file rules go in Help. Whole-list downloads go on Export; the Table keeps 'Download these N' and 'Vendor files for these N'. Scoring starts on the Score page. Release statistics go on Data.
10. Long lists show at most 25 rows inline (10 on the gene page and the regional credible set), then 'Show all N' and a download.
11. Figures carry a title, an (i) and one small ⤓ menu (SVG, PNG, data). No on-screen provenance caption.
12. Rankings say how they are ordered. A 'Top N' list is ordered by tier, then score, then a tie-break stated on the page (proposed: known locus, assay pass, MAF; G to confirm). Until G confirms, it says how many tie: '10 of 15 SNPs tied at the top score'. GWAS lists rank by p or by locus, never by tier.
13. Pages follow the job type. GWAS jobs get Association-first tabs and the GWAS files, with no Panel tab. They keep one route to an assay: KASP/Agena for the credible-set SNPs. SNP-list jobs get the panel and the vendor tools.
14. One name per thing. One gene label everywhere: the Ensembl name, else the catalogue name, else '~VGLL3' with a tooltip. One count helper for the known-loci catalogue. Panels are named by the markers actually chosen (n_selected), never by the target.
15. Simplify; don't add or re-decide. Thresholds, weights, tier rules, tie-breaks and candidate definitions belong to G; only how they are shown changes here. New work that is a feature rather than a cut is deferred: the full-TSV column reorder, the 2-column variant layout and the QQ strata toggle.
16. Small, reversible commits: one per page or area ('simplify: overview'), each listing what moved where. The commit that removes the badges also adds the caveat line, the qualifiers in principle 2 and the synthetic header partial, so no build ships with the caveats gone and nothing in their place. Land after the bug fixes other engineers are making in the same templates.
17. Order, by user impact: (1) caveat line, synthetic header partial, qualifiers, captions and footer; (2) Overview top-10 and tiles; (3) Table filters, columns and drawer; (4) Panel and Export; (5) Association and regional plot; (6) evidence card; (7) Score, the GWAS page and Landing; (8) Gene and Known loci; (9) Help, Methods, Data, Tour and Report.

## Page by page

### Site-wide (nav, footer, caveat line, figure chrome)

**Target:** Nav: Score · Known loci · Locus browser · Help ▾ (Help, Data, Methods, Run locally), plus the release pill. A one-line footer of ≤28 words that includes the data credit. One caveat line per page, merged with SYNTHETIC on synthetic jobs. Every figure card shows only its title, (i) and ⤓.

- Footer becomes one line: 'Release dev · Ssal_v3.1 · Data: AQUA-FAANG, Ensembl 116, EVA, published studies · Methods · Privacy · How to cite · Run locally'. Remove both sha256 paragraphs, the data-source list, the PROVISIONAL badge and the chromatin-palette toggle, which moves to the locus browser's Display options. Ask G whether AQUA-FAANG or salmobase need a fuller visible credit.
- Replace every per-element PROVISIONAL badge, the 'P' tile markers and the '(PROVISIONAL: …)' clauses with one line rendered by the shared results header partial: 'Prototype: tiers rank annotated evidence, not proven effects; rules are provisional. Methods →'.
- SYNTHETIC: on a synthetic job the line reads 'SYNTHETIC data · Prototype: tiers rank annotated evidence, not proven effects. Methods →' on every tab, card, regional plot and drawer of that job. Drop the H1 badge and keep the figure watermark. If only the demo chip is synthetic, show no page line. Instead the chip card reads 'Demo chip (synthetic)' and the chip-compare heading reads 'Compared with the demo chip (synthetic)'.
- Replace 'pending decision by G', 'until G has vetted the rows' and 'G to choose' with 'under review'. Remove on-page mentions of weights.yaml, tracks.yaml and catalog/known_loci.tsv; they stay under Methods → All settings and in the downloads.
- Figure cards: replace the SVG/PNG/TSV buttons with one '⤓' menu (a <details> element). Hide the on-screen figcaption ('Release dev · preset … · job created …'); it is already in each SVG's <desc> and in the exports' '#' lines.
- Nav: rename 'Explore' to 'Locus browser' and open it at 25:28,985,000-29,010,000 (vgll3) when no region is given. Merge 'Data & methods' and 'Help' into one 'Help' menu. Keep the release pill and drop the 'salmobase · dev' bar.
- Gene labels: one helper used everywhere. Show the Ensembl name, else the catalogue name, else '~VGLL3' with the tooltip 'Unnamed in Ensembl; named by its human ortholog'. This replaces 'unnamed (human VGLL3)'.
- Jargon gets one-line tooltips and no new inline prose. MAF: 'minor allele frequency in 504 public fish, pooled; your strain can differ'. LORe: 'region where the duplicated chromosomes still pair; probes may cross-hybridise'. A/T or C/G: 'strand-ambiguous; needs care on arrays'. Add tooltips for molQTL, GERP and the chromatin state names. The Trait control's tooltip names that trait's conditions, e.g. 'disease_resistance: Liver only (no immune tissue, gill or skin sampled)'.

### Landing /snp/

**Target:** ≤120 visible words. Above the fold: H1, a 2-sentence lede, two buttons, the search box with 4 chips, and the vgll3 figure. Below it: one link line to Known loci. Nothing else.

- Lede: 'Upload a list of Atlantic salmon SNPs and see which have the most functional evidence. Each SNP gets a tier from 1 (strongest) to 4 (no evidence found, not evidence of no effect), with the evidence behind it.'
- Add two buttons under the lede: 'Score your SNPs' (primary, → /snp/score/) and 'Take the tour'.
- Search: delete the 50-word syntax paragraph. Placeholder: 'Gene, rs ID, position or region'. Chips: vgll3 · rs863754587 · 25:28996360 · 25:28,990,000-29,000,000. Add a small 'What can I search?' link to Help#search.
- Delete the 5 nav cards; they repeat the top nav.
- Delete the 7 release-stat tiles; their numbers become one line on the Data page.
- Replace the 8-row known-loci table with one line from the shared count helper: 'Known loci: 37 published entries for 8 traits →'.
- Delete the 'Score the public variants of genes or intervals' form; it becomes the 'Genes or regions' tab on Score.

### Score /snp/score/

**Target:** ≤160 visible words, one card, one action. Above the fold: H1, lede, one 'Try it' example, an input card with tabs (Upload file | Paste positions | Genes or regions), one Score button, one formats line, one accurate privacy line and one GWAS link.

- Lede: 'Upload or paste Atlantic salmon SNPs (Ssal_v3.1). Each gets a functional tier and the evidence behind it.'
- Remove all four 'Trait preset' selects. This is safe: jobs.py precomputes tiers.parquet for every preset, so switching the trait on the results page never rescores. Under the button: 'You choose the trait on the results page.'
- Examples: one primary button, 'Try it: 37 published salmon SNPs (a few seconds)', and a secondary link, '50,000 public sites'. Remove 'Demo chip SYNTHETIC' from here; it becomes 'Use the demo chip (synthetic)' inside Panel → chip compare.
- Merge Upload and Paste into one card with tabs 'Upload file | Paste positions | Genes or regions'. The third tab takes the gene/interval form from the landing and gene pages.
- Replace the 5-row formats table with one line: 'VCF, SNP table, PLINK .bim/.map, Illumina/Axiom manifest or rs IDs. Format help →' (Help#formats).
- Replace the 'Your data' box with one accurate line: 'From a VCF only CHROM, POS, ID, REF and ALT are read. Other table columns are kept with the results for 24 h; anyone with the link can see them. Confidential? Run it locally.'
- Replace the GWAS card with one line: 'Have GWAS summary statistics? Analyse them →'. This needs a new GET page at /snp/score/gwas/ (GET currently returns 302). It holds the sumstats form, the example button (which opens with trait=maturation), one format line and the same privacy line ('Summary statistics are kept with the results for 24 h; anyone with the link can see them. Confidential? Run it locally.'). Point association.score's 413 and error renders at the new page instead of views.score_page. Until the page exists, keep a closed GWAS section on Score.

### Results header (all tabs, card, regional plot, drawer, report)

**Target:** Breadcrumb; H1 (list name · N SNPs); one action row: 'Trait: [maturation ▾]' · Report · Score another list · Delete; tabs; the caveat line (with SYNTHETIC on synthetic jobs). SNP-list jobs: Overview · Table · Panel · Export. GWAS jobs: Association · Overview · Table · Export.

- Make this partial the only place the caveat/SYNTHETIC line is rendered, and include it on every page of a job: tabs, card, regional plot, drawer and report.
- Remove 'Download TSV' from the header. Downloads live on Export and in the Table's two filtered links.
- Rename 'Printable report' to 'Report' and keep it only here (remove it from the Panel card).
- Trait control: label it 'Trait' and apply on change. Remove the Apply button and the text 'Tiers are recomputed for the preset's tissues; rules are PROVISIONAL'. The tooltip lists the trait's conditions, e.g. 'maturation: Brain, Gonad' or 'disease_resistance: Liver only (no immune tissue, gill or skin sampled)'.
- Remove the duplicate 'Results' (breadcrumb plus H1).
- GWAS jobs: hide the Panel tab and make Association the first, default tab. Trait stays visible above the Manhattan plot, because PIPs depend on it.

### Results > Overview

**Target:** ≤150 words of prose. Above the fold: 4 tiles on one row, the tier bar with a one-line hint, and the 'Top 10 SNPs' table. Below: 'Where the SNPs are' and 'Active chromatin per condition', then a closed 'More charts (3)', then a one-line upload QC.

- Add 'Top 10 SNPs for <trait>' under the tiles, reusing report.top(). Order: tier, then score, then the stated tie-break (proposed: known locus, assay pass, MAF; G to confirm). Until then, label ties at the cut: '10 of 15 SNPs tied at the top score; ties in genome order'. Columns: SNP with alleles (e.g. 'AX-123 · C>T', linked to its card), gene, tier, evidence, known locus, assay. Link under it: 'All <n> tier 1–2 in the table →'.
- Tiles: SNPs scored · Tier 1–2 · Near a known locus (within 50 kb) · Assay pass. These show even at 0, because 0 is a finding. Cut 'in an active element', 'coding', 'MAF ≥ 0.05', 'molQTL lead SNPs (display only)' and 'upload warnings 0'. Warnings show only as an alert when above 0. Replace the legend line with 'Click any number, bar or cell to list those SNPs.'
- Under the tier bar: 'Tier 1 = strongest functional evidence for this trait · Tier 4 = no evidence found (not evidence of no effect)'.
- Keep open: 'SNPs per tier', 'Where the SNPs are', 'Active chromatin per condition'.
- Put 'Genic region by tier', 'Evidence behind the tiers' and 'Minor allele frequency' under a closed 'More charts (3)'.
- Merge 'Assay design status' and 'Why SNPs warn or fail' into one 'Assay readiness' card and move it to the Panel tab. Cut 'Largest gap per chromosome' and the 'Assay flags' table; the Assay filter and the card's 'hide in table' links replace them.
- Upload QC becomes one line: '<n> rows read · <n> scored · <n> rejected · Ssal_v3.1 confirmed. Details'. It opens by itself when fewer rows are scored than read, or on any of: rejected rows, merged duplicates, indels or multiallelics, unknown chromosomes, unplaced rs IDs, rs IDs moved from ICSASG_v2, alias warnings, an assembly mismatch or reference-allele problems.
- GWAS jobs: tiles SNPs · Tier 1–2 · Loci · Near a known locus. The top-10 table ranks by p and links to Association. Figures: 'SNPs per tier' and 'Active chromatin per condition' only. No Upload QC; the Association QC line covers it.

### Results > Table

**Target:** One row of 5 filters plus 'More filters (n active)'. The table uses the full width with 9 default columns, so MAF and Assay are visible at 1440px without horizontal scroll. Two links act on the filtered rows: a TSV download and vendor files.

- Visible filters: Tier · Gene · Chromosome (from/to) · Min MAF · Assay (All · Pass + warn · Pass + warn, no LORe · Pass only; the same select as Panel). The 'hide …' checkboxes fold into the Assay select where they map onto it. Under 'More filters (n active)', which opens by itself when any of them is set: Region class, Active in, Evidence, known loci only, molQTL lead, the remaining hide options, Columns and Rows.
- Default columns: SNP with alleles ('AX-123 · C>T'), Gene, Region, Tier, Evidence, Chromatin, Known locus, MAF, Assay. Show Position only when the id does not encode the position. molQTL and Flags move under Columns; flags appear in the Assay badge tooltip.
- Open the evidence pane only after a row is clicked, as a drawer. It holds the tier line, the known locus with its caveat, one chromatin line, one assay line and 'Open full card'. No mini locus view and no live ATAC in the drawer. Remove the placeholder column 'Click a SNP to see its evidence.'
- Two links follow the filters: 'Download these <n> (TSV)' and 'Vendor files for these <n> →', which opens Export with scope=filtered (already supported by tools.py _scope). Remove 'Download all (TSV)'.
- Remove the 'Keys: j / k move between SNPs' hint (the keys still work).
- GWAS jobs: default columns SNP with alleles, p, beta (se), Tier, PIP (uniform → functional; blank outside loci), Gene, Region, Chromatin. Default sort is p ascending. Assay, Flags, molQTL and Known locus go under Columns.

### Results > Panel

**Target:** ≤140 words of prose. In order: the compact designer (Markers, Min spacing, Assay, Must include, Design panel); the panel heading with any shortfall alert and one KPI line; the 'Panel markers along the genome' figure; the first 25 markers with 'Show all' and 'Export this panel →'; the Assay readiness card; and a closed chip-compare section.

- Designer shows Markers [384], Min spacing (kb), Assay (same select as the Table; default unchanged from today), Must include and 'Design panel', with one line: 'Picks the best-scoring SNPs that pass the assay filter, spread over every chromosome.' The rest goes under 'Advanced settings (n active)', which opens by itself when anything there is changed: backbone share, min MAF (tooltip: pooled public MAF; your strain can differ), max per gene, max per element, min spacing (cM), cM map, gap highlight and the remaining exclude checkboxes.
- Heading: '<n_selected> markers · maturation · 6 Oct' (no hash, and never the target count). Keep the shortfall alert when fewer markers are chosen than asked for: 'Only 28 of 384 markers could be chosen: the binding constraint is …'.
- Replace the tiles and the tier-mix chart with one KPI line: '<n> markers · <x>% tier 1–2 · <y>% assay pass · median spacing <d> · largest gap <g> (chr <c>)'.
- Keep only the 'Panel markers along the genome' figure, with its gap highlights. Cut 'Tier mix of the panel', 'Spacing between neighbouring markers' and 'Largest gaps in the panel'. Turn 'Why each marker was chosen' into a 'Reason' column (must include / backbone / functional / fill).
- Selected SNPs: show the first 25 rows, then 'Show all <n>'.
- Replace the 7 download buttons and the 'Printable report' button with one 'Export this panel →' link; Export opens with this panel selected.
- Remove the '⚠ 3 vendor design rules broken' box from the panel summary; vendor checks sit next to each file on Export.
- Add the 'Assay readiness' card (moved from Overview): one bar, '<n> pass (<x>%) · <n> warn · <n> fail · <n> not checked', and a list of reasons, each with 'hide in table'.
- Move chip compare below the panel and close it: 'Extending an existing chip? Compare it ▸', with upload of a manifest or 'Use the demo chip (synthetic)'. When a chip is attached, show 5 tiles, the coverage figure, the top 5 gaps and a TSV link instead of 20 rows. If the chip is the demo chip, the section heading says 'synthetic'.
- Replace 'pending decision by G and the breeding partners' with 'under review'.

### Results > Export

**Target:** ≤150 words. One scope choice and 5 download rows. Each vendor row shows its own include count and only that file's checks. 'More formats' and 'About vendor files' are closed. GWAS jobs lead with the GWAS files and keep one KASP/Agena row for the credible-set SNPs.

- Scope default: 'Filtered table (<n>)' when Table filters are active (the existing scope=filtered), else the latest panel for the current trait, else 'All SNPs (<n>)'. Name panels by n_selected ('28 markers · maturation · 6 Oct') and list only the current trait's panels.
- Visible rows: Table (TSV) · KASP / Agena · Illumina · Axiom · Everything (zip). Each vendor row says '<n> of <N> included (<m> left out: assay fail or not checked)'. Today that drop is explained only in the fine print.
- Vendor checks, shown per file for every scope including All SNPs, and worded neutrally beside the file they apply to. Illumina: Infinium bin sizes, and '<n> SNPs within 60 bp of another'. Axiom: 'within 60 bp' and 'alleles unknown <n>'. KASP / Agena: 'alleles unknown <n>'. Error codes (111/340/604) move to Help. Copy the check results into the zip's provenance file.
- Under a closed 'More formats': Parquet, BED, the provenance and lookup files, 'without # provenance lines', and 'Keep SNPs that fail the assay check or are not checked, flagged'.
- Replace the ~230 words of fine print with: 'Vendor files use names like Ssa25p28996360; the lookup file maps them back to your ids. Confirm the layout with your vendor. Details →' (Help#exports).
- GWAS jobs: lead with 'Fine-mapping (TSV): every SNP in a locus with tier score and PIP under both priors', then 'Loci (TSV)', 'Loci (BED)' and 'All SNPs (TSV)'. Add one row, 'KASP / Agena: credible-set SNPs (<n>)', with its checks, or a 'Score these credible-set SNPs as a list →' link (reuse create_from_rows / candidates/). Hide the other vendor rows.
- Show at most one synthetic notice, and only when synthetic data is in the selected files.
- Leave the full TSV's column order and contents as they are. The reorder and the beta/se/p join are deferred, because they are features and would break scripts.

### Results > Association (GWAS)

**Target:** ≤160 words of prose, with the Manhattan plot above the fold at 1440x900. In order: header with Trait, one QC line, Manhattan, an 8-column Loci table with one clumping line, one PIP caveat line and the PIP figure, then a closed QQ plot and closed 'Fine-mapping settings'.

- QC becomes one line: '209,327 rows read, all kept · beta/se on all · λGC 1.07 · 186 SNPs at p < 5e-8 · smallest p 3.3e-30 · alleles on Ssal_v3.1. QC details'. It opens by itself if rows were dropped, beta/se is missing, p was read as text, or alleles failed or mismatched the genome. The 30-word allele/p-as-text note moves to Methods.
- Settings: only Trait stays visible, in the header; PIPs depend on it. 'Fine-mapping settings ▸' is closed and holds Significant p, Suggestive p, Window ± kb, Prior effect SD, Functional λ and Trait SD, with 'Defaults are provisional.' Remove '(weights.yaml finemap)'. The QQ plot is plain: drop the strata control.
- Manhattan comes first, then the Loci table.
- Loci table, 8 columns: Locus (number plus suggestive/LORe badges; links to the regional plot) · Lead SNP (id only) · p · beta (se) · SNPs (sig.), e.g. '1,836 (25)' · Top SNP by PIP (uniform prior; add '→ <id> (functional)' only where the functional prior picks a different SNP; tier badge, id linked to its card) · Gene · 95% credible set (uniform → functional, e.g. '16 → 13'). Drop 'tier 1–2 near lead' and 'Best functional candidate' once G agrees. Remove the per-row 'browser' link.
- Clumping line: 'Loci: SNPs within ±<window> of each lead with p < <suggestive>, strongest first, by distance only (no LD). Long-range LD in farmed lines can split or merge loci.' Fill it from the current settings.
- Cut the fine-mapping table and its 45-word formula paragraph. Above the PIP figure, one line: 'One causal variant per locus, no LD: PIPs depend on the prior SD and λ, and the functional prior on provisional weights. Method →'. Rename the PIP figure's H2 to 'How the functional prior shifts PIPs', so the page has no duplicate H2.
- Close the QQ plot by default.
- Header: replace the Loci TSV, Loci BED and Fine-mapping TSV buttons with one 'Export' link to the Export tab.
- Caveats: one line from the header partial (with SYNTHETIC on synthetic jobs), and no PROVISIONAL badges in section headings.

### Association > Regional plot

**Target:** One title, the locus chips, then a plot whose association lane is the largest track, one PIP caveat line, then the locus's credible-set table covering both priors. No banner beyond the shared caveat line.

- H1: 'Locus 1 · 25:28,951,079-29,051,079 · lead 25_29001079_T_C'. Drop the card H2 'Regional association' and the SVG's own title line on screen.
- Remove the info banner. The legend keeps 'No LD used: colours are tiers, not r²'.
- Make the −log10 p lane about 250 px. Tracks: genes, published loci, the trait's chromatin rows (all 21 only for 'all') and GERP. Drop the ATAC lanes and the public-variant ticks; 'Open in the locus browser' stays.
- Under the plot, one line: 'One causal variant, no LD: PIPs depend on the prior SD and λ.' Then the credible-set table: every SNP in the 95% set under either prior (the sets differ, e.g. locus 4: 16 → 13; locus 8: 49 → 64). Columns: SNP with alleles (linked to its card), p, tier, PIP uniform → functional, and In set (uniform / functional / both). Show the first 10 rows, then 'Show all'.
- Keep provenance only in the exported SVG; remove the 2 provenance lines inside the SVG and the figcaption on screen.

### Evidence card and Variant page

**Target:** ≤180 visible words, or ≤220 with a catalogue caveat. In order: title with one Copy button; the tier line; the GWAS line (GWAS jobs); the known association with its caveat; the chromatin grid or one line saying what was sampled; a slim mini locus view; one assay line; one population line; then closed Expression, Your columns and Details sections.

- Use one title: drop the H2 that repeats the H1. Keep one Copy button: 'Copy 25-28996360-C-T'.
- Tier line: 'Tier 2 · CDS (amino-acid effect not computed) +3' when one evidence term fired. Show the score bars only when 2 or more terms fired. Tier 4 reads 'Tier 4 · no evidence found (not evidence of no effect)'.
- GWAS jobs: one line under the tier: 'GWAS: p 2.6e-30 · beta 0.443 (0.039) · locus 1 · PIP 0.32 → 0.68 (functional prior) · in 95% credible set (one causal variant, no LD)'. Look up gwas.parquet by file_row_number and reuse the fine-mapping in association.py.
- Known association, said once: '★ vgll3_Met54Thr (age at maturity) at this position. Missense; effect allele T (alt) = early maturation (1SW). rs863754587 · doi:10.1038/nature16062 · doi:10.1371/journal.pgen.1005628. Nearby: vgll3_Asn323Lys (2.1 kb), vgll3_tag_SW2020 (16 kb).' When the catalogue row has a caveat, show it as a badge plus its text, e.g. 'knockout had no major effect', 'position inferred', 'suggestive only'. Drop the separate effect-allele badge and the repeated sentences. Fix the variant page's 'Effect allele T. early maturation.'
- When no condition has a peak, replace the 21-cell grid with one line: 'No AQUA-FAANG peak in the 21 conditions sampled (brain, gonad, liver, muscle, 5 embryo stages; 12 AquaGen fish). No immune tissue, gill or skin.' For a blacklisted SNP, add: 'Blacklisted region: no peak here means can't tell, not inactive.' Move this note out of Help before Help's glossary is cut.
- Mini locus view: genes, the trait's chromatin rows and (GWAS) the association lane. Drop the 8 ATAC lanes; 'Open in the locus browser' stays under it.
- Assay: one line, e.g. 'Assay: warn (homopolymer of 7; A/T or C/G SNP)', plus 'Probe flank ▸' with the sequence and a Copy button. Remove the duplicate GC/repeat row from 'Region and elements' and the separate Flags section.
- Replace the 63-90-word population paragraph with: 'MAF from 504 public fish, wild and farmed, pooled; your strain can differ. Chromatin from 12 AquaGen fish. About the data →'.
- Close Expression by default and label it 'Expression of the nearest gene (not necessarily the target) ▸'.
- Replace 'All other columns' with a closed 'Your columns ▸' that shows only the user's uploaded columns, under their original names. Drop the internal columns.
- Show the molQTL section only when the SNP is a lead SNP.

### Gene page /snp/gene/<id>/

**Target:** ≤300 visible words. Gene facts, known loci (with their caveats), expression and the locus figure above the fold. The 10 best variants. The element grid closed.

- Delete the About rows that repeat the subtitle: Ensembl id, location, strand, biotype.
- Public variants: show the 10 best by tier, then 'Show all 131', and keep 'Score these 131' and the TSV download. When every row has the same known-locus name, state it once above the table and hide the column.
- Close the regulatory-element grid by default: 'Regulatory elements near this gene (14) ▸'. The locus figure already draws these states.
- Remove the 'Score an interval' form at the bottom; that is now the 'Genes or regions' tab on Score.
- Remove the developer note 'curated ohnolog pairs come later'.

### Known loci

**Target:** ≤100 words before the first table. 8 trait tables, with Evidence and Effect in one cell and each row's catalogue caveat visible. The ohnolog list closed.

- Intro: '37 published entries for 8 traits: 36 SNPs and 1 gene region. Effect alleles are stated for 12, on the Ssal_v3.1 forward strand. Your SNPs within 50 kb of one get a known-locus badge. Hover a badge for the paper's wording.' Fill the counts and the 50 kb window from the shared helper and the release settings.
- Close the ohnolog box: '11 genes here have a second copy from the salmonid duplication (Ss4R): check the chromosome ▸'.
- Merge Evidence and Effect into one cell: a badge plus one line, e.g. 'missense · T (Met54) = early maturation (1SW)'. Only the 'candidate causal' wording moves to the badge tooltip.
- Keep the caveat column visible on the 17 rows that have one, as a small badge plus its text, e.g. 'knockout had no major effect', 'position inferred', 'suggestive only', 'Tasmanian / Chilean Lochy strain', 'A/B alleles only'.
- Move the ICSASG_v2 position into the row's Notes and keep it in the TSV; breeders matching old v2 arrays need it.
- One count helper feeds the landing page, the header and the intro, so all three agree.
- Remove 'catalog/known_loci.tsv' and 'until G has vetted the rows'.

### Locus browser

**Target:** Core unchanged: inputs, zoom and the figure above the fold. Opens on vgll3 instead of an empty region.

- When no region is given, open at 25:28,985,000-29,010,000.
- Under a closed 'Display options ▸': Signal rows, ChromHMM genome-wide, scale each signal row, and the chromatin palette toggle (its only home, moved from the footer).
- Shorten the 130-word caption to the legend and remove the 'tracks.yaml' mention.

### Printable report

**Target:** Two A4 pages. Title and one caveat line (which says SYNTHETIC when the job is synthetic), 4 key numbers, Top 20 SNPs, 2 figures, a ≤60-word method summary with a link, a short list of data-source references, and a 3-line provenance block.

- Banner: 'Prototype scoring: tiers rank annotated evidence, not proven effects; rules are provisional.' Prefix it with 'SYNTHETIC data ·' on synthetic jobs. Remove the config-key list and both 'pending decision by G'.
- Use the same 4 tiles as the Overview.
- Put the Top 20 SNPs straight after the tiles, with the same order and tie note as the Overview top-10; GWAS jobs rank by p.
- Use 2 figures, the tier bar and the genome map, with no download buttons and no captions.
- Replace the 597-word methods paragraph with a ≤60-word summary and the Methods URL.
- References: keep the data-source citations (AQUA-FAANG, Bertolotti 2020, Ensembl 116, GERP, Brekke 2023, EVA). Drop the '(DOI to add)' placeholders or fill them in.
- Provenance goes last: release, 12-character hashes and the equivalent snpscore command.
- Apply the gene label rule (no 'unnamed (human VGLL3)').

### Help

**Target:** ≤600 visible words, mostly closed FAQ items. Help becomes the only place for formats, search syntax, vendor-file rules and privacy detail.

- Order: Quick start (5 lines) → Questions (closed items, e.g. 'My positions are on ICSASG_v2') → Input formats (one closed item per format, taking the Score table) → Search syntax (moved from the landing page) → Exports and vendor files (moved from Export: naming, bin rules, the 60 bp rule, the assay-fail drop and error codes) → Privacy (what is read, what is stored for 24 h, who can see it).
- Delete the Glossary's tier and evidence-term definitions and the Colour key, and link to Methods, where they are defined. Move the blacklist rule onto the card first (see the card).

### Methods

**Target:** ≤700 visible words. One caveat line at the top. Evidence weights, Tiers, Chromatin states (with the colour key merged in), Presets and a short glossary open; raw settings closed; the benchmark as one line.

- Keep one top line, worded like the site caveat line, and delete the 8+ section PROVISIONAL badges under it.
- Keep open: Evidence weights; Tiers (including 'Tier 4 = no evidence found, not evidence of no effect'); Chromatin states, with a colour swatch column so the separate Colour key goes (no palette toggle here); Presets, with each trait's conditions; and the Glossary moved from Help.
- Put the Assay, Design and Finemap settings tables in one closed 'All settings ▸'.
- Replace the benchmark figure with one line: 'Not yet validated against known causal variants (n = 6).' Restore the figure when n is meaningful.
- Close 'Methods text for a paper' down to its summary and Copy button.

### Data

**Target:** ≤450 visible words. One table of layers with 3 columns; technical details closed.

- Per layer, show three columns: What it is · Source · Version. Rows, file, sha256 and columns go under a closed 'Technical details'.
- Replace the 10x10 signal-track table with '666 AQUA-FAANG signal tracks (ATAC, RNA, ChIP) read live from salmobase.org', and put the table in a closed details section.
- Add one line of release statistics, moved from the landing page.
- Keep the sample statements the card links to: 504 public fish (wild and farmed, pooled) for MAF; 12 AquaGen fish for chromatin and molQTL.

### Guided tour

**Target:** 5 steps of ≤80 words each.

- Steps: 1 Known locus (vgll3) · 2 Variant and locus browser · 3 Score and overview · 4 Filter and design a panel · 5 Your own list.
- Cut developer wording such as 'sorts and pages on the server, so it stays quick on 1.6 million rows' and 'reads a summary made once when the job finished'.
- Use the same privacy wording as Score in step 5.

### Run locally and Search

**Target:** Already lean (Run locally ~230-320 words, Search ~60-150). No change beyond the site-wide footer and caveat line.

- Leave as is.

## Cut, hide or keep

### Cut (48)

| Item | Why |
|---|---|
| Landing: 7 release-stat tiles | They don't help anyone get a result. One line moves to the Data page. |
| Landing: 8-row known-loci table | It repeats the nav item and the Known loci page; one link line replaces it. |
| Landing: 5 nav cards | They repeat the top nav. Two buttons replace them: 'Score your SNPs' and 'Take the tour'. |
| Landing: 50-word search syntax paragraph and 3 of the 7 chips | The chips teach by example; the full syntax moves to Help#search. |
| Score: four 'Trait preset' selects | Every preset is precomputed (jobs.py writes tiers.parquet per preset) and the trait is switched on the results page, so asking up front adds a decision for nothing. |
| Score: 'Your data' box | Cut to one accurate line. Only VCF genotypes go unread; other table columns are stored for 24 h and visible to anyone with the link. The full detail is in Help → Privacy. |
| Results header 'Download TSV' button | It is the third of 3-4 TSV entry points. Export and the Table's filtered links remain. |
| Preset Apply button and the 'rules are PROVISIONAL' text beside it | The select applies on change, and the page's caveat line carries the caveat. The Trait tooltip now names the conditions used. |
| Inline PROVISIONAL badges, 'P' tile markers and caveats in captions and headings | Repeated up to 23 times a page, it becomes noise. One line per page, rendered by the shared header partial, plus the exported files keep the caveat. It now also says what tiers are not: proven effects. |
| Repeated SYNTHETIC badges (H1 badge, captions, section notices) | One line per page (merged with the caveat line) plus the figure watermark. It comes from the header partial, so the card, regional plot, drawer and report of a synthetic job are labelled too. |
| Overview KPI tiles: in active element, coding, MAF ≥ 0.05, molQTL lead (display only), upload warnings = 0 | Each repeats a chart, is display-only or reads 0 as an alert. Warnings show only when above 0. Cutting the molQTL tile needs no sign-off; it is display only. |
| Overview: Largest gap per chromosome chart | The panel genome figure's gap highlights and the chip-compare gaps cover what matters. |
| Overview: Assay flags table | It is the 5th view of the same assay numbers; the assay card's reasons and the Assay filter replace it. |
| Per-figure on-screen provenance caption | Identical under every figure. It stays in the exported SVG/PNG/TSV, where it matters. |
| Footer sha256 provenance lines and data-source list | About 40-75 words on every page, already in every download, the report and the Data page. A data credit of 8 words or fewer stays in the footer. |
| 'salmobase · dev' top bar (kept: release pill) | The release is labelled twice in the chrome. |
| 'pending decision by G' and other internal file or person names | Internal project language. 'Under review' replaces it; the config detail stays under Methods → All settings. |
| Table: always-reserved evidence side pane | It takes 25% of the width and pushes MAF and Assay off-screen. It opens as a slim drawer (no mini locus view) when a row is clicked. |
| Table: 'Download all (TSV)' (kept: 'Download these N (TSV)', added: 'Vendor files for these N →') | The full TSV is on Export. The new link reuses Export's existing filtered scope, so tier 1–2, assay-pass SNPs become a KASP file without designing a panel. |
| Table: 'Keys: j / k' hint | Low-value text; the keys still work. |
| Panel: Tier mix, Spacing histogram and Largest gaps charts | They restate the KPI line and the genome figure's gap highlights. |
| Panel: 'Why each marker was chosen' chart | It becomes a 'Reason' column in the marker table. |
| Panel: 7-button download row and second 'Printable report' button | Replaced by 'Export this panel →', which opens Export with the panel selected. |
| Panel: '⚠ vendor design rules broken' box | The checks move next to each vendor file on Export, where the choice of vendor is made. |
| Hash-named panels and one listed panel per viewed preset | Plain names ('28 markers · maturation · 6 Oct'), and only the current trait's panels are listed. |
| Full TSV column reorder and beta/se/p join for GWAS | Deferred: a feature, not a simplification, and it breaks scripts that index columns by position. |
| GWAS jobs: Panel tab, Illumina/Axiom rows, and the assay, gap, MAF and where views on the Overview | They describe a genotyping array, not the association, and the panel ignores p, which can mislead. |
| Association: QQ strata toggle | A plain, closed QQ plot is enough; strata is a feature for later. |
| Association: separate fine-mapping table and formula paragraph | Credible sets already appear in the Loci column, the PIP figure, the regional table and the Fine-mapping TSV. The formula moves to Methods. |
| Association: tier-based 'Best functional candidate' and 'tier 1–2 near lead' columns | They conflict with the PIP top SNP at loci 3 and 7. Needs G's OK, since it is a method choice. |
| Association: per-locus 'browser' link | It opens the same SVG as the regional plot. The locus number links to the regional plot, which links on to the browser. |
| Association header: Loci TSV, Loci BED, Fine-mapping TSV buttons | The files move to the GWAS Export tab; the header keeps one 'Export' link. |
| Regional plot: info banner, duplicate titles and ATAC lanes | The no-LD caveat stays in the legend and in one PIP line, ATAC stays in the locus browser, and the association lane gets the space. |
| Card: 63-90-word population and data-scope paragraph | One line replaces it, keeping the two facts that matter: MAF is pooled from 504 public fish (your strain can differ) and chromatin comes from 12 AquaGen fish. |
| Card: why-tier score chart for single-term SNPs | One line ('Tier 2 · CDS (amino-acid effect not computed) +3'); the chart stays when 2 or more terms fired. |
| Card: empty 21-cell chromatin grid | One line that names what was sampled (and what was not: immune tissue, gill, skin). The grid stays when there is signal. Blacklisted SNPs say 'can't tell'. |
| Card: duplicate H2 and second Copy button | The id is printed twice in a row. |
| Card: ATAC lanes in the mini locus view | The locus browser is one link away; this cuts about a third of the card's height. |
| Variant page: 2-column layout at ≥1200px | Deferred: a layout feature, not a simplification. |
| Gene page: About rows repeating the subtitle, and the dev note | Duplicate facts and internal wording. |
| Known loci: separate Evidence and Effect columns | Merged into one cell; each row said 'missense' and the effect twice. |
| Report: 597-word methods paragraph and '(DOI to add)' placeholders | Unfinished citations on paper look unprofessional. A ≤60-word summary and the Methods URL replace them. |
| Report: full 64-character sha256 values, and figure download buttons | 12-character hashes in a provenance block at the end; the full hashes stay in the downloads. |
| Help: glossary of tiers and evidence terms, and colour key | They duplicate Methods, which becomes their only home. The blacklist rule moves onto the card first. |
| Methods: separate Colour key | Merged into the Chromatin states table as a swatch column, so Methods fits in 700 words. |
| Methods: benchmark figure (n = 6, smoke test) | The figure is replaced by one honest line, 'Not yet validated against known causal variants (n = 6)', not hidden silently. |
| Tour: 8 steps of ~140-330 words | 5 steps of ≤80 words, without implementation details. |
| Special layout for small lists (open on Table under ~500 SNPs) | Not worth a second layout: the top-10 table and the 'hide empty figures' rule cover small lists. |

### Hide behind one click (advanced) (28)

| Item | Why |
|---|---|
| Gene/interval public-variant scoring form (landing, and 'Score an interval' on the gene page) | An advanced route that now appears in 3 places. It becomes one 'Genes or regions' tab on Score; the gene page keeps 'Score these 131'. |
| Score: 5-row formats table | It repeats Help. One line and a link replace it. |
| Score: GWAS summary-statistics form | A different task with different outputs. It moves to its own GET page, with the same privacy line, linked by one line. A closed section stays on Score until that page exists. |
| Score: 'Demo chip SYNTHETIC' example | Scoring a fake chip as a list confuses newcomers. It moves to Panel → chip compare, labelled synthetic. |
| Overview: Genic region by tier, Evidence behind the tiers, Minor allele frequency charts | Analyst diagnostics, under a closed 'More charts (3)'. |
| Overview: Upload QC block | One line when all is fine. It opens by itself on any problem: fewer scored than read, rejects, merged duplicates, indels or multiallelics, unknown chromosomes, unplaced or moved rs IDs, alias warnings, assembly or reference-allele problems. |
| Per-figure SVG/PNG/TSV buttons | One ⤓ menu per figure: 27 buttons on the Overview become 9 icons. |
| Footer chromatin-palette toggle | A niche preference. It moves to the locus browser's Display options only. |
| Table: secondary filters (Region class, Active in, Evidence, known loci only, molQTL, leftover hide options, Columns, Rows) | Under 'More filters (n active)', which opens by itself when used. Bookmarked URLs keep working. |
| Table: Position, molQTL and Flags default columns | Position repeats the SNP id, molQTL is display-only and the Assay badge carries the flags. All stay under Columns. |
| Panel designer: backbone share, MAF, per-gene and per-element caps, cM spacing, cM map, gap highlight, leftover exclude checkboxes | The defaults make a good panel. Markers, min spacing, Assay and must-include stay visible. |
| Panel: Selected SNPs table rendered with all 384 rows | The first 25 rows, then 'Show all'. This cuts the tab from about 6,400-7,000 words. |
| Panel: compare with an existing chip | Valued by people extending a chip, so it stays, closed below the panel. The gap table shrinks to the top 5 plus a TSV link, and the demo chip is labelled synthetic in the heading. |
| Export: Parquet, BED, provenance and lookup files, 'without # lines', 'keep failed SNPs, flagged' | Under 'More formats'; the zip bundle already contains the extra files. |
| Export: ~230 words of vendor fine print | Two lines stay. Bin rules, the 60 bp rule, naming and error codes move to Help → Exports; the assay-fail drop is now on each vendor row. |
| Association: threshold and prior settings form | Under a closed 'Fine-mapping settings'. Trait stays visible because PIPs depend on it. |
| Association: 10-row Summary statistics QC table | One summary line that opens by itself on problems, so the Manhattan plot moves above the fold. |
| Association: QQ plot | A diagnostic, closed by default. |
| Card: 'All other columns' dump | A closed 'Your columns' keeps the user's own uploaded columns under their original names. The internal columns are cut. |
| Card: raw assay keys, duplicate GC/repeat row, separate Flags section | One assay line, with the probe flank under 'Probe flank ▸'. |
| Card: expression section | Closed, and labelled 'nearest gene (not necessarily the target)', so it isn't read as the SNP's own effect. |
| Gene page: 131-row variant table | The 10 best by tier, then 'Show all 131'; 'Score these 131' stays. |
| Gene page: 14x21 regulatory-element grid | Closed by default; the locus figure draws the same states. |
| Known loci: Ss4R ohnolog box | A one-line warning stays visible; the 11 Ensembl-id bullets go into a closed section. |
| Known loci: ICSASG_v2 column | Moved into the row's Notes and kept in the TSV for breeders matching old v2 arrays. |
| Locus browser: signal rows, genome-wide ChromHMM and scaling options | Under 'Display options'; the figure is the page. |
| Methods: Assay, Design and Finemap settings tables | Under one closed 'All settings'. |
| Data: per-layer file, rows, sha256 and columns; 10x10 signal-track table | Under 'Technical details'; the visible table is What · Source · Version. |

### Keep (or add, small) (28)

| Item | Why |
|---|---|
| Landing: vgll3 hero figure | It shows what the portal does in one picture and leads into the tour. |
| Score: known-loci and 50k examples | One-click results are the best onboarding. Known loci is the primary example and 50k the secondary. |
| Short qualifiers next to the numbers they qualify (tier 4, no-peak scope, CDS, PIP, catalogue caveats, pooled MAF, LD clumping) | Each one changes how a number is read and is 15 words or fewer. Without them the simpler page would overstate the evidence. |
| Overview: Top 10 SNPs table (from the report) | New on the Overview, built from report.top(). It answers the first question, 'which SNPs?', and says how ties are ordered. GWAS jobs rank by p. |
| Overview tiles that read 0 (Tier 1–2, Near a known locus) | 0 tier 1–2 or 0 near a known locus is a finding, not empty space. |
| Overview: SNPs per tier, Where the SNPs are, Active chromatin per condition | They answer 'how many good SNPs, where, in which tissues'; chromatin is the portal's core evidence. |
| Overview: Assay design status and Why SNPs warn or fail | Merged into one 'Assay readiness' card on the Panel tab, where assay decisions are made. Assay pass stays as an Overview tile. |
| Table and Panel: Assay select (All · Pass + warn · Pass + warn, no LORe · Pass only) | It decides what goes on a chip, and LORe probes may cross-hybridise. It stays visible and is the same control on both tabs. |
| Table: alleles in the SNP cell ('AX-123 · C>T') | Ref/alt are not among the 9 default columns, but A/T or C/G and KASP design depend on them. They cost no extra column. |
| Panel shortfall alert ('Only 28 of 384 markers could be chosen: …') | It is the most important thing on the tab when it fires. Panel names and headings use n_selected, never the target. |
| Panel KPI '% assay pass' | Added to the KPI line; it is the first number a lab lead checks. |
| Panel: Panel markers along the genome figure | It shows coverage and gaps in one view. |
| Export: filtered-table scope | It already exists (tools.py _scope). It is the default when Table filters are active: filtered, then latest panel, then all. |
| Export: TSV, KASP/Agena, Illumina, Axiom and zip bundle | The core 'send it to the vendor' task. Each vendor row now says how many SNPs it includes and why the rest were left out. |
| Export: per-file vendor checks (Illumina bins, within 60 bp, alleles unknown) | Shown beside the file they apply to, for every scope including All SNPs, worded neutrally, and copied into the zip's provenance file. |
| GWAS jobs: 'KASP / Agena: credible-set SNPs' row (or 'Score these credible-set SNPs as a list') | The one route from a GWAS hit to a lab assay, so GWAS users are not left with no vendor path. |
| Association: Manhattan, Loci table and PIP slope figure | The core GWAS result. The Loci table drops from 12 to 8 columns. |
| Association: top SNP and credible-set size under both priors | The functional prior rests on provisional weights (prior ratio up to 54.6×). Showing only its pick would hide that. The uniform pick shows, plus the functional one where it differs. |
| Association: clumping note's LD caveat | Long-range LD in farmed lines can split or merge loci. One clause. |
| Regional plot: 95% credible-set table (both priors) | New here, moved from the Association page. This is where the SNP to validate is chosen, so it lists both sets and marks each SNP's membership. |
| Card: GWAS stats line (p, beta, se, locus, PIP, credible set) | New and short. Today these values exist only as unlabelled plot points. It carries the one-causal-variant, no-LD qualifier. |
| Card: catalogue caveat on the known-association line | 17 of 37 catalogue rows carry one (e.g. 'knockout had no major effect'). The card's word budget allows for it. |
| Known loci: caveat column (17 of 37 rows) | Strain-specific, inferred-position or 'suggestive only' rows must not look as solid as the vgll3 SNPs. |
| Known loci catalogue and per-trait tables | High value to both breeders and geneticists. |
| Report: data-source references (AQUA-FAANG, Bertolotti 2020, Ensembl 116, GERP, Brekke 2023, EVA) | A printed report must credit its data. |
| Nav: 'Explore' label and its empty start | Renamed 'Locus browser' and opening at vgll3. Data, Methods and Help merge into one Help menu. |
| Jargon tooltips (MAF, LORe, A/T or C/G, molQTL, GERP, state names, Trait conditions) | New tooltips that add no visible text and help newcomers. |
| Run locally and Search pages | Already lean. |

## Risks and sign-offs

- Biology and method calls belong to G (CLAUDE.md). Get G's OK, and record it in CLAUDE.md, before shipping: dropping the tier-based 'Best functional candidate' in favour of the PIP top SNP; the tier hint wording; the Top-N tie-break (known locus, assay pass, MAF), with ties labelled until then; and whether the footer data credit is enough for AQUA-FAANG and salmobase. Dropping the molQTL tile needs no sign-off; it is display only.
- Caveats lost in the cut. If the badges go before the caveat line, the qualifiers and the synthetic header partial are in place, a build ships overstating the evidence. Land them in the same commit. A cropped screenshot of one figure or tile no longer carries PROVISIONAL or SYNTHETIC, so keep the caveat in exported figures and files, the synthetic watermark, and the report banner, which must say SYNTHETIC on synthetic jobs.
- Unlabelled synthetic pages. The SYNTHETIC line is only as good as the partial's coverage. Check that the card opened directly, the regional plot, the Table drawer, the report and chip compare with the demo chip all carry it.
- Word budgets against honesty. The qualifiers add about 10-40 words on the card, the Known loci page and Association. The budgets allow for this (card ≤220 with a caveat). When a page still runs over, cut layout text, not qualifiers.
- Hidden active state. If 'More filters' and 'Advanced settings' do not show '(n active)' and open by themselves when anything is non-default, users will read filtered tables or custom panels without knowing it. Ship the auto-open with the collapse, not later; compute n_active on the server.
- QC lines that open by themselves must trigger on every real problem: fewer scored than read, rejects, merged duplicates, indels or multiallelics, unknown chromosomes, unplaced or moved rs IDs, alias warnings, assembly or reference-allele mismatches, and dropped GWAS rows or failed alleles. Otherwise collapsing them hides failures.
- A Top 10 can still look like a verdict. With 15-19 SNPs tied at the top score in the GWAS example, order is arbitrary until the tie-break is agreed. Keep the tie label until then, and rank GWAS lists by p.
- Removing the preset select from Score depends on every preset being precomputed (jobs.py writes tiers.parquet per preset; association uses ?trait=). The GWAS example must open with trait=maturation.
- Moving GWAS off Score needs a new GET page at /snp/score/gwas/, and association.score's error renders must point at it. Until it exists, keep a closed GWAS section on Score.
- GWAS jobs lose the Panel tab and the Illumina/Axiom files. Only the credible-set KASP/Agena row remains; anyone wanting a full panel from GWAS hits must rescore them as a SNP list.
- Vendor checks now sit beside each file. Someone who downloads only the zip could miss them, so copy the check results into the zip's provenance file.
- Other engineers are fixing bugs in the same templates now. Land this plan after their fixes, as small per-page commits ('simplify: <page>') that each list what moved where, so conflicts stay small and each cut can be reverted on its own, as the owner wants.
- Discoverability. Moved features (GWAS, chip compare, Parquet/BED, palette, settings tables, Your columns) will prompt 'where did X go?' questions. Each has exactly one visible link where it used to be; watch early feedback before cutting further.
- Count consistency. The catalogue has 37 rows (36 SNPs and 1 presence/absence gene region; 8 traits; effect alleles for 12; caveats on 17), and the known-locus window is 50 kb. Generate the counts and the window from one helper and the release settings, or the landing page, header and intro will drift apart again.
