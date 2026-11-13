#!/usr/bin/env bash
# The other species' releases on the NREC demo (serve.py RELEASES: rainbow trout). update.sh runs this after a deploy:
# a release that is not in /srv/snpportal/releases/<version>/ yet is fetched from this repository's GitHub data release
# data-<version> (prep/github_release.sh: the release, its genome and its public pool, built where the release was,
# as the VM's 2 GB RAM can't), every file checked against SHA256SUMS and the genome against the manifest. Nothing here
# stops a deploy: a release that can't be fetched is reported and the portal keeps the species it has.
set -uo pipefail
ROOT=/srv/snpportal
REPO=garethgillard/salmo-snp
for v in $(sed -n 's/^RELEASES = {\(.*\)}.*/\1/p' "$ROOT/salmo-snp/snpportal/snpportal/serve.py" | grep -o ': "[^"]*"' | tr -d ':" '); do
  [ -f "$ROOT/releases/$v/manifest.json" ] && continue
  free=$(df -Pk "$ROOT" | awk 'NR == 2 { print $4 }')
  [ "$free" -gt 5000000 ] || { echo "release $v not fetched: under 5 GB free on the VM" >&2; continue; }
  T=$(mktemp -d "$ROOT/.fetch-XXXXXX")
  (
    set -e
    names=$(curl -fsSL "https://api.github.com/repos/$REPO/releases/tags/data-$v" |
            python3 -c "import json, sys; print(*[a['name'] for a in json.load(sys.stdin)['assets']])")
    for n in $names; do
      curl -fsSL --retry 3 -o "$T/$n" "https://github.com/$REPO/releases/download/data-$v/$n"
      tar -xf "$T/$n" -C "$T" && rm "$T/$n"
    done
    "$ROOT/venv/bin/python" - "$T/site" "$v" <<'PY'
import hashlib, json, sys
from pathlib import Path
from snpscore.release import verify
site, version = Path(sys.argv[1]), sys.argv[2]
release = site / "releases" / version
problems = verify(release)
genome = json.loads((release / "manifest.json").read_text())["genome"]
for ext, want in (genome.get("sha256") or {}).items():
    path = site / "raw" / (genome["file"] + ("" if ext == "fa.gz" else ext))
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    if h.hexdigest() != want:
        problems.append(f"{path.name} differs from the manifest's sha256")
sys.exit("\n".join(problems) if problems else 0)
PY
    mkdir -p "$ROOT/releases" "$ROOT/genome"
    mv "$T"/site/raw/*.fa.gz* "$ROOT/genome/"
    [ -d "$T/pool" ] && mv "$T/pool" "$T/site/releases/$v/pool"
    chmod -R a+rX "$T/site/releases/$v"
    mv "$T/site/releases/$v" "$ROOT/releases/$v"
  ) && echo "release $v fetched" || echo "release $v could not be fetched (is data-$v published?)" >&2
  rm -rf "$T"
done
exit 0
