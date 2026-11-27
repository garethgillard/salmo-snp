"""Score SNPs and see the results: the Score page (upload, paste or example -> a job; its GWAS tab posts to
association.score), job status, the results page with tabs (Overview | Table | Panel), downloads with provenance,
figures and 'Delete now' (the card is in locus.py).
Views that show a user's SNPs are private: no caching, same-origin referrers, and error reports without POST
values, uploaded file names, local variables or DuckDB message text."""
from __future__ import annotations

import os
import tempfile
from functools import lru_cache, wraps
from pathlib import Path
from urllib.parse import urlencode

import duckdb
from django.core.files.uploadedfile import UploadedFile
from django.core.files.uploadhandler import FileUploadHandler
from django.core.handlers.exception import response_for_exception
from django.http import FileResponse, Http404, HttpResponseNotAllowed, StreamingHttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.datastructures import MultiValueDict
from django.views.debug import SafeExceptionReporterFilter
from django.views.decorators.csrf import csrf_exempt, csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_POST

from . import figures, jobs, results as result_views, tools

SUFFIXES = (".vcf.gz", ".vcf", ".tsv.gz", ".tsv", ".csv.gz", ".csv", ".txt.gz", ".txt", ".bim", ".map")
SV_SUFFIXES = (".vcf.gz", ".vcf", ".bed.gz", ".bed", ".tsv.gz", ".tsv", ".csv.gz", ".csv", ".txt.gz", ".txt")  # structural variants
PASTE_LINES = 10_000
SV_PASTE_LINES = 10_000  # pasted regions (structural variants)
TABS = ("overview", "table", "panel", "export")  # panel: the automatic designer, unlinked (testing only; the Design panel page is curated)
CURRENT = "snpportal_current"  # cookie: the results this browser last opened
MINE = "snpportal_results"  # cookie: the results this browser opened, newest first: the Score page lists them
MAX_MINE = 30
EXAMPLES = {  # the release's demo/ files (name without extension) -> (title, what it is; {n}: its rows); the title names the job
    "known_loci": ("Known loci", "{n:,} from published studies"),
    "chip_demo_SYNTHETIC": ("SNP chip", "synthetic, {n:,} SNPs"),
    "gwas_maturation_SYNTHETIC": ("GWAS", "synthetic, maturation"),  # posted to association.score with trait=maturation
    "public_50k": ("Public SNPs", "{n:,} sites, an even sample"),  # on the Score page only when a release has no other example
    "known_svs": ("Known SVs", "{n:,} published structural variants"),  # SV examples: scored as SVs (sv=True below)
    "svs_demo_SYNTHETIC": ("SVs", "synthetic, {n:,} structural variants"),
}
CHIPS = {  # the Score page's 'Try' buttons, kept short (G, 2026-11-27): name and count ({k}: its rows, 53k); a synthetic
    # file's button says so in its tooltip (EXAMPLES), and its results in their title
    "known_loci": ("Known loci", "{k}"),
    "chip_demo_SYNTHETIC": ("SNP chip", "{k}"),
    "gwas_maturation_SYNTHETIC": ("Maturation GWAS", "{k}"),
    "public_50k": ("Public SNPs", "{k}"),
    "known_svs": ("Known SVs", "{k}"),
    "svs_demo_SYNTHETIC": ("SV calls", "{k}"),
}
TRY = ("known_loci", "chip_demo_SYNTHETIC", "gwas_maturation_SYNTHETIC", "known_svs", "svs_demo_SYNTHETIC")  # the Score page's examples
SV_EXAMPLES = ("known_svs", "svs_demo_SYNTHETIC")
INPUTS = {"file": "SNPs", "sv": "Structural variants", "gwas": "GWAS results", "regions": "Genes or regions"}  # Score tabs
# (G, 2026-11-27: in this order)
# (SNPs: a file or pasted lines, so ?input=paste and a pasted list's errors show that tab)


