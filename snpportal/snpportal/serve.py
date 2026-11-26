"""The salmo-snp command: the portal on your own computer, so a SNP list never leaves it.

    salmo-snp download [VERSION] [--from URL|FOLDER]   the data: a release snapshot and the genome, each file checked
                       [--species rainbow_trout|all]   (a release is for one species; default: Atlantic salmon)
    salmo-snp serve [--release FOLDER] [--port N]      the portal on http://127.0.0.1:8000/snp/ (this computer only)
    salmo-snp info                                     where the data and your results are, and how big
    salmo-snp rules [--copy]                           the tier rules in use, checked; --copy: your own copy to edit

Everything lives in one data folder (SALMO_SNP_HOME, else the platform's: ~/Library/Application Support/salmo-snp,
~/.local/share/salmo-snp or %LOCALAPPDATA%\\salmo-snp): releases/<version>/, genome/, results/ (kept until you delete
them), secret_key and, if you made one, weights.yaml: your own tier rules, used instead of the shipped ones and left
alone by an update of the package (SNPSCORE_WEIGHTS names another file). The published data is a folder (snpdata
publish) on a web server, or a copy of it on a disk: releases/<version>/ with SHA256SUMS, releases/latest.json, and
raw/ with the genome."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import urllib.request
from pathlib import Path

RELEASE = "2026-11-25"  # the data release this version of the code expects (Atlantic salmon, the default species)
RELEASES = {"atlantic_salmon": RELEASE, "rainbow_trout": "trout-2026-11-25"}  # ... and per species: the species bar's
# where the data is published (salmobase, G 2026-11-24: releases/<version>/ and releases/latest.json); a copy elsewhere
# (a mirror, a share) with SALMO_SNP_DATA_URL or `salmo-snp download --from`
DATA_URL = os.environ.get("SALMO_SNP_DATA_URL") or "https://salmobase.org/datafiles/datasets/salmo-snp"


def published(datafiles):
    """The releases folder inside a server's own copy of what DATA_URL serves: <datafiles>/datasets/salmo-snp/releases
    for salmobase's datafiles folder (the salmobase server reads its releases there, in place: settings.py), or None
    when DATA_URL is not an address under salmobase's datafiles."""
    from snpscore.bbi import SALMOBASE
    return Path(datafiles, DATA_URL[len(SALMOBASE):], "releases") if datafiles and DATA_URL.startswith(SALMOBASE) else None


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


def held(but):
    """{sha256: file} of what the other installed releases hold, by their SHA256SUMS: most layers do not change from
    one release to the next, and such a file is copied from the release that has it instead of downloaded."""
    out = {}
    for sums in sorted((HOME / "releases").glob("*/SHA256SUMS")):
        if sums.parent != but:
            for digest, name in (line.split(None, 1) for line in sums.read_text().splitlines() if line.strip()):
                out[digest] = sums.parent / name.strip().lstrip("*")
    return out


def get(source, name, target, digest, same=None):
    """Fetch one file unless `target` already has `digest`; refuse it when it doesn't match. `same`: a file here that
    should have that digest (held): copied if it does, which the caller is told (True)."""
    if target.exists() and (digest is None or sha256(target) == digest):
        return
    if same and same.is_file() and sha256(same) == digest:
        copy(same.parent, same.name, target)
        return True
    print(f"  {name}", flush=True)
    copy(source, name, target)
    if digest and sha256(target) != digest:
        target.unlink()
        sys.exit(f"salmo-snp: {name} does not match its sha256: try again, or tell the data's publisher")


