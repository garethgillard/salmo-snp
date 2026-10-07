"""Printable report of a finished job (P3.5), two A4 pages: the caveat line, the Overview's key numbers, the top 20
SNPs (ordered as the Overview's top list, with the table filters in the URL, if any), the panel of ?panel=<hash>, two
figures, a short methods summary with references, and a 3-line provenance block. portal.css /* report */ lays it out;
the browser's 'Save as PDF' makes the PDF. The numbers come from results.overview and results.top, so they match the
results tabs for the same URL parameters."""
from __future__ import annotations

import re
from urllib.parse import urlencode

from django.shortcuts import render
from django.urls import reverse
from django.utils.safestring import mark_safe

from . import jobs, results, tools
from .views import finished, private

TOP = 20
FIGURES = ("tiers", "ideogram")  # the report's two figures, when their data exist


def rebase(href, base):
    """Overview links are relative to the results page ('?tab=table&...', '#qc'): make them point there."""
    return f"{base}{href}" if href and href[0] in "?#" else href


def overview(request, key, job):
    """results.overview() for a page other than the results page: KPI and figure links point at the results page."""
    base = reverse("snpportal:results", args=[key])
    ov = results.overview(request, key, job)
    for k in ov["kpis"]:
        k["href"] = rebase(k.get("href"), base)
    ov["figs"] = {name: dict(fig, svg=mark_safe(str(fig["svg"]).replace('href="?', f'href="{base}?')))
                  for name, fig in list(ov["figs"].items()) + [(f["name"], f) for f in ov["more_figs"]]}
    return ov


def methods(job, d, trait):
    """(paragraphs, references) of snpscore's methods text for the job's release snapshot; ([], []) when this
    snpscore has none. The known-loci DOIs come from the current release while it is the job's."""
    try:
        from snpscore.export import methods_text
        weights = d / "weights.yaml"
        text = methods_text(d / "manifest.json", weights if weights.exists() else None, trait,
                            None if jobs.release_changed(job) else jobs.release())
    except (ImportError, OSError, KeyError, TypeError, ValueError):
        return [], []
    body, _, refs = text.partition("\n\nReferences\n")
    return [p for p in body.split("\n\n") if p.strip()], [r[2:] if r.startswith("- ") else r for r in refs.splitlines() if r.strip()]


def references(refs):
    """The data-source references without placeholders; the known-loci line keeps its DOIs only."""
    out = []
    for r in refs:
        r = r.replace(" (DOI to add)", "")
        if r.startswith("Known loci ("):
            r = "Known-loci catalogue: " + r.rsplit("): ", 1)[-1]
        out.append(r)
    return out


def panel(request, key, d):
    """The summary of ?panel=<hash> (a panel designed on the Panel tab), or None."""
    tag = request.GET.get("panel", "")
    info = jobs.read_json(d / "panels" / f"{tag}.json") if re.fullmatch(r"[0-9a-f]{16}", tag) else None
    if not info or "summary" not in info:
        return None
    s = info["summary"]
    q = urlencode({"tab": "panel", "trait": info.get("preset", "all")})
    return {"name": tools.panel_name(info), "line": tools.panel_line(s), "short": tools._short(s),
            "url": f"{reverse('snpportal:results', args=[key])}?{q}"}


@private
def report(request, key):
    """/snp/results/<key>/report/?trait=[&table filters][&panel=<hash>]: the printable report."""
    job = finished(key)
    d = jobs.folder(key)
    ov = overview(request, key, job)
    trait = ov["trait"]
    best = results.top(request, key, job, TOP)
    filters = {k: v for k, v in best["chosen"].items() if k != "trait"}
    _, refs = methods(job, d, trait)
    base = reverse("snpportal:results", args=[key])
    label = dict(jobs.presets(d)).get(trait, trait)
    m = jobs.manifest(d)
    synthetic = bool(job.get("synthetic_input") or job.get("synthetic_layers") or tools.chip_info(d).get("synthetic"))
    command = next((line[2:] for line in jobs.provenance(job, trait, filters) if line.startswith("# equivalent command")), "")
    return render(request, "snpportal/report.html", {
        "nav": "score", "job": job, "key": key, "title": f"Report · {job.get('label') or 'results'}", "trait": trait, "preset": label,
        "crumbs": [("Score SNPs", reverse("snpportal:upload")), ("Results", f"{base}?{urlencode({'trait': trait, **filters})}"),
                   ("Report", None)],
        "meta": " · ".join(x for x in [f"{job['n_rows']:,} SNPs" if job.get("n_rows") is not None else None, f"trait {label}",
                                       f"printed {jobs.utc()}"] if x),
        "actions": [{"label": "Back to the results", "url": f"{base}?{urlencode({'trait': trait, **filters})}"}],
        "kpis": ov["kpis"], "figs": [ov["figs"][n] for n in FIGURES if n in ov["figs"]], "panel": panel(request, key, d),
        "top": best, "filters": filters, "synthetic": synthetic,
        "table_url": f"{base}?{urlencode({'tab': 'table', 'trait': trait, **filters})}",
        "methods_url": request.build_absolute_uri(reverse("snpportal:methods")), "refs": references(refs),
        "release": f"{m.get('version') or job.get('release')} ({m.get('assembly') or job.get('assembly', 'Ssal_v3.1')})",
        "provenance": [f"Release {job.get('release')} ({job.get('assembly', 'Ssal_v3.1')}); manifest {(job.get('manifest_sha256') or '')[:12]}; "
                       f"weights {(job.get('weights_sha256') or 'none')[:12]}; input {(job.get('input_sha256') or 'n/a')[:12]}",
                       f"snpscore {job.get('snpscore_version')}; DuckDB {job.get('duckdb_version')}; job created {job.get('created_utc')}; "
                       f"deleted after {jobs.utc(jobs.expires(key))}",
                       command.replace("equivalent command: ", "Equivalent command: ")]})
