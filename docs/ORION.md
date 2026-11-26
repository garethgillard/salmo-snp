# Building the data releases on Orion and hosting them on salmobase: brief (2026-11-24)

This brief is for the chat that builds the releases on Orion, NMBU's HPC cluster, over SSH. It starts with the plan
of the next build and the steps of every build, which is all a build needs. The rest is the record: what G decided,
what the latest build contains (releases 2026-11-25 and trout-2026-11-25, planned and built on 2026-11-25), how a
build runs, what the first builds there found and made (releases 2026-11-24 and trout-2026-11-24), how a release
reaches salmobase and the live app, and what would make all of it faster. Keep it up to date as the work goes on.
Read [../AGENTS.md](../AGENTS.md) first: its rules apply here too.

## The next build: the plan and the steps

G, 2026-11-25: "From now, the builds will run on orion in a separate orion ssh chat, using a build plan it pulls
from the repo and serve the data by syncing it to salmobase."

**The plan (G, 2026-11-26: the scoring decisions, docs/DECISIONS.md; and "The build run is allowed to do testing and
changes as it goes too").** The next build, once the pull request with G's scoring answers is merged: releases
`atlantic_salmon-Ssal_v3.1-<date>` and `rainbow_trout-USDA_OmykA_1.1-<date>`, the first named
<species>-<assembly>-<date> (G, 2026-11-26: "add salmon genome name to the salmon one ... the genome version ...
consistant between salmon and trout ... atlantic and rainbow in the name"). Their data is that of 2026-11-25 and
trout-2026-11-25, with whatever salmobase has changed since, and:
1. **A new layer, `cne`, in both species** (DECISIONS #74): fetch downloads the paper's pike CNEs from Zenodo (record
   21415252, `Supplementary_Data_4.txt`, 20.8 MB, md5 68fbe278fe32c3c812c509b7cd5f0341) and projects them through
   salmobase's `Aqua-Faang/alignments/salmon-trout-pike/maf_ref_Ssal_A/` and `maf_ref_Omyk_A/` (29 files each, about
   2 GB, read from SNPDATA_SALMOBASE on Orion; snpdata/cne.py, minutes from the disk). zenodo.org has not been tried
   from Orion: if a job can't reach it, run `snpdata fetch` for both registries once on a login node first (the
   projection takes about 5 minutes on 4 cores) and the jobs find the files. fetch must say
   `Ssal_A_pike_cnes.bed: 1,438,398 runs, 33,649,069 bp, 403,884 CNEs` and
   `Omyk_A_pike_cnes.bed: 1,391,810 runs, 33,143,090 bp, 402,078 CNEs` (the code chat's runs of 2026-11-26; salmon's
   is also the scoring chat's). `changes since` lists `cne` as new and no other layer, unless salmobase changed an
   input.
2. **The pools with G's rules and with the genome** (DECISIONS #75: the sequence step runs whenever the genome is on
   the disk), so they carry coding consequences and synonymous counts 1 there as in uploads. G's rules on release
   2026-11-25's pool, before coding consequences, give salmon tiers 1-4 of 1.09 / 5.75 / 18.42 / 74.74%; the
   synonymous SNPs then move down a little: report the build's numbers. The pool step takes longer than before.
3. **The benchmark of the salmon release** (DECISIONS 4b): build_release.sh runs `snpscore benchmark --positives
   molqtl:ca molqtl:e --by-tissue`, writes `benchmark-<version>.tsv` and `.txt` beside the release (not in it, as G
   asked of snapshots), and stops unless the last line reads `v0.1 check (DECISIONS 4b): ...: pass`.
4. **The build run may test and change things as it goes** (G, 2026-11-26): fix what fails in the clone, and report
   every change in the hand-back; the chat on the code takes it into a pull request.