def download(version=None, source=None, genome=True):
    """Release `version` (default: RELEASE; 'latest' reads releases/latest.json) from `source` (a published data folder:
    URL or path; default DATA_URL) into HOME/releases/<version>, and the genome into HOME/genome. Files already there
    with the right sha256 are kept, and a file another installed release holds with that sha256 is copied from it
    (an update fetches only what changed). Returns the release folder."""
    source = source or DATA_URL
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
    here, copied = held(folder), 0
    for digest, name in (line.split(None, 1) for line in sums.splitlines() if line.strip()):
        name = name.strip().lstrip("*")
        target = (folder / name).resolve()
        if folder.resolve() not in target.parents:
            sys.exit(f"salmo-snp: unexpected file name in SHA256SUMS: {name}")
        copied += bool(get(base, name, target, digest, here.get(digest)))
    if copied:
        print(f"  {copied} files are unchanged since a release installed here: copied from it, not downloaded")
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
    candidates), built when it is missing or was made for other rules or another snpscore; a minute or two."""
    from snpscore.pool import build_pool, stale
    if not stale(release):
        return
    print("salmo-snp: scoring the release's public sites for comparison (a minute or two, once per release and rules)",
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


def installed(version):
    """True when release `version` is in the data folder, passes its check, and has its genome (or none is named)."""
    from snpscore.release import check
    folder = HOME / "releases" / version
    return (folder / "manifest.json").exists() and not check(folder) and bool(
        local_genome(folder) or not json.loads((folder / "manifest.json").read_text()).get("genome"))


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


def serve(release=None, port=8000, host="127.0.0.1"):
    """The portal on http://<host>:<port>/snp/: 127.0.0.1, this computer only. A container (deploy/server.sh local)
    listens on 0.0.0.0 inside it and is published on the host's 127.0.0.1 only."""
    given, release = release, pick_release(release)
    if not release or not (release / "manifest.json").exists():
        sys.exit("salmo-snp: no release: run `salmo-snp download` first, or give --release <folder>")
    from snpscore.release import check
    problems = check(release)
    if problems:
        sys.exit(f"salmo-snp: {release} can't be used:\n  " + "\n  ".join(problems))
    genome = local_genome(release)
    check_rules()  # the rules new lists (and the pool) are scored with: a mistake in an edited copy is said now, by its key
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
    from snpportal import jobs
    by_species = jobs.species_releases()  # the default release, and the newest one of each other species downloaded
    for folder in by_species.values():
        ensure_pool(folder)
    print(f"salmo-snp: release {release.name}, results in {HOME / 'results'}")
    from snpscore import score
    if not score.describe_rules()["shipped"]:
        print(f"salmo-snp: your own tier rules, {score.rules_file()}")
    if len(by_species) > 1:
        print("salmo-snp: species " + ", ".join(f"{jobs.species(f)['name']} ({f.name})" for f in by_species.values())
              + ": the species bar at the top right switches")
    if not given and release.name != RELEASE:
        print(f"salmo-snp: this version expects release {RELEASE}, which isn't downloaded: using {release.name} until "
              f"you download {RELEASE}")
    if not genome:
        print("salmo-snp: no local genome, so sequence checks read it from salmobase (that sends genome positions near your "
              "SNPs there): `salmo-snp download` fetches it")
    print(f"salmo-snp: open http://127.0.0.1:{port}/snp/ (this computer only; Ctrl-C stops it)", flush=True)
    call_command("runserver", f"{host}:{port}", use_reloader=False, insecure_serving=True)  # static files too


def secret():
    """A secret key kept in the data folder, so the Design panel's cookie survives a restart."""
    path = HOME / "secret_key"
    if not path.exists():
        import secrets
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(secrets.token_urlsafe(50))
        path.chmod(0o600)
    return path.read_text().strip()


def own_rules():
    """Your own tier rules: weights.yaml in the data folder (`salmo-snp rules --copy` makes it), else None."""
    path = HOME / "weights.yaml"
    return path if path.exists() else None


def rules(copy=False):
    """Say which tier rules are in use and check them; with copy, first copy the shipped ones into the data folder,
    where an update of the package leaves them alone, to edit."""
    from snpscore import score
    if copy:
        target = HOME / "weights.yaml"
        if target.exists():
            sys.exit(f"salmo-snp: {target} is there already: edit it, or delete it to use the shipped rules again")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(score.WEIGHTS, target)
        os.environ.setdefault("SNPSCORE_WEIGHTS", str(target))
        print(f"salmo-snp: copied the shipped tier rules to {target}. Edit it and restart `salmo-snp serve`: new lists "
              "are scored with it, results already made keep their own rules, and the public pool is scored again. "
              "Delete it to use the shipped rules again.")
    check_rules()
    print(rules_line() + ": ok")


