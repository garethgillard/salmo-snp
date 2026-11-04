"""Saved design projects (ROADMAP I7; local installs only): a project is a named folder of panel versions in the data
folder (projects/<name>/), so a Design panel can be kept, compared with an earlier version, shared as a zip and opened
again. A version (v<N>/) holds the panel's SNPs as they were (panel.parquet: every kept SNP with its annotations, tiers
for all conditions and the source it came from), its chip (chip.parquet, chip.json) and meta.json; it never changes.
No database: JSON and Parquet files, as job folders. On a server there are no projects: they would be shared by
everyone who can open the site."""
from __future__ import annotations

import hashlib
import io
import re
import shutil
import uuid
import zipfile
from pathlib import Path

from django.http import FileResponse, Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from snpscore.formats import lit

from . import jobs, panel
from .lib import export as snp_export
from .views import private

DERIVED = ("file_row_number", "snp_key", "dropped", "sources", "on_chip", "dist_to_chip", "near_chip", "novel_functional")
LIST = ("tier", "id", "chrom", "pos", "ref", "alt", "gene_name", "region_class", "assay_status", "panel_source")


def snpscore_weights():
    import snpscore
    return snpscore.score.WEIGHTS


def root():
    """The projects folder: SNPPORTAL_PROJECTS_DIR, else projects/ next to the results folder (the data folder's)."""
    return Path(jobs.setting("SNPPORTAL_PROJECTS_DIR", jobs.results_dir().parent / "projects"))


def slug(name):
    """A project's folder name: letters, digits, '-', '_' and '.', at most 60 characters ('' when nothing is left)."""
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", str(name).strip()).strip("-.")[:60]


def project(name):
    """The folder of an existing project, else 404 (also for names that are not a plain folder name)."""
    d = root() / slug(name)
    if not jobs.local() or not slug(name) or slug(name) != name or not (d / "project.json").is_file():
        raise Http404("No such project")
    return d


def versions(d):
    """meta.json of every version of a project folder, oldest first."""
    found = [jobs.read_json(v / "meta.json") for v in d.glob("v*") if (v / "meta.json").is_file()]
    return sorted(found, key=lambda m: m["version"])


def everything():
    """[{name, slug, versions}] of every project, the most recently saved first."""
    if not root().is_dir():
        return []
    out = [{**jobs.read_json(d / "project.json"), "slug": d.name, "versions": versions(d)}
           for d in root().iterdir() if (d / "project.json").is_file()]
    return sorted(out, key=lambda p: max((v["created_utc"] for v in p["versions"]), default=""), reverse=True)


def save(panel_dir, name, note=""):
    """Save the Design panel in `panel_dir` as the next version of project `name` (made if new). Returns (slug, N)."""
    folder = slug(name)
    if not folder:
        raise ValueError("Give the project a name (letters and digits).")
    con, rel = panel._open(panel_dir)
    if rel is None:
        raise ValueError("The Design panel is empty.")
    s = jobs.read_json(panel_dir / "panel.json")
    columns = [c for c, in con.execute("SELECT column_name FROM (DESCRIBE p)").fetchall()]
    keys = [k for k, in con.execute("SELECT snp_key FROM p ORDER BY snp_key").fetchall()]
    drop = [c for c in DERIVED if c in columns]
    tmp = panel_dir / f".version-{uuid.uuid4().hex}.parquet"  # the connection may write only the panel folder
    con.execute(f"COPY (SELECT * EXCLUDE ({', '.join(drop)}) FROM p ORDER BY file_row_number) TO {lit(tmp)} (FORMAT parquet)")
    con.close()
    d = root() / folder
    d.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not (d / "project.json").exists():
        jobs._write_json(d / "project.json", {"name": str(name).strip()[:80], "created_utc": jobs.utc()})
    n = max([m["version"] for m in versions(d)], default=0) + 1
    v = d / f"v{n}"
    v.mkdir(mode=0o700)
    shutil.move(tmp, v / "panel.parquet")
    chip = jobs.read_json(panel_dir / "chip.json") if (panel_dir / "chip.parquet").exists() else {}
    for f in ("chip.parquet", "chip.json"):
        if chip and (panel_dir / f).exists():
            shutil.copyfile(panel_dir / f, v / f)
    copy_populations(panel_dir, v)
    jobs._write_json(v / "meta.json", {
        "version": n, "created_utc": jobs.utc(), "note": str(note).strip()[:500], "n": len(keys),
        "hash": hashlib.sha256("\n".join(keys).encode()).hexdigest()[:16],
        "sources": [x.get("label") for x in s.get("sources", [])], "chip": chip.get("label"),
        "release": jobs.manifest().get("version"), "weights_sha256": jobs._file("sha256", snpscore_weights())})
    return folder, n


