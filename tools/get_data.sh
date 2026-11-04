#!/usr/bin/env bash
# The data for real use (the tests don't need it), while it is hosted on this repository's GitHub Releases: downloads
# data-<RELEASE> (snpportal/snpportal/serve.py RELEASE) with gh's REST API, unpacks it and runs `salmo-snp download --from` on it,
# which checks every file and copies it into the salmo-snp data folder. About 1 GB; then `salmo-snp serve`.
#   bash tools/get_data.sh [--no-genome]
set -euo pipefail
REPO=$(cd "$(dirname "$0")/.." && pwd)
VERSION=$(sed -n 's/^RELEASE = "\([^"]*\)".*/\1/p' "$REPO/snpportal/snpportal/serve.py")
SALMO=$([ -x "$REPO/.venv/bin/salmo-snp" ] && echo "$REPO/.venv/bin/salmo-snp" || echo salmo-snp)
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
# REST, not `gh release download` (GraphQL), which cloud sessions' proxy refuses
gh api "repos/garethgillard/salmo-snp/releases/tags/data-$VERSION" --jq '.assets[] | "\(.id) \(.name)"' |
  while read -r id name; do
    gh api -H "Accept: application/octet-stream" "repos/garethgillard/salmo-snp/releases/assets/$id" > "$T/$name"
  done
for f in "$T"/*.tar; do tar -xf "$f" -C "$T"; done
"$SALMO" download "$VERSION" --from "$T/site" "$@"
