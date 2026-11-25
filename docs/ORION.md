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
- What goes into this build (G, 2026-11-24, on the list below): the ChromBPNet scores can wait for a later build; the
  AQUA-FAANG citation is updated to the published paper (done: Nat Ecol Evol 2026;10:1959-1981); no benchmark files
  in the snapshot ("aim for only data used in the portal or package tool"); no pool with coding consequences; the
  fSalSal1 conversion can be made on Orion later and is skipped for now; no missense score yet.
- The place on salmobase is `datafiles/datasets/salmo-snp/`.
- Publishing (G, 2026-11-25): "the build is made under the elixir project, where salmobase is. We need only to make
  links and then rsync to salmobase server. Do a test and then if it passes upload the data. Also make sure that the
  portal will read these files." Done that day: Hosting on salmobase, below.
- Where to build (G asked Claude to choose, 2026-11-24): on Orion, started over `ssh orion` from G's Mac, which the
  cloud session can use once G attaches its `git` folder. Orion's nodes have 384 cores and 1.5 TB each against the
  Mac's 8 cores and 16 GB (the trout build needs more than 12 GB); salmobase's files are on its disk; and the upload
  to salmobase goes from Orion anyway. The Mac's inputs are from early November (its unified peaks file is an old
  version), so Orion fetches everything fresh, which takes minutes there, and takes from the Mac only what is not
  online: the Synchrosmolt VCF. One command builds a release: `bash prep/build_release.sh <species> <version>`.

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

### Left out of this build (G, 2026-11-24)

| Candidate | Decision |
|---|---|
| ChromBPNet allele effects, 27 conditions | A later build: they can wait (expected from the Orion repository at the end of the week; variant-score layers, weight 0) |
| Benchmark files in the snapshot | No: a snapshot holds only data the portal or the package uses |
| A pool with coding consequences (`snpscore pool --assay`) | Not now. It still blocks DECISIONS #5 |
| fSalSal1 position conversion | Can be made on Orion (one minimap2 run); skipped for now |
| A missense effect score | Not yet (docs/MISSENSE.md) |
| The input files as a mirror (`publish --raw`) | After the first release is up, and after the fix below. It is the only way to pass on the Synchrosmolt site frequencies |

## How a build runs

One command per release, in `snpdata/`, the same on any machine (`prep/build_release.sh`, tried on the test data):

```bash
MEMORY=64GB PREVIOUS=<the release before> bash prep/build_release.sh salmon <date>
MEMORY=64GB PREVIOUS=<the release before> bash prep/build_release.sh trout trout-<date>
MODE=dry bash prep/orion_publish.sh <date> trout-<date>      # only after the checks; then MODE=run, with G's go-ahead
```

On Orion these run as SLURM jobs (`prep/orion_build.sbatch`, "On Orion" below); elsewhere `snpdata publish
release/<version> --to <a folder>` lays out the same folder by copying.

It runs, and stops at the first that fails: `snpdata fetch` (a file already there is kept), for salmon
`prep/make_demo.sh` (the three example inputs: the step release 2026-11-20 missed), `snpdata build` with DuckDB's
limits, `snpscore pool`, `snpscore verify`, `snpscore diff` against the release before, and a summary of row counts,
catalogue rows, examples and pool tiers to hold against the tables above.

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
of it the motif layer, which scales with cores; the pool a few minutes. On Orion (2026-11-25, 32 cores): the whole
salmon job 18 minutes and 6.1 GB, the trout job 15 minutes and 11 GB (below).

## On Orion: what was found, what is done, what is next (2026-11-25, 01:53)

The work goes on in a chat that runs on Orion itself over SSH (G, 2026-11-24), as the ChromBPNet work does. A cloud
session can reach Orion too, through G's Mac: G attaches the Mac's `git` folder to it (Remote Control), and commands
run there as `ssh orion '...'`. That is how the first of the following was found and prepared; the chat on Orion
made the environment and the two builds. Much of it was read from the notes of the ChromBPNet work
(`~/git/salmo-chrombpnet/AGENTS.md`), which knows the cluster well.

