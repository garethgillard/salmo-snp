#!/usr/bin/env bash
# Publish releases built on Orion on salmobase (docs/ORION.md "Hosting on salmobase"). Each release folder is linked
# into salmobase's share on Orion (Orion's copy of the server's datafiles, in the same elixir project) as
# datasets/salmo-snp/releases/<version>; releases/latest.json names the Atlantic salmon release given (the default species';
# left as it is when only another species' release is published); and the share's folder goes to the server with
# rsync, the links sent as the files they point to, then checked there against SHA256SUMS. A release goes up with its
# pool/, which SHA256SUMS leaves out: the NREC demo takes it (its VM can't build one); installs build their own.
# Never --delete: the server has files the share lacks.
# Run in snpdata/ on a LOGIN node (compute nodes can't reach the server), as a background task: the login node cuts a
# long rsync after about 10 minutes, and a second run goes on from where it stopped.
#   MODE=dry bash prep/orion_publish.sh atlantic_salmon-Ssal_v3.1-2026-11-26 rainbow_trout-USDA_OmykA_1.1-2026-11-26
#   MODE=run bash prep/orion_publish.sh ...    # send it (with G's go-ahead)
set -euo pipefail
mode=${MODE:-dry} host=${HOST:-salmobase}
share=${SHARE:-/mnt/project/ELIXIR/salmobase/datafiles}/datasets/salmo-snp
[ $# -gt 0 ] || { echo "usage: MODE=dry|run bash prep/orion_publish.sh <version> [version ...]" >&2; exit 1; }
case $mode in dry|run) ;; *) echo "MODE is dry or run" >&2; exit 1 ;; esac
case $(hostname) in login*) ;; *) echo "run this on a login node: compute nodes can't reach $host" >&2; exit 1 ;; esac
mkdir -p "$share/releases"
for v in "$@"; do
  r=$(cd "release/$v" && pwd -P)  # release/ links into the project folder
  (cd "$r" && sha256sum -c --quiet SHA256SUMS) || { echo "$v fails its own SHA256SUMS: not published" >&2; exit 1; }
  ln -sfn "$r" "$share/releases/$v"
  echo "$v: $(du -sh "$r" | cut -f1), every file matches SHA256SUMS, linked as $share/releases/$v"
done
for v in "$@"; do  # latest.json: the default species' newest release, Atlantic salmon's (by its manifest)
  key=$(python3 -c 'import json, sys; print((json.load(open(sys.argv[1])).get("species") or {}).get("key", "atlantic_salmon"))' \
        "$share/releases/$v/manifest.json")
  if [ "$key" = atlantic_salmon ]; then
    latest="{\"version\": \"$v\"}"
    [ "$(cat "$share/releases/latest.json" 2>/dev/null)" = "$latest" ] || echo "$latest" > "$share/releases/latest.json"
    break
  fi
done
echo "server $host: $(ssh -o BatchMode=yes -o ConnectTimeout=20 "$host" 'df -h /data | tail -1')"
rs=(rsync -rLt --chmod=D755,F644 --itemize-changes --stats)
if [ "$mode" = dry ]; then
  "${rs[@]}" --dry-run "$share/" "$host:datafiles/datasets/salmo-snp/" | tail -n 16
  echo "dry run: nothing was sent (MODE=run sends it)"
  exit 0
fi
"${rs[@]}" "$share/" "$host:datafiles/datasets/salmo-snp/" | tail -n 16
for v in "$@"; do
  ssh -o BatchMode=yes "$host" "cd datafiles/datasets/salmo-snp/releases/$v && sha256sum -c --quiet SHA256SUMS" &&
    echo "$v: the server's copy matches SHA256SUMS"
done
echo "published $(date '+%F %T'): https://salmobase.org/datafiles/datasets/salmo-snp/releases/"
