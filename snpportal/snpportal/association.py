"""GWAS summary statistics (ROADMAP M7, Wave D): the GWAS upload and example (P7.1), the Association page with a
one-line upload QC, a Manhattan plot, the loci table and a closed tier-stratified QQ plot (P7.2), the regional
association plot over the locus browser's lanes with the locus's credible sets (P7.3), Wakefield ABF fine-mapping with
uniform vs functional priors (P7.4) and the GWAS line of a SNP's evidence card.

A GWAS job is an ordinary job with input_kind 'gwas': jobs.run reads the statistics (snpscore.gwas.prepare:
sumstats.parquet, gwas.json), annotates their positions, and snpscore.gwas.attach writes gwas.parquet (alleles turned
to Ssal_v3.1, keyed by the result's file_row_number). Loci and fine-mapping come from gwas.parquet and the tiers of
the chosen preset, once per trait and settings (loci/<hash>.json and .parquet in the job folder); every setting is a
whitelisted URL parameter (defaults: weights.yaml 'finemap', PROVISIONAL) that every link of these pages keeps. The
figure functions below are pure (plain data -> SVG with literal palette hex)."""
from __future__ import annotations

import math
import os
import re
import uuid
from decimal import Decimal
from html import escape
from pathlib import Path
from urllib.parse import urlencode

from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.datastructures import MultiValueDict
from django.utils.safestring import mark_safe
from django.views.decorators.csrf import csrf_exempt, csrf_protect
from django.views.decorators.debug import sensitive_post_parameters

from snpscore import gwas as sg
from snpscore import locus as sl
from snpscore import panel as snp_panel
from snpscore.formats import lit

from . import explore, figures, jobs, locus, locus_svg, palette, results, views
from .jobs import ident

G = palette.GREY
SUFFIXES = (".fastgwa", ".linear", ".logistic", ".hybrid", ".regenie", ".mlma", ".assoc", ".stats", ".tsv", ".txt",
            ".csv", ".tab")  # accepted upload endings, optionally + .gz; the layout is read from the content
EXAMPLE = "gwas_maturation_SYNTHETIC"  # release demo/ file offered as the GWAS example
FIELDS = {  # URL parameter -> (finemap setting, lowest, highest); the window is given in kb. sugg <= 0.01 keeps clumping fast
    "sig": ("significant", 1e-300, 0.05), "sugg": ("suggestive", 1e-300, 0.01), "window": ("window", 10, 5000),
    "prior_sd": ("prior_sd", 0.01, 5), "lam": ("functional_lambda", 0, 3), "trait_sd": ("trait_sd", 1e-9, 1e9)}
LABELS = {"sig": ("Significant p", ""), "sugg": ("Suggestive p", ""), "window": ("Window ± kb", ""),  # the closed settings form
          "prior_sd": ("Prior effect SD", "W = SD squared, on the standardised scale"),
          "lam": ("Functional λ", "prior proportional to exp(λ × tier score); 0 = uniform"),
          "trait_sd": ("Trait SD", "betas are divided by this; default: the SD that se, N and allele frequency imply, else 1 "
                                   "(a standardised trait)")}
CAP = 60  # -log10 p drawn at most this high; stronger points are triangles at the top
DROPS = {"missing_chrom": "no chromosome", "bad_pos": "position not a whole number",
         "unknown_chrom": "not on chromosomes 1-29 (e.g. unplaced scaffolds)", "other_test": "not the additive test (TEST is not ADD)",
         "bad_p": "p outside (0, 1]", "no_p": "no p, z or beta/se", "duplicate": "duplicate (same position and alleles)"}
HARMONISED = {"ok": "already on the Ssal_v3.1 reference", "swapped": "effect allele was the reference: beta, z and af flipped",
              "strand_flip": "other strand: alleles complemented", "strand_flip_swapped": "other strand and flipped",
              "unchecked": "not checked (no genome sequence or public site)", "mismatch": "alleles don't match the genome (kept as given)",
              "not_snp": "not a SNP (kept as given)", "no_alleles": "no alleles in the file"}
OK_ALLELES = {"ok", "swapped", "strand_flip", "strand_flip_swapped"}  # harmonised to Ssal_v3.1; others open the QC details
ASSUMPTIONS = ("Fine-mapping assumes one causal variant per locus and uses no LD (no public LD reference yet); "
               "results are sensitive to the prior effect SD (W) and to lambda.")
SHOW_CS = 10  # credible-set rows shown under the regional plot before 'Show all'
MAX_LOCI = 200  # loci fine-mapped and listed, strongest first (the page says when there are more)


def chrom_key(c):
    return (0, int(c), "") if str(c).isdigit() else (1, 0, str(c))


# ---- the GWAS upload and example (POST from the Score page) ----

def suffix_of(name):
    """The upload's ending if it is a summary-statistics file ('.fastgwa', '.tsv.gz', ...), else None."""
    name = name.lower()
    gz = ".gz" if name.endswith(".gz") else ""
    base = name[:-3] if gz else name
    return next((s + gz for s in SUFFIXES if base.endswith(s)), None)


@csrf_exempt  # so the upload handler can be set before the body is read; _score checks the CSRF token
def score(request):
    """POST a summary-statistics file (or the example) -> a GWAS job -> its Association page."""
    if request.method != "POST":
        return redirect(f"{reverse('snpportal:upload')}#gwas")
    max_mb = float(jobs.setting("SNPPORTAL_MAX_UPLOAD_MB", 300))
    try:
        length = int(request.META.get("CONTENT_LENGTH") or 0)
    except ValueError:
        length = 0
    if length > max_mb * 2 ** 20:
        return views.score_page(request, f"The upload is larger than {max_mb:g} MB. Compress it with gzip, or run "
                                         "snpscore on your own computer (see 'Run it locally').", 413)
    request.exception_reporter_filter = views.PrivateReports()
    handler = views.UploadToResults(request)
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
    preset = request.POST.get("trait", "all")
    preset = preset if preset in dict(jobs.presets()) else "all"
    example, upload = request.POST.get("example"), request.FILES.get("sumstats")
    try:
        if example:
            found = views.examples().get(example) if example.startswith("gwas_") else None
            if found is None:
                raise jobs.InputError("That example is not part of this release.")
            key = jobs.create(found["path"], found["suffix"], "gwas", preset, "Example: synthetic maturation GWAS",
                              synthetic=found["synthetic"], move=False)
        elif upload:
            suffix = suffix_of(upload.name)
            if suffix is None:
                raise jobs.InputError("Upload summary statistics as a table (.tsv, .txt, .csv, optionally gzipped) or as "
                                      "GCTA-fastGWA, PLINK2 .glm, regenie, BOLT-LMM or GEMMA output.")
            if not upload.size:
                raise jobs.InputError("The uploaded file is empty.")
            key = jobs.create(Path(upload.path), suffix, "gwas", preset, "Uploaded GWAS summary statistics")
        else:
            raise jobs.InputError("Choose a summary-statistics file or the GWAS example.")
    except jobs.InputError as e:
        return views.score_page(request, str(e), 400)
    except jobs.QueueFull:
        response = views.score_page(request, "The portal is busy scoring other lists. Please try again in a minute.", 503)
        response["Retry-After"] = "60"
        return response
    return redirect(f"{reverse('snpportal:association', args=[key])}?{urlencode({'trait': preset})}")


