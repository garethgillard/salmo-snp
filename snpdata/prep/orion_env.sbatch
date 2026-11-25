#!/bin/bash
# The Python 3.12 environment of the Orion builds (docs/ORION.md), made in a small SLURM job, not on a login node:
# conda-forge's Python in /mnt/project/ELIXIR/salmo-snp/env (with Orion's conda 25.7.0-2: the older mamba is too old),
# the three folders installed editable from this clone as CI does, then tools/check.sh.
#   sbatch prep/orion_env.sbatch        # from snpdata/ in the clone (~/git/salmo-snp), as prep/orion_build.sbatch
# A second run keeps the environment, installs and checks again; remove the folder to make it from scratch.
# No time limit, on purpose (G's rule for Orion).
#SBATCH --job-name=salmo-snp-env
#SBATCH --partition=orion
#SBATCH --account=biovit_elixir
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --output=/mnt/project/ELIXIR/salmo-snp/logs/%x-%j.out
set -euo pipefail
ENV=/mnt/project/ELIXIR/salmo-snp/env
cd "${SLURM_SUBMIT_DIR:-.}/.."
[ -f tools/check.sh ] || { echo "submit from snpdata/ in the clone" >&2; exit 1; }
[ -x "$ENV/bin/python" ] || /cluster/software/Miniconda3/25.7.0-2/bin/conda create -y -p "$ENV" \
  --override-channels -c conda-forge python=3.12 pip   # conda-forge only, as environment.yml
export PATH=$ENV/bin:$PATH
python -m pip install -e "snpscore[test]" -e snpdata -e snpportal
# the cores a job may use: build_release.sh's default threads and the motif layer's workers
cores=$(python -c 'import os; print(len(os.sched_getaffinity(0)))')
echo "$(python --version) on $(hostname): $cores cores (SLURM_CPUS_PER_TASK=${SLURM_CPUS_PER_TASK:-unset})"
bash tools/check.sh
