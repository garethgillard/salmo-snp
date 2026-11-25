# Building the data releases on Orion and hosting them on salmobase: brief (2026-11-24)

This brief is for the chat that builds the releases on Orion, NMBU's HPC cluster, over SSH. It holds what G decided,
what the next build contains (planned on 2026-11-25), how a build runs, what the first builds there found and made
(releases 2026-11-24 and trout-2026-11-24), and how a release reaches salmobase and the live app. Keep it up to date
as the work goes on. Read [../AGENTS.md](../AGENTS.md) first: its rules apply here too.

## Decided (G, 2026-11-24)

- Releases are built on Orion from now on: SLURM jobs, with salmobase's data on the same file system. Not on G's Mac
  and not on GitHub's runners (the `species-data` workflow), which the handover in TRACKER step 9 still describes.
- The built release snapshots are uploaded to salmobase's data files, and the live app and every install fetch them
  from there. This is plan 5 of AGENTS.md: the publishing code exists (`snpdata publish`, `salmo-snp download`,
  `serve.py DATA_URL`); it has only ever pointed at GitHub Releases.
- What went into the builds of 2026-11-25 (G, 2026-11-24): the ChromBPNet scores could wait for a later build; the
  AQUA-FAANG citation became the published paper (Nat Ecol Evol 2026;10:1959-1981); no benchmark files in the
  snapshot ("aim for only data used in the portal or package tool"); no pool with coding consequences; the fSalSal1
  conversion can be made on Orion later and is skipped for now; no missense score yet.
- The build after those (G, 2026-11-25): "plan the next build using the new gill salmo-chrombpnet model available,
  and the new trout immunomap data on salmobase". The plan is the next section.
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

## The next build (planned 2026-11-25)

G, 2026-11-25: "plan the next build using the new gill salmo-chrombpnet model available, and the new trout immunomap
data on salmobase". Nothing is built yet. The numbers below were read from salmobase on 2026-11-25 and measured
against releases 2026-11-24 and trout-2026-11-24 in a cloud session. G answered the plan's questions the same day
(DECISIONS #60 to #64), and the repository is ready for the build but for one file: the gill scores (What it needs
first, 1).

**New on salmobase since the last build**

- **The gill ChromBPNet model**, `datafiles/datasets/chrombpnet/AtlanticSalmon/v1/Gill/` (2026-11-25): five fold
  models trained on the reads of the three gill conditions together (212,433 training peaks; counts r in held-out
  peaks 0.58 to 0.63), a scorer that needs only numpy and onnxruntime (`scorer/chrombpnet_predict.py`), and a
  benchmark. It publishes no per-SNP scores beyond 200 test SNPs (its benchmark scored 241,881). Its
  allelic-imbalance test is too small to say whether the predicted direction is right (10 significant sites, half
  of them agree). Licence: PolyForm Noncommercial, NMBU, as salmo-snp.
- **The unified peaks v6** (2026-11-25; `VERSION.md` beside the files). The trout file gained the ImmunoMap. The
  salmon file is v5 with the summary label and its colour back in columns 7 and 8.
- **The trout ImmunoMap** (INRAE; head kidney in vivo; ENA PRJEB57395): chromatin states of PBS (6 fish) and Vibrio
  (fish 2, 3, 4 and 6; two failed) from one ChromHMM model each (ATAC, H3K4me3, H3K27ac, H3K27me3), their robust
  peaks, the nf-core output and an ImmunoMap folder in the trout trackhub. Poly I:C has signal tracks but no states
  (its H3K4me3 and H3K27ac failed), so no peak is named for it. The in vitro leukocytes have signal tracks only.

### Atlantic salmon, release `<date>` (the one before: 2026-11-24)

