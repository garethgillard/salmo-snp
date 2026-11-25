#!/usr/bin/env bash
# One test of a running portal through its pages alone: the health page, then, for each species the portal offers,
# every example of the Score page scored through the job queue and its result opened. For a deploy (the NREC demo, the
# salmobase server: docs/SALMOBASE.md) and for a release before it is published (a portal started on it). It makes
# results as a visitor does and deletes them; it sends no SNPs of its own. Needs curl and python3.
#   bash tools/smoke.sh https://158-39-75-9.sslip.io
#   bash tools/smoke.sh http://127.0.0.1:8090 salmobase.org    # behind a proxy: the name the site answers to
#   EXAMPLES=known_loci bash tools/smoke.sh <address>          # only these examples (default: all the page offers)
set -euo pipefail
base=${1:?the address of the portal, without /snp/}
host=${2:-}
site=${host:+https://$host}  # what the site calls itself: forms are checked against it
site=${site:-$base}
jar=$(mktemp)
page=$(mktemp)
trap 'rm -f "$jar" "$page"' EXIT
web() { curl -sS --max-time 180 ${host:+-H "Host: $host" -H "X-Forwarded-Proto: https"} -b "$jar" -c "$jar" "$@"; }
post() {  # <path> <field=value ...>: a form, with the page's CSRF token
  local path=$1 args=() field
  shift
  for field in "$@"; do args+=(--data-urlencode "$field"); done
  web -o /dev/null -w '%{redirect_url}' -H "Referer: $site/snp/" \
    --data-urlencode "csrfmiddlewaretoken=$(awk '/csrftoken/ {print $7}' "$jar")" "${args[@]}" "$base$path"
}

health=$(web -f "$base/snp/health/?tracks=1")
python3 - "$health" <<'PY'
import json, sys
h = json.loads(sys.argv[1])
print(f"health: {h['status']}; release {h['release']['version']} ({h['release']['assembly']}); species {h.get('species')}; "
      f"genome {h['genome']}; public pool {'fits' if h.get('pool_fits', h['pool']) else 'MISSING OR STALE'}; "
      f"tracks {h.get('tracks')}; predict {h.get('predict')}")
sys.exit(h["status"] != "ok")
PY
species=$(python3 -c 'import json, sys; print(" ".join(json.loads(sys.argv[1]).get("species") or ["-"]))' "$health")
failed=0
for s in $species; do
  web -f -o /dev/null "$base/snp/"  # the cookie with the CSRF token
  [ "$s" = - ] || post /snp/species/ "species=$s" > /dev/null
  web -f -o "$page" "$base/snp/"
  examples=${EXAMPLES:-$(grep -o 'name="example" value="[^"]*"' "$page" | sed 's/.*value="//; s/"//' | sort -u | tr '\n' ' ')}
  for example in $examples; do
    grep -q "name=\"example\" value=\"$example\"" "$page" || continue  # another species' example
    job=$(post /snp/ "example=$example")
    job=${job%%\?*}
    job=/snp/${job#*/snp/}
    case $job in /snp/results/*/) ;; *) echo "$s $example: FAILED to start"; failed=1; continue ;; esac
    start=$(date +%s)
    until web -o /dev/null -D - "$base${job}status/" | grep -qi '^hx-refresh: true'; do
      [ $(( $(date +%s) - start )) -lt "${WAIT:-900}" ] || break
      sleep 2
    done
    web -o "$page.job" "$base$job"
    if grep -q 'id="results"' "$page.job"; then
      echo "$s $example: scored in $(( $(date +%s) - start )) s"
    else
      echo "$s $example: FAILED: $(grep -o 'could not be scored[^<]*<[^>]*>[^<]*' "$page.job" | sed 's/<[^>]*>//g' | head -1)"
      failed=1
    fi
    post "${job}delete/" > /dev/null || true
    rm -f "$page.job"
  done
done
[ "$failed" = 0 ] && echo "smoke: ok" || { echo "smoke: FAILED"; exit 1; }
