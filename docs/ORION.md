# Building the data releases on Orion and hosting them on salmobase: brief (2026-11-24)

This brief starts the chat that builds the next releases on Orion, NMBU's HPC cluster, over SSH. It holds what was
known on 2026-11-24: what G decided, what the next build contains, how a build runs, what changes on Orion, how the
result reaches salmobase and the live app, and what has to be found out on Orion first. Keep it up to date as the work
goes on. Read [../AGENTS.md](../AGENTS.md) first: its rules apply here too.

Marked **to find out** are the things nobody could check from a cloud session: they are the first job on Orion.

## Decided (G, 2026-11-24)

- Releases are built on Orion from now on: SLURM jobs, with salmobase's data on the same file system. Not on G's Mac
  and not on GitHub's runners (the `species-data` workflow), which the handover in TRACKER step 9 still describes.
- The built release snapshots are uploaded to salmobase's data files, and the live app and every install fetch them
  from there. This is plan 5 of AGENTS.md: the publishing code exists (`snpdata publish`, `salmo-snp download`,
  `serve.py DATA_URL`); it has only ever pointed at GitHub Releases.
- The salmon build waited for the new layers (PR #29, merged 2026-11-24). Nothing holds it now.

## The next build: what is in it

### Atlantic salmon, release `<date>` (the one before: 2026-11-20)

| Part | What changes | Check after the build |
|---|---|---|
| `chromatin` | The unified peaks v5 on salmobase (2026-11-23): the same 328,894 peaks, with gill and head kidney states from retrained models. Release 2026-11-20 has v3. The Locus browser's state tracks already show v5 | 328,894 rows; the input's sha256 was 627534ad... on 2026-11-24 (v3: 8190b375...); salmobase's VERSION.md says which version is current |
| `summit` (new) | The nearest ATAC summit inside a robust peak: distance, signal, rank, condition. From 27 MACS2 peak files (400 MB) | 2,468,735 rows |
| `pike` (new) | Sequence aligned to northern pike, gaps of up to 50 bp closed. From one 90 MB depth track | 1,226,940 rows |
| `synchrosmolt_af` | The parents' whole-genome set: 112 fish, replacing 108 fish and 411,908 SNPs. Its VCF is not online: it is on Orion | 3,993,949 rows, `ns` 112; catalogue row `hubsmolt_ssa14_50815335` takes its effect allele (A) from these fish's minor allele: check A is still the minor allele |
| `motif` | Computed again, as it depends on `chromatin`. The peaks and sites are the same | 533,163 rows, as in 2026-11-20 |
| Catalogue | 46 rows: the 40 known loci and 6 structural variants | manifest `catalog.rows` 46 |
| Examples (`demo/`) | `known_loci.tsv`, `known_svs.tsv` (6), `svs_demo_SYNTHETIC.tsv` (300, made by the build), and three that need `bash prep/make_demo.sh` before the build: `public_50k.vcf`, `chip_demo_SYNTHETIC.tsv`, `gwas_maturation_SYNTHETIC.tsv` | All six listed in the manifest's `demo`. **Release 2026-11-20 lacks the last three** (the runner never ran make_demo.sh), so the live demo has offered only the Known loci example since 2026-11-20 |
| The public pool | Built again for the new release. weights.yaml gained two terms at weight 0, so tiers do not change | About 3.44 million sites; the tier shares of 2026-11-20 were 0.38%, 6.15%, 8.49% and 84.98% |
| Unchanged | `region`, `regbuild`, `gerp`, `blacklist`, `lore`, `gene`, `transcripts`, `transcripts_ncbi`, `gene_ortholog`, `ss4r`, `flank_variants`, `public_af` (7,572,808), `molqtl` (2,656), `cm`, `expression`; the alias table, rs IDs, `liftover_icsasg_v2` (735,344 blocks), flank keys, synteny, Bgee, tracks.yaml | `snpscore diff <2026-11-20> <new>` lists only the rows above |

### Rainbow trout, release `trout-<date>` (the one before: trout-2026-11-13)

serve.py on main already names `trout-2026-11-24`, which was never built: the runner's build ran out of memory.

| Part | What changes | Check |
|---|---|---|
| `summit` (new) | From 17 MACS2 peak files (300 MB) | 1,257,737 rows |
| `pike` (new) | From the trout depth track | 1,192,301 rows |
| Catalogue | 13 rows: 11 and 2 structural variants | `catalog.rows` 13 |
| Examples | `known_loci.tsv`, `known_svs.tsv` (2), `svs_demo_SYNTHETIC.tsv` (300), `public_50k.vcf` (cut from `public_af` by the build) | All four in `demo` |
| Unchanged | The other layers: `chromatin` 194,002, `public_af` 18,801,055, `flank_variants` 46,593,552, `motif` 1,029,347 | `snpscore diff` |

### Not in it unless G adds it

| Candidate | State | To decide |
|---|---|---|
| ChromBPNet allele effects, 27 conditions | Expected from the Orion repository at the end of the week of 2026-11-24 (docs/CHROMBPNET.md says how they come back) | Wait for them, or build now and again when they are in. They are variant-score layers, weight 0 |
| The AQUA-FAANG citation | layers.yaml and the release cite the preprint; the paper is out (Nat Ecol Evol 2026, doi:10.1038/s41559-026-03171-6). A release carries its citations, so the text should change before the build | G's OK: layers.yaml is a biology file |
| Benchmark files in the snapshot | `snpscore benchmark` writes them in seconds; no install has them, so Methods shows no benchmark | Add as a build step |
| A pool with coding consequences | `snpscore pool --assay` reads the genome. Without it the pool has no coding consequences, which blocks DECISIONS #5 | Try it on Orion, where memory is no limit |
| fSalSal1 position conversion | Postponed by G (2026-11-06) until I20; it needs one minimap2 run, which is easy on Orion | Leave, unless G wants it now |
| A missense effect score | Planned only (docs/MISSENSE.md), also for Orion | A later release |
| The input files as a mirror (`publish --raw`) | Lets anyone rebuild, and is the only way to pass on the Synchrosmolt site frequencies. Needs one fix first (below) | After the first release is up |

## How a build runs

The commands are the ones snpdata/README.md gives; nothing is special to a machine. In `snpdata/`:

```bash
snpdata fetch                                  # the inputs into data/raw; a file already there is kept
bash prep/make_demo.sh                         # the three example inputs (salmon); needs data/raw
snpdata build --out release/<date> --memory 32GB --threads 16 --temp <scratch>/duckdb
snpscore pool --release release/<date> --memory 16GB
snpscore diff <the release before> release/<date>     # the changelog: only the intended changes
snpdata publish release/<date> --to <the salmobase folder>
```

Trout: the same with `--layers rainbow_trout/layers.yaml --data data/rainbow_trout/raw` and `--out
release/trout-<date>`; no make_demo.sh.

What was added for Orion on 2026-11-24 (tested on the fixture only):
- `SNPDATA_SALMOBASE=<folder>`: fetch reads every `https://salmobase.org/datafiles/...` input from that folder when
  the file is there, and downloads the rest. Most of the bytes are salmobase's: the genome, the 504-fish VCF (975 MB,
  streamed), the peak files and depth tracks.
