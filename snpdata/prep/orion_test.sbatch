#!/bin/bash
# The test of built releases as a SLURM job on Orion (docs/ORION.md, step 3): prep/release_test.sh with the Python
# environment used there. Submit from snpdata/ in the clone, after both builds have finished:
#   sbatch --job-name=test-<date> prep/orion_test.sbatch atlantic_salmon-Ssal_v3.1-<date> rainbow_trout-USDA_OmykA_1.1-<date>
# No time limit, on purpose (G's rule for Orion: the partition has none).
#SBATCH --partition=orion
#SBATCH --account=biovit_elixir
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --output=/mnt/project/ELIXIR/salmo-snp/logs/%x-%j.out
set -euo pipefail
PROJECT=/mnt/project/ELIXIR/salmo-snp
export PATH=$PROJECT/env/bin:$PATH
export TMPDIR=/mnt/ScratchProjects/ELIXIR/salmo-snp/tmp
mkdir -p "$TMPDIR"
cd "${SLURM_SUBMIT_DIR:-.}"
bash prep/release_test.sh "$@"
