"""Design panel (/snp/panel/): a curated SNP panel built from Table selections of any results ('Add to panel' on the
Table copies its whole selection: the cart), compared with an existing chip (the usual case: SNPs to add to it),
checked and exported as vendor files.

It belongs to one browser: its folder (results/panel-<uuid>) is named by an HttpOnly cookie, never by a URL, and
jobs.cleanup removes it 24 hours after it was started (its 'created' marker). To keep it longer, download its TSV
and score that list again later. Its SNPs carry their tiers for all 21 conditions, so SNPs from lists scored for
other conditions compare."""
from __future__ import annotations

import os
import shutil
import tempfile
import time
import uuid
from urllib.parse import urlencode

import duckdb
import snpscore
from django.http import FileResponse, Http404, HttpResponse, HttpResponseNotAllowed
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.datastructures import MultiValueDict
from django.utils.safestring import mark_safe
from django.views.decorators.csrf import csrf_exempt, csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from snpscore import export as snp_export
from snpscore import panel as snp_panel
from snpscore.formats import lit

from . import figures, jobs, results, tools
from .views import UploadToResults, accepted_suffix, finished, private

COOKIE = "snpportal_panel"
BIN = 250_000  # the figure's marks: one per 250 kb, coloured by the best tier in it
SHOWN, LISTED = 50, 2000  # SNPs listed, then with 'Show all'
SCOPES = {"all": "all panel SNPs", "new": "SNPs not on the chip"}


# ---- the panel folder: this browser's only ----

def _keep():
    return 3600 * float(jobs.setting("SNPPORTAL_KEEP_HOURS", 24))


def _folder(request):
    """This browser's panel folder, or None (no cookie, or a panel that is gone or expired)."""
    try:
        d = jobs.results_dir() / f"panel-{uuid.UUID(request.COOKIES.get(COOKIE, ''))}"
    except ValueError:
        return None
    try:
        fresh = time.time() - (d / "created").stat().st_mtime < _keep()
    except FileNotFoundError:
        return None
    return d if fresh and (d / "panel.json").exists() else None


def _new():
    d = jobs.results_dir() / f"panel-{uuid.uuid4()}"
    d.mkdir(mode=0o700)
    (d / "created").touch(mode=0o600)  # never changes: cleanup counts the 24 hours from it
    jobs._write_json(d / "panel.json", {"sources": [], "next": 1, "created_utc": jobs.utc()})
    return d


def _cookie(response, d):
    left = max(0, int(_keep() - (time.time() - (d / "created").stat().st_mtime)))
    response.set_cookie(COOKIE, d.name[len("panel-"):], max_age=left, httponly=True, samesite="Lax")
    return response


def count(request):
    """The nav's 'Design panel' badge: the panel's SNP count (empty without a panel)."""
    d = _folder(request)
    s = jobs.read_json(d / "panel.json") if d else {}
    n = sum(x["n"] for x in s.get("sources", [])) - len(s.get("dropped", []))  # sources overlap: an upper bound
    return HttpResponse(f" ({n:,})" if n else "", content_type="text/plain")


def holds(request, snp):
    """For a SNP's card: None without a panel, else {sources: ['S1', ...] that hold it (same chrom, pos and alleles),
    chip: where the panel's chip has its nearest marker, in words (None without a chip)}."""
    d = _folder(request)
    if d is None:
        return None
    s, files = jobs.read_json(d / "panel.json"), sorted(d.glob("source_*.parquet"))
    con = jobs.connect([d])
    found = []
    if files:
        src = f"read_parquet([{', '.join(lit(f) for f in files)}], union_by_name=true)"
        alleles = [c for c in ("ref", "alt") if c in snp and c in {r[0] for r in con.execute(f"DESCRIBE SELECT * FROM {src}").fetchall()}]
        same = " AND ".join(["chrom = ?", "pos = ?"] + [f"coalesce({c}, '') = ?" for c in alleles])
        found = [x for x, in con.execute(f"SELECT DISTINCT panel_source FROM {src} WHERE {same}",
                                         [snp["chrom"], snp["pos"]] + [snp.get(c) or "" for c in alleles]).fetchall()]
    names = {x["id"]: f"S{i + 1}" for i, x in enumerate(s.get("sources", []))}
    out = {"sources": [names.get(x, "?") for x in sorted(found)], "chip": None}
    if (d / "chip.parquet").exists():
        label = (jobs.read_json(d / "chip.json").get("label") or "your chip").lower()
        dist = con.execute(f"SELECT min(abs(pos - ?)) FROM read_parquet({lit(d / 'chip.parquet')}) WHERE chrom = ?",
                           [snp["pos"], snp["chrom"]]).fetchone()[0]
        out["chip"] = (f"On {label}." if dist == 0 else f"The nearest marker of {label} is {tools._bp(dist)} away." if dist is not None
                       else f"No marker of {label} on this chromosome.")
    con.close()
    return out