class PrivateReports(SafeExceptionReporterFilter):
    """Error reports from portal views never show POST values or local variables (they may hold SNPs).
    score() also empties request.FILES before an error is reported, so reports never name an uploaded file."""

    def get_post_parameters(self, request):
        return {name: self.cleansed_substitute for name in request.POST} if request is not None else {}

    def get_traceback_frame_variables(self, request, tb_frame):
        return []


def private(view):
    """no-store caching, same-origin referrers and content-free error reports for a view that shows a user's SNPs."""
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        request.exception_reporter_filter = PrivateReports()
        try:
            response = view(request, *args, **kwargs)
        except Http404 as e:  # the site's 404 page, but with the headers below
            response = response_for_exception(request, e)
        except duckdb.Error as e:  # its message can quote SNPs: error reports and logs get the type and traceback only
            raise RuntimeError(f"{type(e).__name__} in a portal query (message withheld)").with_traceback(e.__traceback__) from None
        response["Cache-Control"] = "no-store, private"
        response["Referrer-Policy"] = "same-origin"
        return response
    return wrapped


class UploadToResults(FileUploadHandler):
    """Streams an uploaded file straight into a 0600 file in the results dir: never into memory or the system
    temp dir. discard() removes whatever a job didn't take."""

    def __init__(self, request=None):
        super().__init__(request)
        self.paths, self.out = [], None

    def new_file(self, *args, **kwargs):
        super().new_file(*args, **kwargs)
        fd, path = tempfile.mkstemp(dir=jobs.results_dir(), prefix=".upload-")
        self.paths.append(path)
        self.out = os.fdopen(fd, "wb")

    def receive_data_chunk(self, raw_data, start):
        self.out.write(raw_data)

    def file_complete(self, file_size):
        self.out.close()
        uploaded = UploadedFile(open(self.paths[-1], "rb"), name=self.file_name, content_type=self.content_type, size=file_size)
        uploaded.path = self.paths[-1]
        return uploaded

    def upload_interrupted(self):
        self.discard()

    def discard(self):
        if self.out:
            self.out.close()
        for path in self.paths:
            Path(path).unlink(missing_ok=True)


def accepted_suffix(name, suffixes=SUFFIXES):
    return next((s for s in suffixes if name.lower().endswith(s)), None)


def examples():
    """{name: {title, what, label (the job's), chip and detail (the Score page's), path, suffix, synthetic}} for the
    release's example inputs (demo/ and catalog/known_loci.tsv)."""
    release = jobs.release()
    files = sorted((release / "demo").iterdir()) if (release / "demo").is_dir() else []
    found = {}
    for p in files + [release / "catalog" / "known_loci.tsv"]:
        suffix = accepted_suffix(p.name, SV_SUFFIXES if p.name.startswith(SV_EXAMPLES) else SUFFIXES)
        name = suffix and p.name[:-len(suffix)]
        if name and name not in found and p.is_file():
            title, what = EXAMPLES.get(name, (name.replace("_", " "), ""))
            synthetic = "SYNTHETIC" in p.name
            chip, detail = CHIPS.get(name, (title, "synthetic" if synthetic else ""))
            if "{" in what + detail:
                n = _rows(p, p.stat().st_mtime_ns)
                what, detail = what.format(n=n), detail.format(n=n, k=short_count(n))
            found[name] = {"title": title, "what": what, "label": f"{title} (synthetic)" if synthetic else title,
                           "chip": chip, "detail": detail,
                           "path": p, "suffix": suffix, "synthetic": synthetic, "sv": name in SV_EXAMPLES}
    return found


def short_count(n):
    """40 -> '40', 53,917 -> '53k', 209,327 -> '209k', 1,600,000 -> '1.6M': a count on a small button."""
    return str(n) if n < 1000 else f"{n // 1000}k" if n < 1_000_000 else f"{n / 1e6:.1f}M"


@lru_cache(maxsize=64)
def _rows(path, mtime_ns):
    """Data rows of an example file (lines that are not '#' comments, minus the header), counted once per version."""
    with open(path) as f:
        return sum(1 for line in f if line.strip() and not line.startswith("#")) - 1


