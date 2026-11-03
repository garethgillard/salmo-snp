#!/usr/bin/env bash
# The new user's path, as the README gives it, on the test fixture: install the built wheels (not the source folders)
# into a fresh venv with the newest dependencies they allow, publish the fixture release as the data folder, then
# salmo-snp download (release and genome), snpscore annotate, salmo-snp serve and salmo-snp info.
#   bash tools/user_install_test.sh [python]      (default python3; CI runs it on the newest Python)
# It caught DuckDB 2.0 and a hand-edited manifest; it needs no network beyond PyPI.
set -euo pipefail
PY=${1:-python3}
REPO=$(cd "$(dirname "$0")/.." && pwd)
T=$(mktemp -d)
trap 'kill $(jobs -p) 2>/dev/null || true; rm -rf "$T"' EXIT
"$PY" -m venv "$T/env"
E="$T/env/bin"
"$E/pip" install -q --upgrade pip build
for d in snpscore snpdata snpportal; do "$E/python" -m build -q --wheel --outdir "$T/dist" "$REPO/$d" >/dev/null; done
"$E/pip" install -q "$T"/dist/*.whl
"$E/python" -c "import sys, duckdb, django; print('python', sys.version.split()[0], '| duckdb', duckdb.__version__, '| django', django.get_version())"

cd "$T"  # the published data folder, made from the fixture as snpdata publish makes the real one
F="$REPO/snpdata/tests/fixture"
"$E/python" -c "from snpdata import build, publish; publish(build('$REPO/snpdata/layers.yaml', '$F', 'build/2026-01-01'), 'site', '$REPO/snpdata/layers.yaml', '$F')" > /dev/null

export SALMO_SNP_HOME="$T/home"
"$E/salmo-snp" download latest --from "$T/site"
"$E/snpscore" annotate "$F/snps.vcf" --release "$T/home/releases/2026-01-01" -o "$T/out.tsv"
"$E/salmo-snp" serve --release "$T/home/releases/2026-01-01" --port 8765 > "$T/serve.log" 2>&1 &
for _ in $(seq 60); do curl -fs -o /dev/null http://127.0.0.1:8765/snp/ && break; sleep 1; done
for page in /snp/ /snp/known-loci/ "/snp/locus/?r=25:28980000-29020000&open=genes" /snp/help/ /static/snpportal/portal.css; do
  code=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:8765$page")
  echo "$code $page"
  [ "$code" = 200 ] || { cat "$T/serve.log"; exit 1; }
done
curl -fs -o "$T/score.html" http://127.0.0.1:8765/snp/  # (not piped into grep -q: with pipefail that races)
grep -q "Running on this computer" "$T/score.html" || { echo "the Score page doesn't say it is local"; exit 1; }
# score a pasted list through the portal's job queue, as a user would
curl -fs -c "$T/cookies" -o /dev/null http://127.0.0.1:8765/snp/
token=$(awk '/csrftoken/ {print $7}' "$T/cookies")
curl -fs -b "$T/cookies" -H "Referer: http://127.0.0.1:8765/snp/" -o /dev/null \
  --data-urlencode "csrfmiddlewaretoken=$token" --data-urlencode $'paste=25 28996360 C T\n9 23837450' http://127.0.0.1:8765/snp/
for _ in $(seq 60); do
  state=$(cat "$T"/home/results/*/job.json 2>/dev/null | "$E/python" -c "import json, sys; print(json.load(sys.stdin)['state'])" 2>/dev/null || true)
  [ "$state" = done ] || [ "$state" = failed ] && break
  sleep 1
done
echo "portal job: $state"
[ "$state" = done ] || { cat "$T/serve.log"; exit 1; }
"$E/salmo-snp" info
echo "user install: ok"