# ---- adding a Table selection ----

@private
def add(request, key):
    """POST from the Table: copy the whole selection of results `key` (its rows, with their tiers for all
    conditions) into this browser's panel, starting one if needed, and go back to the Table."""
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    job = finished(key)
    jd = jobs.folder(key)
    query = results.selection(jd)
    req = results.selection_request(query)
    back = f"{reverse('snpportal:results', args=[key])}?{query + '&' if query else ''}tab=table"
    con, types, where, _ = results.open_result(req, key, write=True)
    n = con.execute(f"SELECT count(*) FROM v {where}").fetchone()[0]
    cap = int(jobs.setting("SNPPORTAL_MAX_PANEL_SNPS", 50_000))
    if not n or n > cap:
        return redirect(f"{back}&panel_error={'empty' if not n else 'many'}")
    rows = jd / f".panel-rows-{uuid.uuid4().hex}.parquet"
    con.execute(f"COPY (SELECT file_row_number FROM v {where}) TO '{rows}' (FORMAT parquet)")
    con.close()
    d = _folder(request) or _new()
    s = jobs.read_json(d / "panel.json")
    i = s["next"]
    try:
        _copy(jd, rows, d / f"source_{i}.parquet", i)
    finally:
        rows.unlink(missing_ok=True)
    s["sources"].append({"id": i, "job": str(key), "label": job.get("label") or "Results", "n": n, "selection": query,
                         "filters": [label for _, label, _ in results.filters(req, types, jobs.weights(jd))],
                         "synthetic": bool(job.get("synthetic_input") or job.get("synthetic_layers")), "added_utc": jobs.utc()})
    s["next"] = i + 1
    jobs._write_json(d / "panel.json", s)
    return _cookie(redirect(f"{back}&added={n}"), d)


def _copy(jd, rows, out, source):
    """source_<n>.parquet: the selected result rows with their tiers for all conditions (tier__all), the source id and
    the row in its results."""
    con = jobs.connect([jd, out.parent], out.parent)
    result, tiers = jd / "result.parquet", jd / "tiers.parquet"
    columns = [c for c, in con.execute(f"SELECT column_name FROM (DESCRIBE SELECT * FROM read_parquet('{result}'))").fetchall()]
    stored = [c for c, in con.execute(f"SELECT column_name FROM (DESCRIBE SELECT * FROM read_parquet('{tiers}'))").fetchall()] \
        if tiers.exists() else []
    picked = [c for c in jobs.TIER_COLUMNS if f"{c}__all" in stored]
    drop = ["file_row_number"] + [c for c in jobs.TIER_COLUMNS if c in columns and c in picked]
    tier_sql = "".join(f", t.{jobs.ident(c + '__all')} AS {c}" for c in picked)
    join = f"JOIN read_parquet('{tiers}') t USING (file_row_number)" if picked else ""
    tmp = out.with_name(f".{out.name}.{uuid.uuid4().hex}")
    con.execute(f"COPY (SELECT r.* EXCLUDE ({', '.join(drop)}){tier_sql}, {int(source)} AS panel_source, "
                f"r.file_row_number AS source_row FROM read_parquet('{result}', file_row_number=true) r "
                f"JOIN read_parquet('{rows}') s USING (file_row_number) {join}) TO '{tmp}' (FORMAT parquet)")
    con.close()
    tmp.chmod(0o600)
    os.replace(tmp, out)


