"""The salmo-snp command: the portal on your own computer, so a SNP list never leaves it.

    salmo-snp download [VERSION] [--from URL|FOLDER]   the data: a release snapshot and the genome, each file checked
    salmo-snp serve [--release FOLDER] [--port N]      the portal on http://127.0.0.1:8000/snp/ (this computer only)
    salmo-snp info                                     where the data and your results are, and how big

Everything lives in one data folder (SALMO_SNP_HOME, else the platform's: ~/Library/Application Support/salmo-snp,
~/.local/share/salmo-snp or %LOCALAPPDATA%\\salmo-snp): releases/<version>/, genome/, results/ (kept until you delete
them) and secret_key. The published data is a folder (snpdata publish) on a web server, or a copy of it on a disk:
releases/<version>/ with SHA256SUMS, releases/latest.json, and raw/ with the genome."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import urllib.request
from pathlib import Path

RELEASE = "2026-11-05"  # the data release this version of the code expects
DATA_URL = os.environ.get("SALMO_SNP_DATA_URL")  # where the data is published (set once it is hosted, e.g. on salmobase)


def data_home():
    if os.environ.get("SALMO_SNP_HOME"):
        return Path(os.environ["SALMO_SNP_HOME"])
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "salmo-snp"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "salmo-snp"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "salmo-snp"


HOME = data_home()


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read(source, name):
    """Bytes of `name` under a URL or a folder."""
    if "://" in str(source):
        with urllib.request.urlopen(str(source).rstrip("/") + "/" + name, timeout=60) as r:
            return r.read()
    return Path(source, name).read_bytes()


def copy(source, name, target):
    """`name` under a URL or folder into `target`, through a .part file."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".part")
    if "://" in str(source):
        with urllib.request.urlopen(str(source).rstrip("/") + "/" + name, timeout=60) as r, open(tmp, "wb") as f:
            shutil.copyfileobj(r, f, 1 << 20)
    else:
        shutil.copyfile(Path(source, name), tmp)
    tmp.replace(target)


def get(source, name, target, digest):
    """Fetch one file unless `target` already has `digest`; refuse it when it doesn't match."""
    if target.exists() and (digest is None or sha256(target) == digest):
        return
    print(f"  {name}", flush=True)
    copy(source, name, target)
    if digest and sha256(target) != digest:
        target.unlink()
        sys.exit(f"salmo-snp: {name} does not match its sha256: try again, or tell the data's publisher")


def download(version=None, source=None, genome=True):
    """Release `version` (default: RELEASE; 'latest' reads releases/latest.json) from `source` (a published data folder:
    URL or path; default DATA_URL) into HOME/releases/<version>, and the genome into HOME/genome. Files already there
    with the right sha256 are kept. Returns the release folder."""
    source = source or DATA_URL
    if not source:
        sys.exit("salmo-snp: the data isn't published at a default address yet: give --from <URL or folder>")
    if version == "latest":
        version = json.loads(read(source, "releases/latest.json"))["version"]
    version = version or RELEASE
    base = f"{str(source).rstrip('/')}/releases/{version}"
    try:
        sums = read(base, "SHA256SUMS").decode()
    except (OSError, ValueError):
        sys.exit(f"salmo-snp: no release {version} at {source} (looked for releases/{version}/SHA256SUMS)")
    folder = HOME / "releases" / version
    print(f"release {version} -> {folder}", flush=True)
    for digest, name in (line.split(None, 1) for line in sums.splitlines() if line.strip()):
        name = name.strip().lstrip("*")
        target = (folder / name).resolve()
        if folder.resolve() not in target.parents:
            sys.exit(f"salmo-snp: unexpected file name in SHA256SUMS: {name}")
        get(base, name, target, digest)
    (folder / "SHA256SUMS").write_text(sums)  # kept: `snpscore verify` and the portal's system check re-hash against it
    from snpscore.release import check
    problems = check(folder)
    if problems:
        sys.exit("salmo-snp: the downloaded release is damaged:\n  " + "\n  ".join(problems))
    if genome:
        download_genome(folder, source)
    ensure_pool(folder)
    print("done: start it with `salmo-snp serve`")
    return folder


def ensure_pool(release):
    """The release's public background pool (snpscore pool: the Overview's comparison with public sites, gene-page
    candidates), built when it is missing or was made for other rules or another snpscore; about a minute."""
    from snpscore.pool import build_pool, stale
    if not stale(release):
        return
    print("salmo-snp: scoring the release's public sites for comparison (about a minute, once per release and rules)",
          flush=True)
    try:
        build_pool(release, threads=max(2, min(8, os.cpu_count() or 2)), memory_limit="4GB")
    except Exception as e:  # the portal works without it: the Overview then leaves out the public comparison
        print(f"salmo-snp: could not build the public pool ({type(e).__name__}): the Overview leaves out its comparison")


def download_genome(release, source):
    """The release's genome (bgzipped FASTA, .fai, .gzi) into HOME/genome: from <source>/raw/ when published there,
    else from the genome URL in the manifest; checked against the manifest's sha256 when it has them."""
    g = json.loads((release / "manifest.json").read_text()).get("genome") or {}
    name = g.get("file") or g.get("url", "").rsplit("/", 1)[-1]
    if not name:
        return
    sums = g.get("sha256") or {}
    print(f"genome -> {HOME / 'genome'}", flush=True)
    for ext in (".fai", ".gzi", ""):
        target = HOME / "genome" / (name + ext)
        try:
            get(f"{str(source).rstrip('/')}/raw", name + ext, target, sums.get(ext or "fa.gz"))
        except (OSError, ValueError):  # not mirrored there: the genome's own address
            get(g["url"].rsplit("/", 1)[0], name + ext, target, sums.get(ext or "fa.gz"))


