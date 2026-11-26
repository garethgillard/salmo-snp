#!/bin/bash
# One release as a SLURM job on NMBU's Orion (docs/ORION.md): prep/build_release.sh with the paths, the Python
# environment (prep/orion_env.sbatch) and the limits used there. First run 2026-11-25: 18 minutes (salmon), 15 (trout).
#   sbatch --job-name=salmon-<date> prep/orion_build.sbatch salmon <date>    -> atlantic_salmon-Ssal_v3.1-<date>
#   sbatch --job-name=trout-<date> prep/orion_build.sbatch trout <date>      -> rainbow_trout-USDA_OmykA_1.1-<date>
# The release before is the newest of the species in release/ (the project folder's): the layers that did not change
# are copied from it, and `snpscore diff` lists what did. A third argument names another one: a release in release/,
# else a folder in /mnt/project/ELIXIR/salmo-snp/previous/ with its manifest (the diff alone).
# Submit from snpdata/ in the clone (~/git/salmo-snp), where `data` and `release` are links into the project folder.
# No time limit, on purpose (G's rule for Orion: the partition has none).
#SBATCH --partition=orion
#SBATCH --account=biovit_elixir
#SBATCH --cpus-per-task=32
#SBATCH --mem=96G
#SBATCH --output=/mnt/project/ELIXIR/salmo-snp/logs/%x-%j.out
set -euo pipefail
PROJECT=/mnt/project/ELIXIR/salmo-snp
SCRATCH=/mnt/ScratchProjects/ELIXIR/salmo-snp
export PATH=$PROJECT/env/bin:$PATH        # the Python 3.12 environment with snpscore and snpdata installed
export TMPDIR=$SCRATCH/tmp
mkdir -p "$TMPDIR"
cd "${SLURM_SUBMIT_DIR:-.}"
previous=
if [ -n "${3:-}" ]; then
  previous=$PROJECT/release/$3
  [ -f "$previous/manifest.json" ] || previous=$PROJECT/previous/$3
fi
MEMORY=64GB SPILL=$SCRATCH/spill-$2 PREVIOUS=$previous bash prep/build_release.sh "$1" "$2"