# ---- the panel's SNPs ----

def _open(d):
    """(connection reading the panel folder and the release, writing only the folder; view p, or None when empty):
    p has one row per SNP kept in the panel (the first source's), `sources` (the source ids that hold it), snp_key
    (chrom:pos:ref:alt) and file_row_number in genome order; with a chip, also on_chip, dist_to_chip, near_chip and
    novel_functional (snp_panel.compare_sql). View pa also holds the SNPs dropped by hand (dropped: true), for the
    list to show them; downloads, the chip comparison and every count read p."""
    con = jobs.connect([d, jobs.release()], d)
    files = sorted(d.glob("source_*.parquet"))
    if not files:
        return con, None
    con.execute("CREATE VIEW u AS SELECT * FROM read_parquet([" + ", ".join(f"'{f}'" for f in files) + "], union_by_name=true)")
    columns = [c for c, in con.execute("SELECT column_name FROM (DESCRIBE u)").fetchall()]
    same = ", ".join(["chrom", "pos"] + [f"coalesce({c}, '')" for c in ("ref", "alt") if c in columns])
    key = "concat_ws(':', " + ", ".join(["chrom", "pos"] + [f"coalesce({c}, '')" for c in ("ref", "alt") if c in columns]) + ")"
    dropped = [lit(k) for k in jobs.read_json(d / "panel.json").get("dropped", [])]
    con.execute(f"""CREATE VIEW pa0 AS SELECT * EXCLUDE (_n), row_number() OVER (ORDER BY TRY_CAST(chrom AS INTEGER), chrom, pos) - 1
                    AS file_row_number, {key} AS snp_key, list_contains({'[' + ', '.join(dropped) + ']' if dropped else '[]::VARCHAR[]'}, {key})
                    AS dropped FROM (SELECT *, row_number() OVER (PARTITION BY {same} ORDER BY panel_source, source_row) AS _n,
                    list(DISTINCT panel_source) OVER (PARTITION BY {same}) AS sources FROM u) WHERE _n = 1""")
    con.execute("CREATE VIEW p0 AS SELECT * FROM pa0 WHERE NOT dropped")
    chip = d / "chip.parquet"
    if chip.exists():
        window = snp_panel.settings(jobs.weights())["chip_window"]
        con.execute(f"CREATE VIEW pa AS {snp_panel.compare_sql('pa0', f'read_parquet({chr(39)}{chip}{chr(39)})', window)}")
    else:
        con.execute("CREATE VIEW pa AS SELECT * FROM pa0")
    con.execute("CREATE VIEW p AS SELECT * FROM pa WHERE NOT dropped")
    con.execute("CREATE VIEW v AS SELECT * FROM p")  # tools.assay_readiness reads v
    return con, "p"


