#!/bin/bash
# One release as a SLURM job on NMBU's Orion (docs/ORION.md): prep/build_release.sh with the paths, the Python
# environment and the limits used there. Written on 2026-11-24 from a cloud session and not yet run: fix it on first use.
#   sbatch --job-name=salmon-<date> prep/orion_build.sbatch salmon <date> 2026-11-20
#   sbatch --job-name=trout-<date> prep/orion_build.sbatch trout trout-<date> trout-2026-11-13
# The third argument names the release before, whose manifest is in /mnt/project/ELIXIR/salmo-snp/previous/<name>/.
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
MEMORY=64GB SPILL=$SCRATCH/spill-$2 PREVIOUS=$PROJECT/previous/$3 bash prep/build_release.sh "$1" "$2"