- `snpdata build --memory --threads --temp`: DuckDB's limits. Without them DuckDB takes 80% of the node's memory and
  every core, whatever the job was given. The trout build needs them: on a 16 GB runner it failed reading the pooled
  `public_af` cohorts at 12.4 GB. If a limit with a temp folder is not enough, the next thing to try is
  `SET preserve_insertion_order = false` in build's connection, tested against the fixture's hashes first.
- The motif layer starts one worker per core the job may use, not per core of the node.

Times known: fetch about 7 minutes (salmon, by download); the salmon build about 5 hours on 4 cores and 7 GB, most
of it the motif layer, which scales with cores; the pool a few minutes.

## On Orion: what to set up, and what to find out

Proposed places, as for salmo-chrombpnet (G to confirm): the repository in `~/git/salmo-snp/`, inputs and releases
under `/mnt/project/ELIXIR/salmo-snp/` (`raw/`, `raw_trout/`, `private/`, `release/`), DuckDB's temp folder under
`/mnt/ScratchProjects/ELIXIR/salmo-snp/`. Give the commands those folders with `--data` and `--out`; never commit
them.

1. **To find out: where salmobase's data files are on Orion**, whether that folder is the one the web server shows
   or a copy that is synced, and who may write to it. Its web layout is `datafiles/{genomes,datasets,TSV,...}`, and
   `datasets/` holds `Aqua-Faang/`, `nf-rasqual-data/` and others. `SNPDATA_SALMOBASE` is the folder that holds
   `genomes/` and `datasets/`.
2. **To find out: do compute nodes reach the internet?** fetch still downloads from ftp.ensembl.org,
   jun2026.archive.ensembl.org (BioMart), ftp.ebi.ac.uk (rs IDs), ftp.ncbi.nlm.nih.gov, jaspar.elixir.no,
   www.bgee.org, www.biorxiv.org and raw.githubusercontent.com; trout also from ftp.sra.ebi.ac.uk. If only the login
   node does, run fetch there (it is light with the salmobase files on disk) and build in a job.
3. **The Synchrosmolt VCF**: `MOWI_synchro_phased_parents_wgs.vcf.gz` is on Orion (G has it). layers.yaml reads it
   from `../private/` beside the data folder: link it there before fetch. Its genotypes never leave fetch.
4. **Python**: 3.11 or newer, with `pip install -e snpscore -e snpdata -e snpportal` (or `conda env create -f
   environment.yml`). No other tool is needed; minimap2 only for fSalSal1.