def score_page(request, error=None, status=200, tab=None, targets=""):
    """The Score page, also the home page: the tabs SNPs (a file or pasted lines) | Genes or regions | Structural
    variants | GWAS results (?input=, or `tab` after an error, so each form's errors come back on its own tab), the
    examples (TRY) and the tour link under them; beside them this browser's results."""
    from .explore import FLANK, FLANKS  # the gene/region flank choices (explore.candidate_job reads them)
    tab = tab if tab in INPUTS else request.GET.get("input") if request.GET.get("input") in INPUTS else "file"
    found, listed = examples(), mine(request)
    return no_store(listed, render(request, "snpportal/score.html", {
        "nav": "score", "title": "Score SNPs by functional evidence", "error": error, "tabs": INPUTS.items(), "tab": tab, "mine": listed,
        "tries": [dict(found[name], name=name, gwas=name.startswith("gwas_"))  # a release without them: its public sample
                  for name in (TRY if any(n in found for n in TRY) else ("public_50k",)) if name in found],
        "sv_lines": SV_PASTE_LINES,
        "targets": targets, "flanks": FLANKS, "flank": FLANK, "paste_lines": PASTE_LINES,
        "max_mb": f"{float(jobs.setting('SNPPORTAL_MAX_UPLOAD_MB', 300)):g}",
        "keep_hours": f"{float(jobs.setting('SNPPORTAL_KEEP_HOURS', 24)):g}", "local": jobs.local(),
        "positions": jobs.position_choices(),
        "results_dir": jobs.results_dir(),
        "weights": score_weights(request),  # the user's own weights and bands, remembered (G, 2026-11-27)
    }, status=status))


@csrf_exempt  # so the upload handler can be set before the body is read; _score checks the CSRF token
def score(request):
    """The Score page. A POST (file, pasted positions or an example) becomes a job and redirects to its results."""
    if request.method != "POST":
        return score_page(request)
    max_mb = float(jobs.setting("SNPPORTAL_MAX_UPLOAD_MB", 300))
    try:
        length = int(request.META.get("CONTENT_LENGTH") or 0)
    except ValueError:
        length = 0
    if length > max_mb * 2 ** 20:  # rejected before Django reads (and spools) the body
        return score_page(request, f"The upload is larger than {max_mb:g} MB. Compress it with gzip or split it, "
                                   "or run snpscore on your own computer (see 'Run it locally').", 413)
    request.exception_reporter_filter = PrivateReports()
    handler = UploadToResults(request)
    request.upload_handlers = [handler]
    try:
        return _score(request)
    except Exception:
        request._files = MultiValueDict()  # keep uploaded file names out of the error report
        raise
    finally:
        handler.discard()


@csrf_protect
@sensitive_post_parameters()
def _score(request):
    tab = "sv" if request.POST.get("kind") == "sv" else "paste" if request.POST.get("paste") else "file"
    try:
        key, preset = start_job(request)
    except jobs.InputError as e:
        return score_page(request, str(e), 400, tab)
    except jobs.QueueFull:
        response = score_page(request, "The portal is busy scoring other lists. Please try again in a minute.", 503, tab)
        response["Retry-After"] = "60"
        return response
    params = {"trait": preset} if preset != "all" else {}
    url = reverse("snpportal:results", args=[key])
    return remember(redirect(f"{url}?{urlencode(params)}" if params else url), request)


