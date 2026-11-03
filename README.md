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
leave it; a public site (on salmobase, later) runs the same code. [AGENTS.md](AGENTS.md) is for developers: the plan,
the rules and how to run the tests.

## Run it on your own computer

The portal runs on your own computer, so confidential SNP lists (breeding companies' included) never leave it. You need
Python 3.8 or newer (3.12 recommended), about 2 GB of disk, and access to this GitHub repository while it is private.

```bash
conda create -n salmo-snp -c conda-forge --override-channels python=3.12   # or: python3 -m venv salmo-snp-env
conda activate salmo-snp                                                    #     . salmo-snp-env/bin/activate
pip install "git+https://github.com/garethgillard/salmo-snp#subdirectory=snpscore" \
            "git+https://github.com/garethgillard/salmo-snp#subdirectory=snpportal"
salmo-snp download --from <data address>   # once: the release (~300 MB) and the genome (~1 GB), every file checked
salmo-snp serve                            # then open http://127.0.0.1:8000/snp/ (only this computer can reach it)
```

`<data address>` is where the data is published (a web address, once it is hosted on salmobase, or a folder: a copy of
the published data on a disk or share works the same, for computers without internet access). Use conda-forge, not
Anaconda's default channel, which needs a paid licence at larger organisations.

- **Where things are kept**: one data folder, shown by `salmo-snp info`: `~/Library/Application Support/salmo-snp`
  (macOS), `~/.local/share/salmo-snp` (Linux) or `%LOCALAPPDATA%\salmo-snp` (Windows); set `SALMO_SNP_HOME` to use
  another. It holds `releases/`, `genome/` and `results/`. Results stay until you delete them (Delete in the portal,
  or remove the folder).
- **What leaves your computer**: nothing you upload or score. The portal fetches public data only: AQUA-FAANG signal
  and chromatin tracks for the region you view in the locus browser (from salmobase). With `--no-genome`, sequence
  checks also read the genome from salmobase, near your SNPs' positions; the default download avoids that.
- **Scripts and pipelines**: `snpscore annotate my_snps.vcf --release <release folder> -o out.tsv` scores without the
  portal (`snpscore -h`).
- **Updating**: rerun the `pip install` with `--force-reinstall` (pip skips a GitHub install whose version number
  hasn't changed), then `salmo-snp download` (it fetches the release the new version expects and keeps files that
  haven't changed).
- **Removing**: `pip uninstall salmo-snp snpscore`, then delete the data folder.

## Licence

[PolyForm Noncommercial 1.0.0](LICENSE): free for research, teaching and other noncommercial use, including by
universities, public research institutes and government bodies. Commercial use (for example by breeding companies)
needs the author's permission; contact Gareth Gillard. The data in a release keep their sources' licences (listed in
`snpdata/layers.yaml`).
