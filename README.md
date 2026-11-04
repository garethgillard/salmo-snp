# salmo-snp

Which of your Atlantic salmon SNPs are likely to matter? salmo-snp scores SNPs (assembly Ssal_v3.1) against public
functional data: open chromatin and active regulatory elements in 21 AQUA-FAANG tissues and stages, protein-coding
changes, conserved sequence, TF motifs and published associations. Each SNP gets a tier from 1 (strongest evidence)
to 4 (none found), with the evidence behind it. The portal also shows each SNP's evidence card and a locus browser,
fine-maps GWAS summary statistics with a functional prior, and designs marker panels with vendor-ready files.

Public demo: https://158.39.75.9/snp/ (public data only: don't upload confidential lists there).

## Run it on your own computer

The portal runs on your own computer, so confidential SNP lists (breeding companies' included) never leave it.

You need:
- Python 3.11 or newer (3.12 recommended; tested on 3.11 and 3.14 too). Linux is tested on every change; macOS and
  Windows aren't tested automatically yet.
- About 2 GB of disk: the release (~300 MB), the genome (~800 MB) and your results.
- While the repository is private, a GitHub account with access to it and the GitHub CLI, `gh`, logged in
  (`gh auth login`, then `gh auth setup-git` so that pip can read the repository).

1. Make a Python environment and install the two packages (one command, so pip takes both from GitHub):
   ```bash
   conda create -n salmo-snp -c conda-forge --override-channels python=3.12   # or: python3 -m venv salmo-snp-env
   conda activate salmo-snp                                                    #     . salmo-snp-env/bin/activate
   pip install "git+https://github.com/garethgillard/salmo-snp#subdirectory=snpscore" \
               "git+https://github.com/garethgillard/salmo-snp#subdirectory=snpportal"
   ```
   Use conda-forge, not Anaconda's default channel, which needs a paid licence at larger organisations.
2. Get the data, once: the release and the genome, every file checked against its sha256. Until the data is hosted on
   salmobase it is a GitHub Release of this repository, named after the release this version of salmo-snp expects
   (`salmo-snp info` names it):
   ```bash
   gh release download data-2026-11-03 -R garethgillard/salmo-snp      # two files, ~1.1 GB
   tar -xf salmo-snp-data-2026-11-03.tar && tar -xf salmo-snp-genome-Ssal_v3.1.tar
   salmo-snp download --from site      # checks every file and copies it into the data folder; then delete site/
   ```
   In a clone of the repository, `bash tools/get_data.sh` does the same. Once the data is hosted online,
   `salmo-snp download` alone will do (or `--from <address>`; a copy of the published folder on a disk or a share
   works too, for computers without internet).
3. Start it, and open http://127.0.0.1:8000/snp/ (only this computer can reach it; Ctrl-C stops it):
   ```bash
   salmo-snp serve
   ```
   The Score page has examples to try; Help lists the input formats (VCF, tables, PLINK, chip manifests, rs IDs,
   GWAS summary statistics) and the guided tour shows the rest.

- **Where things are kept**: one data folder, shown by `salmo-snp info`: `~/Library/Application Support/salmo-snp`
  (macOS), `~/.local/share/salmo-snp` (Linux) or `%LOCALAPPDATA%\salmo-snp` (Windows); set `SALMO_SNP_HOME` to use
  another. It holds `releases/`, `genome/` and `results/`. Results stay until you delete them (Delete in the portal,
  or remove the folder).
- **What leaves your computer**: nothing you upload or score. The portal fetches public data only: AQUA-FAANG signal
  and chromatin tracks for the region you view in the locus browser (from salmobase). With `--no-genome`, sequence
  checks also read the genome from salmobase, near your SNPs' positions; the default download avoids that.
- **Scripts and pipelines**: `snpscore annotate my_snps.vcf --release <release folder> -o out.tsv` scores without the
  portal (`snpscore -h`; the release folder is the one `salmo-snp info` lists). snpscore installs on its own too.
- **Updating**: rerun the `pip install` with `--force-reinstall` (pip skips a GitHub install whose version number
  hasn't changed). When the new version expects a newer release, `salmo-snp serve` says so and uses the old one until
  you get the new one as in step 2 (the genome is kept if it hasn't changed).
- **Removing**: `pip uninstall salmo-snp snpscore`, then delete the data folder.

### If something goes wrong
- `salmo-snp serve` says there is no release: step 2 hasn't been done for this data folder (`salmo-snp info`).
- `Repository not found` or a password prompt from pip: GitHub doesn't know you have access; run `gh auth login`
  and `gh auth setup-git`, or ask Gareth Gillard for access.
- The port is taken: `salmo-snp serve --port 8001`.
- Certificate errors (old Python builds, or a network that inspects HTTPS): point Python at your CA bundle, e.g.
  `SSL_CERT_FILE=/path/to/ca.pem salmo-snp serve` (downloads and the locus browser's public tracks both read it).
- Without internet everything works except the locus browser's signal rows, which come from salmobase and show as
  unavailable.

## The repository

| Folder | What it does |
|---|---|
| [`snpdata/`](snpdata) | Collects the public sources and builds the annotation release, served as static files (`snpdata`) |
| [`snpscore/`](snpscore) | Scores a SNP list against a release: evidence and a tier per SNP (`snpscore`, Python) |
| [`snpportal/`](snpportal) | The web portal: upload, results, evidence cards, locus browser, GWAS and marker-panel tools (Django; the `salmo-snp` package) |

A public site (on salmobase, later) runs the same code. For developers and their AI assistants:
[AGENTS.md](AGENTS.md) (the plan, the rules and how to run the checks) and [docs/TRACKER.md](docs/TRACKER.md)
(what's next).

## Licence

[PolyForm Noncommercial 1.0.0](LICENSE): free for research, teaching and other noncommercial use, including by
universities, public research institutes and government bodies. Commercial use (for example by breeding companies)
needs the author's permission; contact Gareth Gillard. The data in a release keep their sources' licences (listed in
`snpdata/layers.yaml`).