# ---- settings, data and analysis for one request ----

def settings(request, weights, report=None):
    """Fine-mapping and loci settings: weights.yaml 'finemap' (provisional), the trait SD the statistics imply (gwas.json
    `report`, as snpscore gwas does), then the request's whitelisted overrides. A value as the form shows the default
    (e.g. the implied trait SD to 6 digits) is the default, so the trait SD stays 'estimated', not 'given'."""
    changes, shown = {}, form_values(sg.settings(weights, report)) if request else {}
    for param, (name, low, high) in FIELDS.items():
        given = request.GET.get(param, "").strip() if request else ""
        try:
            value = float(given)
        except ValueError:
            continue
        if given != shown.get(param) and math.isfinite(value) and low <= value <= high:
            changes[name] = int(value * 1000) if name == "window" else value
    cfg = sg.settings(weights, report, **changes)
    cfg["suggestive"] = max(cfg["suggestive"], cfg["significant"])
    return cfg


def finemap_used(a):
    """The settings used, as snpscore gwas records them in gwas.json 'finemap' (the DEFAULTS keys and trait_sd_source),
    for snpscore.export.methods_text(finemap=). An snpscore whose settings() has no trait_sd_source: worked out here."""
    cfg = a["cfg"]
    source = cfg.get("trait_sd_source") or (
        "given" if cfg["trait_sd"] != a["defaults"]["trait_sd"] else "estimated from se, N and allele frequency"
        if a["report"].get("trait_sd_estimate") else "weights.yaml (1 = a standardised trait)")
    return {**{k: cfg[k] for k in sg.DEFAULTS}, "trait_sd_source": source}


def form_values(cfg):
    """{URL parameter: value as shown} of the settings form."""
    return {"sig": f"{cfg['significant']:g}", "sugg": f"{cfg['suggestive']:g}", "window": f"{cfg['window'] / 1000:g}",
            "prior_sd": f"{cfg['prior_sd']:g}", "lam": f"{cfg['functional_lambda']:g}", "trait_sd": f"{cfg['trait_sd']:g}"}


def query_of(request):
    """The request's fine-mapping settings as given (FIELDS only), for every link that must open the same loci."""
    return {k: request.GET[k][:40] for k in FIELDS if request.GET.get(k)} if request else {}


def url(name, key, a, **params):
    """A link to page `name` of job `key` that keeps the analysis' trait and settings."""
    return f"{reverse(name, args=[key])}?{urlencode({'trait': a['trait'], **a['query'], **params})}"


def gwas_job(key):
    """job.json of a finished GWAS job, else 404."""
    job = views.finished(key)
    if job.get("input_kind") != "gwas" or not (jobs.folder(key) / "gwas.parquet").exists():
        raise Http404("These results have no GWAS summary statistics")
    return job


def analyse(request, key):
    """{con (view g: gwas.parquet with the trait's tiers, genes (the catalogue's names for genes Ensembl leaves
    unnamed), region and LORe; view fm: the fine-mapping), cfg, defaults (cfg without the request's settings), loci
    (the MAX_LOCI strongest), total (all loci), fm (locus -> summary), trait, d, n, query (the request's settings),
    report (gwas.json)}. Clumping and fine-mapping run once per trait and settings; later requests read
    loci/<hash>.json and .parquet."""
    con, types, _, chosen = results.open_result(request, key, write=True)
    trait, d = chosen["trait"], jobs.folder(key)
    w, report = jobs.weights(d), jobs.read_json(d / "gwas.json") or {}
    cfg = settings(request, w, report)
    keep = [c for c in ("tier", "tier_score", "tier_evidence", "region_class", "gene_name", "gene_ortholog_human",
                        "gene_id", "lore", "known_locus") if c in types]
    names = explore.aliases() if {"gene_name", "gene_id"} <= set(keep) else {}
    alias = ("LEFT JOIN (VALUES " + ", ".join(f"({lit(g)}, {lit(n)})" for g, n in names.items()) + ") a(gene_id, alias) "
             "ON a.gene_id = v.gene_id") if names else ""
    cols = "".join(", coalesce(v.gene_name, a.alias) AS gene_name" if c == "gene_name" and alias else f", v.{ident(c)}" for c in keep)
    con.execute(f"CREATE VIEW g AS SELECT s.*{cols} FROM read_parquet({lit(d / 'gwas.parquet')}) s JOIN v USING (file_row_number) {alias}")
    folder, h = d / "loci", snp_panel.params_hash({"v": 1, "trait": trait, "max_loci": MAX_LOCI, **cfg})
    saved = jobs.read_json(folder / f"{h}.json")
    if not saved:  # table fm stays from finemap; later requests read it back from the parquet
        loci = [{k: float(v) if isinstance(v, Decimal) else v for k, v in x.items()} for x in sg.clump(con, "g", cfg)]
        total, loci = len(loci), loci[:MAX_LOCI]
        fm = sg.finemap(con, "g", loci, cfg)
        saved = {"loci": loci, "total": total, "n": con.execute("SELECT count(*) FROM g").fetchone()[0], "fm": fm}
        folder.mkdir(mode=0o700, exist_ok=True)
        if loci:
            tmp = folder / f".tmp-{uuid.uuid4().hex}.parquet"
            con.execute(f"COPY fm TO {lit(tmp)} (FORMAT parquet)")
            os.chmod(tmp, 0o600)
            os.replace(tmp, folder / f"{h}.parquet")
        jobs._write_json(folder / f"{h}.json", saved)  # last, so a .json means its parquet is complete
        saved = jobs.read_json(folder / f"{h}.json") or saved  # as later requests read it (JSON keys are strings)
    elif saved["loci"]:
        con.execute(f"CREATE VIEW fm AS SELECT * FROM read_parquet({lit(folder / f'{h}.parquet')})")
    loci, total, n, fm = saved["loci"], saved["total"], saved["n"], {int(k): v for k, v in saved["fm"].items()}
    return {"con": con, "cfg": cfg, "defaults": settings(None, w, report), "loci": loci, "total": total, "fm": fm, "trait": trait,
            "d": d, "n": n, "types": types, "query": query_of(request), "report": report}


