#!/bin/sh
# Two uses of the Docker image (G, 2026-11-26: deployed as a Docker image published in salmobase's datafiles, which
# users can also run instead of the Python package):
#   salmo-snp-server         the portal as a service on a server (below)
#   salmo-snp-server local   on a user's own computer: the data in /data (downloaded and checked at the first start,
#                            and when a new image names a new release; SALMO_SNP_SPECIES=all for every species,
#                            SALMO_SNP_DATA_URL for a copy of the published folder), results kept there until
#                            deleted, as `salmo-snp serve`: run with -p 127.0.0.1:8000:8000 so only this computer reaches it.
# The portal as a service on a server: what the salmobase container runs (deploy/Dockerfile) and what a server
# without Docker runs from a virtual environment (docs/SALMOBASE.md). It needs the packages installed (snpscore,
# salmo-snp, gunicorn) and two folders:
#   SNPSCORE_SALMOBASE   salmobase's datafiles folder, read only: the published releases, the genomes, the AQUA-FAANG
#                        tracks and the models' files are read where they are (snpsite/settings.py). Without it:
#                        SNPSCORE_RELEASE (a release folder) and SNPSCORE_GENOME_DIR, as before.
#   SNPPORTAL_DATA       the portal's own folder (default /data): results/, static/ and secret_key.
# Also: DJANGO_ALLOWED_HOSTS (the site's name), SNPPORTAL_BIND (default 0.0.0.0:8000, for a container; a server:
# 127.0.0.1:<port>, behind Apache), GUNICORN_WORKERS (1), SNPPORTAL_KEEP_HOURS (720: 30 days).
# It makes the secret key at the first start, looks at each species' release (snpportal_prepare: a missing default
# release stops it; the public pool of a release whose folder it may write to is built; a published folder is read
# only, its pools are built on Orion and published with the release, and a line says when one does not fit this
# version's weights), runs Django's checks (a damaged release stops it here), removes results older than
# SNPPORTAL_KEEP_HOURS every hour, and starts gunicorn.
set -e
DATA=${SNPPORTAL_DATA:-/data}
[ -w "${HOME:-/nonexistent}" ] || export HOME="$DATA"  # a container run as another user: gunicorn keeps a socket in ~
if [ "${1:-}" = local ]; then  # a user's own computer: the Python package's own commands, its data in /data
  unset SNPSCORE_SALMOBASE DJANGO_STATIC_URL SNPPORTAL_SERVE_STATIC
  export SALMO_SNP_HOME="$DATA"
  cd "$DATA"
  salmo-snp download --if-missing --species "${SALMO_SNP_SPECIES:-atlantic_salmon}" ${SALMO_SNP_DATA_URL:+--from "$SALMO_SNP_DATA_URL"}
  exec salmo-snp serve --host 0.0.0.0 --port 8000
fi
export SNPPORTAL_RESULTS_DIR="${SNPPORTAL_RESULTS_DIR:-$DATA/results}"
export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-snpsite.settings}" DJANGO_DEBUG="${DJANGO_DEBUG:-0}"
export DJANGO_STATIC_URL="${DJANGO_STATIC_URL:-/snp/static/}" SNPPORTAL_SERVE_STATIC="${SNPPORTAL_SERVE_STATIC:-1}"
export SNPPORTAL_COOKIE_PATH="${SNPPORTAL_COOKIE_PATH:-/snp/}"  # beside another site: its pages never get our cookies
mkdir -p "$SNPPORTAL_RESULTS_DIR"
chmod 700 "$SNPPORTAL_RESULTS_DIR"
cd "$DATA"  # not a checkout of the repository: its snpportal/ folder would hide the installed package from python -m
if [ -z "$DJANGO_SECRET_KEY" ]; then
  [ -f "$DATA/secret_key" ] || (umask 077 && python -c "import secrets; print(secrets.token_urlsafe(50))" > "$DATA/secret_key")
  DJANGO_SECRET_KEY=$(cat "$DATA/secret_key")
  export DJANGO_SECRET_KEY
fi
if [ -z "$DJANGO_STATIC_ROOT" ]; then  # a container has them from its build; a virtual environment collects them here
  export DJANGO_STATIC_ROOT="$DATA/static"
  python -m django collectstatic --noinput -v 0
fi
python -m django snpportal_prepare
python -m django check
(while sleep 3600; do python -m django snpportal_cleanup || true; done) &
exec gunicorn snpsite.wsgi --bind "${SNPPORTAL_BIND:-0.0.0.0:8000}" --workers "${GUNICORN_WORKERS:-1}" --threads 8 \
  --timeout 300 --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-*}"