**Found**
- **SLURM**: partition `orion` for CPU jobs, 6 nodes of 384 cores and 1.5 TB each; no time limits, and G's rule for
  all Orion work is never to set one (`--time`). The account is `biovit_elixir`, as for the ChromBPNet jobs. Nothing
  heavy on a login node. A job is bound to its cores (task/cgroup and task/affinity), so `os.sched_getaffinity` in a
  job is its own cores: build_release.sh's default threads and the motif workers follow `--cpus-per-task`.
- **The login environment**: `/etc/profile.d/z99_orion_apptainer.sh` exports `DATA=/data/$USER`, the login shell
  also has `SCRATCH` and `TMPDIR`, and sbatch passes them into a job. build_release.sh's setting for the inputs was
  `DATA`, so the first two builds tried to fetch into `/data/gagi` and stopped at once; it is `RAW` now.
- **Network**: login and compute nodes reach GitHub over HTTPS, salmobase.org, Ensembl, EBI, NCBI, JASPAR, Bgee and
  bioRxiv, so fetch can run in a job. Port 22 to github.com is blocked; salmo-snp is public, so clone it over HTTPS.
- **Storage**: `/mnt/project/ELIXIR/` (group `elixir`: 2.9 of 5 TB used) and `/mnt/ScratchProjects/ELIXIR/`.
- **Python**: the default python3 is 3.8, and the module's mamba is too old.
  `/cluster/software/Miniconda3/25.7.0-2/bin/conda` (conda 26.1.1) makes the environment, from conda-forge only (G's
  `~/.condarc` also lists bioconda and defaults).