def lines_of(cfg, n):
    """Threshold lines: [(-log10 p, label, dash, tooltip)], labelled as conventions."""
    out = [(-math.log10(cfg["significant"]), f"p {cfg['significant']:.0e} convention", "",
            f"p {cfg['significant']:.0e}: genome-wide significance (a convention, not a rule for salmon)")]
    if n:
        bonf = 0.05 / n
        out.append((-math.log10(bonf), f"Bonferroni {bonf:.1e}", "6 3", f"Bonferroni 0.05/{n:,} = {bonf:.1e}"))
    out.append((-math.log10(cfg["suggestive"]), f"p {cfg['suggestive']:.0e} suggestive", "2 3",
                f"p {cfg['suggestive']:.0e}: suggestive threshold (loci start below it)"))
    return out


def provenance(job, a):
    """'#' lines for downloads and captions: the job's provenance plus the GWAS settings and the CLI command."""
    cfg = a["cfg"]
    lines = [x for x in jobs.provenance(job, a["trait"]) if not x.startswith("# equivalent command")]
    lines.append(f"# GWAS settings (PROVISIONAL defaults, weights.yaml finemap): significant {cfg['significant']:g}, suggestive "
                 f"{cfg['suggestive']:g}, window {int(cfg['window']):,} bp, prior_sd {cfg['prior_sd']:g} (W {cfg['prior_sd'] ** 2:g}), "
                 f"functional lambda {cfg['functional_lambda']:g}, trait_sd {cfg['trait_sd']:g} ({finemap_used(a)['trait_sd_source']}), "
                 f"coverage {cfg['coverage']:g}")
    lines.append("# " + ASSUMPTIONS)
    lines.append(f"# equivalent command: snpscore gwas <your summary statistics> --release <release {job.get('release')}> "
                 f"--trait {a['trait']}")
    return lines


# ---- figures: pure functions (plain data -> SVG) ----

def _dots(points, colour, width, outline=None):
    """Many points as one path of zero-length round-capped strokes (compact: about 12 bytes a point)."""
    if not points:
        return ""
    d = "".join(f"M{x:.1f} {y:.1f}h0" for x, y in points)
    under = (f'<path d="{d}" stroke="{outline}" stroke-width="{width + 1.4}" stroke-linecap="round"/>' if outline else "")
    return under + f'<path d="{d}" stroke="{colour}" stroke-width="{width}" stroke-linecap="round"/>'


def _yaxis(x, sy, top, step, label, height_px, t):
    out = [f'<line x1="{x}" x2="{x}" y1="{sy(0):.1f}" y2="{sy(top):.1f}" stroke="{G[500]}"/>']
    v = 0
    while v <= top + 1e-9:
        out.append(f'<line x1="{x - 4}" x2="{x}" y1="{sy(v):.1f}" y2="{sy(v):.1f}" stroke="{G[500]}"/>'
                   + figures._text(x - 6, sy(v) + 3.5, f"{v:g}", "end", font_size=10, fill=G[700]))
        v += step
    out.append(f'<text x="14" y="{t + height_px / 2:.0f}" text-anchor="middle" font-size="11" fill="{G[700]}" '
               f'transform="rotate(-90 14 {t + height_px / 2:.0f})">{escape(label)}</text>')
    return "".join(out)


def _step(top):
    k = 10 ** math.floor(math.log10(max(top, 1) / 5))
    return next(m * k for m in (1, 2, 5, 10) if top / (m * k) <= 6)


def manhattan_svg(points, sizes, lines, leads, title, desc, synthetic=False):
    """points: [(chrom, pos, -log10 p, tier)]; sizes: {chrom: length}; lines: [(-log10 p, label, dash, tooltip)]; leads:
    [{chrom, pos, neglog10p, label, url}]. Chromosomes in alternating greys, tier 1-2 SNPs on top in tier colours,
    points above CAP as triangles at the top; points are de-duplicated per half pixel. The threshold labels sit in the
    right-hand margin, outside the data, pushed apart when their lines are close."""
    width, height, left, right, top_px, bottom = 1100, 350, 58, 126, 28, 42
    chroms = sorted({p[0] for p in points} | {x["chrom"] for x in leads}, key=chrom_key)
    span = {c: sizes.get(c) or max([p[1] for p in points if p[0] == c] + [1]) for c in chroms}
    gap = 4 if len(chroms) > 1 else 0
    avail = width - left - right - gap * max(0, len(chroms) - 1)
    total = sum(span.values()) or 1
    x0, x = {}, left
    for c in chroms:
        x0[c], x = x, x + avail * span[c] / total + gap
    ymax = min(CAP, max([p[2] for p in points] + [x[0] for x in lines] + [1]) * 1.05)
    step = _step(ymax)
    ymax = math.ceil(ymax / step) * step
    h = height - top_px - bottom
    sy = lambda v: top_px + h - h * min(v, ymax) / ymax
    sx = lambda c, pos: x0[c] + avail * pos / total
    body, grey, tiers, capped, seen = [], ([], []), {1: [], 2: []}, [], set()
    order = {c: i for i, c in enumerate(chroms)}
    for c, pos, nlp, tier in points:
        px, py = sx(c, pos), sy(nlp)
        if nlp > ymax:
            capped.append((px, c, pos, nlp))
            continue
        coloured = tier in (1, 2) and nlp >= 2  # tier colours only above the thinned background (p <= 0.01)
        cell = (round(px * 2), round(py * 2), tier if coloured else 0)
        if cell in seen:
            continue
        seen.add(cell)
        (tiers[tier] if coloured else grey[order[c] % 2]).append((px, py))
    for i, c in enumerate(chroms):
        if i % 2:
            body.append(f'<rect x="{x0[c] - gap / 2:.1f}" y="{top_px}" width="{avail * span[c] / total + gap:.1f}" height="{h}" fill="{G[50]}"/>')
    body.append(_yaxis(left - 6, sy, ymax, step, "-log10 p", h, top_px))
    body.append(_dots(grey[0], G[700], 2.6) + _dots(grey[1], G[500], 2.6))
    for t in (2, 1):
        body.append(_dots(tiers[t], palette.TIERS[t][0], 3.4, G[900]))
    for px, c, pos, nlp in capped:
        body.append(f'<path d="M{px:.1f} {top_px - 1} l4 7 l-8 0z" fill="{G[900]}"><title>{escape(c)}:{pos:,} '
                    f'p {sg.p_text(nlp)} (above the axis)</title></path>')
    red, labels, last = palette.STATUS["fail"][0], [], -99
    for y, label, dash, tip in sorted((x for x in lines if x[0] <= ymax), key=lambda x: -x[0]):  # top line first
        dashed = f' stroke-dasharray="{dash}"' if dash else ""
        body.append(f'<line x1="{left}" x2="{width - right}" y1="{sy(y):.1f}" y2="{sy(y):.1f}" stroke="{red}"{dashed}><title>{escape(tip)}</title></line>')
        last = max(sy(y) + 3.5, last + 12)  # labels at least 12 px apart
        labels.append(f'<g><title>{escape(tip)}</title>' + figures._text(width - right + 6, last, label, font_size=10, fill=red) + "</g>")
    for x in leads:
        px, py = sx(x["chrom"], x["pos"]), sy(x["neglog10p"])
        mark = (f'<path d="M{px:.1f} {py - 7:.1f} l6 7 l-6 7 l-6 -7z" fill="{palette.WHITE}" stroke="{G[900]}" stroke-width="1.6">'
                f'<title>{escape(x["label"])}</title></path>')
        body.append(f'<a href="{escape(x["url"])}">{mark}</a>' if x.get("url") else mark)
    last = -99
    for c in chroms:
        mid = x0[c] + avail * span[c] / total / 2
        if mid - last > 14:
            body.append(figures._text(mid, height - bottom + 16, c, "middle", font_size=10, fill=G[700]))
            last = mid
    body += labels
    body.append(figures._text((left + width - right) / 2, height - 8, "chromosome (Ssal_v3.1)", "middle", font_size=11, fill=G[700]))
    body.append(figures._legend([(palette.TIERS[1][0], "tier 1"), (palette.TIERS[2][0], "tier 2 (p <= 0.01, drawn on top)"),
                                 (palette.WHITE, "diamond: locus lead, opens its regional plot")], left + 4, 6))
    return figures.svg(width, height, title, desc, "".join(body), synthetic)


