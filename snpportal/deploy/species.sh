#!/usr/bin/env bash
# The releases this code names on the NREC demo (serve.py RELEASE, the default species', and RELEASES: rainbow trout).
# The default species' goes in /srv/snpportal/release (SNPSCORE_RELEASE), the one it replaces into releases/<version>
# (results made with it keep it); the others in releases/<version>. Two ways in, both checked the same
# way (every file against SHA256SUMS, the genome against the manifest) before anything is put in place:
#   species.sh                   update.sh runs this after a deploy: a release that is not in
#                                /srv/snpportal/releases/<version>/ yet is fetched from where the data is published
#                                (DATA_URL, salmobase: releases/<version>/, every file of its SHA256SUMS, and the pool
#                                beside it in releases/<version>/pool/), its genome from the manifest's address.
#   species.sh stdin <version>   update.sh's `release <version>`: the same folders as a tar on stdin (site/releases/
#                                <version>/, site/raw/ with the genome, pool/), sent by the species-data workflow,
#                                which builds the release from the public sources on GitHub's runner. Replaces the
#                                release if the VM has it.
# The pool comes with the release, as the VM's 2 GB RAM can't build it. Nothing here stops a deploy: a release that
# can't be fetched is reported and the portal keeps the species it has.
set -uo pipefail
ROOT=/srv/snpportal
DATA_URL=${SALMO_SNP_DATA_URL:-https://salmobase.org/datafiles/datasets/salmo-snp}  # as serve.py DATA_URL
SERVE=$ROOT/salmo-snp/snpportal/snpportal/serve.py

default_version() { sed -n 's/^RELEASE = "\([^"]*\)".*/\1/p' "$SERVE"; }
version_of() {  # the version in folder $1's manifest, or nothing
  [ -f "$1/manifest.json" ] && "$ROOT/venv/bin/python" -c 'import json, sys; print(json.load(open(sys.argv[1]))["version"])' "$1/manifest.json"
}

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
  if [ "$v" = "$(default_version)" ]; then  # the default species' new release replaces /srv/snpportal/release
    old=$(version_of "$ROOT/release")
    mkdir -p "$ROOT/releases"
    if [ -n "$old" ] && [ "$old" != "$v" ]; then
      rm -rf "$ROOT/releases/$old" && mv "$ROOT/release" "$ROOT/releases/$old"  # kept for the results made with it
    else
      rm -rf "$ROOT/.release-old" && { [ ! -d "$ROOT/release" ] || mv "$ROOT/release" "$ROOT/.release-old"; }
    fi
    mv "$T/site/releases/$v" "$ROOT/release" && rm -rf "$ROOT/.release-old" "$ROOT/releases/$v"
    return
  fi
  rm -rf "$ROOT/releases/.old-$v"
  [ -d "$ROOT/releases/$v" ] && mv "$ROOT/releases/$v" "$ROOT/releases/.old-$v"
  mv "$T/site/releases/$v" "$ROOT/releases/$v" && rm -rf "$ROOT/releases/.old-$v"
}

named() {  # the versions serve.py names: RELEASE (the default species'), then those of RELEASES
  default_version
  sed -n 's/^RELEASES = {\(.*\)}.*/\1/p' "$SERVE" | grep -o ': "[^"]*"' | tr -d ':" '
}

if [ "${1:-}" = stdin ]; then
  v=${2:-}
  grep -qxF "$v" <<< "$(named)" || { echo "release '$v' is not one this code names (serve.py RELEASE, RELEASES)" >&2; exit 1; }
  T=$(mktemp -d "$ROOT/.fetch-XXXXXX")
  trap 'rm -rf "$T"' EXIT
  tar -xf - -C "$T" --no-same-owner || { echo "release $v: the archive could not be read" >&2; exit 1; }
  install_site "$T" "$v" || { echo "release $v was not installed: it failed its checks" >&2; exit 1; }
  echo "release $v installed"
  exit 0
fi

for v in $(named); do
  { [ -f "$ROOT/releases/$v/manifest.json" ] || [ "$(version_of "$ROOT/release")" = "$v" ]; } && continue
  free=$(df -Pk "$ROOT" | awk 'NR == 2 { print $4 }')
  [ "$free" -gt 5000000 ] || { echo "release $v not fetched: under 5 GB free on the VM" >&2; continue; }
  T=$(mktemp -d "$ROOT/.fetch-XXXXXX")
  (
    set -e
    base=$DATA_URL/releases/$v site=$T/site/releases/$v
    mkdir -p "$site" "$T/site/raw" "$T/pool"
    curl -fsSL --retry 3 -o "$site/SHA256SUMS" "$base/SHA256SUMS"
    while read -r _ name; do  # install_site checks each file against these sums
      case $name in /*|*..*) echo "release $v: unexpected file name in SHA256SUMS: $name" >&2; exit 1 ;; esac
      mkdir -p "$(dirname "$site/$name")"
      curl -fsSL --retry 3 -o "$site/$name" "$base/$name"
    done < "$site/SHA256SUMS"
    read -r url file < <("$ROOT/venv/bin/python" -c 'import json, sys; g = json.load(open(sys.argv[1]))["genome"]
print(g["url"], g["file"])' "$site/manifest.json")
    for ext in "" .fai .gzi; do curl -fsSL --retry 3 -o "$T/site/raw/$file$ext" "$url$ext"; done
    for f in pool.parquet background.json; do  # without a published pool the VM says it is stale: deploy.yml builds it
      curl -fsSL --retry 3 -o "$T/pool/$f" "$base/pool/$f" || { rm -rf "$T/pool"; break; }
    done
    install_site "$T" "$v"
  ) && echo "release $v fetched" || echo "release $v could not be fetched from $DATA_URL (is it published?)" >&2
  rm -rf "$T"
done
exit 0