- **salmobase**: `/mnt/project/ELIXIR/salmobase/datafiles` is Orion's copy of the server's datafiles folder. The
  server has files the copy lacks, so fetch downloads from salmobase.org (leave `SNPDATA_SALMOBASE` unset unless a
  file's checksum is compared first). Uploads go from a login node to the ssh alias `salmobase`
  (web-05.orion.nmbu.no; `test.salmobase` is the test server), as `salmo-chrombpnet/scripts/08_salmobase_sync.sh`
  does: stage in the copy, make the server folder over ssh, `rsync -rlt --chmod=D755,F644` and never `--delete`,
  rerun when the login node cuts a long rsync (it does after 10 minutes), then check the server's files against
  SHA256SUMS. A dry run first, and each upload only with G's go-ahead.
- **G's Mac** (8 cores, 16 GB): the clone in `/Users/gagi/git/salmo-snp`, salmon inputs from early November, the
  Synchrosmolt VCF, releases up to 2026-11-05 and trout-2026-11-13. No trout inputs.

**Done**
- Folders: `/mnt/project/ELIXIR/salmo-snp/` with `data/raw`, `data/private`, `data/rainbow_trout/raw`, `release`,
  `logs`; `/mnt/ScratchProjects/ELIXIR/salmo-snp/`.
- `data/private/MOWI_synchro_phased_parents_wgs.vcf.gz`, copied from the Mac (sha256 8d7e12fd...).
- The three trout cohort site files of the workflow run of 2026-11-24, saved from GitHub before they expired
  (2026-11-27): on the Mac in `snpdata/data/rainbow_trout/cohorts-2026-11-24/`, and on Orion in
  `data/rainbow_trout/raw/` where fetch finds them and skips the 78 GB from ENA. sha256: G1023-03 f36d6985...,
  G0424-02 7705bb24..., G0824-027 74ed2cdd....
- The manifests of the releases before, for the diff: `/mnt/project/ELIXIR/salmo-snp/previous/2026-11-20/` and
  `previous/trout-2026-11-13/`.
- The clone in `~/git/salmo-snp` (main at e02767f), with `snpdata/data` and `snpdata/release` linked into the
  project folder, so every command keeps its default paths and the Synchrosmolt file is where layers.yaml looks.
- The environment `/mnt/project/ELIXIR/salmo-snp/env` (job 1544995, 12 minutes): Python 3.12.16, DuckDB 2.0.1,
  Django 5.2.19, PyYAML 6.0.4; `tools/check.sh` passed.
- Releases `2026-11-24` and `trout-2026-11-24` in `/mnt/project/ELIXIR/salmo-snp/release/`, built on 2026-11-25 by
  jobs 1545335 and 1545336 (32 cores and 96 GB each, on one node at the same time):

  | | salmon `2026-11-24` | `trout-2026-11-24` |
  |---|---|---|
  | The whole job | 18 minutes | 15 minutes |
  | fetch | 11.5 minutes | 4 minutes (the cohort files were there) |
  | build | 6 minutes, the motif layer included | 10 minutes |
  | pool | 34 s, 3,436,671 sites | 26 s, 3,372,181 sites |
  | Peak memory | 6.1 GB | 11 GB |
  | Size | 513 MB with its pool; the inputs 3.2 GB | 979 MB with its pool (120 MB); the inputs 2.3 GB |

- Every check of the tables above passed: the row counts; `ns` 112 at all 3,993,949 Synchrosmolt sites; the hub
  SNP's A still the parents' minor allele (G>A, 0.2455); 46 and 13 catalogue rows; the six and four examples; the
  chromatin input v5 (627534ad...); `snpscore verify`. Two results differ from what the tables expected, both
  explained:
  - `snpscore diff` also lists layers that did not change. It compares file checksums: a Parquet file records the
    DuckDB version that wrote it (trout-2026-11-13 was built with 2.0.0, so every trout layer differs), and
    positional layers are written in `chrom, start` order only, so rows that share a start come out in the order
    the threads finish. Salmon's `transcripts` and `transcripts_ncbi` (693,481 and 450,337 shared starts) hold
    exactly the rows of 2026-11-20 (compared with its GitHub data release). Trout's `public_af` and
    `flank_variants` read the cohort files of the 2026-11-24 workflow run, other bytes than for trout-2026-11-13,
    with the same row counts.
  - Tier 2 of the pool is 6.16%, not 6.15%: 184 of the 3,436,671 sites changed tier (tier 2 211,438 -> 211,572,
    tier 3 291,820 -> 291,705), every one at a gill or head kidney state that v5 changed (compared site by site
    with the pool built for 2026-11-20 in salmo-chrombpnet's results). The weights' two new terms change nothing.

- Both releases published on salmobase on 2026-11-25, tested before and after the upload, and the pull request that
  makes salmobase the default merged (Hosting on salmobase, below).

**Deployed (2026-11-25, G asked)**: the deploy's species.sh installed 2026-11-24 and trout-2026-11-24 on the NREC
demo from salmobase, each with its published pool, and the live site was checked with them (docs/TRACKER.md, "Where
things stand"). The installer was also run from a cloud session against the address: every file of 2026-11-24
matched its checksum.

**Next**
1. The older releases on the VM (2026-11-05, trout-2026-11-13, and 2026-11-20 a day after the deploy) go at the
   next deploy: species.sh now removes a release the code no longer names once nothing kept on the server was made
   with it (G, 2026-11-25), before it fetches, so the room counts (4.9 GB were free, under the 5 GB a fetch asks for).
2. So that `snpscore diff` lists only real changes: write positional layers in a full order (every column after
   `chrom, start`), which gives the same bytes on any number of threads.
3. Before anyone uses `salmo-snp download latest` or `snpdata publish --raw` for both species: the first two
   faults below.

**The next builds**, as this one:
- The environment, once: `sbatch prep/orion_env.sbatch` from `snpdata/`. It makes
  `/mnt/project/ELIXIR/salmo-snp/env` with `/cluster/software/Miniconda3/25.7.0-2/bin/conda create` (conda-forge's
  Python 3.12), then runs `pip install -e "snpscore[test]" -e snpdata -e snpportal` and `bash tools/check.sh` in the
  clone; a second run installs and checks again.
- One job per species, from `snpdata/` (32 cores, 96 GB, no time limit; the log goes to
  `/mnt/project/ELIXIR/salmo-snp/logs/`). The date is the day of the build, and a name that was published is never
  built again: `sbatch --job-name=salmon-<date> prep/orion_build.sbatch salmon <date> <the release before>` and
  `sbatch --job-name=trout-<date> prep/orion_build.sbatch trout trout-<date> <the trout release before>`. The
  release before is a folder in `release/`, or in `/mnt/project/ELIXIR/salmo-snp/previous/` with its manifest.json.
- Then publishing: `MODE=dry bash prep/orion_publish.sh <salmon version> <trout version>`, and `MODE=run` with G's
  go-ahead (Hosting on salmobase).
- While a build runs, leave the clone as it is (no pull, no branch switch): the jobs run its code.
- If a download fails in fetch (it reads from Ensembl, EBI, NCBI, JASPAR, Bgee, bioRxiv and GitHub besides
  salmobase): rerun the job, as fetch keeps what it has. Failing that, G's Mac has every input that is not
  salmobase's, all of fixed versions, in `~/git/salmo-snp/snpdata/data/raw/`: from the Mac, `rsync -t <file>
  orion:/mnt/project/ELIXIR/salmo-snp/data/raw/`. Never take the Mac's `AtlanticSalmon_unified_peaks.bed`: it is
  an old version.

## Hosting on salmobase

Since 2026-11-25 the data is at `https://salmobase.org/datafiles/datasets/salmo-snp` (`datafiles/datasets/salmo-snp/`
on the server `salmobase`), the default of serve.py `DATA_URL`:

```
releases/<version>/        the snapshot: every file of the release and SHA256SUMS; salmon and trout side by side
releases/<version>/pool/   the public pool built with the release (not in SHA256SUMS): the NREC demo takes it
releases/latest.json       the default species' newest release
```

How it is published (G, 2026-11-25: "the build is made under the elixir project, where salmobase is. We need only to
make links and then rsync to salmobase server"): `prep/orion_publish.sh`, from `snpdata/` on a login node. It checks
each release against its SHA256SUMS, links it into salmobase's share on Orion
(`/mnt/project/ELIXIR/salmobase/datafiles/datasets/salmo-snp/releases/<version>` -> the release folder), writes
`latest.json`, and sends the share's folder with `rsync -rLt --chmod=D755,F644` (the links as the files they point
to; never `--delete`), then checks the server's copy against SHA256SUMS. `MODE=dry` (the default) shows what would
go; `MODE=run` sends it, with G's go-ahead. `salmo-snp download` takes the genome from the address in the manifest
(salmobase's `genomes/` folder for both species), so no `raw/` is needed.

Published on 2026-11-25 (G: "Do a test and then if it passes upload the data"), after these tests passed:
- an install from the staged share (`salmo-snp download --from <share folder>`, both species, the genomes from
  salmobase checked against the manifests), then the portal on it (`salmo-snp serve`): health ok, and the examples
  Known loci, Known SVs and the SYNTHETIC chip (salmon) and Known loci and Known SVs (trout, by the species bar)
  scored with no error;
- the rsync dry run: 71 files and 10 folders, 1.56 GB, all new, nothing deleted.

Then the upload (22 seconds) and, after it: the server's copy matched SHA256SUMS; `salmo-snp download --species all`
with this pull request's defaults installed both releases from the address, and the portal on that install passed
the same test (Public SNPs instead of the chip); `deploy/species.sh` on a mock of the VM installed both from the
address, the salmon release as /srv/snpportal/release (the release before moved to releases/) and both pools.

The pull request that made salmobase the default (2026-11-25):

| Where | Change |
|---|---|
| `serve.py` | `DATA_URL` defaults to the address (`SALMO_SNP_DATA_URL` still overrides it); `RELEASE` 2026-11-24 |
| `tools/get_data.sh` | `salmo-snp download`: no GitHub token |
| `snpportal/deploy/species.sh` | Fetches a release the VM lacks from the address (its SHA256SUMS files, the genome from the manifest's address, the pool from `releases/<version>/pool/`) instead of the GitHub data release |
| The deploy workflow's job for stale pools | Reads the release from the address (through `tools/get_data.sh`) |
| README and the Data page | `salmo-snp download`, without the GitHub Release steps |
| `species-data` workflow, `prep/github_release.sh` | Kept, no longer the way: salmon cannot build on a runner (its Synchrosmolt input is not online) |

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

## Text to start the chat on Orion

```
We are on Orion over SSH. Clone https://github.com/garethgillard/salmo-snp.git into ~/git/ if it is not there (else
pull main), and read AGENTS.md, then docs/ORION.md: it says what the next Atlantic salmon and rainbow trout data
releases contain, what is already prepared here and what is next. Go on from "Next" in its section "On Orion".
Tell me before any job is submitted and before anything is published; never set a SLURM time limit.
```
