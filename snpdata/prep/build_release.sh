#!/usr/bin/env bash
# One release from start to finish, the same way on any machine (a SLURM job on Orion, a Mac): the inputs that are
# missing, the example inputs, the build, the public pool, a check of every file, and a summary to compare with
# docs/ORION.md. Run in snpdata/; it stops at the first step that fails, and a second run goes on from the inputs
# that are there. Nothing is published: that is `snpdata publish <release> --to <the site folder>`.
#   bash prep/build_release.sh salmon 2026-11-26      -> release/atlantic_salmon-Ssal_v3.1-2026-11-26
#   bash prep/build_release.sh trout 2026-11-26       -> release/rainbow_trout-USDA_OmykA_1.1-2026-11-26
# A release is named <species>-<assembly>-<date> (G, 2026-11-26; `snpdata name`): give the day of the build (default
# today), or the whole name. The releases before that day keep their names (2026-11-25, trout-2026-11-25).
# Environment (all optional):
#   MEMORY=32GB THREADS=16   DuckDB's limits (defaults: 16GB, and the cores this job may use)
#   SPILL=<folder>           where DuckDB may spill to (default: <release folder>/../.spill-<version>, removed after)
#   SNPDATA_SALMOBASE=<dir>  a copy of salmobase's datafiles folder: fetch reads salmobase's files from it
#   PREVIOUS=<release>       the release before, as a folder (default: the species' newest release in OUT, by build date):
#                            a layer whose settings and inputs did not change is copied from it instead of computed
#                            again (`snpdata build --reuse`; G, 2026-11-25), and `snpscore diff` lists what changed
#                            since. A folder with the manifest alone gives the diff
#   FRESH=1                  compute every layer again, whatever PREVIOUS holds
#   SKIP_FETCH=1             use the inputs as they are (no network)
#   RAW=<dir> OUT=<dir>      the inputs and where releases go (defaults: data/raw or data/rainbow_trout/raw, release).
#                            With another RAW the salmon examples (prep/make_demo.sh) are left as they are. (Not
#                            DATA: Orion exports DATA=/data/$USER at every login.)
set -euo pipefail
species=${1:?salmon or trout}
case $species in
  salmon) layers=layers.yaml; default=data/raw ;;
  trout) layers=rainbow_trout/layers.yaml; default=data/rainbow_trout/raw ;;
  *) echo "the species is salmon or trout" >&2; exit 1 ;;
esac
prefix=$(snpdata name --layers "$layers")  # atlantic_salmon-Ssal_v3.1, rainbow_trout-USDA_OmykA_1.1
given=${2:-$(date +%F)}
case $given in
  "$prefix"-[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]) version=$given ;;
  [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]) version=$prefix-$given ;;
  *) echo "a $species release is named $prefix-<date>: give the day of the build, e.g. $(date +%F)" >&2; exit 1 ;;
esac
data=${RAW:-$default}
out=${OUT:-release}/$version
[ ! -e "$out" ] || { echo "$out exists: a release never changes, so choose another name (or remove a failed build)" >&2; exit 1; }
previous=${PREVIOUS:-}
if [ -z "$previous" ]; then  # the species' newest release already there, by its build date (the earlier names too)
  previous=$(python -c 'import json, sys
from pathlib import Path
found = [(m.get("created") or "", str(p.parent)) for p in Path(sys.argv[1]).glob("*/manifest.json")
         for m in [json.loads(p.read_text())] if (m.get("species") or {}).get("key", "atlantic_salmon") == sys.argv[2]]
print(max(found)[1] if found else "")' "${OUT:-release}" "${prefix%%-*}")
fi
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
reuse=()
if [ -n "$previous" ] && [ -z "${FRESH:-}" ]; then reuse=(--reuse "$previous"); fi
step "build -> $out ($threads threads, $memory${reuse[1]:+, unchanged layers from $previous})"
snpdata build --layers "$layers" --data "$data" --out "$out" --memory "$memory" --threads "$threads" --temp "$spill" \
  ${reuse[@]+"${reuse[@]}"}
rm -rf "$spill"
step "public pool"
snpscore pool --release "$out" --memory "$memory" --threads "$threads"
step "every file against the manifest"
snpscore verify "$out"
if [ -n "$previous" ]; then
  step "changes since $previous"
  snpscore diff "$previous" "$out"
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
