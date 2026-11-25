#!/bin/sh
# The salmobase container's start (deploy/Dockerfile): the secret key (kept in /data), the public pool when the
# release folder is writable, Django's checks (a damaged release stops it here), an hourly cleanup of results older
# than SNPPORTAL_KEEP_HOURS (24), then gunicorn on port 8000.
set -e
mkdir -p /data/results
chmod 700 /data/results
if [ -z "$DJANGO_SECRET_KEY" ]; then
  [ -f /data/secret_key ] || python -c "import secrets; print(secrets.token_urlsafe(50))" > /data/secret_key
  DJANGO_SECRET_KEY=$(cat /data/secret_key)
  export DJANGO_SECRET_KEY
fi
snpscore pool --release "$SNPSCORE_RELEASE" --if-stale --memory "${SNPPORTAL_POOL_MEMORY:-4GB}" \
  || echo "salmo-snp: no public pool (is /release read-only?): the Overview leaves out the public comparison"
python -m django check
(while sleep 3600; do python -m django snpportal_cleanup || true; done) &
exec gunicorn snpsite.wsgi --bind 0.0.0.0:8000 --workers "${GUNICORN_WORKERS:-1}" --threads 8 --timeout 300 \
  --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-*}"
