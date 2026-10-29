# Research sweep: data sources, gaps and corrections (2026-10-06)

Six research lenses (genetic map, known loci, liftover and allele frequencies, vendor formats, AQUA-FAANG, comparable portals),
each spot-verified by a second agent, then synthesised. Paths like `verify/...` refer to the session's scratch folder; the files
that matter are being folded into this repo by Push 2 (see ROADMAP.md 'Push 2' and TRACKER.md).


Synthesis dated 2026-10-06. It draws on six verified research reports: genetic map, known loci, liftover and allele frequencies, vendor formats, AQUA-FAANG, and portal gaps. It also includes four new checks made for this synthesis, marked **[new check]**.

No file in `salmo-snpscore` or `salmo-snpportal` was changed. Scratch paths below are relative to `/private/tmp/claude-501/-Users-gagi-git-salmo-snpscore/6570252b-1d06-4c10-b640-f679ca04e7ee/scratchpad/research/`.

Conventions:
- Effort uses the ROADMAP scale (S/M/L).
- Thresholds quoted from papers are precedents, not decisions. Under CLAUDE.md, biology and policy calls belong to G.
- Byte sizes are HTTP Content-Length values or the size of the downloaded file.

## 0. At a glance

| # | Push | Recommendation | Roadmap items | Effort | Waiting on G |
|---|---|---|---|---|---|
| 1 | Genetic map | Use the Brekke 2023 map, which is already on Ssal_v3.1 and needs no lift, as an interval layer with interpolated male and female cM | P6.9, P6.3 | S (layer) + S (cM spacing) | Which sex to show; how to treat unmarked chromosome ends; whether to use the male map on chr 2, 8 and 17 |
| 2 | Known loci | Grow the catalogue from 6 to 36 rows across 8 traits. 12 rows have a stated effect allele. | P5.3, P1.7 | S–M | Vetting the rows; QTL intervals |
| 3 | Liftover | Now: join EVA release 9 v2 and v3.1 on rs ID, which also delivers rsID search. Later: offsets from the NCBI Remap GFF. | P2.5, P5.12, P2.1 | S now, M–L later | Whether partners need it |
| 4 | Population AF | **Fix P6.1's AF source** (new finding: the fixture AF is not the 504-fish AF). Use the 504-panel INFO AF. A second population could come from PRJEB34225 via the rs bridge. | P6.1, P6.10, P7.6 | S (fix), M (second population) | Permission to host; how to describe the population |
| 5 | Vendor exports | 13 spec changes to the "now" items P6.2 and P6.4, plus a reference TOP/BOT oracle | P6.2, P6.4, P4.5 | S | Current templates from the genotyping lab |
| 6 | AQUA-FAANG | Exact itemRgb colour table, citation block, ENA accessions and fish metadata | P4.3c, P5.4, palette | S | Colour choice; citation wording; state definitions |
| 7 | molQTL | Real lead-SNP point layer from nf-RASQUAL at weight 0. **Coloc (P7.8) cannot run on these tables.** | P4.6, P7.8 | S–M | Licence; significance rule; asking the authors for full outputs |
| 8 | TF motifs | Score 838 JASPAR2022 PFMs on ref and alt, rank by AQUA-FAANG maelstrom activity, display only | P5.9 | M | p-value threshold; motif scope |
| 9 | Missing features | Ranked list in §9 | various | S–M | Some items |

Section 10 lists roadmap text that the research contradicts. These corrections should go to the engineers who are building P6.1, P6.2 and P6.4 now.

---

## 1. Genetic map (cM) layer: P6.9