The checks then: the summary's rows equal those of 2026-11-25 except `cne`, and the release test ends `release test:
ok`. Publish with G's go-ahead, then hand back the two names, fetch's two `cne` lines, the pools' tiers, the v0.1 line
and any change made on the way. The liver ChromBPNet model is not a layer yet: its folder on salmobase has the model
and no `scores/` file, so it runs on demand only (the card's Predict button, from lib/models.yaml). Later, each when G
says: the missense run ([MISSENSE.md](MISSENSE.md)), the ChromBPNet scores of every public site, and allelic imbalance
in the 12 fish (the tests that decide DECISIONS #53 and #58).

Tomorrow, the salmobase release: once the code is merged, G tags it (vX.Y.Z), the release workflow builds the wheels
and the Docker image, this chat publishes the image beside the releases (`snpportal/deploy/publish_image.sh`;
SALMOBASE.md "Working from Orion") and installs it on the server from there (SALMOBASE.md "Install, once"), each step
when G says.

**The steps**, the same for every build (the commands are for `snpdata/` in the clone `~/git/salmo-snp`):

1. Pull main, while no build runs (the jobs run the clone's code). If a `pyproject.toml` changed since the last
   build: `sbatch prep/orion_env.sbatch`.
2. Tell G, then submit one job per species; the date is the day of the build, and a name that was published is
   never built again:
   `sbatch --job-name=salmon-<date> prep/orion_build.sbatch salmon <date>` and
   `sbatch --job-name=trout-<date> prep/orion_build.sbatch trout <date>`, which build `atlantic_salmon-Ssal_v3.1-<date>` and
   `rainbow_trout-USDA_OmykA_1.1-<date>` (G, 2026-11-26: every release named <species>-<assembly>-<date>; `snpdata name` says it).
   Each fetches what is missing or has changed on salmobase, copies the unchanged layers from the release before,
   builds the rest and the pool, and checks every file ("How a build runs").
3. Read the end of each log (`/mnt/project/ELIXIR/salmo-snp/logs/`): `changes since` must list the layers the plan
   names and no other, and the summary's rows must be the plan's. Then test the two releases together:
   `sbatch --job-name=test-<date> prep/orion_test.sbatch atlantic_salmon-Ssal_v3.1-<date> rainbow_trout-USDA_OmykA_1.1-<date>` starts the portal on them as a user
   runs it and scores every example of both species through the job queue (`prep/release_test.sh`; two to three
   minutes); its log must end with `release test: ok`. Anything else is a finding: stop and tell G.
4. `MODE=dry bash prep/orion_publish.sh atlantic_salmon-Ssal_v3.1-<date> rainbow_trout-USDA_OmykA_1.1-<date>` on a login node, and with G's go-ahead `MODE=run`
   ("Hosting on salmobase").
5. Hand back to the chat that works on the code: the two versions, the `changes since` and summary lines of both
   logs, and anything that was not as planned. That chat names the releases in serve.py (a pull request, which G
   merges).
6. When G says, the portal is updated to the version that names them: on the salmobase server by this chat
   ([SALMOBASE.md](SALMOBASE.md), which is the brief for installing and updating the portal there), and on the NREC
   demo, while it lasts, by GitHub's `deploy` workflow.

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

## The latest build: releases 2026-11-25 and trout-2026-11-25

G, 2026-11-25: "plan the next build using the new gill salmo-chrombpnet model available, and the new trout immunomap
data on salmobase". Planned, prepared, built on Orion and published on salmobase the same day
(`releases/latest.json` names 2026-11-25 since 13:11 GMT). G answered the plan's questions that day (DECISIONS #60
to #64). The tables below were the plan: their numbers were measured before the build, against releases 2026-11-24
and trout-2026-11-24.

**The result**, checked from a cloud session on the published files (2026-11-25):

- **Salmon `2026-11-25`** (built from main d48f4a6 in 7 minutes): `chrombpnet_gill` has 216,586 SNPs with score,
  percentile and effect (105,604 predicted more accessible, 110,981 less), built from the score file published at
  13:01 GMT (the manifest's source checksum is the published one, 88007cf6...). The set was the 216,592 single-base
  SNPs of release 2026-11-24 inside the model's 212,433 training peaks: 176,604 public sites and 39,988 only in the
  Synchrosmolt set. Six are not scored, on chromosome 15 at positions 318 to 531: within 1,057 bp of the
  chromosome's end, where the model's window does not fit. `chromatin` is v6, its states in all 27 conditions equal
  to 2026-11-24's row by row, with `summary` filled. Every other layer has the rows of 2026-11-24 (`transcripts`
  and `transcripts_ncbi` in another order), and the pool's 3,436,671 sites are in the same tiers to the SNP
  (13,048, 211,572, 291,705, 2,920,346).
- **Trout `trout-2026-11-25`** (11 minutes): `chromatin` 205,722 peaks in 19 conditions; `summit` 1,383,135 from 18
  peak files (PBS's among them; Vibrio's summits were skipped, #64); `motif` 1,083,423, the number predicted;
  tracks.yaml with 733 signal tracks and 19 state and 19 peak tracks; the new wording and samples. The pool's
  3,372,181 sites: tiers 0.28%, 4.98%, 5.05% and 89.69% (9,592, 167,768, 170,441, 3,024,380; before: 9,368,
  166,066, 164,629, 3,032,118). `snpscore diff` lists `chromatin`, `summit` and `motif`, and the two transcript
  layers for their row order.
- **The installer**, on Orion and again from a cloud session: `salmo-snp download` fetched both releases from the
  address with every file matching its checksum, and `snpscore verify` passed on both. The portal on them: for
  salmon the Table's Scores column, the Locus browser's effects row and the card's Predict button (none of the 40
  known-loci SNPs lies in a gill peak, so each shows 'not scored' and the button is how to see its prediction); for
  trout the 19 conditions with the 'HK PBS' and 'HK Vibrio' rows and the new state in the legend.
- **Who made the scores**: the build chat on Orion itself, with the model release's own scorer on CPU (onnxruntime,
  in salmo-chrombpnet's scorer environment): 48 SLURM tasks of 4 CPUs, about an hour; the scorer's self-test
  passed. One fold model takes about 4.6 GB at batch 32, and 8 GB was not enough: 16 GB for a 4-CPU task, 32 GB for
  the self-test. The scripts and the full per-SNP tables (JSD and the scorer's other scores) are in
  `/mnt/project/ELIXIR/salmo-snp/chrombpnet_gill/`.
- Worth knowing about the scores: SNPs in gill peaks do not rank high by |log2 fold change| alone. Their median
  percentile among the 100,000 random SNPs is 0.44, and 0.7% are in the top 1%. The score is a relative change, and
  the scorer's active-allele quantile, which says whether the place is accessible at all, is not in the layer.

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

### Atlantic salmon, release 2026-11-25 (the one before: 2026-11-24)

| Part | What changes | Check after the build |
|---|---|---|
| `chrombpnet_gill` (new) | A per-variant score layer (snpdata/README.md "A per-variant score"), in layers.yaml since 2026-11-25: the gill model's prediction of what the alt allele does to accessibility, each SNP scored by the fold that held its chromosome out. Columns: `score` (the absolute log2 fold change), `effect` (the log2 fold change, signed) and `percentile` (the scorer's, among 100,000 random public SNPs). Shown in the Table's Scores column and on the card with an arrow for the direction, and in the Locus browser's Predicted allele effects row (up and red: the alt allele more accessible; down and blue: less). It counts nothing (weights.yaml `variant_scores: {}`, DECISIONS #53). First set (#60): the public and Synchrosmolt SNPs inside the model's training peaks; every site later. **The score file does not exist yet** (What it needs first, 1) | About 216,592 rows, with `effect` and `percentile` among the columns; a public SNP in a gill peak has `chrombpnet_gill_score`, `_effect` and `_percentile` after `snpscore annotate`. Or no such layer, and a line in the build's log saying so, when the file was not published in time |
| `chromatin` | Input v6. Nothing scored changes: read with the build's reader, it has the 328,894 peaks of release 2026-11-24 and the same state in every one of the 27 conditions. `summary` is filled again (empty since v3; nothing shows it) | 328,894 rows |
| The public pool | Built again, as weights.yaml changed (a weak state that only trout has: nothing changes for salmon). pike is still 0 (DECISIONS #54) | 3,436,671 sites; tiers 0.38%, 6.16%, 8.49%, 84.98%, as for 2026-11-24 |
| Unchanged | Every other layer and table of 2026-11-24: `summit` 2,468,735, `pike` 1,226,940, `synchrosmolt_af` 3,993,949, `motif` 533,163, `public_af` 7,572,808, `molqtl` 2,656, `liftover_icsasg_v2` 735,344 blocks, the catalogue's 46 rows, the six examples | `snpscore diff 2026-11-24 <new>`: `chrombpnet_gill` and `chromatin` are new or changed. It compares file checksums, so it also lists the layers whose rows share a start (`transcripts`, `transcripts_ncbi`, as on 2026-11-25): compare those row by row |

### Rainbow trout, release trout-2026-11-25 (the one before: trout-2026-11-24)

| Part | What changes | Check after the build |
|---|---|---|
| `chromatin` | Input v6: 205,722 peaks (194,002) in 19 conditions, `HeadKidney_invivo_pbs` and `HeadKidney_invivo_vibrio` being new. 46,534 peaks carry a head kidney state and 12,043 exist only there; the 17 other conditions keep their states. Head kidney counts in the tiers, as salmon's does (G, #62). The new label `Weak_accessible_chromatin` (14,494 PBS peaks) is a weak state (G, #63). The trout head kidney models name no peak an active enhancer, so active there means Active TSS | 205,722 rows, 19 condition columns (the input has no overlapping peaks) |
| `summit` | PBS's merged-replicate MACS2 peaks join the 17 files. Vibrio has no such file on salmobase: the merged files of conditions with a failed fish were withdrawn (#64) | More than 1,257,737 rows; 18 conditions (19 with a Vibrio file) |
| `motif` | Computed again, as it follows `chromatin` | 1,083,423 rows: the public sites inside a v6 peak (1,029,347) |
| tracks.yaml | Regenerated on 2026-11-25 from the trout trackhub with its ImmunoMap folder: 733 signal tracks (603), 19 state tracks and 19 robust peak tracks (17 each). The 130 new signal tracks are ATAC, H3K27ac, H3K27me3, H3K4me3, input and RNA-seq of head kidney in vivo (PBS, poly I:C, Vibrio) and of leukocytes in vitro | The Locus browser offers 'HK PBS' and 'HK Vibrio' state rows; the Table's Chromatin filter offers head kidney |
| Wording | 19 conditions; the ImmunoMap in the samples, the Methods and Help texts and the state legend (the species block of layers.yaml) | The trout pages name 19 conditions, and their sample texts name head kidney after PBS or Vibrio |
| The public pool | The same 3,372,181 sites. Tiers change at head kidney peaks: of the 18,801,055 public sites, 350,142 lie in a peak with a head kidney state, 158,124 where head kidney is active, and 7,266 where no other condition is; 19,925 lie in a peak whose only counted state is the new weak one | The tier shares of trout-2026-11-24 were 0.28%, 4.92%, 4.88%, 89.92%; expect tiers 1 to 3 to grow a little |
| Unchanged | `pike` 1,192,301, `public_af` 18,801,055, `flank_variants` 46,593,552, the gene and regulatory layers, the catalogue's 13 rows, the four examples | `snpscore diff`, read as for salmon |

### What it needed

1. **The gill scores**: asked of the ChromBPNet work (its own repository and chat on Orion), and made in the end
   by the build chat with the model release's scorer (above). Published in time, at 13:01 GMT on 2026-11-25, with
   216,586 of the 216,592 SNPs asked for. A build does not wait for
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

   (The public sites among them are 176,604: the 176,608 counted four public records with longer alleles, from
   before the single-base rule.)

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
   draws the effects row and the new state; both fixtures and the tests follow. After publishing, serve.py
   `RELEASE` and `RELEASES` were set to the new releases (the pull request after the build). Not done: positional
   layers written in a full order ("Next" below), which would let later diffs list only what changed.

### Left for the next build

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
MEMORY=64GB bash prep/build_release.sh salmon <date>
MEMORY=64GB bash prep/build_release.sh trout <date>          # -> release/rainbow_trout-USDA_OmykA_1.1-<date>
MODE=dry bash prep/orion_publish.sh atlantic_salmon-Ssal_v3.1-<date> rainbow_trout-USDA_OmykA_1.1-<date>   # only after the checks; then MODE=run, with G's go-ahead
```