def copy_populations(src, dst):
    """The user's populations (I9: per-SNP counts only) from one panel or version folder to another."""
    if (src / "populations.json").exists():
        shutil.copyfile(src / "populations.json", dst / "populations.json")
        (dst / "populations").mkdir(mode=0o700, exist_ok=True)
        for f in (src / "populations").glob("*.parquet"):
            shutil.copyfile(f, dst / "populations" / f.name)


def open_in_panel(d, n):
    """A new Design panel holding version n of project folder d (one source, its chip): returns the panel folder."""
    v = d / f"v{n}"
    meta, name = jobs.read_json(v / "meta.json"), jobs.read_json(d / "project.json").get("name", d.name)
    out = panel._new()
    con = jobs.connect([v, out], out)
    con.execute(f"COPY (SELECT * REPLACE (1 AS panel_source) FROM read_parquet({lit(v / 'panel.parquet')})) "
                f"TO {lit(out / 'source_1.parquet')} (FORMAT parquet)")
    con.close()
    for f in ("chip.parquet", "chip.json"):
        if (v / f).exists():
            shutil.copyfile(v / f, out / f)
    copy_populations(v, out)
    jobs._write_json(out / "panel.json", {"sources": [{"id": 1, "project": d.name, "version": n, "label": f"{name}, version {n}",
                                                       "n": meta["n"], "selection": "", "filters": [meta.get("note") or "saved panel"],
                                                       "synthetic": False, "added_utc": jobs.utc()}],
                                          "next": 2, "created_utc": jobs.utc()})
    return out


def diff(d, a, b):
    """(added, removed): the SNPs in version b and not in a, and in a and not in b, as display rows."""
    pa, pb = d / f"v{a}" / "panel.parquet", d / f"v{b}" / "panel.parquet"
    con = jobs.connect([d])
    cols = [c for c, in con.execute(f"SELECT column_name FROM (DESCRIBE SELECT * FROM read_parquet({lit(pb)}))").fetchall()]
    shown = [c for c in LIST if c in cols]
    key = "concat_ws(':', chrom, pos, coalesce(ref, ''), coalesce(alt, ''))" if {"ref", "alt"} <= set(cols) else "concat_ws(':', chrom, pos)"

    def only(x, y):
        rows = con.execute(f"SELECT {', '.join(jobs.ident(c) for c in shown)} FROM read_parquet({lit(x)}) WHERE {key} NOT IN "
                           f"(SELECT {key} FROM read_parquet({lit(y)})) ORDER BY TRY_CAST(chrom AS INTEGER), pos").fetchall()
        return [dict(zip(shown, r)) for r in rows]
    out = only(pb, pa), only(pa, pb)
    con.close()
    return out


# ---- pages ----

def _need_local(request):
    return None if jobs.local() else render(request, "snpportal/stub.html", {
        "nav": "panel", "title": "Projects", "message": "Saved projects are kept only by a copy of the portal on your own "
                                                       "computer (Run locally), where nobody else can open them."}, status=404)


@private
def page(request):
    """/snp/projects/: every project with its versions, a diff between two, export, and an import form."""
    stop = _need_local(request)
    if stop:
        return stop
    ctx = {"nav": "panel", "title": "Projects", "projects": everything(), "error": request.GET.get("error"),
           "formats": ("tsv", "kasp", "illumina", "axiom")}
    a, b, name = request.GET.get("a"), request.GET.get("b"), request.GET.get("project")
    if name and a and b and a.isdigit() and b.isdigit():
        d = project(name)
        if not all((d / f"v{x}" / "panel.parquet").exists() for x in (a, b)):
            raise Http404("No such version")
        added, removed = diff(d, int(a), int(b))
        ctx["diff"] = {"project": jobs.read_json(d / "project.json").get("name", name), "a": int(a), "b": int(b),
                       "n_added": len(added), "n_removed": len(removed),
                       "tables": [(f"Added in version {b}", added[:500], len(added)),
                                  (f"Removed since version {a}", removed[:500], len(removed))]}
    return render(request, "snpportal/projects.html", ctx)