**Recommendation.** Build the layer from **Brekke et al. 2023** (Sci Rep, [10.1038/s41598-023-47208-3](https://doi.org/10.1038/s41598-023-47208-3), CC BY 4.0). Use the full map from the bioRxiv v2 supplement, because the journal supplement only points to a missing `S1_Table.xls`.
- It is the only public pedigree map found that is already on Ssal_v3.1 with chromosome names 1–29, so it needs no liftover.
- It gives sex-specific cM.
- The fish are the Norwegian AquaGen breeding population: "founders from 41 Norwegian rivers" and 5,568 full-sib families. The map was built with LepMap3 using genome order and the Haldane mapping function.

Add Gao et al. 2023 (North American) later, only if G wants a second lineage.

**Data source.**
- URL: `https://www.biorxiv.org/content/biorxiv/early/2023/08/21/2023.06.07.543993/DC1/embed/media-1.txt?download=true`
- Size and licence: 1,346,167 B. The bioRxiv API gives `cc_by` for v1 and v2. Re-fetched today: HTTP 200, served chunked with no Content-Length.
- Columns: `chr snpid Mb male_cM female_cM`. **The `Mb` column holds base pairs.**
- 34,842 markers; the paper says 35,032. Per-chromosome cM lengths and the totals match Table 1 exactly: 1,482.96 cM male and 2,173.80 cM female.
- Positions are sorted and cM never decreases. There are no duplicate IDs or positions. Median marker spacing is 33.5 kb.
- Local copy: `cm/brekke_map.txt`.

**[new check] Brekke coordinates validated against independent data.** The report had called the coordinates uncheckable, because the file has only Affx IDs.
- I sampled six 6 MB BGZF chunks of the salmobase 504-fish VCF by HTTP Range (chr 2, 6, 10, 11, 14, 19 and 25), plus the chr1 head.
- **675 of 1,056 Brekke markers (64%) in those spans sit exactly on a 504-panel SNP. Random positions in the same spans hit 0.3–0.5% of the time.**
- That is strong evidence the positions are Ssal_v3.1 coordinates. The misses are expected: the 504 panel keeps only MAF > 0.01 sites that pass the HWE filter.
- Script: `synth/brekke_vs_504.py`. A position check against the CGD array VCF found 0 overlaps, so the two arrays share no SNP positions.

**Build plan** (fits the existing interval layer and ASOF join, `start < pos <= end`):
1. Have `snpscore fetch` download media-1.txt.
2. Turn each pair of consecutive markers on a chromosome into one BED interval: `start = pos_i`, `end = pos_{i+1}`. Store `cm_m0, cm_m1, cm_f0, cm_f1` on each interval. There are no duplicate positions, so no interval has zero length.
3. Add a flat interval `[0, pos_1]` and a flat interval `[pos_n, chrom_len]`, each with `extrapolated = true`. Chromosome lengths come from the local `.fai`.
4. In annotate, compute `cM = c0 + (pos - start) / (end - start) * (c1 - c0)` in SQL. Output `genmap_male_cM` and `genmap_female_cM`, and a sex-averaged mean only if G wants it.
5. P6.3 already plans a pluggable distance metric. The cM distance between two SNPs is the difference of their interpolated values. Because cM never decreases, the P6.9 monotonic acceptance test passes by construction.

**Effort.** S for the layer: one fetch entry, a small prep step, one `layers.yaml` entry and one SQL expression. Plus S for cM spacing in the panel.

**Risks.**
- **Unmarked chromosome ends.**
  - Right ends: chr17 12.1 Mb, chr5 10.9 Mb, chr3 8.2 Mb, chr2 6.9 Mb, chr8 6.6 Mb.
  - Left ends: chr4 6.4 Mb, chr17 5.7 Mb, chr6 4.1 Mb, chr2 3.3 Mb.
  - Male crossovers cluster near the telomeres, so a flat cM there understates male distances.
- **Male map on chr 2, 8 and 17 is nearly flat:** 19.54, 2.01 and 3.79 cM. The authors write that they "are unable to pick up all crossovers in males on these chromosomes".
- The marker count differs from the paper (34,842 vs 35,032), with small per-chromosome differences, although the cM lengths match.
- It is a single population, a Norwegian farmed strain.

**Alternatives checked.**
- **Gao 2023, North American** (figshare S2 `https://ndownloader.figshare.com/files/40063042`, 1,587,141 B, CC BY 4.0; HEAD returns 403, ranged GET returns 206). It needs a flank lift; a chr22 pilot placed 90% uniquely with r 0.997 against Brekke. Its fused groups LG8, LG12 and LG20 span two Ssal_v3.1 chromosomes each.
- **Tsai 2016** (UK, ICSASG_v2, de novo order). More order errors in the pilot (6.4% male, 10.9% female), and its maps are inflated (4,769 / 7,153 cM).
- **Raynaud 2025** gives LD-based ρ, not cM.

**Open questions for G.**
1. Brekke only, or also the North American map (Gao)?
2. Default to sex-specific or sex-averaged cM?
3. Unmarked ends: hold cM flat, or extrapolate at some rate?
4. Use the male map on chr 2, 8 and 17, or fall back to female or averaged cM there?

---

## 2. Known-loci catalogue expansion: P5.3 and P1.7

**Recommendation.** Grow the P5.3 catalogue from the 6 benchmark rows to the **36-row corrected candidate file** `verify/known_loci_candidates.corrected.tsv` (17,397 B, 13 columns). Keep `benchmark/known_loci.tsv` (6 rows) unchanged as the test benchmark, so the fixture stays small.
- Merge the new file into the release catalogue. It needs two columns it does not have yet: `ensembl_gene` and `icsasg_v2`.
- Fill `effect_allele` only for the 12 rows where the paper states an allele unambiguously.
- Show every other row as "association, allele not stated".

| Trait | Rows | Rows with effect allele |
|---|---|---|
| Age at maturity (Sinclair-Waters 2020, Ayllon 2015, Mohamed 2019 Tasmanian, Rivera 2026 Chilean Lochy) | 14 | 10 (vgll3 ×2, akap11, six6, vgll3 tag, ndufs4, rora, cntn4, lig1-like, fbxo34-like) |
| PD resistance (Manousi 2025, Aslam 2020, Hillestad 2020) | 7 | 0 (Aslam: the minor allele C has α +0.83 on Ct; sign uncertain) |
| CMS resistance (Boison 2019, Hillestad 2020) | 5 | 0 (Boison AX-97886034: favourable = Affymetrix allele A; nucleotide unknown) |
| IPN resistance (Moen 2015, Houston 2012, Pavelin 2021) | 4 | 1 (cdh1 S167P: C = Pro = resistance; position inferred) |
| Sea lice (Onabanjo 2024; suggestive only) | 2 | 0 |
| Flesh colour (Helgeland 2019) | 2 | 1 (rs863785818: A on the + strand = red) |
| Smoltification (Cairnduff 2024) | 1 | 0 |
| Sex (sdY gene region) | 1 | 0 |

**Key corrections for the catalogue and cards.**
- **vgll3 Met54Thr** is rs863754587 at 25:28996360 C/T, and T (Met) is the early-maturation allele.
  - Ensembl numbers the residue differently. On ENSSSAT00000230965 it is **T46M** (aCg/aTg). The other transcript, ENSSSAT00000085090, gives R43W in another reading frame.
  - Keep the paper's label for display and use the ENSSSAT00000230965 consequence. The offset is 8.
- **vgll3 Asn323Lys** is rs864205331 at 25:28998410, and C (Asn) is the early allele.
  - Ayllon's text says "Asp", but the codons (aaC/aaG) and Mohamed 2019 Table 3 support Asn.
- **vgll3 tag at 25:28980165.**
  - EVA now has the Ssal_v3.1 ID **rs9024526732** (G/A). The corrected TSV still carries the v2-only rs863710280.
  - The paper's "251 kb downstream" holds only on v2. On v3.1 the SNP is about 15 kb *upstream* of vgll3, so never show v2 "distance to gene" labels here.
- **bco1l rs863785818.** The roadmap's "to verify" is resolved: EVA alleles are A/C, so **A on the + strand = red**. The paper reports this as T = red.
- **sdY coordinates** are 1-based NC_059444.1:102,356,407–102,360,988. NCBI Gene now shows a newer assembly (GCF_965601325), so do not take current NCBI Gene coordinates.

**Data sources.**
- The paper supplements are listed in the known-loci report.
- EVA identifiers API: `https://www.ebi.ac.uk/eva/webservices/identifiers/v1/clustered-variants/{rs}`. 23 of the 26 rs IDs were re-queried and matched.
- Ensembl VEP REST: `https://rest.ensembl.org/vep/salmo_salar/region/25:28996360-28996360:1/T?content-type=application/json`.

**Effort.** S to merge and badge the rows. M if the card needs per-row confidence labels and QTL-interval rows.

**Risks.**
- **Inferred positions:**
  - cdh1 is not in EVA.
  - The Pavelin KASP rows use window midpoints, because the genotype supplement is 0/1/2 with no allele key.
  - The smolt marker sits beside a C run that is 13 bp on v3.1 versus 10 bp on v2.
- The Moen 2015 quotes came from a page-summarising fetch. Check them against the PDF.
- **The 50 kb matching window will match one SNP to several rows.** For example, the PD rows sit within 32 kb of each other at 3:95.08–95.12 Mb. Annotate must list all matches or pick the nearest.
- The sea-lice rows are only suggestive (p 1.1e-6 and 2.2e-5).
- The two Mohamed 2019 Tasmanian hits and the two Rivera 2026 Lochy hits are farmed-strain specific.
- 13 items are unresolved (`known_loci_unresolved.tsv`): the nae1 missense, Moen SNP1–3, North American flesh colour, omega-3, fillet fat, CMS chr23 (paywalled), Caligus, the PD/CMS QTL intervals, and growth (no robust lead).

**Open questions for G.**
1. Vet the 36 rows. Should the suggestive and farmed-strain-specific rows appear, and with what badge?
2. Should rows without an effect allele be shown?
3. Which QTL intervals (interval rows) should be added, and from which papers?
4. Include sdY? It is unresolved whether the reference copy is the Y-linked one.
5. Confirm the vgll3 display labels (Met54Thr, with Ensembl T46M shown as secondary).

---

## 3. Liftover table ICSASG_v2 ↔ Ssal_v3.1: P2.5, P5.12 and P2.1

**Recommendation.** Work in three tiers.

1. **Now (S): rs bridge from EVA release 9.**
   - Join the ICSASG_v2 and Ssal_v3.1 rs releases on rs ID in one DuckDB query. Output: `rs, v2_chrom, v2_pos, v31_chrom, v31_pos, ref/alt on each, strand_flip`.
   - This one table delivers P5.12 (rsID search) and the known-variant part of P2.5. It needs no runtime network: P2.5 currently plans calls to NCBI efetch and Ensembl REST, which are outside the runtime allowlist.
   - Most array SNPs are covered. Ssal_v3.1 source-study (SID) line counts:

     | Study | Lines |
     |---|---|
     | AQUAGEN_AQUAGEN_SSA_2015.1 | 748,441 |
     | ROSLIN_HOUSTON_01-15-2014 | 274,680 |
     | PRJEB107807 (CGD array) | 63,791 |
2. **Later (M–L): NCBI Remap alignment** for positions that are not EVA variants, such as published GWAS positions. Convert the GFF `match` rows to a non-overlapping offset table and use an ASOF join. We would have to write the converter, since no GFF→chain tool was found.
3. **Keep `prep/lift_icsasg_v2.py`** (flank match) for chip manifests that include flanks. The chr22 pilot placed 90% of 71-bp flanks uniquely.

**Data sources.** All re-fetched today with HTTP 200.

| File | Size (B) | Notes |
|---|---|---|
| `https://ftp.ebi.ac.uk/pub/databases/eva/rs_releases/release_9/by_species/salmo_salar/GCA_905237065.2/8030_GCA_905237065.2_current_ids.vcf.gz` | 146,249,215 | 15,272,533 rs over 15,362,350 lines; CHROM `ssa01`–`ssa29`, unplaced `contigNNN` |
| `https://ftp.ebi.ac.uk/pub/databases/eva/rs_releases/release_9/by_species/salmo_salar/GCA_000233375.4/8030_GCA_000233375.4_current_ids.vcf.gz` | 184,908,787 | 19,688,093 rs; unplaced sequences named `scf_jcf…` |
| `https://ftp.ncbi.nlm.nih.gov/pub/remap/Salmo_salar/3.0/GCF_000233375.1_ICSASG_v2/GCF_905237065.1_Ssal_v3.1/GCF_000233375.1-GCF_905237065.1.gff` | 239,892,106 | Static since 2022-06-06 (the Remap tool was retired in November 2023). Report: 71.99% best-hit coverage, 13.47% inversion. |
| `https://hgdownload.soe.ucsc.edu/hubs/GCF/905/237/065/GCF_905237065.1/GCF_905237065.1.chromAlias.txt` | 335,127 | refseq / ssa / ensembl / genbank / ucsc names |

The EVA rs files have no allele frequencies. INFO holds only SID, VC and flags.

**Chromosome naming rules for P2.1.** Each rule was checked on all 29 chromosomes.
- `ssaNN`: `int(name[3:])`.
- RefSeq: `int(acc[3:9]) - 59441`.
- GenBank `HG993260+k`: chromosome k+1.
- **GenBank version caveat:** chromosomes 9, 11, 18 and 26 are `.2` in Ssal_v3.1 (HG993268.2, HG993270.2, HG993277.2, HG993285.2).
  - **HG993277.1 is a replaced sequence of a different length:** 84,482,589 bp, against 84,084,598 for .2 and Ensembl chr18.
  - The P2.1 alias check should warn when it sees HG993277.1. The CGD VCF (PRJEB107807) uses it for chr18.

**Acceptance evidence.** EVA confirms two of the six known-loci v2→v3.1 pairs:
- vgll3: CM003303.1:28656101 → 25:28996360
- bco1l: CM003304.1:19081573 → 26:19138923

The other four were not re-checked in this synthesis.

**Effort.**
- S for the rs bridge. Two VCFs go through DuckDB into one parquet. Whether DuckDB's CSV reader handles these BGZF files directly is untested.
- M–L for the Remap converter.

**Risks.**
- **The EVA v3.1 positions are EVA's own remaps,** not independent placements: all but 2 of the 15,362,350 lines carry `REMAPPED`.
- Some rs IDs sit on more than one line. Drop or flag rs IDs that map to several positions.
- 4,177 rs are unmapped.
- About 13% of the alignment is inverted, so the alleles must be complemented on flipped strands.
- The vgll3 region was rearranged between assemblies: about +340 kb, and the tag SNP lies on the opposite strand.
- The two raw files total 331 MB. They are downloaded at build time and never committed.

**Open questions for G.**
1. Do partners need v2 support soon? This repeats the existing open question.
2. Is an EVA-remapped position acceptable as the v3.1 truth for v2-only uploads?
3. Is rs-only coverage enough for now, or should all v2 positions be supported (the Remap tier)?

---

## 4. Population allele frequencies: P6.1, P6.10 and P7.6

**[new check] P6.1 currently reads the wrong frequency.**
- ROADMAP P6.1 says "public_af reads the 12-fish VCF INFO fields AF (imputed on 504 fish)" and expects AF 0.67 at 25:28996360.
- I read that site straight from the salmobase 504-fish VCF:

  | Site | 504-fish panel | Fixture (12-fish VCF) |
  |---|---|---|
  | 25:28996360 | `NS=504;AN=1008;AF=0.480159;AC=484;…;HWE=2.0525e-06` | `AR2=1;DR2=1;AF=0.67` |
  | 25:29064238 | `AF=0.758929` | `AF=0.88` |

- The fixture values match 12-fish allele counts: 16/24 = 0.67 and 21/24 = 0.875.
- 4,873 of the 7,555 fixture AF values (64.5%) equal k/24 to 2 decimals. My rough expectation for unrelated 2-dp values is about 25%.
- I infer that the INFO AF is Beagle's frequency across the 12 output fish, not across the 504. Either way, **it is not the 504-panel AF.**

**Recommendation.**
1. **P6.1 (S, must):** take `public_af` from the 504-panel INFO fields (AF, MAF, AC, AN, NS) at build time.
   - The 504-panel `ID` is `CHROM_POS_REF_ALT`, which allows an allele-aware join.
   - Change the acceptance value to 0.480159, or keep the 12-fish AF as a separate, clearly labelled field.
   - Store frequencies only, never genotypes, per CLAUDE.md.
2. **Relabel the population.** **[new check]** The name matching below is mine; the matching to PRJEB38061 comes from the verified report.
   - 479 of the 504 sample names match Bertolotti 2020 (PRJEB38061, wild and farmed fish of "both European and North American descent"). 459 match exactly and 20 after reformatting.
   - **The 12 unmatched A/J IDs are exactly the 12 AQUA-FAANG BodyMap fish:** J8, J9, J10, J15, J16, J18, A14, A15, A19, A20, A22, A24.
   - The remaining 13 are Cigene_2–5, Ssal_1–4, Nams_15_401/402/503, and two Tess/Alta WGS samples.
   - The nf-RASQUAL paper calls the filter population "wild Atlantic salmon". So the roadmap's "European farmed fish" does not describe the AF panel.
   - Whether any North American fish are among the 504 is **unverified**.
3. **P6.10, second population (M).**

   | Candidate | Assembly | Fish | File | Use |
   |---|---|---|---|---|
   | PRJEB34225, USDA North American farmed (Gao 2020, doi:10.3389/fgene.2020.00085) | ICSASG_v2 | 80, 3 stocks | `https://ftp.ebi.ac.uk/pub/databases/eva/PRJEB34225/Salmon_SNP_80_samples_gatk_EBI_noINFO.vcf.gz` (4,909,775,506 B) | Best North American source. Compute AF from GT, then lift via the §3 rs bridge (v2 position → rs → v3.1). |
   | PRJEB107807, Complex Gill Disease (Institute of Aquaculture) | Ssal_v3.1 (header GCA_905237065.2) | 1,710 | `https://ftp.ebi.ac.uk/pub/databases/eva/PRJEB107807/cgd_genos.eva_ready.ref2.vcf.gz` (36,473,717 B; re-checked) | A farmed breeding population, but limited to 63,809 array SNPs. CHROM is HG names, with **HG993277.1 for chr18**. INFO is only `PR`. |
   | PRJEB114348, Synchrosmolt (NMBU) | Ssal_v3.1 | 108 parents | `https://ftp.ebi.ac.uk/pub/databases/eva/PRJEB114348/Synchrosmolt_phased_parents_snp.eva_header.vcf.gz` (12,433,059 B; re-checked) | 411,908 SNPs. INFO is `.`, so AF must be computed from GT. Origin not checked. |
   | Lehnert et al. (Dryad 10.5061/dryad.hdr7sqvfc and 10.5061/dryad.4m5d5m9) | Not stated | Canadian populations | genepop, 707 MB and 418 MB | Positions and assembly unchecked; last resort. |

4. **P7.6 LD.** The 504-panel VCF is phased with Beagle (`beagle.22Jul22.46e.jar`): `https://salmobase.org/datafiles/datasets/nf-rasqual-data/ALL_chrome_phased_filtered_HWE_1e6_biSNPs_MAF_0.01.vcf.gz`, **974,625,672 B**. The roadmap's "929 MB" is the directory listing's binary-unit size. The server supports Range requests (used above).

**Effort.**
- S to switch the P6.1 source: build-time streaming of a 975 MB file, with only frequencies kept.
- M for a second population, including the lift.

**Risks.**
- **The panel mixes populations.** Pooled AF hides structure.
  - The HWE filter (`INFO/HWE < 1e-6` excluded) may drop strongly differentiated sites.
  - The vgll3 Met54Thr site itself has HWE p = 2.05e-6 with ExcHet = 1 (a heterozygote deficit), only just above the cut.
- The 12 AQUA-FAANG fish are inside the 504, so AF and the functional data are not independent samples.
- Reuse terms for the EVA/ENA genotype sets were not checked.
- None of these genotypes may go into the repo, fixtures or tests.

**Open questions for G.**
1. May we derive and host AF, and later packed haplotypes, from the 504-panel VCF?
2. How should the panel be described? Can Bertolotti sample metadata split it into European and North American, or per river? Sample prefixes suggest about 40 groups of 10, not re-checked.
3. Which second population, if any: North American (PRJEB34225), a farmed breeding population (CGD array), or both?
4. Should the 12-fish AF be kept as a separate field labelled "AQUA-FAANG fish"?

---

## 5. Vendor export compliance: P6.2 and P6.4 (being built now)

**Recommendation.** Apply these changes to the spec before the writers are finished. The reference TOP/BOT implementation is `topbot_reference.py` (Python 3.8). It reproduces Illumina's 16 worked examples plus the Figure 1 case, 17/17 checks, so the P6.4 unit tests can use it as an oracle.

1. **No provenance lines inside vendor files.** No vendor document allows comment lines, and Illumina asks for headers to be removed before a score file is reused as input. Put provenance in a sidecar `.provenance.txt` and in the zip's `manifest.json`. TSV and BED exports may keep `#` lines. Change the P6.4 acceptance test "Every export starts with provenance lines" to match.
2. **`Genome_Build_Version` must be numeric.** The iSelect note says "Enter genome version number. Otherwise, enter 0", and the help's example is `38`. Use `0` (documented) or `3.1` (unverified). Record Ssal_v3.1 / GCF_905237065.1 in the sidecar.
3. **Neighbouring variants in UPPERCASE IUPAC,** not lowercase as P6.2 says. KASP treats lowercase as "uncertain" and designs around it. KASP marks neighbouring indels as `N`. Decide whether Ensembl soft-mask lowercase passes through to KASP; the default should be to uppercase it.
4. **TOP/BOT "cannot determine" outcome,** for when the flank walk runs out (Illumina code 103: "TOP/BOT strand cannot be determined").
5. **Panel-level Infinium bin rule (error 111):**
   - Any A/T or C/G SNP needs at least 100 SNPs in each Infinium I bin that is used; warning 604 recommends 200 for polyploid species.
   - A used Infinium II bin needs at least 1000 loci.
   - The panel designer (P6.3) should warn, or exclude A/T and C/G SNPs by default.
6. **Count neighbouring variants per side.** Axiom designs accept one clean 35-nt side (Douglas-fir paper). `max_flank_variants 0` over both sides is stricter than needed.
7. **Optional base-specific homopolymer limits:** G/C runs > 4 and A/T runs > 6, as in the carp array design. The existing `gc [0.30, 0.70]` already matches the carp rule.
8. **Locus names valid for all three vendors:** `[A-Za-z0-9_]`, at most 20 characters (KASP; its template says 25), not starting with `rs` or `cg`, and unique. The 2016 Illumina note discourages underscores. A deterministic alphanumeric name, for example `Ssa25p28996360` (at most 15 characters), passes everywhere. Keep the user's ID in a lookup column.
9. **Unplaced scaffolds → `Chromosome 0`** for Illumina, which says "Contig numbers are not accepted". At most 255 distinct chromosome values (error 117).
10. **Spacing warning when panel markers are ≤ 60 bp apart** (Illumina warning 340). Thermo says interfering SNPs can be as close as 10 bases.
11. **Flank lengths:**
    - Illumina: more than 50 bp on each side (current help). P6.4's 60 bp is fine.
    - KASP: at least 50 bp; up to 100 helps.
    - Axiom: 35 + `[A/B]` + 35, the "71-mer" in Houston 2014.
12. **Keep the column-header dict per template version.**
    - The 2016 note's order ends `… Plus_Minus, Force_Infinium_I, Species`.
    - The current help lists `… Plus_Minus, Species, Force_Infinium_I, Replication_Count`.
    - Use `Species = Other` and `Force_Infinium_I = FALSE`.
13. **Fix the P4.5 acceptance value.** On ENSSSAT00000230965 the change is **T46M**, not T54M: Ensembl `/map/translation` puts residue 46 at 25:28996359–28996361. Record the offset of 8 as the named constant the spec already allows for.

**Test vector (vgll3 Met54Thr, rs863754587, 25:28996360, Ensembl 116 reference C):**
```
GCTGGGTGTTTACAGTAGGATGCAGCAGGACAGCA[C/T]GGAGCAGCAGTTTCCAGGGCGGAGACAGCAACAGC
```
- GC is 0.59, the longest homopolymer is 3, and there is no N.
- For Illumina, `[C/T]` is BOT with Allele A = T.
- The neighbour-variant, uniqueness and repeat checks have not been run on it.

**Paralogue risk specific to salmon.**
- About one-third of the genome is tetraploid (Gidskehaug 2011).
- The 2016 Illumina note says no repeat checking is done for unlisted species. If Atlantic salmon is unlisted in DesignStudio (unverified), our LORe, blacklist and ohnolog flags (P6.8) are the only paralogue check.

**Sources.**
- Illumina:
  - TOP/BOT note: `https://www.illumina.com/documents/products/technotes/technote_topbot.pdf` (195,969 B)
  - iSelect design note: `https://www.illumina.com/Documents/products/technotes/technote_iselect_design.pdf` (243,952 B)
  - DesignStudio help: `https://help.connected.illumina.com/design-studio-array/product-guides/input-target-files`
- LGC KASP:
  - Design guide: `https://biosearchassets.blob.core.windows.net/assetsv6/factsheet_kasp-assay-design.pdf` (289,917 B)
  - Template: `https://biosearchassets.biosearchtech.com/assetsv6/SNP-submission-template.xlsx` (211,503 B)
- Houston 2014 (doi:10.1186/1471-2164-15-90)
- Xu 2014, carp array (doi:10.1186/1471-2164-15-307)
- Howe 2020, Douglas-fir array (doi:10.1186/s12864-019-6383-9)
- Full notes: `vendor_formats.md`

**Effort.** S, as spec and test edits to items already in progress.

**Risks.**
- The DesignStudio template sits behind a login.
- Thermo's submission columns are not public.
- Agena (named in P6.4) was not researched. Label it "unverified" or drop it from the P6.4 title.

**Open questions for G.**
1. Who supplies the current Illumina and Axiom templates? Can the CIGENE genotyping lab confirm TOP/BOT orientation, the build field and the thresholds?
2. Should A/T and C/G SNPs be excluded by default?
3. Is the `Ssa25p28996360` naming scheme acceptable?

---

## 6. AQUA-FAANG colours, citations and metadata: P4.3c, P5.4 and palette

**Colours.** The canonical source is `https://raw.githubusercontent.com/AQUA-FAANG/AQUA-FAANG-salmonids/main/chromatin-state-annotations/annotation_reports/state_annotations.tsv` (630 B, re-checked). Every RGB value in the salmobase BEDs matches it. State numbers are ChromHMM emission-order numbers.

| Label | AQUA-FAANG hex | Portal now (`salmo-snpportal/snpportal/palette.py`) | BodyMap | DevMap |
|---|---|---|---|---|
| Active TSS | #BF2026 | #B2182B | E3 | E9 |
| Flanking upstream | #E81E25 | #F4A582 | E4 | E10 |
| Flanking downstream | #E81E25 | #F4A582 | E2 | E11 |
| Bivalent | #9C247F | #762A83 | – | E3 |
| Active enhancer | #F99B1F | #E66101 | E7 | E6 |
| Primed enhancer | #FFD078 | #FEE08B | E6 | E7 |
| Poised enhancer 1 | #F9E700 | #92C5DE | E10 | E4 |
| Poised enhancer 2 | #F9F291 | #92C5DE | E9 | – |
| ZNF genes and repeats | #50BE96 | #BABABA | E1 | E12 |
| Repressed polycomb | #006367 | #878787 | E12 | E1 |
| Accessible chromatin | #7CD3F6 | #2166AC | E5 | E8 |
| Unknown 1 | #C0C0C0 | #DDDDDD | E8 | E5 |
| Quiescent | #FFFFFF | #F0F0F0 | E11 | E2 |

**Recommendation on colours.** This is G's decision; the ROADMAP already lists it as an open question. If G chooses AQUA-FAANG colours:
- Read the 13 hex values from `state_annotations.tsv` at build time, or hard-code them.
- Keep the portal's short labels.
- Always pair the colour with the label, because Flanking up and down share #E81E25.
- Give Quiescent (#FFFFFF) a border.
- Never use the yellows (#F9E700, #F9F291) as text backgrounds.

**Model facts for the glossary and tiers.**
- **BodyMap and DevMap are separate 12-state models.** Bivalent exists only in DevMap; Poised enhancer 2 only in BodyMap.
- No written state definitions exist. The only definition is the emission figure `https://salmobase.org/datafiles/datasets/Aqua-Faang/figures/chromHMM.png`, with signal for ATAC, H3K27ac, H3K4me1, H3K4me3 and H3K27me3. Do not invent definitions.
- Peak tie-break rule, from the salmobase README: "When a peak overlapped multiple states, the state was assigned in an order of importance (same order as in the figure above)". The figure's row order is the table order above.
- Files: BodyMap has 16 conditions and DevMap 5.
  - Format: BED9 with a track line and `itemRgb="On"`, 200 bp bins, chromosomes only, in lexicographic chromosome order.
  - Sizes: `.bed` 55–89 MB, `.bb` 11–18 MB.
  - The server answers Range requests with 206 and sends CORS headers. So P4.3c can read the `.bb` files remotely.

**Citation block for P5.4.**
- **AQUA-FAANG:** Baudement M-O, Perojil Morata D, Gillard GB, … Kent MP, Lien S, Macqueen DJ. *Salmonids reveal principles of regulatory evolution following autotetraploidization.* bioRxiv 2025. doi:10.64898/2025.12.18.695160.
  - v1 was posted 2025-12-21 and v2 2025-12-23. It is CC-BY and not yet published in a journal.
  - Author spelling varies between versions ("Perojil-Morata" in v2 metadata).
- **nf-RASQUAL:** Nguyen DT, Sandve SR, Lien S, Grønvold L. BMC Genomics 2025;26:1070. doi:10.1186/s12864-025-12302-5 (PMC12636203).
- **Genetic map, if used:** Brekke et al. 2023 Sci Rep, doi:10.1038/s41598-023-47208-3. The map file comes from bioRxiv 2023.06.07.543993 v2.
- **FAANG portal:** Harrison et al. 2021, Front Genet 12:639238 (doi:10.3389/fgene.2021.639238).
- **SalmoBase:** Samy et al. 2017, BMC Genomics 18, as the preprint cites it. The DOI was not captured.
- **JASPAR 2022, if motifs are used:** **[new check]** jaspar.elixir.no says the database "is licensed under the Creative Commons Attribution 4.0 International License". The JASPAR 2022 paper DOI was not checked.
- **Code repositories without a licence:** AQUA-FAANG-salmonids and datngu/nf-RASQUAL_paper have no LICENSE file. Cite them, but ask before redistributing their files.

**Sample metadata for the Data page.**
- **ENA accessions (RNA / ATAC / ChIP):**
  - BodyMap: PRJEB47409 / PRJEB47408 / PRJEB55063
  - DevMap: PRJEB51855 / PRJEB51854 / PRJEB53399
- **BodyMap fish** (BioSamples SAMEA9253105–116):
  - Strain "AQUAGEN commercial salmon", origin "Domesticated diploid".
  - Born at Senter for fiskeforsøk, NMBU Ås, and reared in freshwater in a closed recirculating system.
  - Immature fish (J) were born 2020-01 and mature fish (A) 2019-03. All were sampled in September 2020, for example J8 at 9 months and 95.7 g, and A14 at 16 months and 1,426.3 g.
  - Fish per group:

    | Group | IDs |
    |---|---|
    | Immature female | J8, J9, J10 |
    | Immature male | J15, J16, J18 |
    | Mature female | A14, A15, A24 |
    | Mature male | A19, A20, A22 |
- **DevMap:** Roslin (UEDIN-FAANG-MACQUEEN). Samples are embryo pools, for example 20 embryos at 309 hpf, reared at 8.0 °C. The records have no strain field.
- **Assay gaps:** gill ATAC and CTCF ChIP were discarded. ChIP was done on 2 of 3 replicates, except gonad, which has all 3.
- **FAANG API:** 11 AQUA-FAANG salmon datasets and 271 specimens with UBERON terms. These can go per track in `tracks.yaml` (P4.1).

**Effort.** S.

**Risks.**
- The preprint may change before journal publication, so pin v2 in the citation.
- State labels could be renamed in later versions.

**Open questions for G.**
1. Should the portal use AQUA-FAANG colours or the current palette?
2. How should the portal cite the preprint, and with which author list?
3. G is on the AQUA-FAANG author list. Can G supply one-line state definitions for the glossary, or approve "see emission figure"?
4. Is "AquaGen commercial, domesticated diploid, freshwater, NMBU Ås, 2020" an acceptable description of the BodyMap fish?

---

## 7. molQTL plan: P4.6 and P7.8

**What exists.** The tables are in `github.com/datngu/nf-RASQUAL_paper`, branch `main`:
- Path: `data/output_nf_rasqual/<Tissue>/EXTERNAL_LD_{RNA,ATAC}_eigenMT_results_merged/ALL_eigenMT_results.txt`.
- Example: `https://raw.githubusercontent.com/datngu/nf-RASQUAL_paper/main/data/output_nf_rasqual/Liver/EXTERNAL_LD_RNA_eigenMT_results_merged/ALL_eigenMT_results.txt` (re-checked: HTTP 200).
- These are plain files, not LFS pointers.
- Each table has a `_permute` twin, which is the permutation null.

| Tissue | eGenes (paper) | caPeaks (paper) | ATAC table (B) |
|---|---|---|---|
| Brain | 711 | 507 | 21,739,727 |
| Gill | 681 | – (assay discarded; a 46 MB table exists, **do not use**) | – |
| Gonad | 488 | 220 | 39,420,716 |
| Liver | 276 | 308 | 29,764,416 |
| Muscle | 263 | 131 | 40,165,935 |

RNA tables are 1.94–2.80 MB each.

Columns are `snps gene statistic pvalue FDR beta BF TESTS`:

| Column | Meaning |
|---|---|
| `snps` | `chr_pos_ref_alt`, 1-based. 5 of 5 REF bases were checked against NC_059442.1. |
| `gene` | An ENSSSAG ID from **Ensembl 106**, or a peak written as `Interval_N:chr:start:end:strand:len` in featureCounts' 1-based inclusive form |
| `statistic` | RASQUAL χ² |
| `pvalue` | p-value of that χ² |
| **`FDR`** | **A copy of `pvalue`**; do not show it as an FDR |
| `beta` | RASQUAL π, the "Effect size (Pi)". Its allele direction is unverified. |
| `BF` | eigenMT/Bonferroni-adjusted p. **BF < 0.1 reproduces the paper's Liver counts (276 eGenes, 308 caPeaks).** |
| `TESTS` | Effective number of tests |

**There is one row per feature: the lead SNP only.** Liver RNA has 19,406 rows for 19,406 genes.

**Recommendation.**
1. **Phase 1 (S–M): a real P4.6 point layer.**
   - Fetch the 9 usable tables: 5 RNA and 4 ATAC, leaving out Gill ATAC.
   - Parse `snps` into chrom, pos, ref and alt for an allele-aware join.
   - Convert peak IDs to BED with `start - 1`, but first check whether the upstream SAF already added 1.
   - Keep `tissue, kind, feature, pi, pvalue, BF, TESTS` and a `sig` flag. The cutoff is G's; the paper used BF < 0.1.
   - Keep `weights.yaml molqtl: 0` and drop the SYNTHETIC watermark only for real rows.
   - Map Ens106 gene IDs to Ens116, for example through `genes.parquet` with Ensembl ID history for misses. How many IDs changed is unknown.
2. **Card text.** For example: "lead SNP for <gene> in <tissue>, eigenMT-adjusted p = …, π = …". Make no direction claim until the meaning of π is confirmed.
3. **P7.8 coloc is blocked by the data, not by code.** Coloc ABF needs per-SNP statistics across each region. These tables hold only the lead SNP per feature (this is my inference from the table structure). Options:
   - Ask the authors for the full RASQUAL outputs.
   - Re-run nf-rasqual (L effort).
   - Keep P7.8 synthetic.
4. VEP files in `data/vep_results/` have a 0-based `#Uploaded_variation`. Join on the 1-based `Location` column.
5. `coloc_analysis/` contains per-tissue genotype VCFs. Never copy them into the repo.

**Effort.** S–M for Phase 1. Full coloc is L, or depends on the authors.

**Risks.**
- **Only 12 fish:** low power, and the lead-SNP effects suffer from winner's curse.
- The meaning of π is unconfirmed.
- The `FDR` column is misleading.
- Licence: none on the repo. The article is CC BY-NC-ND 4.0 according to the portal-gaps report.
- Gene IDs are on Ensembl 106.
- The Gill ATAC table exists although the paper says gill ATAC was discarded.
- The `FDR == pvalue` check was done only on the Liver RNA table.

**Open questions for G.**
1. Will G ask the authors (Nguyen, Sandve, Lien, Grønvold) for permission to redistribute derived rows, and for full per-SNP outputs?
2. Should significance be BF < 0.1 as in the paper, or permutation-based from the `_permute` tables?
3. Should non-significant leads be shown?
4. Keep molQTL at weight 0?
5. Which allele does π refer to? The authors could confirm.

---

## 8. TF motif layer: P5.9

**Data.**

| File | URL | Size | Contents |
|---|---|---|---|
| PFMs | `https://salmobase.org/datafiles/datasets/Aqua-Faang/TFBS/motifs/JASPAR2022_vertebrates.pfm` | 270,260 B, re-checked | **[new check]** 838 motifs, raw counts in 4 columns. Header: retrieved 2021-12-20 from `JASPAR2022_CORE_vertebrates_non-redundant_pfms_transfac.txt`. IDs look like `MA0004.1_MA0004.1.Arnt`. |
| Motif-to-factor map | `.../TFBS/motifs/JASPAR2022_vertebrates.motif2factors.txt` | 44,613 B | |
| Activity scores | `.../TFBS/scores/AtlanticSalmon_{BodyMap,DevMap}_{enhancers,promoters}_scores.txt` | e.g. BodyMap enhancers 57,479 B | `gimme maelstrom` per-condition motif activity (z-score and corr per condition). 82, 104, 123 and 181 motifs. **[new check]** 247 unique motifs across the 4 files, all present in the PFM file. No coordinates or alleles. |

**Recommendation (M).** Score each candidate SNP in pure Python with no new dependency:
1. For each single-base SNP, take the reference sequence ± (maximum motif length − 1) using the P6.2 genome reader.
2. For each motif and each strand, score every placement that covers the SNP, for ref and for alt, as log-odds. The pseudocount and background are provisional: genome base composition is a reasonable default.
3. Compute the exact p-value of each score from a per-motif score distribution (integer-scaled dynamic programming, cached per motif). This copies FIMO's p-value semantics without FIMO.
4. Output `motif`, `motif_id`, `motif_tf`, `motif_ref_p`, `motif_alt_p`, `motif_delta`, plus `motif_activity`.
   - `motif_activity` is the motif's maelstrom z-score in the active preset's conditions, taken from the promoter or enhancer file according to the SNP's state.
   - Display only, at weight 0.
5. Default threshold, labelled PROVISIONAL: the nf-RASQUAL precedent. It used FIMO `--thresh 0.01` and kept motif–variant pairs where at least one allele had p < 1e-4, with JASPAR 2020 CORE vertebrates non-redundant.
6. Run the scan only on uploaded or candidate SNPs, not genome-wide. Consider limiting it to SNPs in ATAC peaks or to the 247 maelstrom motifs.
7. The P5.9 acceptance test (a planted disrupting allele) fits this design unchanged.

**Effort.** M.

**Risks.**
- **Chance hits are frequent.** My estimate: 838 motifs × about 24 SNP-covering placements gives roughly 20,000 tests per allele, so about 2 hits per allele are expected at p < 1e-4 by chance. A "hit" alone is weak evidence; the ref–alt difference matters.
- JASPAR vertebrate motifs are mostly from mammals, and salmon has duplicated TF genes after the salmonid-specific whole-genome duplication (Ss4R).
- Maelstrom z-scores measure motif activity across peak sets, not evidence for a particular site.
- JASPAR 2022 here versus 2020 in nf-RASQUAL.
- Pure-Python speed is unmeasured. For 50K SNPs it may need the peak or tier restriction.

**Open questions for G.**
1. Which p threshold, and should the score difference between alleles be required?
2. Scan all 838 motifs, or only the 247 that maelstrom reported as differential?
3. Should the scan be limited to SNPs in active elements?
4. Keep the layer display-only?

---

## 9. Top missing features, ranked

| # | Feature | Why | Effort | Data and source |
|---|---|---|---|---|
| 1 | **Correct the public AF source** (§4) | P6.1 is a "now/must" item and currently shows 12-fish frequencies as population AF | S | 504-panel VCF (salmobase, 974.6 MB) |
| 2 | rsID search and v2 → v3.1 for known variants (§3) | Turns P5.12 from "needs verification" into a buildable item, and covers most legacy array SNPs | S | EVA release 9 (331 MB) |
| 3 | Known-loci catalogue (36 rows) with a "published associations" lane and card callout (§2) | P5.3 has only 6 rows; breeders search by trait | S–M | `verify/known_loci_candidates.corrected.tsv` |
| 4 | Real molQTL lead-SNP layer at weight 0 (§7) | Replaces a synthetic contract with public data | S–M | nf-RASQUAL_paper tables |
| 5 | cM layer and cM spacing (§1) | Bp spacing is a poor proxy where crossovers cluster at the telomeres | S | Brekke media-1.txt |
| 6 | Bulk precomputed downloads per preset (move P8.7 earlier) | Confidential lists can then be joined locally; LocusZoom.js makes the same privacy argument for in-browser drawing | M | Pool or EVA sites |
| 7 | Full VEP at build time from the Ensembl 116 offline cache | Consequences plus regulatory-build overlap in 23 cell types; keep VEP-lite for new SNPs | S–M | `https://ftp.ensembl.org/pub/release-116/variation/indexed_vep_cache/salmo_salar_vep_116_Ssal_v3.1.tar.gz` (361,495,216 B, re-checked). It has **no known variants and no SIFT/PolyPhen**: all 1,112 `all_vars.gz` files are empty. VEP would be an external prep tool, not a Python dependency, but ask G. |
| 8 | Search by NCBI gene ID or LOC symbol, and a deep link to SalmoBase | Breeders use LOC names | S | `https://salmobase.org/genes/id/<ENSSSAG>?assembly=Ssal_v3.1` (a real ID gives 200, a fake one 404) |
| 9 | FAANG accessions and UBERON terms per track | FAIR metadata on the Data page and in exports | S | api.faang.org |
| 10 | "Report a problem" link (never sending coordinates), changelog, release DOI | Trust and citability | S | None |
| 11 | Display-only condition layers for disease, immune and smolt traits | Sea lice, AGD, antiviral and smolt presets | M each | Head-kidney antiviral chromatin (doi:10.1101/gr.280579.125) and liver ATAC through smoltification (doi:10.1371/journal.pone.0302388). **File locations unverified.** |
| 12 | Imputation pointer in Help (don't build a server) | Animal-SNPAtlas already offers salmon imputation | S | Animal-SNPAtlas (doi:10.1093/nar/gkac954): ICSASG_v2, 342 fish; R² 0.786 with Beagle and 0.823 with Minimac3 |
| 13 | GO enrichment; human GWAS Catalog and ZFIN phenotypes of orthologs | Gene-page context | S–M | Sources not checked |

Longer-range ideas seen in comparable portals:
- ChickenGTEx: tissue-specificity scores, eight metrics including tau.
- PigGTEx: TWAS, SMR, PheWAS.

These need many more samples than 12 fish and are out of scope for now.

---

## 10. Roadmap text contradicted by the research (for the engineers)

| Item | Current text | Evidence | Suggested change |
|---|---|---|---|
| P6.1 | "AF (imputed on 504 fish)"; acceptance AF 0.67 at 25:28996360 | 504-panel INFO AF = **0.480159** there. The fixture value 0.67 ≈ 16/24, a 12-fish frequency. | Source AF from the 504-panel VCF and change the acceptance value, or label the 12-fish AF separately |
| P6.2 | Neighbours "as lowercase IUPAC codes" | KASP: lowercase = uncertain, avoid | Uppercase IUPAC; `N` for indels (KASP) |
| P6.4 | "Every export starts with provenance lines" | No vendor allows comment lines | Sidecar file plus manifest; `#` lines only in TSV and BED |
| P6.4 | `Genome_Build_Version=Ssal_v3.1` | Docs: "version number… Otherwise, enter 0" | `0` (or `3.1`, unverified) |
| P6.4 | "KASP/Agena" | Agena not researched | Mark Agena unverified |
| P6.4 | TOP/BOT rule | Code 103 exists for undeterminable strands | Add a "cannot determine" outcome; use `topbot_reference.py` as the test oracle |
| P4.5 | Expects 'T54M' on ENSSSAT00000230965 | Ensembl residue 46 (T46M, ACG/ATG) | Named offset constant = 8 |
| P4.6 | Tissues "Brain/Gill/Liver/Muscle"; data "synthetic until tables arrive" | Brain, Gill (RNA only), Gonad, Liver, Muscle; the tables are public | Use the real tables; exclude Gill ATAC |
| P7.8 | Coloc from the nf-rasqual tables | Tables hold the lead SNP per feature only | Needs full outputs from the authors |
| P5.12 | "needs verification: EVA Ssal_v3.1 rsID release" | Release 9 has 15,272,533 rs. The release 7 VCF has `ssa26 19138923 rs863785818 A C`, and the EVA API gives HG993285.2:19138923 (= chr26). | Mark as public-available-now |
| P2.5 | Flank lift via NCBI efetch and Ensembl REST | The EVA rs bridge needs no runtime network | rs bridge first; Remap GFF for the rest |
| P2.1 | Alias table | chr 9, 11, 18 and 26 are `.2` GenBank versions; HG993277.1 is a different sequence | Accept the `.2` names; warn on HG993277.1 |
| P6.9 | "lifted to Ssal_v3.1" | Brekke is native Ssal_v3.1 (validated here: 64% of sampled markers sit exactly on 504-panel sites) | No lift needed for Brekke |
| P5.3 | bco1l "to verify" | EVA A/C; Helgeland T = red | A (+ strand) = red |
| P7.6 | "929 MB" | 974,625,672 B (the listing uses binary units) | Cosmetic |
| Open questions | "Where are the nf-rasqual tables?"; "AF … from European farmed fish" | Tables found (§7). The AF panel is mostly the Bertolotti 2020 collection plus the 12 AQUA-FAANG fish. | Update the questions |

---

## 11. Not verified (consolidated)

**Genetic map**
- Contents of the Brenna-Hansen S1.doc.
- MacLeod-Bigley data availability.
- Size of the Raynaud tarball.
- Why Brekke has 34,842 markers rather than 35,032.

**Known loci**
- Moen 2015 quotes against the PDF.
- The nae1 coordinate.
- Allele-level effects for the IPN KASP/RAD markers, PD, the CMS meta-analysis and Rivera's "Effect".
- Which sdY copy the reference carries.
- Four of the six benchmark v2→v3.1 pairs.

**Liftover**
- Any ready-made ICSASG_v2↔Ssal_v3.1 chain file.
- Accuracy of a chain converted from the Remap GFF.
- Whether DuckDB reads the EVA BGZF VCFs directly.

**Allele frequencies**
- Whether any North American fish are in the 504.
- Reuse terms of the EVA/ENA genotype sets.
- The Lehnert assemblies.
- Synchrosmolt origin.
- PRJEB107807 chr18 coordinates (labelled HG993277.1).
- Exactly how the fixture AF was computed. The 12-fish explanation is an inference.

**Vendors**
- Thermo submission columns.
- Whether Illumina accepts text in `Genome_Build_Version` or `#` lines.
- Whether salmon is listed in DesignStudio.
- Agena.

**AQUA-FAANG**
- The 107-page supplement (no PDF tool was available).
- Peak start convention in the nf-RASQUAL interval IDs.
- Direction of π.

**molQTL**
- `FDR == pvalue` in tables other than Liver RNA.
- Why a Gill ATAC table exists.
- How many Ens106 gene IDs changed by Ens116.

**Portal features**
- Animal QTLdb salmon content (site under maintenance).
- Locations of the antiviral and smolt peak files.
- The salmobase "West" cell dataset.

## 12. Files

Under `research/`:

| Path | Contents |
|---|---|
| `next_push_data_and_gaps.md` | This file |
| `synth/brekke_vs_504.py` | Brekke coordinate check against the 504 panel |
| `synth/JASPAR2022_vertebrates.pfm` | Downloaded copy of the AQUA-FAANG PFM file |
| `cm/brekke_map.txt`, `cm/lift_pilot2.py`, `cm/*.v31.tsv` | Genetic map files and the chr22 lift pilot |
| `verify/known_loci_candidates.corrected.tsv`, `known_loci_unresolved.tsv` | Known-loci catalogue and unresolved items |
| `topbot_reference.py`, `vendor_formats.md`, `vendor/` | Vendor notes, sources and the TOP/BOT oracle |
| `portal_gaps.md` | Pre-correction portal-gaps report (the corrections are in §9 here) |
| `verify_liftover/`, `verify_aqf/`, `cm_verify/` | Re-fetched copies from the verification passes |