def _figure(con, d, chip, res, synthetic):
    """The panel along the genome (a mark per 250 kb, coloured by the best tier), with the chip's markers per Mb
    above it and its gaps highlighted when there is a chip."""
    rows = con.execute(f"SELECT chrom, pos // {BIN} * {BIN}, min(tier), count(*) FROM p GROUP BY ALL ORDER BY ALL").fetchall()
    marks = [(c, b, b + BIN, tools._tier_fill(t), f"{c}:{b / 1e6:.2f}–{(b + BIN) / 1e6:.2f} Mb: {n:,} SNPs (best tier {t})")
             for c, b, t, n in rows]
    counts = dict(con.execute("SELECT chrom, count(*) FROM p GROUP BY 1").fetchall())
    density, gaps = None, []
    legend = [(tools._tier_fill(t), figures.TIER_NAMES[t]) for t in (1, 2, 3, 4)]
    if chip:
        top = max([n for _, _, n in chip["density"]] + [1])
        density = [(c, mb * 1_000_000, (mb + 1) * 1_000_000, n / top, f"{c}:{mb}–{mb + 1} Mb: {n:,} chip markers")
                   for c, mb, n in chip["density"]]
        gaps = [(g["chrom"], g["start"], g["end"], f"Chip gap {g['chrom']}:{g['start']:,}–{g['end']:,} ({tools._bp(g['size'])})")
                for g in res["gaps"]]
        legend += [(figures.mix(figures.palette.GREY[200], figures.palette.GREY[700], 0.6), "chip markers per Mb"),
                   tools._gap_legend(f"chip gap > {res['summary']['gap_bp'] / 1e6:g} Mb")]
    ends = con.execute("SELECT chrom, max(pos) FROM p GROUP BY 1").fetchall()
    return tools.coverage(tools._chroms(d, ends) if (d / "manifest.json").exists() else _chroms(ends), marks,
                          "Panel SNPs along the genome", "Panel SNPs per 250 kb, coloured by tier (all conditions)"
                          + ("; the chip's markers per Mb above, chip gaps highlighted" if chip else ""),
                          synthetic, gaps, density, counts, legend)


def _chroms(ends):
    """[(chrom, length)] from the release's chromosome sizes, with the panel's chromosomes in any case."""
    sizes = {k: int(v) for k, v in (jobs.manifest().get("chrom_sizes") or {}).items()}
    for c, end in ends:
        sizes[c] = max(sizes.get(c, 0), int(end))
    return [(c, sizes[c]) for c in sorted(sizes, key=results._chrom_key)]


# ---- the page ----

@private
def page(request):
    """/snp/panel/: the sources, the panel at a glance, the chip comparison, the assay check, the SNP list and the
    downloads; an empty panel says how to fill it."""
    d = _folder(request)
    ctx = {"nav": "panel", "title": "Design panel", "error": request.GET.get("error")}
    if d is None:
        return render(request, "snpportal/panel.html", ctx)
    s = jobs.read_json(d / "panel.json")
    con, rel = _open(d)
    chip = jobs.read_json(d / "chip.json") if (d / "chip.parquet").exists() else {}
    synthetic = any(x.get("synthetic") for x in s["sources"]) or bool(chip.get("synthetic"))
    ctx.update(sources=[{**x, "url": f"{reverse('snpportal:results', args=[x['job']])}?{x['selection'] + '&' if x['selection'] else ''}tab=table"}
                        for x in s["sources"]],
               meta=f"Deleted after {jobs.utc((d / 'created').stat().st_mtime + _keep())} · only this browser can open it",
               chip=chip, chip_demo=(jobs.release() / "demo" / "chip_demo_SYNTHETIC.tsv").is_file(),
               chip_error=tools.CHIP_ERRORS.get(request.GET.get("chip_error"), "").format(cap=f"{tools.chip_cap():,}") or None)
    if rel is None:
        return render(request, "snpportal/panel.html", ctx)
    types = dict(con.execute("SELECT column_name, column_type FROM (DESCRIBE p)").fetchall())
    n = con.execute("SELECT count(*) FROM p").fetchone()[0]
    several = con.execute("SELECT count(*) FROM p WHERE len(sources) > 1").fetchone()[0]
    tiers = dict(con.execute("SELECT tier, count(*) FROM p GROUP BY 1").fetchall()) if "tier" in types else {}
    res = None
    if chip:
        pool = jobs.release() / "pool" / "pool.parquet"
        res = snp_panel.compare(con, d / "chip.parquet", "all", weights=jobs.weights(), table="p0", pool=pool if pool.exists() else None,
                                chrom_sizes=jobs.manifest().get("chrom_sizes"))
        cs = res["summary"]
        on = con.execute("SELECT count(*) FILTER (WHERE on_chip), count(*) FILTER (WHERE NOT on_chip) FROM p").fetchone()
        ctx["compare"] = [(f"{cs['chip_snps']:,}", "chip markers"), (f"{on[0]:,}", "already on the chip"),
                          (f"{on[1]:,}", "not on the chip"), (f"{cs['novel_functional']:,}", f"tier 1–2 with no chip marker within {tools._bp(cs['window_bp'])}"),
                          (f"{cs['gaps']:,}", f"chip gaps over {tools._bp(cs['gap_bp'])}")]
    every = request.GET.get("show") == "all"
    order = "genome" if request.GET.get("order") == "genome" else "problems"
    new_only = bool(chip) and request.GET.get("chip") == "new"
    dropped = con.execute("SELECT count(*) FROM pa WHERE dropped").fetchone()[0]
    ctx.update(n=n, several=several, tiers=sorted((t, k) for t, k in tiers.items() if t is not None),
               fig=mark_safe(_figure(con, d, chip, res, synthetic)),
               readiness=tools.assay_readiness(con, types, synthetic, lambda **_: None),
               rows=_rows(con, dict(con.execute("SELECT column_name, column_type FROM (DESCRIBE pa)").fetchall()), s["sources"],
                          LISTED if every else SHOWN, order, new_only),
               more=None if every or n + dropped <= SHOWN else "?" + urlencode({k: v for k, v in (("show", "all"), ("order", order),
                                                                                         ("chip", "new" if new_only else "")) if v and v != "problems"}),
               order=order, new_only=new_only, dropped=dropped,
               downloads=_downloads(con, chip, n))
    return render(request, "snpportal/panel.html", ctx)