@private
@require_POST
def save_view(request):
    """POST from the Design panel: save it as the next version of the named project."""
    stop = _need_local(request)
    if stop:
        return stop
    d = panel._folder(request)
    if d is None:
        return redirect(reverse("snpportal:design_panel"))
    try:
        name, n = save(d, request.POST.get("name", ""), request.POST.get("note", ""))
    except ValueError as e:
        return redirect(f"{reverse('snpportal:design_panel')}?error={e}")
    return redirect(f"{reverse('snpportal:projects')}?saved={name}-v{n}#{name}")


@private
@require_POST
def open_view(request, name, n):
    """POST: version n of a project becomes this browser's Design panel (the current one is left as it is)."""
    d = project(name)
    if not (d / f"v{n}" / "meta.json").exists():
        raise Http404("No such version")
    return panel._cookie(redirect(reverse("snpportal:design_panel")), open_in_panel(d, n))


@private
def download(request, name, n):
    """A version's SNPs: ?format=tsv (default) or a vendor file (kasp, illumina, axiom), with provenance."""
    d = project(name)
    v = d / f"v{n}"
    if not (v / "panel.parquet").exists():
        raise Http404("No such version")
    fmt = request.GET.get("format", "tsv")
    if fmt not in ("tsv", "kasp", "illumina", "axiom"):
        raise Http404("Unknown format")
    out = v / f".download-{uuid.uuid4().hex}"
    meta = {"tool": "salmo-snp project", "filters": {"project": name, "version": n}, "panel": jobs.read_json(v / "meta.json")["hash"]}
    snp_export.export(v / "panel.parquet", fmt, out, jobs.release(), "all", meta)
    for sidecar in v.glob(f"{out.name}.*"):  # vendor files' provenance and lookup sidecars: the zip bundle has those
        sidecar.unlink()
    f = open(out, "rb")
    out.unlink()  # the open file stays readable; nothing is left behind (Windows keeps it until closed)
    return FileResponse(f, as_attachment=True, filename=snp_export.filename(fmt, jobs.manifest().get("version", "release"), "all", f"{name}_v{n}"))


@private
def export_zip(request, name):
    """The whole project as a zip, to share or to keep elsewhere; Import brings it back."""
    d = project(name)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(d.rglob("*")):
            if f.is_file() and not f.name.startswith("."):
                z.write(f, f"{d.name}/{f.relative_to(d).as_posix()}")
    buf.seek(0)
    return FileResponse(buf, as_attachment=True, filename=f"{d.name}.salmo-snp-project.zip")


@private
@require_POST
def import_zip(request):
    """POST a project zip (from Export): it becomes a new project (named '<name>-2' when the name is taken). Only the
    files a project holds are read: project.json and v<N>/{meta.json, panel.parquet, chip.parquet, chip.json}."""
    stop = _need_local(request)
    if stop:
        return stop
    upload = request.FILES.get("project")
    if not upload:
        return redirect(f"{reverse('snpportal:projects')}?error=Choose a project zip to import.")
    allowed = re.compile(r"^[^/]+/(project\.json|v\d+/(meta\.json|panel\.parquet|chip\.parquet|chip\.json|populations\.json"
                         r"|populations/[a-z0-9_]+\.parquet))$")
    try:
        with zipfile.ZipFile(upload) as z:
            names = [i for i in z.infolist() if allowed.match(i.filename)]
            heads = {i.filename.split("/")[0] for i in names}
            if len(heads) != 1 or not any(i.filename.endswith("/project.json") for i in names):
                raise ValueError
            base = slug(heads.pop()) or "project"
            folder, k = base, 1
            while (root() / folder).exists():
                k += 1
                folder = f"{base}-{k}"
            d = root() / folder
            for i in names:
                target = d / i.filename.split("/", 1)[1]
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                target.write_bytes(z.read(i))
    except (zipfile.BadZipFile, ValueError, KeyError):
        return redirect(f"{reverse('snpportal:projects')}?error=That file is not a project exported from the portal.")
    return redirect(f"{reverse('snpportal:projects')}#{folder}")
