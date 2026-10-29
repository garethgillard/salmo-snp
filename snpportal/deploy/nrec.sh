#!/usr/bin/env bash
# Deploy the public demo to an NREC VM (GOLD Ubuntu 22.04/24.04, dualStack network, ports 22/80/443 open):
#   bash deploy/nrec.sh <ssh host> <web name> [<web name> ...]
#   e.g.  bash deploy/nrec.sh nrec 158.39.75.9 158-39-75-9.sslip.io   (the address: https://158.39.75.9/snp/)
# Each name gets its own Caddy site and HTTPS certificate; an IPv4 address gets Let's Encrypt's short-lived IP
# certificate (Caddy 2.10 or newer). The first name is the one checked at the end.
# From this Mac it copies snpscore/ and snpportal/ (code only), the release and the genome to /srv/snpportal, then on the VM it
# installs Python packages, Caddy (HTTPS from Let's Encrypt), a 2 GB swap file if there is none, and three systemd
# units: gunicorn, and an hourly snpportal_cleanup. DuckDB gets half the RAM and every CPU. Safe to rerun after a
# change: results and the secret key are kept.
set -euo pipefail
HOST=$1
shift
NAMES="$*"
NAME=$1  # the first name, for the check at the end
ROOT=$(cd "$(dirname "$0")/../.." && pwd)  # the salmo-snp repository
SNPSCORE=$ROOT/snpscore
RELEASE=${RELEASE:-$SNPSCORE/release/dev}
GENOME=$SNPSCORE/data/raw/Salmo_salar.Ssal_v3.1.dna_sm.toplevel.fa.gz
SKIP=(--exclude .git/ --exclude .venv/ --exclude __pycache__/ --exclude .claude/ --exclude .DS_Store
      --exclude /data/ --exclude /release/ --exclude /results/)

ssh "$HOST" 'sudo mkdir -p /srv/snpportal/genome && sudo chown -R "$USER" /srv/snpportal'
rsync -az --delete "${SKIP[@]}" "$SNPSCORE/" "$HOST:/srv/snpportal/salmo-snpscore/"
rsync -az --delete "${SKIP[@]}" "$ROOT/snpportal/" "$HOST:/srv/snpportal/salmo-snpportal/"
rsync -az --delete "$RELEASE/" "$HOST:/srv/snpportal/release/"
rsync -az "$GENOME" "$GENOME.fai" "$GENOME.gzi" "$HOST:/srv/snpportal/genome/"

ssh "$HOST" "NAMES='$NAMES' NAME=$NAME GENOME=$(basename "$GENOME") bash -s" <<'REMOTE'
set -euo pipefail
cd /srv/snpportal
if ! command -v caddy >/dev/null; then  # Caddy's own apt repository (caddyserver.com/docs/install)
  sudo apt-get update -q
  sudo apt-get install -y -q python3-venv debian-keyring debian-archive-keyring apt-transport-https curl gnupg
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key | sudo gpg --batch --yes --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt | sudo tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
  sudo apt-get update -q && sudo apt-get install -y -q caddy
fi
if ! swapon --show | grep -q .; then  # a small VM: swap as a safety net for big lists
  sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap -q /swapfile && sudo swapon /swapfile
  echo "/swapfile none swap sw 0 0" | sudo tee -a /etc/fstab >/dev/null
fi
[ -d venv ] || python3 -m venv venv
venv/bin/pip install -q --upgrade pip
venv/bin/pip install -q "django>=4.2,<5" "duckdb==1.2.2" gunicorn -e salmo-snpscore
[ -f secret_key ] || (umask 077 && python3 -c "import secrets; print(secrets.token_urlsafe(50))" > secret_key)
mkdir -p results && chmod 700 results
cat > env <<EOF
DJANGO_SETTINGS_MODULE=sandbox.settings
DJANGO_DEBUG=0
DJANGO_SECRET_KEY=$(cat secret_key)
DJANGO_ALLOWED_HOSTS=${NAMES// /,}
DJANGO_STATIC_ROOT=/srv/snpportal/static
SNPSCORE_RELEASE=/srv/snpportal/release
SNPSCORE_GENOME=/srv/snpportal/genome/$GENOME
SNPPORTAL_RESULTS_DIR=/srv/snpportal/results
SNPPORTAL_DUCKDB_THREADS=$(nproc)
SNPPORTAL_DUCKDB_MEMORY=$(( $(free -m | awk '/^Mem:/ {print $2}') / 2 ))MB
EOF
chmod 600 env
(set -a && . ./env && cd salmo-snpportal && ../venv/bin/python manage.py collectstatic --noinput -v 0)

sudo tee /etc/systemd/system/snpportal.service >/dev/null <<EOF
[Unit]
Description=Functional SNP portal (public demo)
After=network.target
[Service]
User=$USER
WorkingDirectory=/srv/snpportal/salmo-snpportal
EnvironmentFile=/srv/snpportal/env
ExecStart=/srv/snpportal/venv/bin/gunicorn sandbox.wsgi --bind 127.0.0.1:8000 --workers 1 --threads 8 --timeout 300
Restart=always
[Install]
WantedBy=multi-user.target
EOF
sudo tee /etc/systemd/system/snpportal-cleanup.service >/dev/null <<EOF
[Unit]
Description=Delete expired SNP portal results
[Service]
Type=oneshot
User=$USER
WorkingDirectory=/srv/snpportal/salmo-snpportal
EnvironmentFile=/srv/snpportal/env
ExecStart=/srv/snpportal/venv/bin/python manage.py snpportal_cleanup
EOF
sudo tee /etc/systemd/system/snpportal-cleanup.timer >/dev/null <<EOF
[Unit]
Description=Hourly SNP portal cleanup
[Timer]
OnCalendar=hourly
Persistent=true
[Install]
WantedBy=timers.target
EOF
for name in $NAMES; do  # one site per name; an IPv4 address gets Let's Encrypt's short-lived IP certificate
  tls=""
  [[ $name =~ ^[0-9.]+$ ]] && tls=$'\ttls {\n\t\tissuer acme {\n\t\t\tprofile shortlived\n\t\t}\n\t}\n'
  printf '%s {\n%s\tencode gzip\n\tredir / /snp/\n\thandle_path /static/* {\n\t\troot * /srv/snpportal/static\n\t\tfile_server\n\t}\n\treverse_proxy 127.0.0.1:8000\n}\n\n' "$name" "$tls"
done | sudo tee /etc/caddy/Caddyfile >/dev/null
sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null
sudo chmod 755 /srv/snpportal /srv/snpportal/static  # Caddy reads the static files; results stay 0700
sudo systemctl daemon-reload
sudo systemctl enable -q --now snpportal-cleanup.timer
sudo systemctl enable -q snpportal
sudo systemctl restart snpportal
sudo systemctl reload caddy || sudo systemctl restart caddy
sleep 2
systemctl is-active snpportal caddy
curl -s -o /dev/null -w "local: HTTP %{http_code}\n" -H "Host: $NAME" -H "X-Forwarded-Proto: https" http://127.0.0.1:8000/snp/
REMOTE
echo "Deployed: https://$NAME/snp/"
