#!/usr/bin/env bash
# One release from start to finish, the same way on any machine (a SLURM job on Orion, a Mac): the inputs that are
# missing, the example inputs, the build, the public pool, a check of every file, and a summary to compare with
# docs/ORION.md. Run in snpdata/; it stops at the first step that fails, and a second run goes on from the inputs
# that are there. Nothing is published: that is `snpdata publish <release> --to <the site folder>`.
#   bash prep/build_release.sh salmon 2026-11-25
#   bash prep/build_release.sh trout trout-2026-11-25
# Environment (all optional):
#   MEMORY=32GB THREADS=16   DuckDB's limits (defaults: 16GB, and the cores this job may use)
#   SPILL=<folder>           where DuckDB may spill to (default: <release folder>/../.spill-<version>, removed after)
#   SNPDATA_SALMOBASE=<dir>  a copy of salmobase's datafiles folder: fetch reads salmobase's files from it
#   PREVIOUS=<release>       an earlier release folder: `snpscore diff` lists what changed since
#   SKIP_FETCH=1             use the inputs as they are (no network)
#   DATA=<dir> OUT=<dir>     the inputs and where releases go (defaults: data/raw or data/rainbow_trout/raw, release).
#                            With another DATA the salmon examples (prep/make_demo.sh) are left as they are.
set -euo pipefail
species=${1:?salmon or trout}
version=${2:?the release name: <date> for salmon, trout-<date> for rainbow trout}
case $species in
  salmon) layers=layers.yaml; default=data/raw ;;
  trout) layers=rainbow_trout/layers.yaml; default=data/rainbow_trout/raw ;;
  *) echo "the species is salmon or trout" >&2; exit 1 ;;
esac
case "$species:$version" in
  salmon:[0-9]*|trout:trout-[0-9]*) ;;
  *) echo "a salmon release is named <date>, a rainbow trout one trout-<date>" >&2; exit 1 ;;
esac
data=${DATA:-$default}
out=${OUT:-release}/$version
[ ! -e "$out" ] || { echo "$out exists: a release never changes, so choose another name (or remove a failed build)" >&2; exit 1; }
threads=${THREADS:-$(python -c 'import os; print(len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else os.cpu_count())')}
memory=${MEMORY:-16GB}
spill=${SPILL:-$(dirname "$out")/.spill-$version}
step() { echo "== $(date '+%F %T') $*"; }

if [ -z "${SKIP_FETCH:-}" ]; then
  step "inputs -> $data"
  snpdata fetch --layers "$layers" --data "$data"
fi
if [ "$species" = salmon ] && [ "$data" = "$default" ]; then
  step "example inputs (public 50k, SYNTHETIC chip and GWAS)"
  bash prep/make_demo.sh
fi
step "build -> $out ($threads threads, $memory)"
snpdata build --layers "$layers" --data "$data" --out "$out" --memory "$memory" --threads "$threads" --temp "$spill"
rm -rf "$spill"
step "public pool"
snpscore pool --release "$out" --memory "$memory" --threads "$threads"
step "every file against the manifest"
snpscore verify "$out"
if [ -n "${PREVIOUS:-}" ]; then
  step "changes since $PREVIOUS"
  snpscore diff "$PREVIOUS" "$out"
fi
step "summary (compare with docs/ORION.md)"
python - "$out" <<'PY'
import json, sys
from pathlib import Path
release = Path(sys.argv[1])
m = json.loads((release / "manifest.json").read_text())
print(f"release {m['version']}  {m['species']['name']}  {m['assembly']}  snpscore {m['snpscore_version']}  duckdb {m['duckdb_version']}")
for layer in m["layers"]:
    print(f"  {layer['name']:<18}{layer['rows']:>12,}  {layer['type']}")
for key in ("alias", "rsid", "flank_keys", "synteny", "bgee"):
    if key in m:
        print(f"  {key:<18}{m[key]['rows']:>12,}")
for name, entry in (m.get("liftover") or {}).items():
    print(f"  liftover_{name:<9}{entry['blocks']:>12,}  blocks")
print(f"  catalogue rows: {(m.get('catalog') or {}).get('rows')}")
print("  examples: " + ", ".join(d["file"].removeprefix("demo/") for d in m.get("demo", [])))
pool = release / "pool" / "background.json"
if pool.exists():
    b = json.loads(pool.read_text())
    tiers = (b.get("tiers") or {}).get("all") or {}
    print(f"  pool: {b.get('n_sites'):,} sites; tiers " + ", ".join(f"{t} {100 * v['share']:.2f}%" for t, v in sorted(tiers.items())))
PY
step "done: $out. To publish: snpdata publish $out --to <salmobase's datafiles>/datasets/salmo-snp"
