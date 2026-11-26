#!/usr/bin/env bash
# Publish the portal's Docker image on salmobase (G, 2026-11-26: "We should have the docker uploaded into the same
# salmobase datafiles, then salmobase can use this docker to set it up on it's server"), beside the data releases:
# datasets/salmo-snp/docker/ holds salmo-snp-<version>.docker.tar.gz with its .sha256, compose.yml (this checkout's
# deploy/compose.salmobase.yml, which runs the image on salmobase's server), smoke.sh (tools/smoke.sh, the check of a
# running portal), SHA256SUMS and latest.json (the newest version, its file and sha256). The image file is the GitHub
# Release asset of the tag v<version> (the release workflow builds it), or FILE=<a file deploy/image.sh build made>.
# Never --delete: earlier versions stay, so a server can go back. Run on an Orion login node (compute nodes can't
# reach the server), in a checkout of that version, as snpdata/prep/orion_publish.sh is:
#   MODE=dry bash snpportal/deploy/publish_image.sh 0.2.0    # the default: fetch, check, stage, show what would go
#   MODE=run bash snpportal/deploy/publish_image.sh 0.2.0    # send it (with G's go-ahead)
set -euo pipefail
v=${1:?usage: MODE=dry|run bash snpportal/deploy/publish_image.sh <version>}
mode=${MODE:-dry} host=${HOST:-salmobase}
share=${SHARE:-/mnt/project/ELIXIR/salmobase/datafiles}/datasets/salmo-snp
here=$(cd "$(dirname "$0")" && pwd)
name="salmo-snp-$v.docker.tar.gz" out="$share/docker"
case $mode in dry|run) ;; *) echo "MODE is dry or run" >&2; exit 1 ;; esac
case $(hostname) in login*) ;; *) [ -n "${ANY_HOST:-}" ] || { echo "run this on a login node: compute nodes can't reach $host" >&2; exit 1; } ;; esac
mkdir -p "$out"
if [ -n "${FILE:-}" ]; then
  cp "$FILE" "$out/$name.part" && cp "$FILE.sha256" "$out/$name.sha256"
else
  url="https://github.com/garethgillard/salmo-snp/releases/download/v$v/$name"
  curl -fsSL --retry 3 -o "$out/$name.part" "$url" && curl -fsSL --retry 3 -o "$out/$name.sha256" "$url.sha256"
fi
want=$(cut -d' ' -f1 "$out/$name.sha256")
if [ "$(sha256sum "$out/$name.part" | cut -d' ' -f1)" != "$want" ]; then
  rm -f "$out/$name.part" "$out/$name.sha256"
  echo "$name does not match its sha256: not published" >&2
  exit 1
fi
mv "$out/$name.part" "$out/$name"
cp "$here/compose.salmobase.yml" "$out/compose.yml"
cp "$here/../../tools/smoke.sh" "$out/smoke.sh"
printf '{"version": "%s", "file": "%s", "sha256": "%s"}\n' "$v" "$name" "$want" > "$out/latest.json"
(cd "$out" && sha256sum -- *.docker.tar.gz compose.yml smoke.sh > SHA256SUMS)
echo "$name: $(du -h "$out/$name" | cut -f1), matches its sha256; staged in $out with compose.yml, smoke.sh and latest.json"
[ -z "${ANY_HOST:-}" ] || { echo "ANY_HOST: staged only, nothing sent"; exit 0; }
rs=(rsync -rt --chmod=D755,F644 --itemize-changes --stats)
if [ "$mode" = dry ]; then
  "${rs[@]}" --dry-run "$out/" "$host:datafiles/datasets/salmo-snp/docker/" | tail -n 16
  echo "dry run: nothing was sent (MODE=run sends it)"
  exit 0
fi
"${rs[@]}" "$out/" "$host:datafiles/datasets/salmo-snp/docker/" | tail -n 16
ssh -o BatchMode=yes "$host" "cd datafiles/datasets/salmo-snp/docker && sha256sum -c --quiet SHA256SUMS" && echo "on $host: every file matches SHA256SUMS"
