#!/usr/bin/env bash
# A release that was built on GitHub's runner (the species-data workflow) exists only on the NREC demo: this copies
# it, its pool and its genome from the VM to this Mac and puts it on GitHub as the data release data-<version>
# (prep/github_release.sh), for local installs and the deploy workflow's pools. Run it from anywhere in a clone:
#   bash snpdata/prep/release_from_demo.sh [version] [ssh host]     defaults: serve.py's rainbow trout release, nrec
# Needs this Mac's SSH access to the VM (as deploy/nrec.sh), gh signed in, and snpdata and snpscore installed.
set -euo pipefail
cd "$(dirname "$0")/.."  # snpdata/
VERSION=${1:-$(sed -n 's/^RELEASES = {.*"rainbow_trout": "\([^"]*\)".*/\1/p' ../snpportal/snpportal/serve.py)}
HOST=${2:-nrec}
for tool in snpdata snpscore gh rsync; do
  command -v "$tool" > /dev/null || { echo "$tool is not on the PATH (conda activate salmo-snp?)" >&2; exit 1; }
done
mkdir -p release "data/from_demo/$VERSION"
rsync -az --delete "$HOST:/srv/snpportal/releases/$VERSION/" "release/$VERSION/"
genome=$(python3 -c "import json, sys; print(json.load(open(sys.argv[1]))['genome']['file'])" "release/$VERSION/manifest.json")
rsync -az "$HOST:/srv/snpportal/genome/$genome" "$HOST:/srv/snpportal/genome/$genome.fai" \
  "$HOST:/srv/snpportal/genome/$genome.gzi" "data/from_demo/$VERSION/"
snpscore verify "release/$VERSION"
GENOME="data/from_demo/$VERSION/$genome" POOL=1 bash prep/github_release.sh "release/$VERSION"
echo "done: https://github.com/garethgillard/salmo-snp/releases/tag/data-$VERSION"
