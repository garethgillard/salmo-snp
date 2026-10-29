# salmo-snp

Which of your Atlantic salmon SNPs are likely to matter? salmo-snp scores SNPs (assembly Ssal_v3.1) against public
functional data: open chromatin and active regulatory elements in 21 AQUA-FAANG tissues and stages, protein-coding
changes, conserved sequence, TF motifs and published associations. Each SNP gets a tier from 1 (strongest evidence)
to 4 (none found), with the evidence behind it.

Public demo: https://158.39.75.9/snp/

| Folder | What it does |
|---|---|
| [`snpdata/`](snpdata) | Collects the public sources and builds the annotation release, served as static files (`snpdata`) |
| [`snpscore/`](snpscore) | Scores a SNP list against a release: evidence and a tier per SNP (`snpscore`, Python) |
| [`snpportal/`](snpportal) | The web portal: upload, results, evidence cards, locus browser, GWAS and marker-panel tools (Django) |

The portal installs as one Python package (`salmo-snp`) that runs on your own computer, so confidential SNP lists never
leave it; the public site runs the same code. [AGENTS.md](AGENTS.md) has the plan, the rules and how to run the tests.

## Run it on your own computer

```bash
pip install "git+https://github.com/garethgillard/salmo-snp#subdirectory=snpscore" \
            "git+https://github.com/garethgillard/salmo-snp#subdirectory=snpportal"
salmo-snp download <release URL>      # once per release: about 300 MB, every file checked against its sha256
salmo-snp serve                       # http://127.0.0.1:8000/snp/, for this computer only
```

Your SNP lists and results stay on your computer (results in ~/.salmo-snp, kept 30 days); the portal only fetches
public data, such as AQUA-FAANG signal for the region you view. Developers: [AGENTS.md](AGENTS.md).

## Licence

[PolyForm Noncommercial 1.0.0](LICENSE): free for research, teaching and other noncommercial use, including by
universities, public research institutes and government bodies. Commercial use (for example by breeding companies)
needs the author's permission; contact Gareth Gillard. The data in a release keep their sources' licences (listed in
`snpdata/layers.yaml`).
