#!/usr/bin/env bash
# Update the NREC demo to a commit of origin/main. GitHub Actions' deploy workflow (run when G asks) runs it over SSH
# after the tests pass (the deploy key's authorized_keys line forces this script, so that key can do nothing else);
# nrec.sh runs it too.
# After installing, deploy/species.sh fetches the releases of the other species this code names (rainbow trout) that
# the VM doesn't hold yet, from the GitHub data release: the portal's species bar then offers them.
# `release <version>` takes such a release as a tar on stdin instead (the species-data workflow builds and sends it).
# The commit comes in SSH_ORIGINAL_COMMAND (or $1); anything that is not a commit on origin/main means origin/main.
# If the portal doesn't answer after the restart, it goes back to the previous commit and fails.
# `pool` instead takes a public pool (pool.parquet and background.json, a .tar.gz on stdin) that the deploy workflow
# built for the code installed here: the VM's 2 GB RAM can't build one. It replaces the release's pool only if
# snpscore.pool.stale says it fits this release, weights.yaml and snpscore.
set -euo pipefail
cd /srv/snpportal/salmo-snp
export GIT_SSH_COMMAND="ssh -i $HOME/.ssh/salmo_snp_read -o IdentitiesOnly=yes"
want=${SSH_ORIGINAL_COMMAND:-${1:-}}
before=$(git rev-parse HEAD 2>/dev/null || true)
release=/srv/snpportal/release

stale() {  # whether the release's pool is stale for the code installed here
  ! /srv/snpportal/venv/bin/python -c 'import sys; from snpscore.pool import stale; sys.exit(stale(sys.argv[1]))' "$release"
}

answers() {  # restart the portal; succeed when it answers
  sudo systemctl restart snpportal
  host=$(sed -n 's/^DJANGO_ALLOWED_HOSTS=\([^,]*\).*/\1/p' /srv/snpportal/env)
  for _ in $(seq 20); do
    sleep 2
    code=$(curl -s -o /dev/null -w "%{http_code}" -H "Host: $host" -H "X-Forwarded-Proto: https" http://127.0.0.1:8000/snp/ || true)
    [ "$code" = 200 ] && return 0
  done
  return 1
}

if [[ $want == release\ * ]]; then  # `release <version>`: another species' release as a tar on stdin (species.sh)
  bash snpportal/deploy/species.sh stdin "${want#release }" || exit 1
  answers || { echo "the portal did not answer after the new release" >&2; exit 1; }
  exit 0
fi

if [ "$want" = pool ]; then
  new=$(mktemp -d "$release/.pool-XXXXXX")
  trap 'rm -rf "$new" "$release/pool.previous"' EXIT
  tar -xzf - -C "$new" --no-same-owner pool.parquet background.json
  chmod 755 "$new" && chmod 644 "$new"/*
  rm -rf "$release/pool.previous"
  [ -d "$release/pool" ] && mv "$release/pool" "$release/pool.previous"
  mv "$new" "$release/pool"
  if stale; then
    rm -rf "$release/pool" && [ -d "$release/pool.previous" ] && mv "$release/pool.previous" "$release/pool"
    echo "the pool sent doesn't fit this release, weights.yaml and snpscore: the old one is kept" >&2
    exit 1
  fi
  answers || { echo "the portal did not answer after the new pool" >&2; exit 1; }
  echo "public pool updated: $(sed -n 's/.*"created": "\([^"]*\)".*/\1/p' "$release/pool/background.json")"
  exit 0
fi

git fetch -q origin main
if [[ ! $want =~ ^[0-9a-f]{40}$ ]] || ! git merge-base --is-ancestor "$want" origin/main 2>/dev/null; then
  want=$(git rev-parse origin/main)
fi

install() {  # check out $1, install its packages, say if the pool is stale, collect static files, restart; succeed only when the portal answers
  git checkout -q --force --detach "$1"
  # the newest versions the packages allow (security fixes arrive with each deploy)
  /srv/snpportal/venv/bin/pip install -q --upgrade --upgrade-strategy eager gunicorn -e snpscore -e snpportal || return 1
  # The public pool is never built here: the VM's 2 GB RAM can't, and trying swapped for 17 min until the SSH session
  # dropped (2026-11-06). The deploy workflow builds it and sends it (`pool` above) when this line says so.
  if stale; then echo "the public pool is stale (new weights.yaml or snpscore)" >&2; fi
  bash snpportal/deploy/species.sh || true  # the other species' releases, fetched once from the GitHub data release
  (set -a && . /srv/snpportal/env && cd snpportal && /srv/snpportal/venv/bin/python manage.py collectstatic --noinput -v 0)
  answers
}

if install "$want"; then
  echo "deployed $(git log -1 --format='%h %s')"
else
  echo "the portal did not answer at $want; back to ${before:-nothing}" >&2
  [ -n "$before" ] && install "$before" || true
  exit 1
fi