def start_job(request):
    """Create the job for a POSTed example, file or paste. Returns (key, preset)."""
    preset = "all"  # tiers always count all 27 conditions
    example, upload, paste = request.POST.get("example"), request.FILES.get("snps"), request.POST.get("paste", "").strip()
    weights = jobs.parse_weights(request.POST)  # the form's evidence weights where they differ from the defaults
    cuts = jobs.parse_cuts(request.POST)  # the form's score-band cut-offs, None when left blank (from the public SNPs)
    name = job_name(request)  # the form's Name box, else the file's name or the date
    positions = request.POST.get("positions") if request.POST.get("positions") in dict(jobs.position_choices()) else None
    if example:
        found = examples().get(example)
        if found is None:
            raise jobs.InputError("That example is not part of this release.")
        return jobs.create(found["path"], found["suffix"], "sv" if found["sv"] else "snps", preset, f"Example: {found['label']}",
                           synthetic=found["synthetic"], move=False, weights=weights, cuts=cuts), preset
    if request.POST.get("kind") == "sv":
        return start_sv_job(request, preset, weights, cuts), preset
    if upload:
        suffix = accepted_suffix(upload.name)
        if suffix is None:
            raise jobs.InputError("This file type isn't accepted. Upload a VCF (.vcf or .vcf.gz), a table (.tsv, .csv or "
                                  ".txt, optionally gzipped) or a PLINK .bim/.map file: see Format help.")
        if not upload.size:
            raise jobs.InputError("The uploaded file is empty.")
        name = name or Path(upload.name or "").name[:80] or "Uploaded list"  # else the file's name names the results
        return jobs.create(Path(upload.path), suffix, "snps", preset, name, positions=positions, weights=weights, cuts=cuts), preset
    if paste:
        if positions == "flank":
            raise jobs.InputError("Pasted lines have no flank sequences to place them by: choose the assembly they are on, "
                                  "or upload a file with the flanks.")
        rows = jobs.parse_paste(paste, PASTE_LINES)  # converted from another assembly like a file (G, 2026-11-27)
        return jobs.create_from_rows(rows, name or f"Pasted {jobs.utc()}", preset, kind="snps", input_format="paste",
                                     weights=weights, cuts=cuts, positions=positions), preset
    raise jobs.InputError("Choose a file, paste some positions or pick an example.")


def start_sv_job(request, preset, weights=None, cuts=None):
    """Create the job for POSTed structural variants: a file (svs) or pasted regions (sv_paste). Returns the key."""
    upload, paste = request.FILES.get("svs"), request.POST.get("sv_paste", "").strip()
    if upload:
        suffix = accepted_suffix(upload.name, SV_SUFFIXES)
        if suffix is None:
            raise jobs.InputError("This file type isn't accepted for structural variants. Upload a VCF (.vcf or .vcf.gz), a "
                                  "BED file or a table (.tsv, .csv or .txt, optionally gzipped): see Format help.")
        if not upload.size:
            raise jobs.InputError("The uploaded file is empty.")
        name = job_name(request) or Path(upload.name or "").name[:80] or "Uploaded SVs"
        return jobs.create(Path(upload.path), suffix, "sv", preset, name, weights=weights, cuts=cuts)
    if paste:
        rows = jobs.parse_sv_paste(paste, SV_PASTE_LINES)
        return jobs.create_from_sv_rows(rows, job_name(request) or f"Pasted SVs {jobs.utc()}", preset, weights=weights, cuts=cuts)
    raise jobs.InputError("Choose a file of structural variants, or paste some regions.")


def cut_fields(d=None, job=None, own=None):
    """The score-band cut-off fields (G, 2026-11-27): [(tier, value)] filled with the user's own cut-offs (a job's, or
    `own`; else blank, so they follow the weights) and the cut-offs in use as placeholders."""
    c = job.get("cuts") or {} if job else {}
    now = list((jobs.weights(d) or {}).get("tiers") or figures.default_cuts()) if d else list(figures.default_cuts())
    own = c.get("now") if c.get("source") == "own" else own
    return {"cuts": [(t, own[t - 1] if own else "", now[t - 1]) for t in (1, 2, 3)], "max_cut": jobs.MAX_CUT, "cuts_own": bool(own)}


WEIGHTS_COOKIE = "snp_weights"  # the weights and bands this browser scored with last on the Score page (G, 2026-11-27)