def check_rules():
    """Stop with the mistakes in the tier rules in use, as the portal checks them at start: snpscore's blocks
    (score.check_weights) and the portal's (design, priors)."""
    from snpscore import score
    from snpportal.lib.export import check_rules as portal_problems
    try:
        w = score.load_weights(check=False)  # a YAML mistake, or an own file that is gone, stops here
    except score.RulesError as e:
        sys.exit(f"salmo-snp: {e}")
    problems = score.check_weights(w) + portal_problems(w) if w is not None else []  # every mistake at once
    if problems:
        sys.exit(f"salmo-snp: The tier rules in {score.rules_file()} can't be used:\n  " + "\n  ".join(problems))


def rules_line():
    from snpscore import score
    d = score.describe_rules()
    return (f"tier rules    {d['file']} ({'shipped with snpscore' if d['shipped'] else 'your own'}; "
            f"sha256 {d['sha256'][:12]})")


def size(path):
    return sum(p.stat().st_size for p in Path(path).rglob("*") if p.is_file()) if Path(path).exists() else 0


def info():
    from snpportal.lib.export import installed
    gb = lambda n: f"{n / 1e9:.2f} GB" if n >= 1e9 else f"{n / 1e6:.0f} MB"  # noqa: E731
    print("versions      " + ", ".join(f"{k} {v}" for k, v in installed().items()) + f", Python {sys.version.split()[0]}")
    print(f"data folder   {HOME}")
    print(rules_line())
    for r in releases():
        m = json.loads((r / "manifest.json").read_text())
        what = f"{(m.get('species') or {}).get('name', 'Atlantic salmon')}, {m.get('assembly', '?')}"
        print(f"release       {r.name} ({what}; {gb(size(r))})" + ("  <- this version's" if r.name in RELEASES.values() else ""))
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
    d.add_argument("--from", dest="source", help=f"the published data: a URL or a folder (default: {DATA_URL})")
    d.add_argument("--species", choices=[*RELEASES, "all"], help="this version's release of a species (default: "
                   "atlantic_salmon), or of every species; the portal's species bar switches between those downloaded")
    d.add_argument("--no-genome", action="store_true", help="skip the genome (~1 GB); sequence checks then read it remotely")
    d.add_argument("--if-missing", action="store_true", help="only a release that is not here, or fails its check (the "
                   "Docker image's first start; a later one then needs no network)")
    s = sub.add_parser("serve", help="run the portal on http://127.0.0.1:<port>/snp/, for this computer only")
    s.add_argument("--release", help="a release folder (default: this code's release, else the newest downloaded)")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--host", default="127.0.0.1", help=argparse.SUPPRESS)  # 0.0.0.0 inside a container only
    sub.add_parser("info", help="where the data and results are, and their sizes")
    r = sub.add_parser("rules", help="the tier rules in use (shipped, or your own weights.yaml in the data folder), checked")
    r.add_argument("--copy", action="store_true", help="copy the shipped rules into the data folder, to edit")
    args = p.parse_args(argv)
    if own_rules() and not os.environ.get("SNPSCORE_WEIGHTS"):  # your own rules, which an update leaves alone
        os.environ["SNPSCORE_WEIGHTS"] = str(own_rules())
    if args.cmd == "download":
        versions = [args.version] if args.version or not args.species else (
            list(RELEASES.values()) if args.species == "all" else [RELEASES[args.species]])
        for version in versions:
            if args.if_missing and installed(version or RELEASE):
                print(f"release {version or RELEASE}: here, checked")
                continue
            download(version, args.source, not args.no_genome)
    elif args.cmd == "serve":
        serve(args.release, args.port, args.host)
    elif args.cmd == "rules":
        rules(args.copy)
    else:
        info()


if __name__ == "__main__":
    main()