5. **SLURM**: to find out: the account, partitions and limits. A build job wants 16 cores or more (the motif layer),
   32 GB for salmon and 64 GB for trout to be safe, and a few hours. One job per species; fetch, build, pool and the
   checks can be one script that stops at the first failure and keeps what is done (fetch keeps files; `build
   --reuse <release>` copies unchanged layers from an earlier build).
6. **Trout's allele frequencies** come from three ENA cohort VCFs of 7, 16 and 55 GB, which fetch streams (it keeps
   three site files of about 300 MB). Two ways to skip the streaming: the site files of the workflow run of
   2026-11-24 are GitHub artifacts until **2026-11-27** (`gh run download 45433800948 -R garethgillard/salmo-snp`,
   then put the three `*.sites.vcf.gz` in the trout data folder: fetch keeps them); or check whether ENA is fast
   from Orion, which it may well be.
7. **Start from an empty data folder.** fetch never replaces a file, which is how a Mac's old unified peaks file
   would have gone into a new release. On Orion the first fetch takes everything as it is that day.

## Hosting on salmobase

Proposed: one folder, `datafiles/datasets/salmo-snp/`, so the address is
`https://salmobase.org/datafiles/datasets/salmo-snp` (G to confirm the place). `snpdata publish` lays it out:

```
releases/<version>/      the snapshot: every file of the release and SHA256SUMS; salmon and trout side by side
releases/latest.json     the version published last
raw/                     with --raw: the input files, for rebuilding
```

`salmo-snp download <version> --from <address or folder>` fetches a snapshot from it today, checks every file and
takes the genome from `raw/` or, without it, from the genome's own salmobase address in the manifest. So the first
test after publishing needs no code change: from any computer, `salmo-snp download <version> --from
https://salmobase.org/datafiles/datasets/salmo-snp`, then `salmo-snp serve`.

Then one pull request makes it the default (it can be written in a cloud session once the address answers):

| Where | Change |
|---|---|
| `serve.py` | `DATA_URL` defaults to the address; `RELEASE` and `RELEASES` name the new versions |
| `tools/get_data.sh` | Becomes `salmo-snp download`: no GitHub token |
| `snpportal/deploy/species.sh` | Fetches a release the VM lacks from the address instead of the GitHub data release |
| The public pool for the demo | The VM (2 GB) cannot build one. Publish it beside the snapshots (proposed: `pools/<version>/`, the two files of `<release>/pool/`); species.sh takes it from there, and the deploy workflow's job for stale pools reads the release from the address |
| README and the Data page | The install steps lose `--from site` and the GitHub Release instructions |
| `species-data` workflow, `prep/github_release.sh` | No longer the way; keep or remove (salmon cannot build on a runner anyway: its Synchrosmolt input is not online) |

Three faults in the publishing code that the two-species layout will meet:
- `releases/latest.json` holds one version, the one published last, whatever the species. Nothing reads it but
  `salmo-snp download latest`; make it one version per species before anyone relies on it.
- `raw/` is one folder, and both species have an `alias_filtered.txt`: publishing trout's inputs after salmon's
  keeps salmon's file under that name, and `fetch --mirror` would then build trout with it. Give each species its
  own `raw/` before using `--raw` for both.
- A published version never changes. A second build on the same day needs another name.

The demo VM: 6.5 GB were free on 2026-11-24, a salmon release is about 0.45 GB with its pool and a trout one about
1 GB, and species.sh refuses to fetch under 5 GB free. Remove 2026-11-05 and trout-2026-11-13 from
`/srv/snpportal/releases/` once the new ones are in (results on the server expire after 24 hours, so nothing needs
them).

## Order of work

1. On Orion: find out points 1, 2 and 5 above; set up the clone and the Python environment; `bash tools/check.sh`.
2. G decides the candidates (ChromBPNet now or later; the citation).
3. Salmon: fetch, make_demo.sh, build, pool, the checks of the table, `snpscore diff`.
4. Trout: the same, with the cohort site files or the streaming.
5. Publish both to the salmobase folder; test `salmo-snp download --from` the address from another computer.
6. The pull request of the table above, with `RELEASE` and `RELEASES`; G merges; "deploy to NREC".
7. Record in docs/TRACKER.md what was built and how long it took, and turn the job script into a file in
   `snpdata/prep/` once it has run.

## Text to start the Orion chat

```
We are on Orion over SSH. Clone https://github.com/garethgillard/salmo-snp.git into ~/git/ if it is not there
(else pull main), and read AGENTS.md, then docs/ORION.md: it is the brief for this chat. We build the next Atlantic
salmon and rainbow trout data releases here with SLURM jobs and publish them to salmobase's data files. Start with
its "On Orion: what to set up, and what to find out": tell me what you find and what you need from me, before any
job runs. Large files go under /mnt/project/ELIXIR/salmo-snp/ and temporary ones under
/mnt/ScratchProjects/ELIXIR/salmo-snp/, never into the repository.
```