On Orion these run as SLURM jobs (`prep/orion_build.sbatch`, "On Orion" below); elsewhere `snpdata publish
release/<version> --to <a folder>` lays out the same folder by copying.

It runs, and stops at the first that fails: `snpdata fetch`, for salmon `prep/make_demo.sh` (the three example
inputs: the step release 2026-11-20 missed), `snpdata build` with DuckDB's limits, `snpscore pool`, `snpscore
verify`, `snpscore diff` against the release before, and a summary of row counts, catalogue rows, examples and pool
tiers to hold against the plan's tables.

Nothing is left to do by hand (G, 2026-11-25: "Yes if it's changed you can fetch again. Yes reuse where you can to
save time between releases"); the two steps the builds of 2026-11-25 needed are gone:

- **A changed input is fetched again.** `snpdata fetch` keeps a file that is there, except salmobase's, which
  change under the same address (the unified peaks: v3, v5, v6): it asks the server for each one's size and date,
  compares them with what it noted when it fetched the file (`.fetched.json` in the data folder), and downloads the
  file again when they differ, saying so. Files of other hosts are named by their release and are fetched once.
- **An unchanged layer is copied, not computed.** The build takes the release before (the newest of the species in
  `release/`; `PREVIOUS=<folder>` names another) and copies from it every layer whose settings and input checksums
  are the same, byte for byte (`snpdata build --reuse`). Only from a release built by the same code: the manifest
  records checksums of the build's source (`code`), and after a change to it every layer is computed again, so a
  layer never keeps what an older reader made of its input. `FRESH=1` computes everything whatever is there.
- **The same input gives the same bytes.** Layers are written in a full row order (`ORDER BY ALL`), so a layer that
  is computed again from the same input has the same checksum: `snpscore diff` lists only what changed, and an
  install that updates downloads only that (`transcripts` and `transcripts_ncbi` differed between the builds of
  2026-11-24 and 2026-11-25 for the order of rows that share a start; rewritten in a full order the two are equal).
- **The log says where the time goes**: each step's line ends with its seconds (`chromatin: 328894 rows (12 s)`).
- `orion_publish.sh` writes the salmon release into `latest.json` wherever it stands among the versions given, and
  leaves the file alone when only a trout release is published.

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
salmon job 18 minutes and 6.1 GB, the trout job 15 minutes and 11 GB with every input fetched (below); with the
inputs there, 7 and 11 minutes. With the layers of the release before copied, what is left is the checksums of the
inputs, the tables that are always made again (rs IDs, flank keys, position conversion) and the pool (half a
minute): the next log's seconds will say how long.

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
0. The next build: "Left for the next build" above. The NREC demo runs releases 2026-11-25 and trout-2026-11-25
   since 2026-11-25 (G: "Ok to merge and deploy"; docs/TRACKER.md "Where things stand" has what was checked live).
1. The older releases on the VM (2026-11-05, trout-2026-11-13, and 2026-11-20 a day after the deploy) go at the
   next deploy: species.sh now removes a release the code no longer names once nothing kept on the server was made
   with it (G, 2026-11-25), before it fetches, so the room counts (4.9 GB were free, under the 5 GB a fetch asks for).
2. Done on 2026-11-25, after G's answers to the two questions of that day's builds ("Yes if it's changed you can
   fetch again. Yes reuse where you can to save time between releases"): `fetch` downloads a changed salmobase file
   again, the build copies unchanged layers from the release before, and layers are written in a full row order
   ("How a build runs"). The first build after it computes everything once more (the releases of 2026-11-25 carry
   no record of the code that built them), and its `transcripts` layers get their new order.
3. Before anyone uses `salmo-snp download latest` or `snpdata publish --raw` for both species: the first two
   faults below.

**The next builds**, as this one:
- The environment, once: `sbatch prep/orion_env.sbatch` from `snpdata/`. It makes
  `/mnt/project/ELIXIR/salmo-snp/env` with `/cluster/software/Miniconda3/25.7.0-2/bin/conda create` (conda-forge's
  Python 3.12), then runs `pip install -e "snpscore[test]" -e snpdata -e snpportal` and `bash tools/check.sh` in the
  clone; a second run installs and checks again.
- One job per species, from `snpdata/` (32 cores, 96 GB, no time limit; the log goes to
  `/mnt/project/ELIXIR/salmo-snp/logs/`). The date is the day of the build, and a name that was published is never
  built again: `sbatch --job-name=salmon-<date> prep/orion_build.sbatch salmon <date>` and
  `sbatch --job-name=trout-<date> prep/orion_build.sbatch trout <date>`. The release before is the newest of
  the species in `release/`; a third argument names another (a folder in `release/`, or in
  `/mnt/project/ELIXIR/salmo-snp/previous/` with its manifest.json, which gives the diff alone).
- Then publishing: `MODE=dry bash prep/orion_publish.sh <salmon version> <trout version>`, and `MODE=run` with G's
  go-ahead (Hosting on salmobase). Pull main first: the scripts changed on 2026-11-25.
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

## Faster and simpler builds, tests and deploys (2026-11-25)

G, 2026-11-25: "Look for ways for in the next releases to speed up and simply the building, testing and deploying.
From now, the builds will run on orion in a separate orion ssh chat, using a build plan it pulls from the repo and
serve the data by syncing it to salmobase. For now we deploy to NREC, but soon we'll move the app to the salmobase
server. There we can use the same data that's deployed on salmobase."

**Where the time went**, measured that day:

| Step | Time | What it was |
|---|---|---|
| A build on Orion (32 cores) | 7 minutes (salmon), 11 (trout); 18 and 15 with every input fetched | The motif layer and the large tables; the pool is half a minute, the upload 22 seconds |
| The tests (`tools/check.sh`) | 8 minutes in a cloud session (4 cores), 4 on GitHub's runner | Four suites one after the other on one core; the page tests alone 62% of it |
| A deploy to NREC | 4.5 minutes of tests, then 4 on the VM | The tests run a second time; the VM fetched each new release whole and its genome again (1:45 a release); a change to update.sh needed a second deploy |
| An install's update to a new release | 436 MB (salmon), 903 MB (trout) | Every file again, though 91% and 95% of the bytes were the files of the release before |
| The work around a build | Hours, in two chats | Reading this file, moving an input aside, checking counts by eye, a hand-off pasted between the chats, the same checks made again in the cloud session |

**Done in one pull request** (each tried as said):

- The build: a changed salmobase input is fetched again, unchanged layers are copied from the release before, layers
  are written in a full row order, the log times each step, `latest.json` no longer depends on the order of the
  arguments ("How a build runs"). The whole script was run twice on the test data: the second build copied all 21
  layers and `snpscore diff` reported no change.
- The tests: `tools/check.sh` runs the four suites side by side and the page tests on every core: 2 minutes 15 in
  a cloud session instead of 8, and 1 minute 46 on GitHub's runner instead of about 4. For that the motif layer scores a single batch of SNPs in its own process (as a
  test's small release has), and the page tests' worker processes are spawned, not forked.
- An update downloads only what changed: `salmo-snp download` copies a file that another installed release holds
  with the same sha256 instead of fetching it. From 2026-11-24 to 2026-11-25: 5 files fetched and 32 copied, 49
  seconds in a cloud session where the whole download took minutes, every file checked as before.
- The NREC deploy: update.sh runs the steps of the commit it has just checked out, so a change to them takes effect
  in the deploy that brings it (no second deploy); species.sh copies unchanged files from a release the VM holds and
  keeps a genome that has the manifest's checksum. Tried on a mock of the VM that held 2026-11-24: 8 requests to
  salmobase (the checksums, 5 changed files, the pool) instead of 43, and no genome.

**Then** (G, 2026-11-25: "we should prepare to setup the deployment option to salmobase server. Then we can work on
feature development in this chat, and then hand off building and deploying releases to salmobase in the orion ssh
chat"), in the same pull request:

1. **The app on salmobase reads the published data in place**: built, and tried on a mock of the server's folders;
   [SALMOBASE.md](SALMOBASE.md) is the brief for installing it there. One read-only mount of the server's datafiles
   folder and one setting naming it (`SNPSCORE_SALMOBASE`); an address under `https://salmobase.org/datafiles/` is
   then read from the disk when the file is there, as `SNPDATA_SALMOBASE` already does for fetch.

   | What the app needs | On NREC today | On salmobase |
   |---|---|---|
   | Releases | Fetched by species.sh at a deploy | Read where they are published: `datasets/salmo-snp/releases/` |
   | Genomes | A copy on the VM | Read where they are (`genomes/`: the manifest's address names the file) |
   | AQUA-FAANG tracks of the Locus browser | Read from salmobase.org, about 600 small requests a view | Read from the disk |
   | Public pools | The published one; built on GitHub's runner and sent when the weights change | The published one; built again on Orion and published again when the weights change (the server builds none) |
   | ChromBPNet model files | Fetched once from salmobase.org | Read where they are |
   | Results, the secret key | /srv/snpportal | The app's own data folder |

   No species.sh, no pool job in a deploy workflow, no genome copy, and no request from the server to its own
   public name. Still to find out on the server: Docker or Python, memory, who edits Apache (SALMOBASE.md's survey).
2. **One scripted test**: built. `tools/smoke.sh <address>` asks a running portal's health page and scores every
   example of each species through the job queue; `prep/release_test.sh` (step 3 above) runs it on freshly built
   releases before they are published, and the NREC deploy workflow ends with it. It replaces the checks made by
   hand in the Orion chat and again in the cloud session (most of an hour on 2026-11-25). Tried on releases
   2026-11-25 and trout-2026-11-25: eight examples scored in two and a half minutes.

**Proposed, not built** (DECISIONS #67, #68):

3. **The publisher says which release is current.** Today the code names it (serve.py `RELEASE`, `RELEASES`), so
   every release needs a pull request, the tests and a deploy before the live app shows it. Instead the live app
   would take what `releases/latest.json` names (one version per species, written by the publish script once the
   server's copy is checked) and refuse a release in a format newer than it reads: a release is then live when it
   is published. An install keeps the release its version names, so the same version gives the same data, and
   `salmo-snp download latest` fetches the newest.
4. **The build chat's hand-back.** With 3 nothing in the code has to follow a build. Until then it is the five
   lines of step 5 at the top of this file; or the build chat changes serve.py and this file's record and opens the
   pull request itself, which needs a GitHub token for this repository on Orion (port 22 is blocked there; HTTPS
   works).
5. Smaller: the deploy workflow runs the tests a second time on a commit that main's own run has already tested
   (4.5 minutes a deploy; skipping them needs a wait for that run when the deploy follows a merge at once, so it
   gains little); `raw/` per species before `publish --raw` is used for both.

## Text to start the chat on Orion

```
We are on Orion over SSH. Clone https://github.com/garethgillard/salmo-snp.git into ~/git/ if it is not there (else
pull main), and read AGENTS.md, then docs/ORION.md: its first section, "The next build: the plan and the steps",
says what the next Atlantic salmon and rainbow trout data releases contain and the steps of a build; the rest is
the record of the builds before. docs/SALMOBASE.md is the brief for installing and updating the portal on the
salmobase server, which this chat does too.
Tell me before any job is submitted, before anything is published and before anything is installed or changed on a
server; never set a SLURM time limit.
```
