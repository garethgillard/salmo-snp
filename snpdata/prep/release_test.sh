#!/usr/bin/env bash
# One test of built releases before they are published (docs/ORION.md, step 3): the portal as a user runs it
# (salmo-snp serve) on these releases alone, and tools/smoke.sh against it: the health page, then every example of
# each species scored through the job queue and its result opened. Fails on the first thing that does not work.
# Run in snpdata/, in a job rather than on a login node (prep/orion_test.sbatch); it needs snpportal installed.
#   bash prep/release_test.sh atlantic_salmon-Ssal_v3.1-2026-11-26 rainbow_trout-USDA_OmykA_1.1-2026-11-26   (salmon first)
# OUT=<dir>: where the releases are (default release). PORT=<n>: the port to try them on (default 8765).
set -euo pipefail
[ $# -gt 0 ] || { echo "usage: bash prep/release_test.sh <version> [version ...]" >&2; exit 1; }
home=$(mktemp -d)
trap 'kill $(jobs -p) 2> /dev/null || true; rm -rf "$home"' EXIT
mkdir -p "$home/releases" "$home/genome"
for v in "$@"; do
  r=$(cd "${OUT:-release}/$v" && pwd -P)
  snpscore verify "$r"
  ln -s "$r" "$home/releases/$v"
  # the genome the build read, so that the sequence checks are tried too (else they read salmobase)
  g=$(python -c 'import json, sys; print(json.load(open(sys.argv[1]))["genome"].get("path") or "")' "$r/manifest.json")
  for ext in "" .fai .gzi; do [ ! -f "$g$ext" ] || ln -sf "$g$ext" "$home/genome/"; done
done
port=${PORT:-8765}
SALMO_SNP_HOME=$home salmo-snp serve --release "$home/releases/$1" --port "$port" > "$home/serve.log" 2>&1 &
for _ in $(seq 180); do curl -fs -o /dev/null "http://127.0.0.1:$port/snp/health/" && break; sleep 1; done
bash "$(dirname "$0")/../../tools/smoke.sh" "http://127.0.0.1:$port" || { tail -n 30 "$home/serve.log"; exit 1; }
echo "release test: ok ($*)"
