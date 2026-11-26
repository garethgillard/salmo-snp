#!/bin/sh
# The portal's Docker image as one file (G, 2026-11-26: "we'll only be deploying as a docker image ... uploaded into the
# same salmobase datafiles, then salmobase can use this docker to set it up on it's server. That'll let users also be
# able to choose between a local docker installation, or the python package"):
#   sh snpportal/deploy/image.sh build <version> [folder]   in a checkout of that version: docker build, then
#        salmo-snp-<version>.docker.tar.gz (docker save, gzipped) and its .sha256 in the folder (default: here).
#        Behind a proxy that re-signs TLS: BUILD_ARGS="--secret id=ca,src=<bundle.crt>".
#   sh snpportal/deploy/image.sh load <file or URL>        check the file against the .sha256 beside it (fetched too,
#        for a URL), then docker load: the image salmo-snp:<version> is ready for compose.salmobase.yml or docker run.
# The release workflow builds it for each vX.Y.Z tag; deploy/publish_image.sh puts it in salmobase's datafiles.
set -eu
cmd=${1:-} arg=${2:-}
[ -n "$cmd" ] && [ -n "$arg" ] || { echo "usage: image.sh build <version> [folder] | image.sh load <file or URL>" >&2; exit 1; }
case $cmd in
  build)
    out=${3:-.}
    root=$(cd "$(dirname "$0")/../.." && pwd)
    file="$out/salmo-snp-$arg.docker.tar.gz"
    # shellcheck disable=SC2086  # BUILD_ARGS is a list of options
    docker build ${BUILD_ARGS:-} -f "$root/snpportal/deploy/Dockerfile" -t "salmo-snp:$arg" \
      --label "org.opencontainers.image.version=$arg" --label "org.opencontainers.image.source=https://github.com/garethgillard/salmo-snp" "$root"
    docker save "salmo-snp:$arg" | gzip -6 > "$file.part"
    mv "$file.part" "$file"
    (cd "$out" && sha256sum "$(basename "$file")" > "$(basename "$file").sha256")
    echo "$file: $(du -h "$file" | cut -f1), $(cut -c1-12 "$file.sha256")"
    ;;
  load)
    work=$(mktemp -d)
    trap 'rm -rf "$work"' EXIT
    case $arg in
      http://*|https://*)
        name=$(basename "$arg")
        curl -fsSL --retry 3 -o "$work/$name" "$arg"
        curl -fsSL --retry 3 -o "$work/$name.sha256" "$arg.sha256"
        file="$work/$name" ;;
      *)
        file=$arg
        cp "$arg.sha256" "$work/$(basename "$arg").sha256" ;;
    esac
    want=$(cut -d' ' -f1 "$work/$(basename "$file").sha256")
    got=$(sha256sum "$file" | cut -d' ' -f1)
    [ "$want" = "$got" ] || { echo "$(basename "$file") does not match its sha256: not loaded" >&2; exit 1; }
    gunzip -c "$file" | docker load
    ;;
  *) echo "usage: image.sh build <version> [folder] | image.sh load <file or URL>" >&2; exit 1 ;;
esac
