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
snpdata publish release/<version> --to <the salmobase folder>      # only after the checks, with G's go-ahead
```

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
of it the motif layer, which scales with cores; the pool a few minutes.

## On Orion: what was found, what is done, what is next (2026-11-24, 23:15)

The cloud session reaches Orion through G's Mac: G attaches the Mac's `git` folder to the session (Remote Control),
and commands run there as `ssh orion '...'`, each approved by G at a prompt. Most of what follows was read from the
notes of the ChromBPNet work on Orion (`~/git/salmo-chrombpnet/AGENTS.md`), which knows the cluster well.

**Found**
- **SLURM**: partition `orion` for CPU jobs, 6 nodes of 384 cores and 1.5 TB each; no time limits, and G's rule for
  all Orion work is never to set one (`--time`). Accounts `nmbu` and `biovit_elixir`. Nothing heavy on a login node.
- **Network**: login and compute nodes reach GitHub over HTTPS, salmobase.org, Ensembl and EBI, so fetch can run in
  a job. Port 22 to github.com is blocked; salmo-snp is public, so clone it over HTTPS.
- **Storage**: `/mnt/project/ELIXIR/` (group `elixir`: 2.9 of 5 TB used) and `/mnt/ScratchProjects/ELIXIR/`.
- **Python**: conda and mamba in `/cluster/software/Miniconda3`; the default python3 is 3.8, so make an environment
  with 3.12.
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

**Next** (no job has been submitted)
1. Merge the pull request with the citation and `prep/build_release.sh` (#35).
2. On Orion: `git clone https://github.com/garethgillard/salmo-snp.git ~/git/salmo-snp`; in `snpdata/`, link `data`
   to `/mnt/project/ELIXIR/salmo-snp/data` and `release` to `/mnt/project/ELIXIR/salmo-snp/release`, so every
   command keeps its default paths and the Synchrosmolt file is where layers.yaml looks (`../private/`).
3. The environment, in a small job: `mamba create -y -p /mnt/project/ELIXIR/salmo-snp/env python=3.12 pip`, then
   `pip install -e snpscore -e snpdata -e snpportal`, then `bash tools/check.sh`.
4. For the diff: the manifests of the releases before (2026-11-20 is unpacked under
   `/mnt/project/ELIXIR/salmo-chrombp/salmo-snp/`; trout-2026-11-13 is on the Mac in `snpdata/release/`).
5. One job per species, 32 cores and 96 GB, no time limit, log in `/mnt/project/ELIXIR/salmo-snp/logs/`:
   `MEMORY=64GB SPILL=/mnt/ScratchProjects/ELIXIR/salmo-snp/spill PREVIOUS=<manifest folder> bash
   prep/build_release.sh salmon <date>` and the same for `trout trout-<date>`. The date is the day of the build.
6. Hold each summary against the tables above. Then, with G's go-ahead: `snpdata publish release/<version> --to
   /mnt/project/ELIXIR/salmobase/datafiles/datasets/salmo-snp`, and the upload to `salmobase` as described.
7. The pull request that makes salmobase the default (below), and "deploy to NREC" when G says.

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

## Text to start a new chat, if this one is not continued

```
Read AGENTS.md, then docs/ORION.md: it says what the next Atlantic salmon and rainbow trout data releases contain,
what is already done on Orion and what is next. Orion is reached through my Mac: attach its `git` folder to this
session (Remote Control) and run `ssh orion '...'` from it. Go on from "Next" in docs/ORION.md; tell me before any
job is submitted and before anything is published.
```