def remembered(request):
    """({term: weight}, cut-offs or None) this browser scored with last (the cookie, checked as a form's fields would
    be); ({}, None) when none, or when they no longer fit this release's weights."""
    raw = request.COOKIES.get(WEIGHTS_COOKIE, "")
    fields = dict(pair.split(":", 1) for pair in raw.split(",") if ":" in pair)
    try:
        return jobs.parse_weights(fields), jobs.parse_cuts(fields)
    except jobs.InputError:
        return {}, None


def remember(response, request):
    """Keep the weights and bands of a Score page form that made a job for this browser's next list (a year), or forget
    them when they are the defaults."""
    if request.POST.get("example"):  # an example's button carries no weights: what was remembered stays
        return response
    try:
        chosen, cuts = jobs.parse_weights(request.POST), jobs.parse_cuts(request.POST)
    except jobs.InputError:
        return response
    if chosen or cuts:
        value = ",".join([f"w_{t}:{w}" for t, w in sorted(chosen.items())] + [f"cut_{i}:{c}" for i, c in enumerate(cuts or [], 1)])
        response.set_cookie(WEIGHTS_COOKIE, value, max_age=365 * 86400, httponly=True, samesite="Lax")
    elif WEIGHTS_COOKIE in request.COOKIES:
        response.delete_cookie(WEIGHTS_COOKIE)
    return response


def score_weights(request):
    """The Score page's weights fold: the release's terms filled with this browser's remembered weights (or the
    defaults), the cut-off fields, and 'custom' when they are not the defaults."""
    chosen, cuts = remembered(request)
    terms = [(t, name, chosen.get(t, value), default) for t, name, value, default in jobs.weight_terms()]
    return {"terms": terms, "max": jobs.MAX_WEIGHT, **cut_fields(own=cuts), "custom": bool(chosen or cuts)}


def job_name(request):
    """The Score page's Name box (G, 2026-11-27), or '' to name the results by their file or the date."""
    return " ".join(str(request.POST.get("label") or "").split())[:80]


@private
@csrf_protect
def rename(request, key):
    """POST label (and next=score): renames results, from the Score page's list or the results page."""
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    if jobs.status(key) is None:
        raise Http404("Result not found or expired")
    name = job_name(request)
    if name:
        jobs.update(key, label=name)
    return redirect(reverse("snpportal:upload") if request.POST.get("next") == "score" else reverse("snpportal:results", args=[key]))


def weights_context(key, job):
    """The results pages' evidence weights and score bands (G, 2026-11-27): the Table's Weights control and, when they
    are the user's own, the note on every tab."""
    d = jobs.folder(key)
    note = jobs.rules_text(job)
    return {"terms": jobs.weight_terms(d), "max": jobs.MAX_WEIGHT, "custom": bool(note), "note": note + "." if note else "",
            "error": job.get("weights_error"), "url": reverse("snpportal:rescore", args=[key]), **cut_fields(d, job)}


@private
@csrf_protect
def rescore(request, key):
    """POST from the Table's Weights control (w_<term> fields, or reset=1 for the defaults): tiers the job again with
    those weights and returns to the tab it came from, which shows progress until the new tiers are ready."""
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    job = finished(key)
    tab = request.POST.get("next") if request.POST.get("next") in TABS else "table"
    back = f"{reverse('snpportal:results', args=[key])}?{urlencode({'tab': tab})}"
    if job.get("state") != "done":
        return redirect(back)
    try:
        chosen = {} if request.POST.get("reset") else jobs.parse_weights(request.POST, jobs.folder(key))
        cuts = None if request.POST.get("reset") else jobs.parse_cuts(request.POST)
    except jobs.InputError:
        return redirect(f"{back}&weights_error=1")
    jobs.rescore(key, chosen, cuts)
    return redirect(back)


def finished(key):
    """job.json of a finished job, else 404."""
    job = jobs.status(key)
    if job is None or job["state"] != "done":
        raise Http404("Result not found or expired")
    return job