def _rows(con, types, sources, limit, order="problems", new_only=False):
    """The panel's SNPs as display values, the dropped ones dimmed in their place (to put back): problems first by default
    (assay fail, warn, low MAF, LORe, another panel SNP closer than the panel designer's minimum spacing), else genome
    order; new_only: not on the chip. Each says how close the nearest other kept SNP is when it is that close."""
    names = {x["id"]: f"S{i + 1}" for i, x in enumerate(sources)}
    cfg = snp_panel.settings(jobs.weights())
    spacing, low = int(cfg["min_spacing"]), float(cfg["min_maf"])
    cols = [c for c in ("chrom", "pos", "id", "ref", "alt", "gene_name", "gene_id", "gene_ortholog_human", "region_class", "coding_consequence",
                        "coding_hgvsp", "tier", "assay_status", "public_af_maf", "lore", "on_chip", "near_chip", "dist_to_chip", "sources",
                        "snp_key", "dropped") if c in types]
    maf = "public_af_maf" if "public_af_maf" in types else "NULL"
    lore = "coalesce(lore, false)" if "lore" in types else "false"
    sql = f"""WITH k AS (SELECT snp_key, chrom, pos, coalesce(nullif(id, '.'), chrom || ':' || pos) AS name FROM p),
              n AS (SELECT snp_key, pos - lag(pos) OVER w AS dp, lag(name) OVER w AS np, lead(pos) OVER w - pos AS dn,
                           lead(name) OVER w AS nn FROM k WINDOW w AS (PARTITION BY chrom ORDER BY pos)),
              c AS (SELECT snp_key, CASE WHEN dn IS NULL OR dp <= dn THEN dp ELSE dn END AS close_bp,
                           CASE WHEN dn IS NULL OR dp <= dn THEN np ELSE nn END AS close_to FROM n)
              SELECT {', '.join('a.' + x for x in cols)}, c.close_bp, c.close_to,
                     (a.assay_status = 'fail')::INT * 4 + (a.assay_status = 'warn')::INT * 2 + coalesce({maf} < {low}, false)::INT
                     + {lore}::INT + coalesce(c.close_bp <= {spacing}, false)::INT AS problems
              FROM pa a LEFT JOIN c USING (snp_key)
              {'WHERE NOT coalesce(a.on_chip, false)' if new_only and 'on_chip' in types else ''}
              ORDER BY {'problems DESC, ' if order == 'problems' else ''}a.file_row_number LIMIT {int(limit)}"""
    cur = con.execute(sql)
    names_ = [x[0] for x in cur.description]
    out = []
    for r in (dict(zip(names_, x)) for x in cur.fetchall()):
        g = r.get
        status = g("assay_status") or "not_checked"
        near = g("close_bp") is not None and g("close_bp") <= spacing and not g("dropped")
        chip = None if "on_chip" not in r else "on the chip" if g("on_chip") else (
            f"near · {tools._bp(g('dist_to_chip'))}" if g("near_chip") else "new")
        out.append({"key": g("snp_key"), "dropped": g("dropped"), "snp": g("id") if g("id") not in (None, ".") else f"{g('chrom')}:{g('pos'):,}",
                    "position": f"{g('chrom')}:{g('pos'):,}", "alleles": results._alleles(g),
                    "gene": results.gene_label(g("gene_name"), g("gene_id"), g("gene_ortholog_human")), "region": results.region_text(g),
                    "tier": g("tier"), "assay": (results.ASSAY.get(status, ("?", "not_checked")) + (status.replace("_", " "),)),
                    "maf": None if g("public_af_maf") is None else (f"{g('public_af_maf'):.2f}", g("public_af_maf") < low),
                    "lore": bool(g("lore")), "close": f"{tools._bp(g('close_bp'))} from {g('close_to')}" if near else "",
                    "chip": chip, "sources": " ".join(names.get(x, "?") for x in g("sources") or [])})
    return out


