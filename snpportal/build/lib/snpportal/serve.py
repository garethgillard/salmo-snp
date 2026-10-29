"""The salmo-snp command: run the portal on your own computer, so a SNP list never leaves it.

    salmo-snp download <release URL>         fetch a published release (every file in its SHA256SUMS, checked)
    salmo-snp serve [--release DIR]          the portal on http://127.0.0.1:8000/snp/ (this computer only)

Releases go to ~/.salmo-snp/releases/<version>, results to ~/.salmo-snp/results (kept 30 days). serve uses the newest
downloaded release unless --release names a folder (for example one built with snpdata). The public site runs the same
code behind a web server instead (snpportal/deploy/nrec.sh)."""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
import urllib.request
from pathlib import Path

HOME = Path(os.environ.get("SALMO_SNP_HOME", Path.home() / ".salmo-snp"))
KEEP_HOURS = 30 * 24  # local results; the public site keeps them 24 h


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(url, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".part")
    with urllib.request.urlopen(url, timeout=60) as r, open(tmp, "wb") as f:
        for chunk in iter(lambda: r.read(1 << 20), b""):
            f.write(chunk)
    tmp.replace(target)


def download(url, to=None):
    """Every file listed in <url>/SHA256SUMS, into ~/.salmo-snp/releases/<version>; files already there with the right
    sha256 are kept. Returns the folder."""
    url = url.rstrip("/") + "/"
    with urllib.request.urlopen(url + "SHA256SUMS", timeout=60) as r:
        sums = [line.split(None, 1) for line in r.read().decode().splitlines() if line.strip()]
    folder = Path(to) if to else HOME / "releases" / url.rstrip("/").rsplit("/", 1)[-1]
    for digest, name in sums:
        name = name.strip().lstrip("*")
        target = (folder / name).resolve()
        if folder.resolve() not in target.parents:
            sys.exit(f"salmo-snp: unexpected file name in SHA256SUMS: {name}")
        if target.exists() and sha256(target) == digest:
            continue
        print(f"downloading {name}", flush=True)
        fetch(url + name, target)
        if sha256(target) != digest:
            target.unlink()
            sys.exit(f"salmo-snp: {name} does not match its sha256: try again, or tell the release's publisher")
    print(f"release in {folder}")
    return folder


def newest_release():
    found = sorted(p.parent for p in (HOME / "releases").glob("*/manifest.json"))
    return found[-1] if found else None


def serve(release=None, port=8000):
    release = Path(release) if release else newest_release()
    if not release or not (release / "manifest.json").exists():
        sys.exit("salmo-snp: no release: run `salmo-snp download <release URL>` first, or give --release <folder>")
    os.environ.update({
        "DJANGO_SETTINGS_MODULE": "snpsite.settings", "DJANGO_DEBUG": "0", "DJANGO_ALLOWED_HOSTS": "127.0.0.1,localhost",
        "SNPSCORE_RELEASE": str(release.resolve()), "SNPPORTAL_RESULTS_DIR": str(HOME / "results"),
        "SNPPORTAL_KEEP_HOURS": str(KEEP_HOURS)})
    (HOME / "results").mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("DJANGO_SECRET_KEY", secret())
    import django
    from django.core.management import call_command
    django.setup()
    print(f"salmo-snp: release {release.name}; open http://127.0.0.1:{port}/snp/ (this computer only; Ctrl-C stops it)")
    call_command("runserver", f"127.0.0.1:{port}", use_reloader=False, insecure_serving=True)  # static files too


def secret():
    """A secret key kept in ~/.salmo-snp, so the Design panel's cookies survive a restart."""
    path = HOME / "secret_key"
    if not path.exists():
        import secrets
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(secrets.token_urlsafe(50))
        path.chmod(0o600)
    return path.read_text().strip()


def main(argv=None):
    p = argparse.ArgumentParser(prog="salmo-snp", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("download", help="fetch a published release, every file checked against its SHA256SUMS")
    d.add_argument("url")
    d.add_argument("--to", help="folder (default: ~/.salmo-snp/releases/<version>)")
    s = sub.add_parser("serve", help="run the portal on http://127.0.0.1:<port>/snp/, for this computer only")
    s.add_argument("--release", help="a release folder (default: the newest downloaded one)")
    s.add_argument("--port", type=int, default=8000)
    args = p.parse_args(argv)
    if args.cmd == "download":
        download(args.url, args.to)
    else:
        serve(args.release, args.port)


if __name__ == "__main__":
    main()
