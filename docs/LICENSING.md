# salmo-snp licences summary

2026-11-10, Gareth Gillard. The short form is the README's "Licence"; the texts are `LICENSE`, `CLA.md` and
`CONTRIBUTING.md`.

## Ownership and where it runs

salmo-snp is NMBU software for scoring Atlantic salmon DNA variants, kept in a private GitHub repository.

NMBU is named as the copyright holder; Gareth Gillard (NMBU) is the author and maintainer.

- **Copyright notice** (in `LICENSE`): "Copyright 2026 Norwegian University of Life Sciences (NMBU)".
- **Repository:** private on GitHub (account garethgillard/salmo-snp); access by invitation only. Making it public is
  planned but not scheduled.

## The software licence: PolyForm Noncommercial 1.0.0

The code is under the [PolyForm Noncommercial License 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0),
a standard licence published by the PolyForm Project. It is free for noncommercial use and gives no right to
commercial use.

| Topic | What the licence says |
| --- | --- |
| Who may use it | Anyone, for a noncommercial purpose: personal research, study and testing "without any anticipated commercial application"; and any charitable organisation, educational institution, public research organisation, public safety or health organisation, environmental organisation or government institution, whatever its funding |
| What they may do | Use, copy, change, build new works on and redistribute the software, for those purposes |
| Conditions | Anyone passing on a copy must include the licence terms and the `Required Notice:` line (the NMBU copyright notice) |
| Patents | A patent licence for claims the licensor can license; it ends for anyone who claims in writing that the software infringes a patent |
| Breaches | After a first written notice of a breach, the licensee has 32 days to comply and fix past breaches; otherwise all their licences end |
| Liability | Provided as is, without warranty, and the licensor is not liable for damages, as far as the law allows |
| Not allowed | Sublicensing or transferring the licence; the licensor stays free to grant other licences, which is how commercial permission works |

Commercial companies, such as fish breeding companies, are not covered and need NMBU's permission (next section).

## Commercial use: permission by email

NMBU gives commercial users permission by email. The README states this publicly.

Terms of the email:

- **Who:** one named company, with its organisation number.
- **Scope:** internal use in its breeding and genotyping work, including results and marker panels it makes with the
  software.
- **Versions:** up to and including a named version (for example v1.x).
- **Restrictions:** no redistribution or sale of the software or changed copies; no warranty; otherwise the PolyForm
  terms apply.
- **Data:** the permission covers only the software. Third-party data keeps its own licence.
- **Ending it:** NMBU may end the permission with 3 months' written notice, or at once if its terms are broken.
  Results produced before then remain the company's.
- **Fee:** not set in the template.
- **Signed by:** Gareth Gillard, on behalf of NMBU.
- **Records:** sent emails kept in one place: company, date, versions.

## Contributor License Agreement

Outside contributors keep the copyright in what they write and give NMBU a broad, permanent licence to it, so NMBU can
license the whole project on any terms. The text in `CLA.md` is modelled on the Apache Individual CLA and written for
this project.

| Section | Content |
| --- | --- |
| Parties | The contributor (a person, or the organisation they act for) and NMBU |
| 1. Definitions | "Contribution": any work submitted to the project (pull request, commit, patch, file), including later changes |
| 2. Copyright licence | To NMBU and its licensees: perpetual, worldwide, non-exclusive, no-charge, royalty-free, irrevocable licence to use, copy, change, display, distribute and sublicense, and to license under any terms NMBU chooses, commercial licences included |
| 3. Patent licence | The same scope, for patent claims the contributor can license that the contribution would infringe |
| 4. Contributor's promises | The work is theirs, or they may submit it; third-party material is named with its licence; their employer has agreed where it has rights; no confidential or breeder data |
| 5. No obligation | NMBU need not use any contribution |
| 6. No warranty | Contributions are given as is |
| 7. Notice | The contributor tells NMBU if a promise stops being true |
| 8. Law | Norwegian law |

How it is accepted: on a contributor's first pull request, an automated GitHub check asks them to comment "I have read
the salmo-snp CLA and I accept it". Their GitHub user name, user id, the pull request and the time are stored in the
repository. The pull request cannot be merged until they accept.

`CONTRIBUTING.md` explains the agreement in plain words for contributors.

## Third-party data in the releases

The software ships with a separate data release built from public sources. Each source keeps its own licence, and
NMBU's licence and permissions cover none of them. Two sources still need their owners' permission to redistribute,
and several have no licence recorded in the project.

The releases are currently hosted in the private GitHub repository. The public demo shows their contents openly, and
they will later be published on salmobase.org.

| Source | What the project uses | Licence as recorded in the project |
| --- | --- | --- |
| nf-rasqual molQTL tables (Nguyen et al. 2025, GitHub repository datngu/nf-RASQUAL_paper) | Lead variant per feature, as a layer | **To confirm with the authors:** the repository has no licence file; the article is CC BY-NC-ND 4.0 |
| nf-rasqual 504-fish reference panel (salmobase.org) | Allele frequencies and variant positions only; genotypes never kept | **To confirm:** mostly wild and farmed fish from Bertolotti et al. 2020 (ENA PRJEB38061), plus 12 AQUA-FAANG fish of a commercial strain (AquaGen) |
| nf-rasqual RNA-seq gene counts (salmobase.org) | Expression counts per tissue | Not recorded |
| AQUA-FAANG consortium data (salmobase.org): ATAC peaks, chromatin states, blacklist, rediploidisation table, salmon-trout orthologs, signal tracks | The main regulatory layers | Not recorded |
| salmobase synteny blocks (2021-11) | Duplicated-genome pairs | Not recorded |
| Ensembl release 116 (genome, genes, regulatory build, constrained elements, orthologues) | Genome and gene annotation | Not recorded |
| European Variation Archive (EMBL-EBI) release 9 | Variant IDs and the old-to-new assembly conversion | Not recorded |
| Bgee 16.0 | Gene expression | Not recorded |
| NCBI RefSeq annotation (Ssal_v3.1) | Second gene annotation | NCBI data, no use restrictions |
| Synchrosmolt parents (ENA PRJEB114348, NMBU) | Allele frequencies only | ENA open data (EMBL-EBI terms of use) |
| JASPAR 2024 | Transcription factor motifs | CC BY 4.0 |
| Brekke et al. 2023 linkage map (bioRxiv supplement) | Recombination map | CC BY 4.0 |

Users' own data (their variants and results) is never part of a release or of the repository. In the local install it
stays on the user's computer. On the public demo, uploaded files are deleted after scoring and results after 24 hours.

## Third-party software

The software bundles two front-end libraries and installs three Python libraries. All five are under permissive
licences that allow commercial use and require only that their notices are kept.

| Software | How it is used | Licence |
| --- | --- | --- |
| htmx 2.0.11 | Bundled in the package (with its licence file) | Zero-Clause BSD |
| Bootstrap 5.1.3 | Bundled in the package (with its licence file) | MIT |
| Django 5.2 | Installed with the package | BSD-3-Clause |
| DuckDB 2 | Installed with the package | MIT |
| PyYAML 6 | Installed with the package | MIT |

The public demo server also runs gunicorn and Caddy; these are not distributed to users.