def _downloads(con, chip, n):
    url = reverse("snpportal:panel_download")
    new = con.execute("SELECT count(*) FILTER (WHERE NOT on_chip) FROM p").fetchone()[0] if chip else None
    scopes = [("all", f"All panel SNPs ({n:,})")] + ([("new", f"Not on the chip ({new:,})")] if chip else [])
    return {"scopes": scopes, "formats": [("kasp", "KASP"), ("illumina", "Illumina"), ("axiom", "Axiom")],
            "tsv": f"{url}?format=tsv", "url": url}


# ---- changes: remove a source, the chip, clear ----

@csrf_exempt  # so the upload handler can be set before the body is read; _change checks the CSRF token
@private
def change(request):
    """POST: remove=<source id>, a chip (upload, demo=1, chip_remove=1), or clear=1 (the whole panel). A chip streams
    into the results dir like a SNP list (views.UploadToResults)."""
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    handler = UploadToResults(request)
    request.upload_handlers = [handler]
    try:
        return _change(request)
    except Exception:
        request._files = MultiValueDict()  # keep uploaded file names out of error reports
        raise
    finally:
        handler.discard()


@csrf_protect
@sensitive_post_parameters()
def _change(request):
    d = _folder(request)
    back = redirect(reverse("snpportal:design_panel"))
    if d is None:
        return back
    if request.POST.get("clear"):
        shutil.rmtree(d, ignore_errors=True)
        back.delete_cookie(COOKIE)
        return back
    if request.POST.get("remove"):
        s = jobs.read_json(d / "panel.json")
        i = int(request.POST["remove"]) if request.POST["remove"].isdecimal() else -1
        s["sources"] = [x for x in s["sources"] if x["id"] != i]
        (d / f"source_{i}.parquet").unlink(missing_ok=True)
        jobs._write_json(d / "panel.json", s)
        return back
    if request.POST.get("drop") or request.POST.get("keep"):  # one SNP out of the panel, or back in
        s = jobs.read_json(d / "panel.json")
        out = set(s.get("dropped", []))
        out = out | {request.POST["drop"][:200]} if request.POST.get("drop") else out - {request.POST["keep"]}
        s["dropped"] = sorted(out)
        jobs._write_json(d / "panel.json", s)
        return redirect(reverse("snpportal:design_panel") + "?" + urlencode({k: v for k, v in request.POST.items() if k in ("order", "chip")})
                        + "#list-h")
    if request.POST.get("chip_remove"):
        for path in (d / "chip.parquet", d / "chip.json"):
            path.unlink(missing_ok=True)
        return back
    return _chip(request, d)