@private
def status(request, key):
    """The progress panel, polled by htmx every second; once the job ends it tells htmx to reload the page."""
    job = jobs.status(key)
    response = render(request, "snpportal/_progress.html", {"job": job, "key": key})
    if job is None or job["state"] in ("done", "failed"):
        response["HX-Refresh"] = "true"
    return response


@private
def results(request, key):
    """Progress while the job runs, the error if it failed, else the tabs. Expired or deleted: a 404 page."""
    jobs.cleanup()
    job = jobs.status(key)
    if job is None:
        return render(request, "snpportal/expired.html", {"nav": "score", "title": "Results expired or deleted"}, status=404)
    gwas = job.get("input_kind") == "gwas"  # GWAS jobs: Association first (its own page), no Panel tab
    sv = job.get("input_kind") == "sv"  # SV jobs: no Panel tab either (panels are SNP markers)
    if gwas and job["state"] == "done" and "tab" not in request.GET:
        return redirect(f"{reverse('snpportal:association', args=[key])}?{urlencode({'trait': request.GET.get('trait', 'all'), **result_views.gwas_settings(request)})}")
    tab = request.GET.get("tab", "overview")
    tab = tab if tab in TABS and not ((gwas or sv) and tab == "panel") else "overview"
    synthetic = bool(job.get("synthetic_input") or job.get("synthetic_layers"))
    label = job.get("label") or "Results"
    name = label + (" (synthetic data)" if synthetic and "synthetic" not in label.lower() else "")
    n_text = f"{job['n_rows']:,} SNPs" if job.get("n_rows") is not None else ""
    context = {"nav": "score", "job": job, "key": key, "tab": tab, "gwas": gwas, "sv": sv, "name": name, "n_text": n_text,
               "title": " · ".join(x for x in [name, n_text] if x),
               "meta": jobs.deleted_after(key),
               "synthetic": synthetic, "weights": weights_context(key, job)}
    if job["state"] == "done":
        d = jobs.folder(key)
        trait = "all"  # tiers always count all 27 conditions
        settings = result_views.gwas_settings(request) if gwas else {}
        context.update(trait=trait, query=urlencode(settings), release_changed=jobs.release_changed(job))
        if tab == "table":
            context.update(result_views.table(request, key, job))  # keeps the selection it shows
        elif tab == "overview":
            context.update(result_views.overview(request, key, job))
        elif tab == "panel":
            context.update(tools.panel(request, key, job))
        else:
            context.update(tools.exports(request, key, job))
        context["table_query"] = result_views.selection(d) or urlencode(settings)  # the Table tab returns to the selection
        context["report_url"] = f"{reverse('snpportal:report', args=[key])}?{context['table_query']}"  # printed from Export
    else:  # running or failed: the standard header, with Delete (a finished result is deleted from the Score page's list)
        context["actions"] = [{"label": "Delete", "url": reverse("snpportal:delete", args=[key]), "post": True,
                               "style": "btn-outline-danger", "confirm": "Delete these results now? This can't be undone."}]
    response = render(request, "snpportal/results.html", context)
    response.set_cookie(CURRENT, str(key), max_age=24 * 3600, httponly=True, samesite="Lax")
    keep_mine(response, [str(key)] + [k for k in _mine_keys(request) if k != str(key)])  # the Score page lists it
    return response


@private
def current(request):
    """The nav's Score: the results this browser last opened while they exist, else the Score page."""
    key = request.COOKIES.get(CURRENT, "")
    try:
        if jobs.read(key):
            return redirect(reverse("snpportal:results", args=[key]))
    except (ValueError, OSError, Http404):
        pass
    return redirect(reverse("snpportal:upload"))