def qq_svg(strata, colours, labels, band, title, desc, synthetic=False):
    """strata: {key: {n, lambda, points [(expected, observed)]}}; band [(expected, low, high)] for all SNPs."""
    width, height, left, top_px, size = 560, 470, 58, 16, 360
    emax = max([e for s in strata.values() for e, _ in s["points"]] + [1])
    omax = min(CAP, max([o for s in strata.values() for _, o in s["points"]] + [emax]))
    xstep, step = _step(emax), _step(omax)
    xmax, ymax = math.ceil(emax / xstep) * xstep, math.ceil(omax * 1.02 / step) * step
    sx = lambda v: left + size * min(v, xmax) / xmax
    sy = lambda v: top_px + size - size * min(v, ymax) / ymax
    body = []
    if band:
        upper = " ".join(f"{sx(e):.1f},{sy(hi):.1f}" for e, lo, hi in band)
        lower = " ".join(f"{sx(e):.1f},{sy(lo):.1f}" for e, lo, hi in reversed(band))
        body.append(f'<polygon points="{upper} {lower}" fill="{G[200]}"><title>95% interval of the expected order statistics (all SNPs)</title></polygon>')
    body.append(f'<line x1="{sx(0):.1f}" y1="{sy(0):.1f}" x2="{sx(min(xmax, ymax)):.1f}" y2="{sy(min(xmax, ymax)):.1f}" stroke="{G[500]}" stroke-dasharray="4 3"/>')
    body.append(_yaxis(left - 6, sy, ymax, step, "observed -log10 p", size, top_px))
    v = 0
    while v <= xmax + 1e-9:
        body.append(f'<line x1="{sx(v):.1f}" x2="{sx(v):.1f}" y1="{top_px + size}" y2="{top_px + size + 4}" stroke="{G[500]}"/>'
                    + figures._text(sx(v), top_px + size + 16, f"{v:g}", "middle", font_size=10, fill=G[700]))
        v += xstep
    body.append(figures._text(left + size / 2, top_px + size + 32, "expected -log10 p", "middle", font_size=11, fill=G[700]))
    for key in reversed(list(strata)):  # first stratum (e.g. tier 1) drawn last, on top
        pts = [(sx(e), sy(o)) for e, o in strata[key]["points"] if o <= ymax]
        body.append(_dots(pts, colours.get(key, G[500]), 3.4, G[900]))
        for e, o in strata[key]["points"]:
            if o > ymax:
                body.append(f'<path d="M{sx(e):.1f} {top_px - 1} l4 7 l-8 0z" fill="{G[900]}"><title>{escape(labels.get(key, str(key)))}: '
                            f'p {sg.p_text(o)} (above the axis)</title></path>')
    y = top_px
    for key, s in strata.items():
        lam = f"{s['lambda']:.3f}" if s["lambda"] is not None else "n/a"
        body.append(f'<circle cx="{left + size + 22}" cy="{y + 6}" r="4.5" fill="{colours.get(key, G[500])}" stroke="{G[900]}" stroke-width="0.6"/>'
                    + figures._text(left + size + 32, y + 10, labels.get(key, str(key)), font_size=11)
                    + figures._text(left + size + 32, y + 24, f"n {s['n']:,} · λGC {lam}", font_size=10, fill=G[700]))
        y += 34
    return figures.svg(width, height, title, desc, "".join(body), synthetic)


