"""Predictions on demand (G, 2026-11-25: "see the effect with a button in the snp card ... on demand from the
server"): the SNP card's button runs a sequence model for that one SNP where the portal runs, and shows what the
model predicts for each allele. The models are lib/models.yaml's (the gill ChromBPNet model first) and lib/predict.py
runs them; this module is the card's button, the two addresses behind it and the result.

A job's SNP is named by its job and row, so its position is in no address; a variant page's is public already.
Nothing is stored: the last results stay in this process's memory, so a second click costs nothing. Without the
packages the model needs (numpy and onnxruntime, not in the base install) the card says how to get them."""
from __future__ import annotations

import os
from collections import OrderedDict
from pathlib import Path

from django.http import Http404
from django.shortcuts import render
from django.urls import reverse
from django.utils.safestring import mark_safe

from . import figures, jobs, palette, results
from .lib import predict as lp
from .views import private

CACHE_SIZE = 256
_CACHE = OrderedDict()  # (model, version, chrom, pos, ref, alt) -> lib.predict.predict's result


def models_dir():
    """Where the models' files are kept once fetched: SNPPORTAL_MODELS_DIR, else models/ beside the results folder
    (the data folder of a local install)."""
    return Path(jobs.setting("SNPPORTAL_MODELS_DIR", "") or jobs.results_dir().parent / "models")


def buttons(snp, url):
    """The card's buttons for one row: [{name, label, what, url, missing}] for a single-base SNP of an assembly with
    models, else []. `url(name)` gives the address of a model's prediction; `missing` says how to get the packages
    when this install lacks them (then there is no button)."""
    ref, alt = str(snp.get("ref") or ""), str(snp.get("alt") or "")
    if results.is_sv(snp) or len(ref) != 1 or len(alt) != 1:
        return []
    absent = lp.missing_packages()
    missing = f"needs {' and '.join(absent)} in this install: {lp.INSTALL}" if absent else ""
    return [{"name": m["name"], "label": m["label"], "what": m["what"], "url": url(m["name"]), "missing": missing}
            for m in lp.models(jobs.manifest().get("assembly", ""))]


def share(x):
    """A percentile (0 to 1) as a percentage for a sentence: one decimal, and never a rounded-up '100.0'."""
    return ">99.9" if x >= 0.9995 else f"{100 * x:.1f}"


def result(model, p, ref, alt):
    """What the result fragment shows of one prediction `p` (lib.predict.predict) for the row's alleles ref>alt."""
    up = p["effect"] > 0
    words = model.get("direction") or ["higher", "lower"]
    colour = palette.EFFECTS["up" if up else "down"]
    title = f"{model['label']}: predicted signal with each allele at {p['chrom']}:{p['pos']:,}"
    desc = (f"{model['label']} {p['version']} (fold {p['fold']} model): predicted Tn5 cuts per base with the ref allele {p['ref']} "
            f"and the alt allele {p['alt']}. A model's prediction, not a measurement.")
    return {"p": p, "up": up, "way": words[0 if up else 1] if p["effect"] else "the same", "arrow": "↑" if up else "↓" if p["effect"] else "",
            "effect": results.score_number(p["effect"], sign=True), "ref_counts": f"{p['ref_counts']:.1f}", "alt_counts": f"{p['alt_counts']:.1f}",
            "top": max(1, round(100 * (1 - p["percentile"]))) if p["percentile"] >= 0.5 else None, "percentile": share(p["percentile"]),
            "jsd": results.score_number(p["jsd"]), "jsd_percentile": share(p["jsd_percentile"]), "window": f"{len(p['ref_profile']):,}",
            "quantile": results.score_number(p["active_allele_quantile"]), "reference": model.get("reference") or "the model's reference SNPs",
            "other_strand": f"{ref}>{alt}" if p["other_strand"] else "",
            "figure": mark_safe(figures.profiles(p["ref_profile"], p["alt_profile"], p["ref"], p["alt"], colour, title, desc))}


def fragment(request, name, chrom, pos, ref, alt):
    """The result of one model for one SNP, as the HTML that replaces the card's button."""
    model = next((m for m in lp.models(jobs.manifest().get("assembly", "")) if m["name"] == name), None)
    if model is None:
        raise Http404("No such model for this assembly")
    from . import locus  # imported here: locus imports this module for the card
    ctx = {"model": model, "local": bool(jobs.setting("SNPPORTAL_LOCAL", False))}
    key = (name, model.get("version"), str(chrom), int(pos), str(ref).upper(), str(alt).upper())
    try:
        p = _CACHE.get(key)
        if p is None:
            threads = 2 if (os.cpu_count() or 1) > 1 else 1
            p = lp.predict(model, models_dir() / name / str(model.get("version", "")), locus.reference, chrom, int(pos), ref, alt, threads)
            _CACHE[key] = p
            while len(_CACHE) > CACHE_SIZE:
                _CACHE.popitem(last=False)
        _CACHE.move_to_end(key)
        ctx.update(result(model, p, ref, alt))
    except (lp.NotScored, lp.Unavailable) as e:
        ctx["problem"] = str(e)
    return render(request, "snpportal/_predict.html", ctx)


@private
def job(request, key, row, name):
    """A job's SNP: the address names the job and the row, and the position is read here."""
    from . import locus
    locus.finished(key)
    con, types, _, _ = results.open_result(request, key)
    hit = con.execute(results.CARD_SQL, [row]).fetchone()
    if hit is None:
        raise Http404("No such SNP")
    snp = dict(zip(types, hit))
    if not buttons(snp, lambda n: ""):
        raise Http404("No model for this row")
    return fragment(request, name, snp["chrom"], snp["pos"], snp["ref"], snp["alt"])


@private
def variant(request, spec, name):
    """A variant page's SNP, /snp/variant/<chrom>-<pos>-<ref>-<alt>/predict/<model>/."""
    from . import locus
    from .lib import locus as sl
    m = locus.VARIANT.match(spec)
    if not m or not m.group(3) or not m.group(4):
        raise Http404("Write the variant as chrom-pos-ref-alt, e.g. 25-28996360-C-T")
    try:
        chrom = sl.resolve_chrom(jobs.release(), m.group(1))
    except ValueError as e:
        raise Http404(str(e)) from None
    return fragment(request, name, chrom, int(m.group(2)), m.group(3), m.group(4))


def job_buttons(snp, key, row):
    return buttons(snp, lambda name: reverse("snpportal:predict_job", args=[key, row, name]))


def variant_buttons(snp, spec):
    return buttons(snp, lambda name: reverse("snpportal:predict_variant", args=[spec, name]))
