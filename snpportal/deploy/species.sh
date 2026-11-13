#!/usr/bin/env bash
# The other species' releases on the NREC demo (serve.py RELEASES: rainbow trout). Two ways in, both checked the same
# way (every file against SHA256SUMS, the genome against the manifest) before anything is put in place:
#   species.sh                   update.sh runs this after a deploy: a release that is not in
#                                /srv/snpportal/releases/<version>/ yet is fetched from this repository's GitHub data
#                                release data-<version> (prep/github_release.sh with POOL=1), if it is published.
#   species.sh stdin <version>   update.sh's `release <version>`: the same folders as a tar on stdin (site/releases/
#                                <version>/, site/raw/ with the genome, pool/), sent by the species-data workflow,
#                                which builds the release from the public sources on GitHub's runner. Replaces the
#                                release if the VM has it.
# The pool comes with the release, as the VM's 2 GB RAM can't build it. Nothing here stops a deploy: a release that
# can't be fetched is reported and the portal keeps the species it has.
set -uo pipefail
ROOT=/srv/snpportal
REPO=garethgillard/salmo-snp

install_site() {  # <folder holding site/ and maybe pool/> <version>: check, then move into place
  local T=$1 v=$2
  "$ROOT/venv/bin/python" - "$T/site" "$v" <<'PY' || return 1
import hashlib, json, sys
from pathlib import Path
from snpscore.release import verify
site, version = Path(sys.argv[1]), sys.argv[2]
release = site / "releases" / version
problems = verify(release)
if not problems and json.loads((release / "manifest.json").read_text()).get("version") != version:
    problems.append(f"the manifest's version is not {version}")
genome = json.loads((release / "manifest.json").read_text())["genome"] if not problems else {}
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
  mv "$T"/site/raw/*.fa.gz* "$ROOT/genome/" || return 1
  [ -d "$T/pool" ] && mv "$T/pool" "$T/site/releases/$v/pool"
  chmod -R a+rX "$T/site/releases/$v"
  rm -rf "$ROOT/releases/.old-$v"
  [ -d "$ROOT/releases/$v" ] && mv "$ROOT/releases/$v" "$ROOT/releases/.old-$v"
  mv "$T/site/releases/$v" "$ROOT/releases/$v" && rm -rf "$ROOT/releases/.old-$v"
}

named() {  # the versions serve.py RELEASES names besides the default
  sed -n 's/^RELEASES = {\(.*\)}.*/\1/p' "$ROOT/salmo-snp/snpportal/snpportal/serve.py" | grep -o ': "[^"]*"' | tr -d ':" '
}

if [ "${1:-}" = stdin ]; then
  v=${2:-}
  named | grep -qxF "$v" || { echo "release '$v' is not one this code names (serve.py RELEASES)" >&2; exit 1; }
  T=$(mktemp -d "$ROOT/.fetch-XXXXXX")
  trap 'rm -rf "$T"' EXIT
  tar -xf - -C "$T" --no-same-owner || { echo "release $v: the archive could not be read" >&2; exit 1; }
  install_site "$T" "$v" || { echo "release $v was not installed: it failed its checks" >&2; exit 1; }
  echo "release $v installed"
  exit 0
fi

for v in $(named); do
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
    install_site "$T" "$v"
  ) && echo "release $v fetched" || echo "release $v could not be fetched (is data-$v published?)" >&2
  rm -rf "$T"
done
exit 0