def _chip(request, d):
    """The baseline chip: an uploaded SNP list (manifest, PLINK, VCF, table) or the release's demo chip."""
    demo, upload = jobs.release() / "demo" / "chip_demo_SYNTHETIC.tsv", request.FILES.get("chip")
    if request.POST.get("demo") and demo.is_file():
        src, label, synthetic = demo, "Demo chip", True
    elif upload and upload.size:
        suffix = accepted_suffix(upload.name)
        if suffix is None:
            return redirect(f"{reverse('snpportal:design_panel')}?chip_error=type")
        src, label, synthetic = d / f".chip-input{suffix}", "Your chip", "SYNTHETIC" in upload.name
        os.replace(upload.path, src)
    else:
        return redirect(f"{reverse('snpportal:design_panel')}?chip_error=missing")
    new = d / ".chip-new.parquet"
    try:
        report = snp_panel.read_chip(src, jobs.release(), new, max_snps=tools.chip_cap())
    except (snpscore.InputError, duckdb.Error):
        new.unlink(missing_ok=True)
        return redirect(f"{reverse('snpportal:design_panel')}?chip_error=format")
    finally:
        if src != demo:
            src.unlink(missing_ok=True)
    if not report.get("snps_kept"):
        new.unlink(missing_ok=True)
        return redirect(f"{reverse('snpportal:design_panel')}?chip_error=empty")
    con = jobs.connect([d], d)
    density = [list(x) for x in con.execute(f"SELECT chrom, (pos - 1) // 1000000, count(*) FROM read_parquet('{new}') "
                                            "GROUP BY ALL ORDER BY ALL").fetchall()]
    con.close()
    os.chmod(new, 0o600)
    os.replace(new, d / "chip.parquet")
    jobs._write_json(d / "chip.json", {"label": label, "synthetic": synthetic, "kept": report["snps_kept"],
                                       "rejected": {k: v for k, v in (report.get("rejected") or {}).items() if v},
                                       "density": density, "created_utc": jobs.utc()})
    return redirect(reverse("snpportal:design_panel"))


# ---- downloads ----

@private
def download(request):
    """?format=tsv (the panel's SNPs with their annotations: score that file again to keep the panel beyond 24
    hours) or kasp, illumina, axiom; ?scope=new: only the SNPs not on the chip."""
    d = _folder(request)
    fmt = request.GET.get("format", "tsv")
    if d is None or fmt not in ("tsv", *tools.VENDORS):
        raise Http404("No panel, or no such format")
    con, rel = _open(d)
    if rel is None:
        raise Http404("The panel is empty")
    scope = request.GET.get("scope") if request.GET.get("scope") in SCOPES and (d / "chip.parquet").exists() else "all"
    con.execute("CREATE VIEW out AS SELECT * EXCLUDE (panel_source, source_row, sources) FROM p"  # the panel's own columns stay out
                + (" WHERE NOT on_chip" if scope == "new" else ""))
    table = "out"
    s = jobs.read_json(d / "panel.json")
    meta = {"tool": "salmobase functional SNP portal: Design panel", "preset": "all", "panel": f"{len(s['sources'])} sources",
            "filters": {"scope": SCOPES[scope]}, "synthetic": any(x.get("synthetic") for x in s["sources"]), "created_utc": s.get("created_utc")}
    name = f"panel_{scope}_{fmt}.{'tsv' if fmt == 'tsv' else snp_export.filename(fmt, 'release', 'all', None).rsplit('.', 1)[1]}"
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".export-", suffix="." + name.rsplit(".", 1)[1])
    os.close(fd)
    try:
        snp_export.export(con, fmt, tmp, jobs.release(), "all", meta, request.GET.get("include_failed") == "1",
                          request.GET.get("plain") == "1", table=table, sidecars=False)
        f = open(tmp, "rb")
    except snpscore.InputError as e:
        return render(request, "snpportal/stub.html", {"nav": "panel", "title": "Export not possible", "message": str(e)}, status=400)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return FileResponse(f, as_attachment=True, filename=name, content_type=tools.MIME.get(fmt, "text/plain"))
