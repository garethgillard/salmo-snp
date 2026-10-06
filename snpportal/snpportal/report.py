"""One-page printable report of a finished job (P3.5): KPI tiles, the key figures, the top 20 SNPs for the preset (and
the table filters in the URL, if any), the summary of a designed panel (?panel=<hash>), the methods paragraph from snpscore.export.methods_text, provenance and the
PROVISIONAL disclaimer. portal.css /* report */ lays it out on two A4 pages; the browser's 'Save as PDF' makes the
PDF. The numbers come from results.overview and the Table tab's default sort, so they match those tabs for the same
URL parameters."""
from __future__ import annotations

import re
from urllib.parse import urlencode

from django.shortcuts import render
from django.urls import reverse
from django.utils.safestring import mark_safe

from . import jobs, results, tools
from .jobs import ident
from .views import finished, private

TOP = 20
FIGURES = ("ideogram", "regions", "conditions")  # the report's key figures when their data exist (else the tier bar)
SHOW = ("chrom", "pos", "id", "ref", "alt", "tier", "tier_score", "tier_evidence", "gene_name", "gene_id",
        "gene_ortholog_human", "region_class", "known_locus", "assay_status")


def rebase(href, base):
    """Overview links are relative to the results page ('?tab=table&...', '#qc-h'): make them point there."""
    return f"{base}{href}" if href and href[0] in "?#" else href


def overview(request, key, job):
    """results.overview() for a page other than the results page: KPI and figure links point at the results page."""
    base = reverse("snpportal:results", args=[key])
    ov = results.overview(request, key, job)
    for k in ov["kpis"]:
        k["href"] = rebase(k.get("href"), base)
    ov["figs"] = {name: dict(fig, svg=mark_safe(str(fig["svg"]).replace('href="?', f'href="{base}?')))
                  for name, fig in ov["figs"].items()}
    return ov


def top(request, key):
    """(rows, number of SNPs matching the filters, chosen settings, column names) for the first TOP rows of the Table
    tab with the request's preset and filters: tier, then score (highest first), then file order."""
    con, types, where, chosen = results.open_result(request, key)
    maf, _ = jobs.maf_sql(types)
    cols = [c for c in SHOW if c in types]
    order = "tier ASC NULLS LAST, tier_score DESC NULLS LAST, " if {"tier", "tier_score"} <= set(types) else ""
    cur = con.execute(f"SELECT file_row_number, {', '.join(map(ident, cols))}{f', {maf} AS _maf' if maf else ''} "
                      f"FROM v {where} ORDER BY {order}file_row_number LIMIT {TOP}")
    names = [d[0] for d in cur.description]
    q = urlencode({"trait": chosen["trait"]})
    rows = []
    for r in (dict(zip(names, x)) for x in cur.fetchall()):
        g = r.get
        rows.append({
            "url": f"{reverse('snpportal:card', args=[key, r['file_row_number']])}?{q}",
            "snp": g("id") if g("id") not in (None, ".") else f"{g('chrom')}:{g('pos'):,}",
            "position": f"{g('chrom')}:{g('pos'):,}", "alleles": f"{g('ref')}>{g('alt')}" if g("ref") and g("alt") else g("ref") or "",
            "tier": g("tier"), "score": g("tier_score"), "evidence": g("tier_evidence") or "",
            "gene": results.gene_label(g("gene_name"), g("gene_id"), g("gene_ortholog_human")),
            "region": results.CLASS_LABELS.get(g("region_class"), g("region_class")) or "intergenic",
            "known": g("known_locus") or "", "maf": "" if g("_maf") is None else f"{g('_maf'):.2f}",
            "assay": (g("assay_status") or "not_checked").replace("_", " ")})
    matching = con.execute(f"SELECT count(*) FROM v {where}").fetchone()[0]
    return rows, matching, chosen, set(types) | ({"maf"} if maf else set())


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


def panel(request, key, d):
    """The panel summary of ?panel=<hash> (a panel designed on the Panel tab), or None."""
    tag = request.GET.get("panel", "")
    info = jobs.read_json(d / "panels" / f"{tag}.json") if re.fullmatch(r"[0-9a-f]{16}", tag) else None
    if not info or "summary" not in info:
        return None
    s = info["summary"]
    show = lambda v: ", ".join(map(str, v)) if isinstance(v, list) else ("yes" if v else "no") if isinstance(v, bool) else v
    params = ", ".join(f"{k.replace('_', ' ')} {show(v)}" for k, v in sorted((info.get("params") or {}).items()) if v not in (None, [], ""))
    q = urlencode({"tab": "panel", "trait": info.get("preset", "all")})
    return {"hash": tag, "preset": info.get("preset"), "kpis": tools._panel_kpis(s, s.get("assay_status")), "short": tools._short(s),
            "params": params, "chip": info.get("chip"), "warnings": s.get("warnings") or [],  # vendor checks (snpscore)
            "url": f"{reverse('snpportal:results', args=[key])}?{q}"}


@private
def report(request, key):
    """/snp/results/<key>/report/?trait=[&table filters]: the printable report."""
    job = finished(key)
    d = jobs.folder(key)
    ov = overview(request, key, job)
    trait = ov["trait"]
    rows, matching, chosen, columns = top(request, key)
    filters = {k: v for k, v in chosen.items() if k != "trait"}
    paragraphs, refs = methods(job, d, trait)
    base = reverse("snpportal:results", args=[key])
    figs = [ov["figs"][n] for n in FIGURES if n in ov["figs"]] or [ov["figs"][n] for n in ("tiers",) if n in ov["figs"]]
    label = dict(jobs.presets(d)).get(trait, trait)
    return render(request, "snpportal/report.html", {
        "nav": "score", "job": job, "key": key, "title": "Report", "trait": trait, "preset": label,
        "crumbs": [("Score SNPs", reverse("snpportal:upload")), ("Results", f"{base}?{urlencode({'trait': trait, **filters})}"),
                   ("Report", None)],
        "meta": " · ".join(x for x in [job.get("label"), f"{job['n_rows']:,} SNPs" if job.get("n_rows") is not None else None,
                                       f"preset {label}", f"release {job.get('release')}", f"printed {jobs.utc()}"] if x),
        "actions": [{"label": "Back to the results", "url": f"{base}?{urlencode({'trait': trait, **filters})}"}],
        "kpis": ov["kpis"], "figs": figs, "panel": panel(request, key, d), "rows": rows, "matching": matching, "filters": filters, "columns": columns,
        "table_url": f"{base}?{urlencode({'tab': 'table', 'trait': trait, **filters})}",
        "paragraphs": paragraphs, "refs": refs, "provenance": [line[2:] for line in jobs.provenance(job, trait, filters)],
        "provisional": jobs.manifest(d).get("provisional") or [], "expires": jobs.utc(jobs.expires(key)),
        "synthetic": bool(job.get("synthetic_input") or job.get("synthetic_layers") or tools.chip_info(d).get("synthetic"))})
