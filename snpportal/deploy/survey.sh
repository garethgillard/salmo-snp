#!/usr/bin/env bash
# What a deployment of the portal needs to know about a server, before anything is installed there (the salmobase
# server: docs/SALMOBASE.md). It only reads: nothing is created, changed or started. Run it on the server, e.g. from
# Orion:   ssh salmobase 'bash -s' < snpportal/deploy/survey.sh
say() { printf '\n== %s\n' "$*"; }
try() { "$@" 2>&1 | head -n "${LINES_MAX:-12}"; }

say "who, where, what"
id; hostname -f 2>/dev/null || hostname; uname -srm
[ -r /etc/os-release ] && . /etc/os-release && echo "$PRETTY_NAME"

say "cores, memory, disk"
nproc; try free -g; try df -h "$HOME" /data /srv /var

say "the datafiles folder (what https://salmobase.org/datafiles/ serves)"
for d in "$HOME/datafiles" /data/datafiles /srv/datafiles; do
  [ -e "$d" ] && echo "$d -> $(readlink -f "$d")" && try ls "$d/datasets/salmo-snp/releases" && try ls -ld "$d/datasets/salmo-snp/releases"/* "$d/genomes"
done

say "python (the portal needs 3.11 or newer)"
for p in python3 python3.11 python3.12 python3.13 python3.14 uv conda mamba; do command -v "$p" > /dev/null && echo "$p: $($p --version 2>&1 | head -1) ($(command -v "$p"))"; done

say "containers"
for c in docker podman apptainer singularity; do command -v "$c" > /dev/null && echo "$c: $($c --version 2>&1 | head -1)"; done
command -v docker > /dev/null && { docker ps --format '{{.Names}}\t{{.Image}}\t{{.Ports}}' 2>&1 | head -20; }
command -v podman > /dev/null && { podman ps --format '{{.Names}}\t{{.Image}}\t{{.Ports}}' 2>&1 | head -20; }

say "services this user may run"
sudo -n true 2> /dev/null && echo "sudo: yes, without a password" || echo "sudo: not without a password"
loginctl show-user "$USER" -p Linger 2>&1 | head -1
systemctl --user list-units --type=service --no-pager 2>&1 | head -12
try crontab -l

say "the web server and what runs salmobase"
ps -eo user:12,pid,args --no-headers 2> /dev/null | grep -E 'httpd|apache2|nginx|caddy|gunicorn|uwsgi|daphne|manage\.py|node |java ' | grep -v grep | cut -c1-160 | head -25
for f in /etc/httpd/conf.d /etc/httpd/conf /etc/apache2/sites-enabled /etc/nginx/conf.d /etc/nginx/sites-enabled; do
  [ -d "$f" ] && echo "$f: $(ls "$f" 2>&1 | tr '\n' ' ')" && grep -rhE '^\s*(ProxyPass|proxy_pass|ServerName|server_name|Alias|DocumentRoot)\b' "$f" 2> /dev/null | sort -u | head -30
done

say "ports in use"
(ss -ltn 2> /dev/null || netstat -ltn 2> /dev/null) | head -30

say "what it reaches"
for u in https://github.com https://pypi.org/simple/ https://salmobase.org/datafiles/datasets/salmo-snp/releases/latest.json https://registry-1.docker.io/v2/; do
  echo "$u: $(curl -s -o /dev/null -m 15 -w '%{http_code}' "$u" 2>&1)"
done

say "SELinux"
getenforce 2> /dev/null || echo "not found"
