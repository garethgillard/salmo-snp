#!/bin/bash
# One release as a SLURM job on NMBU's Orion (docs/ORION.md): prep/build_release.sh with the paths, the Python
# environment (prep/orion_env.sbatch) and the limits used there. First run 2026-11-25: 18 minutes (salmon), 15 (trout).
#   sbatch --job-name=salmon-<date> prep/orion_build.sbatch salmon <date> 2026-11-25
#   sbatch --job-name=trout-<date> prep/orion_build.sbatch trout trout-<date> trout-2026-11-25
# The third argument names the release before, for `snpscore diff`: a release in release/ (the project folder's), else
# a folder in /mnt/project/ELIXIR/salmo-snp/previous/ with its manifest.
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
previous=$PROJECT/release/$3
[ -f "$previous/manifest.json" ] || previous=$PROJECT/previous/$3
MEMORY=64GB SPILL=$SCRATCH/spill-$2 PREVIOUS=$previous bash prep/build_release.sh "$1" "$2"
