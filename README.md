# salmo-snp

Which of your Atlantic salmon SNPs are likely to matter? salmo-snp scores SNPs (assembly Ssal_v3.1) against public
functional data: open chromatin and active regulatory elements in 21 AQUA-FAANG tissues and stages, protein-coding
changes, conserved sequence, TF motifs and published associations. Each SNP gets a tier from 1 (strongest evidence)
to 4 (none found), with the evidence behind it.

Public demo: https://158.39.75.9/snp/

| Folder | What it does |
|---|---|
| [`snpscore/`](snpscore) | Builds the annotation release from public sources and scores SNP lists against it (Python, command line) |
| [`snpportal/`](snpportal) | The web portal: upload, results, evidence cards, locus browser, GWAS and marker-panel tools (Django) |

The release build will move to its own `snpdata/` folder, and the portal will ship as a Docker image that also runs
locally, so confidential SNP lists never leave the user's computer. [AGENTS.md](AGENTS.md) has the plan, the rules and
how to run the tests.

## Licence

[PolyForm Noncommercial 1.0.0](LICENSE): free for research, teaching and other noncommercial use, including by
universities, public research institutes and government bodies. Commercial use (for example by breeding companies)
needs the author's permission; contact Gareth Gillard. The data in a release keep their sources' licences (listed in
`snpscore/layers.yaml`).
