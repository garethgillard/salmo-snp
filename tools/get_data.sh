#!/usr/bin/env bash
# The data for real use (the tests don't need it): `salmo-snp download` from salmobase (snpportal/snpportal/serve.py
# DATA_URL), the release this code names (serve.py RELEASE) and its genome, every file checked and copied into the
# salmo-snp data folder, which then builds the release's public pool. About 1.3 GB; then `salmo-snp serve`.
#   bash tools/get_data.sh [VERSION] [--no-genome] [--species all]     VERSION: another release, e.g. trout-2026-11-24
set -euo pipefail
REPO=$(cd "$(dirname "$0")/.." && pwd)
SALMO=$([ -x "$REPO/.venv/bin/salmo-snp" ] && echo "$REPO/.venv/bin/salmo-snp" || echo salmo-snp)
"$SALMO" download "$@"