@private
def download(request, key):
    """The SNPs matching the current preset and filters as TSV, starting with '#' provenance lines (?plain=1 drops
    them). ?format=rejects gives the rows snpscore dropped; other formats come from tools.export."""
    job = finished(key)
    d, fmt = jobs.folder(key), request.GET.get("format", "tsv")
    if fmt == "rejects":
        if not (d / "rejects.tsv").exists():
            raise Http404("No rejected rows")
        return FileResponse(open(d / "rejects.tsv", "rb"), as_attachment=True, filename="rejected_rows.tsv")
    if fmt != "tsv" or request.GET.get("scope"):  # the Export tab's formats and scopes (all, filtered, a panel)
        return tools.export(request, key, job, fmt)
    con, types, where, chosen = result_views.open_result(request, key, write=True)
    columns = "* EXCLUDE (file_row_number)" if request.GET.get("columns") == "all" else result_views.export_select(  # the
        types, result_views.table_columns(d, types, job.get("input_kind") == "gwas"), [s for s, _ in jobs.score_layers(d)])  # Table's
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".export-", suffix=".tsv")  # columns (G, 2026-11-27, from users), else ?columns=all
    os.close(fd)
    try:
        con.execute(f"COPY (SELECT {columns} FROM v {where} ORDER BY file_row_number) TO '{tmp}' (HEADER, DELIMITER '\t')")
        f = open(tmp, "rb")
    finally:
        os.unlink(tmp)  # an open handle keeps the data until the response is closed; nothing is left behind
    named = {k: ("one of your own tracks" if k == "track" else v) for k, v in chosen.items() if k != "trait"}  # not its id
    lines = [] if request.GET.get("plain") else jobs.provenance(job, chosen["trait"], named)
    if lines and tools.chip_info(d).get("synthetic"):  # the Panel tab's chip adds its columns (results._open)
        lines.insert(-1, "# SYNTHETIC: on_chip, dist_to_chip, near_chip and novel_functional come from a synthetic chip")
    response = StreamingHttpResponse(_stream("".join(f"{line}\n" for line in lines).encode(), f),
                                     content_type="text/tab-separated-values; charset=utf-8")
    name = f"snps_{job['release']}_{chosen['trait']}{'_filtered' if len(chosen) > 1 else ''}.tsv"
    response["Content-Disposition"] = f'attachment; filename="{name}"'
    return response


def _stream(header, f):
    with f:
        yield header
        yield from iter(lambda: f.read(1 << 20), b"")


@require_POST
@private
def delete(request, key):
    """'Delete now': remove the job folder; the results URL then shows the expired page. From the Score page's list
    (next=score): back there, without it."""
    jobs.delete(key)
    if request.POST.get("next") != "score":
        return redirect("snpportal:results", key=key)
    return keep_mine(redirect("snpportal:upload"), [k for k in _mine_keys(request) if k != str(key)])


def _mine_keys(request):
    return [k for k in request.COOKIES.get(MINE, "").split(",") if k][:MAX_MINE]


def keep_mine(response, keys):
    response.set_cookie(MINE, ",".join(keys[:MAX_MINE]), max_age=int(jobs.keep_seconds() or jobs.FOREVER),
                        httponly=True, samesite="Lax")
    return response


def no_store(listed, response):
    """A page that lists this browser's results (their names can be file names) is never cached."""
    if listed:
        response["Cache-Control"] = "no-store, private"
    return response


def mine(request):
    """This browser's results that still exist, newest first, for the Score page and the Design panel's picker links:
    [{key, name, species, n, when, state, url, kind}]; species: the name of the species of the job's release (G,
    2026-11-27: under each result on the Score page), None when that release is no longer installed."""
    out = []
    for key in _mine_keys(request):
        try:
            job = jobs.read(key)
        except (ValueError, OSError):
            job = None
        if job:
            release = jobs.release_for(job.get("release"))
            out.append({"key": key, "name": job.get("label") or "Results", "n": job.get("n_rows"), "when": job.get("created_utc"),
                        "species": jobs.species(release)["name"] if release else None,
                        "unit": "SVs" if job.get("input_kind") == "sv" else "SNPs", "kind": job.get("input_kind") or "snps",
                        "state": job.get("state"), "url": reverse("snpportal:results", args=[key]),
                        "current": not out})  # the one opened last
    return out


@private
def figure(request, key, name):
    return result_views.figure(request, key, name, finished(key))
