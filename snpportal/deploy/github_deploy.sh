#!/usr/bin/env bash
# One-time: let GitHub Actions' deploy workflow update the NREC demo (README "Deploying the demo").
#   bash deploy/github_deploy.sh <ssh host> <IPv4>      e.g.  bash deploy/github_deploy.sh nrec 158.39.75.9
# Run deploy/nrec.sh first (it makes the VM's git checkout and its read-only key). This makes a new SSH key, allows it
# on the VM only to run update.sh (a forced command, no shell, no forwarding), stores it as the repository secret
# NREC_DEPLOY_KEY with the VM's host key (NREC_KNOWN_HOSTS) and sets the variable NREC_HOST, then deletes the local copy.
# Rerun to replace the key: the old one is removed from the VM.
set -euo pipefail
HOST=$1
IP=$2
REPO=garethgillard/salmo-snp
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
ssh-keygen -q -t ed25519 -N "" -C "github-actions-deploy" -f "$tmp/key"
line="command=\"/srv/snpportal/salmo-snp/snpportal/deploy/update.sh\",no-port-forwarding,no-X11-forwarding,no-agent-forwarding,no-pty $(cat "$tmp/key.pub")"
ssh "$HOST" "sed -i '/github-actions-deploy\$/d' ~/.ssh/authorized_keys && echo '$line' >> ~/.ssh/authorized_keys"
gh secret set NREC_DEPLOY_KEY --repo "$REPO" < "$tmp/key"
ssh-keyscan -t ed25519 "$IP" 2>/dev/null | gh secret set NREC_KNOWN_HOSTS --repo "$REPO"
gh variable set NREC_HOST --repo "$REPO" --body "$IP"
echo "GitHub Actions can now update $IP; the next push to main deploys after the tests."