def releases():
    return sorted(p.parent for p in (HOME / "releases").glob("*/manifest.json"))


def pick_release(release=None):
    if release:
        return Path(release)
    found = {p.name: p for p in releases()}
    return found.get(RELEASE) or (list(found.values())[-1] if found else None)


def local_genome(release):
    g = json.loads((release / "manifest.json").read_text()).get("genome") or {}
    name = g.get("file") or g.get("url", "").rsplit("/", 1)[-1]
    path = HOME / "genome" / name
    return path if name and all(Path(str(path) + ext).exists() for ext in ("", ".fai", ".gzi")) else None


def serve(release=None, port=8000):
    given, release = release, pick_release(release)
    if not release or not (release / "manifest.json").exists():
        sys.exit("salmo-snp: no release: run `salmo-snp download` first, or give --release <folder>")
    from snpscore.release import check
    problems = check(release)
    if problems:
        sys.exit(f"salmo-snp: {release} can't be used:\n  " + "\n  ".join(problems))
    genome = local_genome(release)
    ensure_pool(release)
    os.environ.update({
        "DJANGO_SETTINGS_MODULE": "snpsite.settings", "DJANGO_DEBUG": "0",
        "SNPSCORE_RELEASE": str(release.resolve()), "SNPPORTAL_RESULTS_DIR": str(HOME / "results"), "SNPPORTAL_LOCAL": "1",
        "SNPPORTAL_RELEASES_DIR": str(HOME / "releases"),  # the others installed, to switch to (I17)
        "SNPSCORE_GENOME_DIR": str(HOME / "genome")})  # each release's genome by its file name, so assemblies never mix
    # 127.0.0.1 only either way; a cloud session's preview pane may name the host otherwise (AGENTS.md "Cloud sessions")
    os.environ.setdefault("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost")
    (HOME / "results").mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("DJANGO_SECRET_KEY", secret())
    import django
    from django.core.management import call_command
    django.setup()
    print(f"salmo-snp: release {release.name}, results in {HOME / 'results'}")
    if not given and release.name != RELEASE:
        print(f"salmo-snp: this version expects release {RELEASE}, which isn't downloaded: using {release.name} until "
              f"you download {RELEASE}")
    if not genome:
        print("salmo-snp: no local genome, so sequence checks read it from salmobase (that sends genome positions near your "
              "SNPs there): `salmo-snp download` fetches it")
    print(f"salmo-snp: open http://127.0.0.1:{port}/snp/ (this computer only; Ctrl-C stops it)", flush=True)
    call_command("runserver", f"127.0.0.1:{port}", use_reloader=False, insecure_serving=True)  # static files too


def secret():
    """A secret key kept in the data folder, so the Design panel's cookie survives a restart."""
    path = HOME / "secret_key"
    if not path.exists():
        import secrets
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(secrets.token_urlsafe(50))
        path.chmod(0o600)
    return path.read_text().strip()


def size(path):
    return sum(p.stat().st_size for p in Path(path).rglob("*") if p.is_file()) if Path(path).exists() else 0


def info():
    from snpportal.lib.export import installed
    gb = lambda n: f"{n / 1e9:.2f} GB" if n >= 1e9 else f"{n / 1e6:.0f} MB"  # noqa: E731
    print("versions      " + ", ".join(f"{k} {v}" for k, v in installed().items()) + f", Python {sys.version.split()[0]}")
    print(f"data folder   {HOME}")
    for r in releases():
        print(f"release       {r.name} ({gb(size(r))})" + ("  <- this version's" if r.name == RELEASE else ""))
    if not releases():
        print(f"release       none: `salmo-snp download` fetches {RELEASE}")
    print(f"genome        {gb(size(HOME / 'genome')) if size(HOME / 'genome') else 'not downloaded'}")
    jobs = [p for p in (HOME / "results").glob("*") if (p / "job.json").exists()] if (HOME / "results").exists() else []
    print(f"results       {len(jobs)} scored lists ({gb(size(HOME / 'results'))}), kept until you delete them "
          "(Delete in the portal, or remove the folder)")
    saved = [p for p in (HOME / "projects").glob("*/project.json")] if (HOME / "projects").exists() else []
    print(f"projects      {len(saved)} saved design projects ({gb(size(HOME / 'projects'))})")


def main(argv=None):
    p = argparse.ArgumentParser(prog="salmo-snp", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("download", help="fetch a release and the genome, every file checked against its sha256")
    d.add_argument("version", nargs="?", help=f"release version (default {RELEASE}, this code's; 'latest' for the newest)")
    d.add_argument("--from", dest="source", help="the published data: a URL or a folder (default: SALMO_SNP_DATA_URL)")
    d.add_argument("--no-genome", action="store_true", help="skip the genome (~1 GB); sequence checks then read it remotely")
    s = sub.add_parser("serve", help="run the portal on http://127.0.0.1:<port>/snp/, for this computer only")
    s.add_argument("--release", help="a release folder (default: this code's release, else the newest downloaded)")
    s.add_argument("--port", type=int, default=8000)
    sub.add_parser("info", help="where the data and results are, and their sizes")
    args = p.parse_args(argv)
    if args.cmd == "download":
        download(args.version, args.source, not args.no_genome)
    elif args.cmd == "serve":
        serve(args.release, args.port)
    else:
        info()


if __name__ == "__main__":
    main()