def pip_svg(panels, title, desc, synthetic=False):
    """Slope chart per locus: each SNP of either credible set from its PIP under the uniform prior (left) to the
    functional prior (right), coloured by tier. panels: [{title, sub, rows [(label, tier, pip_u, pip_f)]}]."""
    pw, ph, per_row = 216, 250, 5
    rows_n = max(1, math.ceil(len(panels) / per_row))
    width, height = pw * min(per_row, max(1, len(panels))) + 40, ph * rows_n + 30
    body = []
    for i, p in enumerate(panels):
        ox, oy = 40 + (i % per_row) * pw, 8 + (i // per_row) * ph
        xa, xb, yt, yb = ox + 24, ox + pw - 96, oy + 40, oy + ph - 34
        sy = lambda v: yb - (yb - yt) * v
        body.append(figures._text(ox, oy + 12, p["title"], font_size=11.5, font_weight="600")
                    + figures._text(ox, oy + 26, p["sub"], font_size=10, fill=G[700]))
        for v in (0, 0.5, 1):
            body.append(f'<line x1="{xa - 4}" x2="{xb}" y1="{sy(v):.1f}" y2="{sy(v):.1f}" stroke="{G[200]}"/>'
                        + figures._text(xa - 6, sy(v) + 3.5, f"{v:g}", "end", font_size=9, fill=G[700]))
        body.append(figures._text(xa, yb + 16, "uniform", "middle", font_size=9.5, fill=G[700])
                    + figures._text(xb, yb + 16, "functional", "middle", font_size=9.5, fill=G[700]))
        labelled = sorted(p["rows"], key=lambda r: -r[3])[:3]
        free = []
        for label, tier, pu, pf in sorted(p["rows"], key=lambda r: -(r[1] or 4)):
            fill = palette.TIERS.get(tier or 4, palette.TIERS[4])[0]
            stroke = fill if (tier or 4) <= 2 else G[500]
            tip = f"{label}: tier {tier}, PIP {pu:.3f} uniform -> {pf:.3f} functional"
            body.append(f'<g><title>{escape(tip)}</title><line x1="{xa}" y1="{sy(pu):.1f}" x2="{xb}" y2="{sy(pf):.1f}" stroke="{stroke}" stroke-width="1.6"/>'
                        f'<circle cx="{xa}" cy="{sy(pu):.1f}" r="3.5" fill="{fill}" stroke="{G[900]}" stroke-width="0.6"/>'
                        f'<circle cx="{xb}" cy="{sy(pf):.1f}" r="3.5" fill="{fill}" stroke="{G[900]}" stroke-width="0.6"/></g>')
        for label, tier, pu, pf in labelled:
            y = sy(pf) + 3.5
            if all(abs(y - other) > 11 for other in free):
                body.append(figures._text(xb + 7, y, label[:16], font_size=9.5, fill=G[900]))
                free.append(y)
    if not panels:
        body.append(figures._text(40, 30, "No locus could be fine-mapped (needs se, or N and allele frequencies).", font_size=11, fill=G[700]))
    body.append(f'<text x="14" y="{height / 2:.0f}" text-anchor="middle" font-size="11" fill="{G[700]}" transform="rotate(-90 14 {height / 2:.0f})">PIP</text>')
    return figures.svg(width, height, title, desc, "".join(body), synthetic)


# ---- figures for a job ----

FIGURES = {  # name -> (title, definition)
    "manhattan": ("Manhattan plot", "-log10 p of every SNP along the genome. SNPs with p > 0.01 are thinned to the strongest per "
                  "50 kb; tier 1-2 SNPs for the trait are drawn on top in tier colours. Lines: genome-wide significance, "
                  "Bonferroni and suggestive thresholds (conventions, not rules for salmon). Diamonds mark locus leads: click "
                  "one for its regional plot."),
    "qq": ("QQ plot by tier", "Observed against expected -log10 p per tier for the trait, each thinned to about 2,000 "
           "quantiles, with lambda_GC = median(z^2)/0.4549 per tier. Grey band: 95% interval of the expected order "
           "statistics for all SNPs. A tier lifting off the diagonal earlier than others is enriched for association, but "
           "tiers differ in size and allele frequency."),
    "pip": ("How the functional prior shifts PIPs", "Posterior inclusion probability (PIP) of each SNP in either 95% "
            "credible set, under a uniform prior (left) and a functional prior proportional to exp(lambda x tier_score) "
            "(right), per locus. Wakefield approximate Bayes factors with one causal variant per locus and no LD."),
}


def figure_data(a, name, job, key, link=True):
    """(svg, header, rows) of a figure for the analysis `a`. Provenance goes in the SVG's <desc> only."""
    con, cfg, trait, synthetic = a["con"], a["cfg"], a["trait"], bool(job.get("synthetic_input") or job.get("synthetic_layers"))
    caption = f"Release {job.get('release')} · trait {trait} · job created {job.get('created_utc')} · thresholds and priors PROVISIONAL"
    desc = FIGURES[name][1] + " " + caption + (" · SYNTHETIC test data" if synthetic else "")
    if name == "manhattan":
        points = sg.manhattan(con, "g")
        sizes = {c: int(s) for c, s in (jobs.manifest(a["d"]).get("chrom_sizes") or {}).items()}
        leads = [{"chrom": x["chrom"], "pos": x["lead"], "neglog10p": x["neglog10p"],
                  "label": f"Locus {x['locus']}: {x['id']} p {sg.p_text(x['neglog10p'])}",
                  "url": url("snpportal:association_region", key, a, locus=x["locus"]) if link else None}
                 for x in a["loci"]]
        svg = manhattan_svg(points, sizes, lines_of(cfg, a["n"]), leads, FIGURES[name][0], desc, synthetic)
        return svg, ["chrom", "pos", "neglog10p", "tier"], sorted(points, key=lambda p: (chrom_key(p[0]), p[1]))
    if name == "qq":
        strata = sg.qq(con, "g", "tier")
        band = next(iter(sg.qq(con, "g", "'all'").values()), {}).get("band", [])
        labels = {t: f"tier {t}" for t in palette.TIERS}
        svg = qq_svg(strata, {t: palette.TIERS[t][0] for t in palette.TIERS}, labels, band, FIGURES[name][0], desc, synthetic)
        rows = [(labels.get(k, k), round(e, 4), round(o, 4)) for k, s in strata.items() for e, o in s["points"]]
        return svg, ["stratum", "expected_neglog10p", "observed_neglog10p"], rows
    mapped = [x for x in a["loci"] if a["fm"].get(x["locus"], {}).get("n")]
    tier = "tier" if "tier" in a["types"] else "NULL"
    rows = con.execute(f"""SELECT locus, coalesce(id, chrom || ':' || pos), {tier}, pip_uniform, pip_functional, pos, cs_uniform, cs_functional
                           FROM fm WHERE cs_uniform OR cs_functional
                           QUALIFY row_number() OVER (PARTITION BY locus ORDER BY greatest(pip_uniform, pip_functional) DESC, pos) <= 15
                           ORDER BY locus, greatest(pip_uniform, pip_functional) DESC, pos""").fetchall() if mapped else []
    panels = []
    for x in mapped[:10]:  # the drawn loci
        s = a["fm"][x["locus"]]
        panels.append({"title": f"Locus {x['locus']} · chr{x['chrom']}", "sub": f"credible set {s['size_uniform']} → {s['size_functional']} SNPs",
                       "rows": [r[1:5] for r in rows if r[0] == x["locus"]]})
    svg = pip_svg(panels, FIGURES[name][0], desc, synthetic)
    return svg, ["locus", "snp", "tier", "pip_uniform", "pip_functional", "pos", "cs_uniform", "cs_functional"], rows


def figure_card(a, name, svg, key):
    url = reverse("snpportal:association_figure", args=[key, name])
    query = urlencode({"trait": a["trait"], **a["query"]})
    return {"name": name, "title": FIGURES[name][0], "svg": mark_safe(svg), "svg_url": f"{url}?{query}",
            "tsv_url": f"{url}?{query}&format=tsv", "info": FIGURES[name][1]}


# ---- pages ----

def card_url(key, row, a):
    return f"{reverse('snpportal:card', args=[key, row])}?{urlencode({'trait': a['trait'], **a['query']})}"


def loci_rows(a, key):
    """The loci table: one dict per locus with its links and its top SNP by PIP under the uniform prior, plus the
    functional prior's top SNP where it differs (top, top_f: {id, tier, card})."""
    tops, tier = {}, "tier" if "tier" in a["types"] else "NULL"
    if a["loci"]:
        label = "coalesce(id, chrom || ':' || pos)"
        tops = {r[0]: r[1:] for r in a["con"].execute(f"""
            SELECT locus, arg_max(file_row_number, pip_uniform), arg_max({tier}, pip_uniform), arg_max({label}, pip_uniform),
                   arg_max(file_row_number, pip_functional), arg_max({tier}, pip_functional), arg_max({label}, pip_functional)
            FROM fm GROUP BY locus""").fetchall()}
    out = []
    for x in a["loci"]:
        top = tops.get(x["locus"])
        u = {"id": top[2], "tier": top[1], "card": card_url(key, top[0], a)} if top else None
        f = {"id": top[5], "tier": top[4], "card": card_url(key, top[3], a)} if top and top[3] != top[0] else None
        out.append({**x, "p": sg.p_text(x["neglog10p"]), "fm": a["fm"].get(x["locus"], {}), "top": u, "top_f": f,
                    "card": card_url(key, x["row"], a) if x.get("row") is not None else None,
                    "region": url("snpportal:association_region", key, a, locus=x["locus"]),
                    "gene_tip": explore.UNNAMED_TIP if (x.get("gene") or "").startswith("~") else ""})
    return out


def qc_items(report, cfg):
    """(label, value) rows of the GWAS upload QC details."""
    items = [("Format detected", report.get("format")), ("Rows read", report.get("rows_read")), ("Rows kept", report.get("kept"))]
    items += [(f"Dropped: {DROPS.get(k, k)}", v) for k, v in (report.get("dropped") or {}).items()]
    items += [("Rows with beta and se", f"{100 * (report.get('with_beta_se') or 0):.1f}%"),
              ("Rows with z recovered from p", report.get("z_from_p")), ("Rows with N and allele frequency", report.get("with_af_n")),
              ("λGC = median(z²)/0.4549", report.get("lambda_gc")), ("Smallest p", report.get("min_p")),
              ("Rows at p < 5e-8", report.get("n_significant")),
              ("Trait SD used (betas are divided by it)", f"{cfg['trait_sd']:.3g}"),
              ("Trait SD implied by se, N and af", f"{report['trait_sd_estimate']:.3g}" if report.get("trait_sd_estimate")
               else "n/a (needs N and allele frequency)")]
    items += [(f"Alleles: {HARMONISED.get(k, k)}", v) for k, v in (report.get("harmonised") or {}).items()]
    if report.get("unknown_chromosomes"):
        items.append(("Most common dropped chromosome names", ", ".join(f"{u['name']} ({u['rows']:,})" for u in report["unknown_chromosomes"][:5])))
    return items


def qc_line(report, cfg):
    """(the QC in one line, problem). A problem opens the QC details by itself: dropped rows or unknown chromosomes,
    beta/se missing, z recovered from p, alleles not checked or not matching the genome, or a trait SD far from the
    one se, N and af imply (snpscore.gwas.trait_sd_implied: betas on another scale than the trait SD used)."""
    read, kept, beta = report.get("rows_read") or 0, report.get("kept") or 0, report.get("with_beta_se") or 0
    odd = sum(n for k, n in (report.get("harmonised") or {}).items() if k not in OK_ALLELES)
    lam = report.get("lambda_gc")
    parts = [f"{read:,} rows read, " + ("all kept" if kept == read else f"{kept:,} kept"),
             "beta/se on " + ("all" if beta >= 1 else f"{100 * beta:.0f}%"), f"λGC {lam:.2f}" if lam is not None else "λGC n/a",
             f"{report.get('n_significant') or 0:,} SNPs at p < 5e-8", f"smallest p {report.get('min_p')}",
             f"alleles of {odd:,} rows not checked or not matching" if odd else "alleles on Ssal_v3.1"]
    implied = (sg.trait_sd_implied(report, cfg) if hasattr(sg, "trait_sd_implied")  # an older snpscore: only the sentence
               else report.get("trait_sd_estimate") if sg.trait_sd_warning(report, cfg) else None)
    if implied:  # e.g. betas in phenotype units with trait SD 1: every Bayes factor is about 1 and the prior alone ranks SNPs
        parts.append(f"trait SD {cfg['trait_sd']:.3g} but se, N and af imply {implied:.3g}: PIPs unreliable")
    problem = kept < read or beta < 1 or bool(report.get("z_from_p") or report.get("unknown_chromosomes")) or odd > 0 or bool(implied)
    return " · ".join(parts), problem


@views.private
def association(request, key):
    """The Association page: progress while the job runs, the error if it failed, else the QC line, Manhattan, loci,
    PIPs and a closed QQ plot; the fine-mapping settings are closed (and open by themselves when changed)."""
    jobs.cleanup()
    job = jobs.status(key)
    if job is None:
        return render(request, "snpportal/expired.html", {"nav": "score", "title": "Results expired or deleted"}, status=404)
    ctx = {"nav": "score", "job": job, "key": key, "synthetic": bool(job.get("synthetic_input") or job.get("synthetic_layers")),
           "title": " · ".join(x for x in [job.get("label") or "Results", f"{job['n_rows']:,} SNPs" if job.get("n_rows") is not None else None] if x),
           "crumbs": [("Score SNPs", reverse("snpportal:upload")), ("Results", None)], "meta": f"Deleted after {jobs.utc(jobs.expires(key))}"}
    if job["state"] == "done":
        gwas_job(key)
        a = analyse(request, key)
        d, query = a["d"], urlencode({"trait": a["trait"], **a["query"]})
        values, defaults = form_values(a["cfg"]), form_values(a["defaults"])
        weights, report = jobs.weights(d), a["report"]
        ctx.update(trait=a["trait"], query=query, loci=loci_rows(a, key), release_changed=jobs.release_changed(job),
                   presets=[(v, label, results.trait_tip(weights, v)) for v, label in jobs.presets(d)],
                   figs={name: figure_card(a, name, figure_data(a, name, job, key)[0], key) for name in FIGURES},
                   fields=[(k, LABELS[k][0], values[k], LABELS[k][1]) for k in FIELDS], values=values,
                   changed=sum(values[k] != defaults[k] for k in FIELDS), settings=a["query"].items(),
                   qc=qc_items(report, a["cfg"]), qc_line=qc_line(report, a["cfg"]), finemapped=any(s.get("n") for s in a["fm"].values()),
                   total=a["total"], max_loci=MAX_LOCI)
        ctx["actions"] = [{"label": "Export", "url": f"{reverse('snpportal:results', args=[key])}?{query}&tab=export"},
                          {"label": "Report", "url": f"{reverse('snpportal:report', args=[key])}?{query}"},
                          {"label": "Score another list", "url": reverse("snpportal:upload")}]
    ctx.setdefault("actions", []).append(
        {"label": "Delete", "url": reverse("snpportal:delete", args=[key]), "post": True, "style": "btn-outline-danger",
         "confirm": "Delete these results now? This can't be undone."})
    return render(request, "snpportal/association.html", ctx)


def snp_line(request, key, row, job):
    """The GWAS line of a SNP's evidence card (None outside GWAS jobs): {p, beta, se} and, inside a locus window, the
    locus (the one where its PIP is highest), its PIPs under both priors and its credible-set membership."""
    if job.get("input_kind") != "gwas" or not (jobs.folder(key) / "gwas.parquet").exists():
        return None
    a = analyse(request, key)
    hit = a["con"].execute("SELECT neglog10p, beta, se FROM g WHERE file_row_number = ?", [row]).fetchone()
    if hit is None:
        return None
    out = {"p": sg.p_text(hit[0]), "beta": hit[1], "se": hit[2], "locus": None}
    fm = a["con"].execute("""SELECT locus, pip_uniform, pip_functional, cs_uniform, cs_functional FROM fm WHERE file_row_number = ?
                             ORDER BY greatest(pip_uniform, pip_functional) DESC LIMIT 1""", [row]).fetchone() if a["loci"] else None
    if fm:
        sets = [name for name, inside in (("uniform", fm[3]), ("functional", fm[4])) if inside]
        out.update(locus=fm[0], pip_u=fm[1], pip_f=fm[2],
                   region=url("snpportal:association_region", key, a, locus=fm[0]),
                   cs="in both 95% credible sets" if len(sets) == 2 else f"in the {sets[0]} prior's 95% credible set" if sets
                   else "outside the 95% credible sets")
    return out


@views.private
def figure(request, key, name):
    """A figure as a standalone SVG (no links) or, with ?format=tsv, its data with '#' provenance lines."""
    job = gwas_job(key)
    if name not in FIGURES:
        raise Http404("No such figure")
    a = analyse(request, key)
    svg, header, rows = figure_data(a, name, job, key, link=False)
    if request.GET.get("format") == "tsv":
        lines = [] if request.GET.get("plain") else provenance(job, a)
        body = "\n".join(lines + ["\t".join(header)] + ["\t".join("" if v is None else str(v) for v in r) for r in rows]) + "\n"
        response = HttpResponse(body, content_type="text/tab-separated-values; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{name}_{a["trait"]}.tsv"'
        return response
    response = HttpResponse(svg, content_type="image/svg+xml")
    response["Content-Disposition"] = f'attachment; filename="{name}_{a["trait"]}.svg"'
    return response


@views.private
def download(request, key):
    """?format=loci (TSV), bed (loci) or finemap (every SNP of every locus window with both PIPs and credible sets)."""
    job = gwas_job(key)
    a = analyse(request, key)
    fmt = request.GET.get("format", "loci")
    lines = [] if request.GET.get("plain") else provenance(job, a)
    if fmt == "bed":
        body = "".join(f"{x['chrom']}\t{min(x['start'], x['lead']) - 1}\t{max(x['end'], x['lead'])}\tlocus{x['locus']}_{x['id']}\t"
                       f"{min(1000, round(10 * x['neglog10p']))}\n" for x in a["loci"])
        name, kind = f"gwas_loci_{a['trait']}.bed", "text/plain"
    elif fmt == "finemap":
        if not a["loci"]:
            raise Http404("No loci")
        rows = a["con"].execute("SELECT * EXCLUDE (file_row_number) FROM fm ORDER BY locus, pip_functional DESC")
        header = [c[0] for c in rows.description]
        body = "\t".join(header) + "\n" + "".join("\t".join("" if v is None else str(v) for v in r) + "\n" for r in rows.fetchall())
        name, kind = f"gwas_finemap_{a['trait']}.tsv", "text/tab-separated-values"
    elif fmt == "loci":
        header = ["locus", "chrom", "lead", "id", "p", "neglog10p", "beta", "se", "significant", "start", "end", "n_snps",
                  "n_significant", "n_tier12_near", "candidate", "candidate_tier", "candidate_gene", "gene", "lore",
                  "cs_size_uniform", "cs_size_functional", "prior_ratio"]
        body = "\t".join(header) + "\n"
        for x in a["loci"]:
            s = a["fm"].get(x["locus"], {})
            values = {**x, "p": sg.p_text(x["neglog10p"]), "cs_size_uniform": s.get("size_uniform"),
                      "cs_size_functional": s.get("size_functional"), "prior_ratio": s.get("prior_ratio")}
            body += "\t".join("" if values.get(h) is None else str(values.get(h)) for h in header) + "\n"
        name, kind = f"gwas_loci_{a['trait']}.tsv", "text/tab-separated-values"
    else:
        raise Http404("Unknown format")
    response = HttpResponse("".join(f"{line}\n" for line in lines) + body, content_type=f"{kind}; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{name}"'
    return response


# ---- the regional association plot (P7.3) ----

def lane(a, chrom, start, end, key, locus_id=None, link=True):
    """locus_svg.gwas_lane data for a window: the job's SNPs with -log10 p, tier, shape and credible-set outline
    (functional prior) of locus `locus_id`."""
    con = a["con"]
    lead = next((x for x in a["loci"] if x["locus"] == locus_id), None)
    has_fm = bool(a["loci"]) and any(s.get("n") for s in a["fm"].values())
    fm = (f"LEFT JOIN (SELECT file_row_number, pip_uniform, pip_functional, cs_functional FROM fm WHERE locus = {int(locus_id or 0)}) f "
          "USING (file_row_number)") if has_fm else ""
    cols = "f.pip_uniform, f.pip_functional, f.cs_functional" if has_fm else "NULL, NULL, NULL"
    region = "g.region_class" if "region_class" in a["types"] else "NULL"
    rows = con.execute(f"""SELECT g.file_row_number, g.pos, g.neglog10p, g.tier, g.id, g.ref, g.alt, {region}, {cols}
                           FROM g {fm} WHERE g.chrom = ? AND g.pos > ? AND g.pos <= ?
                           ORDER BY g.neglog10p DESC LIMIT 5000""", [chrom, start, end]).fetchall()
    points = []
    for row, pos, nlp, tier, sid, ref, alt, region_class, pu, pf, cs in rows:
        kind = "lead" if lead and pos == lead["lead"] else "coding" if region_class in ("CDS", "splice_region") else ""
        pips = f" · PIP {pu:.3f} uniform, {pf:.3f} functional" if pu is not None else ""
        title = (f"{sid or '(no id)'} · {chrom}:{pos:,}" + (f" {ref}>{alt}" if ref and alt else "") + f" · p {sg.p_text(nlp)} · tier {tier}"
                 + (f" · {region_class.replace('_', ' ')}" if region_class else "") + pips + (" · in the 95% credible set" if cs else ""))
        points.append({"pos": pos, "neglog10p": nlp, "tier": tier, "kind": kind, "cs": bool(cs), "title": title,
                       "url": card_url(key, row, a) if link else None})
    return {"points": points, "significant": -math.log10(a["cfg"]["significant"]), "note": "No LD used: colours are tiers, not r²"}


def browser_lane(request, key, chrom, start, end, link=True):
    """The association lane for the locus browser when job `key` is a GWAS job (else None), for
    locus_svg.locus(gwas=...): the credible-set rings are those of the locus whose lead is in the window."""
    job = jobs.read(key)
    if not job or job.get("input_kind") != "gwas" or not (jobs.folder(key) / "gwas.parquet").exists():
        return None
    a = analyse(request, key)
    number = next((x["locus"] for x in a["loci"] if x["chrom"] == chrom and start < x["lead"] <= end), None)
    return lane(a, chrom, start, end, key, number, link)


def window_of(a, x):
    """BED window around locus x: the lead +- (farthest credible-set member + 20 kb), between 50 and 250 kb."""
    far = a["con"].execute("SELECT max(abs(pos - ?)) FROM fm WHERE locus = ? AND (cs_uniform OR cs_functional)",
                           [x["lead"], x["locus"]]).fetchone()[0] if a["fm"].get(x["locus"], {}).get("n") else None
    half = int(min(250_000, max(50_000, (far or 0) + 20_000)))
    return x["lead"] - 1 - half, x["lead"] + half


def credible(a, x, key):
    """Every SNP in locus x's 95% credible set under either prior, highest PIP first: [{id, alleles, p, tier, pip_u,
    pip_f, set, card}]."""
    if not a["fm"].get(x["locus"], {}).get("n"):
        return []
    tier = "tier" if "tier" in a["types"] else "NULL"
    rows = a["con"].execute(f"""SELECT file_row_number, coalesce(id, chrom || ':' || pos), ref, alt, neglog10p, {tier},
                                       pip_uniform, pip_functional, cs_uniform, cs_functional
                                FROM fm WHERE locus = ? AND (cs_uniform OR cs_functional)
                                ORDER BY greatest(pip_uniform, pip_functional) DESC, pos""", [x["locus"]]).fetchall()
    return [{"id": sid, "alleles": f"{ref}>{alt}" if ref and alt else "", "p": sg.p_text(nlp), "tier": t, "pip_u": pu, "pip_f": pf,
             "set": "both" if cu and cf else "uniform" if cu else "functional", "card": card_url(key, row, a)}
            for row, sid, ref, alt, nlp, t, pu, pf, cu, cf in rows]


@views.private
def region(request, key):
    """The regional association plot: the GWAS lane (about 250 px) above genes, published loci, the trait's chromatin
    rows and GERP on one x axis, then the locus's credible-set SNPs under both priors (first SHOW_CS, ?all=1 for all).
    ?locus=N or ?r=chrom:start-end; ?download=1 gives the standalone SVG file (with its title and provenance)."""
    job = gwas_job(key)
    a = analyse(request, key)
    number = int(request.GET["locus"]) if request.GET.get("locus", "").isdecimal() else (a["loci"][0]["locus"] if a["loci"] else None)
    x = next((x for x in a["loci"] if x["locus"] == number), None)
    if request.GET.get("r"):
        try:
            chrom, start, end = sl.parse_region(request.GET["r"][:200], jobs.release())
        except ValueError as e:
            raise Http404(str(e)) from None
        x = next((y for y in a["loci"] if y["chrom"] == chrom and start < y["lead"] <= end), x)
    elif x is not None:
        chrom, (start, end) = x["chrom"], window_of(a, x)
    else:
        raise Http404("No locus")
    size = (jobs.manifest().get("chrom_sizes") or {}).get(chrom)
    start, end = sl.clamp(max(0, start), end, size, sl.MIN_WINDOW, sl.MAX_WINDOW)
    download = bool(request.GET.get("download"))
    s = {"chrom": chrom, "start": start, "end": end, "size": size, "trait": a["trait"], "assay": "ATAC", "hmm": False,
         "scale": "shared", "key": None, "row": None, "mark": x["lead"] if x and x["chrom"] == chrom else None,
         "compact": False, "too_wide": False, "error": None}
    inner, notes, synthetic = locus.draw(request, s, download, show=locus.REGION_LANES)
    synthetic = synthetic or bool(job.get("synthetic_input") or job.get("synthetic_layers"))
    data = lane(a, chrom, start, end, key, x["locus"] if x else None, link=not download)
    head = (f"Locus {x['locus']} · {chrom}:{start + 1:,}-{end:,} · lead {x['id']}" if x and x["chrom"] == chrom
            else f"Region {chrom}:{start + 1:,}-{end:,}")
    body, h = locus_svg.gwas_figure(data, chrom, start, end, head if download else "", height=250)
    inner_h = float(re.search(r'height="([\d.]+)"', inner).group(1))
    desc = (f"{head}. -log10 p of the job's SNPs coloured by tier for trait {a['trait']}; diamond: lead; triangles: CDS or "
            "splice; dark ring: 95% credible set under the functional prior. No LD is used. Below: genes, published loci, "
            f"the trait's chromatin rows and GERP. Release {job.get('release')}, job created {job.get('created_utc')}; "
            "thresholds, priors and track sets PROVISIONAL" + ("; SYNTHETIC test data." if synthetic else "."))
    svg = figures.svg(locus_svg.WIDTH, h + inner_h, head, desc, body + inner.replace("<svg ", f'<svg x="0" y="{h:.0f}" ', 1), synthetic)
    if download:
        response = HttpResponse(svg, content_type="image/svg+xml")
        response["Content-Disposition"] = f'attachment; filename="gwas_region_{chrom}_{start + 1}_{end}.svg"'
        return response
    q = urlencode({"trait": a["trait"], **a["query"], **({"r": request.GET["r"][:200]} if request.GET.get("r") else {"locus": x["locus"]} if x else {})})
    wider = "{}:{}-{}".format(chrom, max(1, start + 1 - (end - start)), end + (end - start))
    shown = "{}:{}-{}".format(chrom, start + 1, end)
    here = reverse("snpportal:association_region", args=[key])
    rows = credible(a, x, key) if x else []
    return render(request, "snpportal/association_region.html", {
        "nav": "score", "job": job, "key": key, "title": head, "svg": mark_safe(svg), "notes": notes, "synthetic": synthetic,
        "loci": loci_rows(a, key), "current": x, "trait": a["trait"], "file_name": f"gwas_region_{chrom}_{start + 1}_{end}",
        "svg_url": f"{here}?{q}&download=1", "wider": url("snpportal:association_region", key, a, r=wider),
        "browser": f"{reverse('snpportal:locus')}?{urlencode({'r': shown, 'key': key, 'trait': a['trait'], **a['query']})}",
        "credible": rows if request.GET.get("all") == "1" else rows[:SHOW_CS], "n_credible": len(rows), "all_url": f"{here}?{q}&all=1#credible",
        "finemap_url": url("snpportal:association_download", key, a, format="finemap"),
        "crumbs": [("Results", url("snpportal:results", key, a, tab="overview")),
                   ("Association", url("snpportal:association", key, a)), ("Locus", None)]})