| Part | What changes | Check after the build |
|---|---|---|
| `chrombpnet_gill` (new) | A per-variant score layer (snpdata/README.md "A per-variant score"), in layers.yaml since 2026-11-25: the gill model's prediction of what the alt allele does to accessibility, each SNP scored by the fold that held its chromosome out. Columns: `score` (the absolute log2 fold change), `effect` (the log2 fold change, signed) and `percentile` (the scorer's, among 100,000 random public SNPs). Shown in the Table's Scores column and on the card with an arrow for the direction, and in the Locus browser's Predicted allele effects row (up and red: the alt allele more accessible; down and blue: less). It counts nothing (weights.yaml `variant_scores: {}`, DECISIONS #53). First set (#60): the public and Synchrosmolt SNPs inside the model's training peaks; every site later. **The score file does not exist yet** (What it needs first, 1) | About 216,592 rows, with `effect` and `percentile` among the columns; a public SNP in a gill peak has `chrombpnet_gill_score`, `_effect` and `_percentile` after `snpscore annotate`. Or no such layer, and a line in the build's log saying so, when the file was not published in time |
| `chromatin` | Input v6. Nothing scored changes: read with the build's reader, it has the 328,894 peaks of release 2026-11-24 and the same state in every one of the 27 conditions. `summary` is filled again (empty since v3; nothing shows it) | 328,894 rows |
| The public pool | Built again, as weights.yaml changed (a weak state that only trout has: nothing changes for salmon). pike is still 0 (DECISIONS #54) | 3,436,671 sites; tiers 0.38%, 6.16%, 8.49%, 84.98%, as for 2026-11-24 |
| Unchanged | Every other layer and table of 2026-11-24: `summit` 2,468,735, `pike` 1,226,940, `synchrosmolt_af` 3,993,949, `motif` 533,163, `public_af` 7,572,808, `molqtl` 2,656, `liftover_icsasg_v2` 735,344 blocks, the catalogue's 46 rows, the six examples | `snpscore diff 2026-11-24 <new>`: `chrombpnet_gill` and `chromatin` are new or changed. It compares file checksums, so it also lists the layers whose rows share a start (`transcripts`, `transcripts_ncbi`, as on 2026-11-25): compare those row by row |

### Rainbow trout, release `trout-<date>` (the one before: trout-2026-11-24)

| Part | What changes | Check after the build |
|---|---|---|
| `chromatin` | Input v6: 205,722 peaks (194,002) in 19 conditions, `HeadKidney_invivo_pbs` and `HeadKidney_invivo_vibrio` being new. 46,534 peaks carry a head kidney state and 12,043 exist only there; the 17 other conditions keep their states. Head kidney counts in the tiers, as salmon's does (G, #62). The new label `Weak_accessible_chromatin` (14,494 PBS peaks) is a weak state (G, #63). The trout head kidney models name no peak an active enhancer, so active there means Active TSS | 205,722 rows, 19 condition columns (the input has no overlapping peaks) |
| `summit` | PBS's merged-replicate MACS2 peaks join the 17 files. Vibrio has no such file on salmobase: the merged files of conditions with a failed fish were withdrawn (#64) | More than 1,257,737 rows; 18 conditions (19 with a Vibrio file) |
| `motif` | Computed again, as it follows `chromatin` | 1,083,423 rows: the public sites inside a v6 peak (1,029,347) |
| tracks.yaml | Regenerated on 2026-11-25 from the trout trackhub with its ImmunoMap folder: 733 signal tracks (603), 19 state tracks and 19 robust peak tracks (17 each). The 130 new signal tracks are ATAC, H3K27ac, H3K27me3, H3K4me3, input and RNA-seq of head kidney in vivo (PBS, poly I:C, Vibrio) and of leukocytes in vitro | The Locus browser offers 'HK PBS' and 'HK Vibrio' state rows; the Table's Chromatin filter offers head kidney |
| Wording | 19 conditions; the ImmunoMap in the samples, the Methods and Help texts and the state legend (the species block of layers.yaml) | The trout pages name 19 conditions, and their sample texts name head kidney after PBS or Vibrio |
| The public pool | The same 3,372,181 sites. Tiers change at head kidney peaks: of the 18,801,055 public sites, 350,142 lie in a peak with a head kidney state, 158,124 where head kidney is active, and 7,266 where no other condition is; 19,925 lie in a peak whose only counted state is the new weak one | The tier shares of trout-2026-11-24 were 0.28%, 4.92%, 4.88%, 89.92%; expect tiers 1 to 3 to grow a little |
| Unchanged | `pike` 1,192,301, `public_af` 18,801,055, `flank_variants` 46,593,552, the gene and regulatory layers, the catalogue's 13 rows, the four examples | `snpscore diff`, read as for salmon |

### What it needs first

1. **The gill scores, from the ChromBPNet work** (its own repository and chat on Orion). A build does not wait for
   them (G, 2026-11-25: the release "might not include chrombpnet scores"): while the file is not at the address
   layers.yaml names, `snpdata fetch` says so and goes on, and `snpdata build` leaves the layer out; the build after
   the file is published takes it. The portal can predict one SNP at a time without the file (the card's button:
   snpportal/README.md "Predictions on demand"). The request, as text for that chat:

   ```
   Make the gill score file for the next salmo-snp release (salmo-snp docs/ORION.md, "The next build").
   1. The SNPs: those of salmo-snp release 2026-11-24 inside the Gill v1 model's training peaks. Take chrom, "end"
      (the 1-based position), ref and alt from public_af.parquet and synchrosmolt_af.parquet in
      /mnt/project/ELIXIR/salmo-snp/release/2026-11-24/, keep single-base ref and alt, and keep a SNP when
      start < pos <= end of a peak in training_peaks.narrowPeak.gz (its chromosomes are named chr1-chr29).
      Expected: 216,592 SNPs, 176,608 of them public sites.
   2. Score them with the Gill v1 model, each SNP by the fold that held its chromosome out (the release's scorer
      with --gpu, or variant-scorer as the benchmark did).
   3. Write chrombpnet_gill.tsv.gz: tab-separated, the header chrom pos ref alt score effect percentile, one row
      per scored SNP, chromosomes named 1-29, with score = abs_logfc, effect = logfc and
      percentile = abs_logfc_percentile of the scorer's scores.tsv.
   4. After a dry run and G's go-ahead, publish it with its sha256 as
      datafiles/datasets/chrombpnet/AtlanticSalmon/v1/Gill/scores/chrombpnet_gill.tsv.gz (salmo-snp's layers.yaml
      names that address: say so if it goes elsewhere). The scorer's whole table and its browser track
      (variants.Gill.bed) are welcome beside it.
   Later, not now (G, 2026-11-25): every public and Synchrosmolt site, 9,288,186 SNPs, about 35 GPU-hours.
   ```

   The scorer was tried in a cloud session (4 cores, no GPU): its scores of 44 of the model's test SNPs equal the
   published ones to 0.00001, and it takes 0.3 to 0.5 s a SNP there. The fixture's 697 scores were made that way
   (`snpdata/tests/fixture/chrombpnet_gill.tsv.gz`: real predictions, the same three columns).
2. **From the AQUA-FAANG files, if Vibrio is to have summits (#64)**: a MACS2 call on the merged reads of Vibrio's
   four fish, beside PBS's in `nfcore/RainbowTrout/ImmunoMap/ATAC/results/bwa/mergedReplicate/macs/narrowPeak/`,
   and one more line in the trout layers.yaml (`summit.files`). The build goes without it otherwise.
   Also: VERSION.md cites `chromatin_states/RainbowTrout/ImmunoMap/README.md`, which is not on salmobase (404).
3. **In this repository**: done on 2026-11-25 in one pull request. The salmon registry has the `chrombpnet_gill`
   layer and the trout registry the 19 conditions, PBS's peak file, the ImmunoMap's wording and samples;
   `rainbow_trout/tracks.yaml` is regenerated; weights.yaml lists `Weak_accessible_chromatin` as weak; the portal
   draws the effects row and the new state; both fixtures and the tests follow. Left for after publishing: serve.py
   `RELEASE` and `RELEASES` name the new releases. Not needed for this build: positional layers written in a full
   order ("Next" below), which would let later diffs list only what changed.

### Not in this build

| Candidate | Why |
|---|---|
| A gill score for every public and Synchrosmolt site (9,288,186) | Later (G, 2026-11-25): about 35 GPU-hours. The same file and layer then hold them all, and the percentile keeps its meaning |
| ChromBPNet models of other conditions | One layer each (`chrombpnet_<model>`), as their releases reach salmobase; only gill is there |
| Scores for a user's own SNPs that are not in the scored set | They show 'not scored'. Scoring them in the install needs numpy and onnxruntime, a dependency decision (#61) |
| Benchmark files in the snapshot | No: a snapshot holds only data the portal or the package uses (G, 2026-11-24) |
| A pool with coding consequences (`snpscore pool --assay`) | Not now (G, 2026-11-24). It still blocks DECISIONS #5 |
| fSalSal1 position conversion | Can be made on Orion (one minimap2 run); skipped for now (G, 2026-11-24) |
| A missense effect score | Not yet (docs/MISSENSE.md; DECISIONS #59) |
| The input files as a mirror (`publish --raw`) | After the fix under Hosting on salmobase. It is the only way to pass on the Synchrosmolt site frequencies |

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
catalogue rows, examples and pool tiers to hold against the plan's tables.

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

- What the two releases brought, against 2026-11-20 and trout-2026-11-13. Salmon: `chromatin` from the unified peaks
  v5 (328,894 rows; v3 before), the new layers `summit` (2,468,735) and `pike` (1,226,940), `synchrosmolt_af` from
  the parents' whole-genome set (3,993,949 sites, 112 fish), `motif` computed again (533,163), 46 catalogue rows with
  the structural variants, and the six examples. Trout: `summit` (1,257,737) and `pike` (1,192,301), 13 catalogue
  rows and four examples.
- Every check of that plan passed: the row counts; `ns` 112 at all 3,993,949 Synchrosmolt sites; the hub
  SNP's A still the parents' minor allele (G>A, 0.2455); 46 and 13 catalogue rows; the six and four examples; the
  chromatin input v5 (627534ad...); `snpscore verify`. Two results differ from what the plan expected, both
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
0. The next build: the plan above, and what it needs first.
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

The demo VM: 4.9 GB were free on 2026-11-25, a salmon release is about 0.5 GB with its pool and a trout one about
1 GB, and species.sh refuses to fetch under 5 GB free. Since 2026-11-25 species.sh itself removes the releases the
code no longer names, once nothing kept on the server was made with them ("Next", 1), before it fetches.

## Text to start the chat on Orion

```
We are on Orion over SSH. Clone https://github.com/garethgillard/salmo-snp.git into ~/git/ if it is not there (else
pull main), and read AGENTS.md, then docs/ORION.md: it says what the next Atlantic salmon and rainbow trout data
releases contain ("The next build"), what they need first, and how the builds before were run here ("On Orion").
Tell me before any job is submitted and before anything is published; never set a SLURM time limit.
```
