#!/usr/bin/env bash
# Update the NREC demo to a commit of origin/main. GitHub Actions runs it over SSH after the tests pass on main (the
# deploy key's authorized_keys line forces this script, so that key can do nothing else); nrec.sh runs it too.
# The commit comes in SSH_ORIGINAL_COMMAND (or $1); anything that is not a commit on origin/main means origin/main.
# If the portal doesn't answer after the restart, it goes back to the previous commit and fails.
set -euo pipefail
cd /srv/snpportal/salmo-snp
export GIT_SSH_COMMAND="ssh -i $HOME/.ssh/salmo_snp_read -o IdentitiesOnly=yes"
want=${SSH_ORIGINAL_COMMAND:-${1:-}}
before=$(git rev-parse HEAD 2>/dev/null || true)
git fetch -q origin main
if [[ ! $want =~ ^[0-9a-f]{40}$ ]] || ! git merge-base --is-ancestor "$want" origin/main 2>/dev/null; then
  want=$(git rev-parse origin/main)
fi

install() {  # check out $1, install snpscore, collect static files, restart; succeed only when the portal answers
  git checkout -q --force --detach "$1"
  /srv/snpportal/venv/bin/pip install -q -e snpscore
  (set -a && . /srv/snpportal/env && cd snpportal && /srv/snpportal/venv/bin/python manage.py collectstatic --noinput -v 0)
  sudo systemctl restart snpportal
  host=$(sed -n 's/^DJANGO_ALLOWED_HOSTS=\([^,]*\).*/\1/p' /srv/snpportal/env)
  for _ in $(seq 20); do
    sleep 2
    code=$(curl -s -o /dev/null -w "%{http_code}" -H "Host: $host" -H "X-Forwarded-Proto: https" http://127.0.0.1:8000/snp/ || true)
    [ "$code" = 200 ] && return 0
  done
  return 1
}

if install "$want"; then
  echo "deployed $(git log -1 --format='%h %s')"
else
  echo "the portal did not answer at $want; back to ${before:-nothing}" >&2
  [ -n "$before" ] && install "$before" || true
  exit 1
fi
