"""Breeder tools on a finished job (ROADMAP P6.3, P6.4, P6.6): the Panel tab (compare with a chip, then design a
panel), the Export tab and its downloads, and the figures of both.

lib.panel and lib.export do the work. This module turns whitelisted URL parameters into their arguments,
keeps each panel as panels/<hash>.parquet (+ .json) and the chip as chip.parquet (+ chip.json) in the job folder (they
expire with the job), and draws the figures. The hash is of the parameters, so the same URL gives the same file. The
designer's form is POSTed (must-include ids are the user's SNP names: never in a URL) and shows the panel by its hash.
Design defaults, the chip window W and the assay rules come from the job's weights.yaml snapshot: all PROVISIONAL."""
from __future__ import annotations

import inspect
import json
import math
import os
import re
import tempfile
import uuid
import zipfile
from datetime import datetime
from functools import wraps
from urllib.parse import urlencode

import duckdb
from django.http import FileResponse, Http404, HttpResponse, HttpResponseNotAllowed
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.datastructures import MultiValueDict
from django.utils.safestring import mark_safe
from django.views.decorators.csrf import csrf_exempt, csrf_protect
from django.views.decorators.debug import sensitive_post_parameters

import snpscore
from .lib import export as snp_export, panel as snp_panel
from snpscore.formats import lit

from . import figures, jobs, palette, results

EXPORTS = ("tsv", "parquet", "bed", "illumina", "axiom", "kasp", "agena", "primer3", "bundle", "priors")  # ?format=
VENDORS = ("illumina", "axiom", "kasp", "agena", "primer3")
MAX_TARGET = 20_000  # largest panel the form designs
MAX_MUST = 200  # must-include ids per panel
SHOWN = 25  # selected SNPs listed on the page, then 'Show all' (up to LISTED; the exports have all)
LISTED = 500
BIN = 250_000  # bp per tick in the coverage strips (about one pixel of the longest chromosome)
TOP_GAPS = 5  # chip gaps listed on the page (the figure's TSV has all)
EXCLUDE = {  # panel exclusion checkbox = a result column -> label
    "blacklist": "blacklisted region", "lore": "LORe region", "strand_ambiguous": "A/T or C/G alleles",
    "flank_variants": "public variants within 35 bp", "near_chip": "near a chip marker (within W)"}
REASONS = {"must_include": ("must include", "One of your must-include ids"),  # selection_reason -> (label, tooltip)
           "backbone": ("backbone", "The best SNP in its genome bin, so every chromosome is covered"),
           "functional": ("functional", "Tier 1–3, by design score"), "fill": ("fill", "Tier 4, by design score")}
BINDING = {"min_spacing": "the minimum spacing", "min_spacing_cm": "the minimum spacing in cM", "max_per_gene": "the per-gene cap",
           "max_per_element": "the per-element cap"}
CM_MAPS = {"mean": "sex-averaged", "female": "female", "male": "male"}  # lib.panel.CM_MAPS
FORMATS = [  # (format, label, contents) of the Export tab's rows; vendor rows add their counts and checks
    ("tsv", "Table (TSV)", "Every annotation column, one row per SNP."),
    ("kasp", "KASP", ""), ("illumina", "Illumina", ""), ("axiom", "Axiom", ""),
    ("agena", "Agena MassARRAY", ""), ("primer3", "Primer3 (amplicon, GT-seq)", ""),  # I14: layouts PROVISIONAL
    ("bundle", "Everything (zip)", "The table, BED and vendor files, with methods, provenance and figures."),
]
MORE_FORMATS = [("parquet", "Parquet", "the same columns; provenance in the file's metadata"),
                ("bed", "BED", "chrom, pos − 1, pos and the SNP name, for genome browsers"),
                ("priors", "Genomic-prediction priors (zip)", "SNP categories for BayesRC, GFBLUP/MultiBLUP and LDAK")]  # P6.5
MIME = {"tsv": "text/tab-separated-values; charset=utf-8", "bed": "text/plain; charset=utf-8", "parquet": "application/vnd.apache.parquet",
        "bundle": "application/zip", "priors": "application/zip", **{v: "text/csv; charset=utf-8" for v in VENDORS},
        "primer3": "text/plain; charset=utf-8"}
CHIP_ERRORS = {  # ?chip_error= -> message (codes only: no file content or names in URLs)
    "missing": "Choose a chip file, or use the demo chip.",
    "type": "This file type isn't accepted for a chip. Upload a manifest or table (.csv, .tsv, .txt, optionally gzipped), "
            "a VCF or a PLINK .bim/.map file.",
    "size": "The chip file is too large. Compress it with gzip, or keep only the chromosome and position columns.",
    "format": "The chip file could not be read. It needs chromosome and position columns (e.g. Chr/MapInfo, CHROM/POS) or "
              "a VCF, PLINK or Illumina/Axiom manifest layout: see Help for the accepted formats.",
    "empty": "None of the chip's positions are on Ssal_v3.1 chromosomes 1–29. Are they on another assembly (ICSASG_v2)? "
             "Then tick 'Positions on another assembly' to place the markers by their flank sequences.",
    "icsasg_v2": "The chip's positions could not be converted from ICSASG_v2 with this release.",
    "fsalsal1": "The chip's positions could not be converted from fSalSal1 with this release.",
    "flank": "The chip's markers could not be placed by flank sequence: the file needs a column of flank or probe sequences "
             "(Axiom 'Flank', Illumina 'SourceSeq' or 'TopGenomicSeq', with the SNP as [A/B]), and the release flank keys.",
    "rows": "The chip file has more than {cap} markers. Keep only the markers you need, or compare it on your own "
            "computer with python -m snpportal.lib.cli compare (see Run it locally).",
}
MAX_CHIP = 1_000_000  # chip markers read in the request (SNPPORTAL_MAX_CHIP_SNPS, at most SNPPORTAL_MAX_SNPS)
MUST = re.compile(r"[\w.:-]{1,60}")


def _views():
    from . import views  # views imports this module: import it when first needed
    return views


def private(view):
    """views.private (no-store, same-origin referrers, content-free error reports), applied when called."""
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        return _views().private(view)(request, *args, **kwargs)
    return wrapped


# ---- the job's result, with the preset's tiers and the chip columns ----

def _columns(con, rel):
    return dict(con.execute(f"SELECT column_name, column_type FROM (DESCRIBE SELECT * FROM {rel})").fetchall())


def _open(d, trait, weights, selected=False):
    """Sandboxed connection that reads the job folder and the release (genome neighbours, pool) and writes only the
    job folder, with view v = the result plus the tiers of `trait` (as on the Table tab) and, when the job has a chip,
    view vc = v plus on_chip, dist_to_chip, near_chip and novel_functional (results.chip_view). With `selected`, v
    holds only the SNPs of the Table's selection (the Panel designs from it). Returns (con, view name, its types)."""
    con = jobs.connect([d, jobs.release()], d)
    con.execute(f"CREATE VIEW r AS SELECT * FROM read_parquet({lit(d / 'result.parquet')}, file_row_number=true)")
    columns = _columns(con, "r")
    tiers, suffix = jobs.trait_tiers(d, weights, trait) if weights else (None, None)
    stored = _columns(con, f"read_parquet({lit(tiers)})") if tiers else {}
    picked = [c for c in jobs.TIER_COLUMNS if f"{c}__{suffix}" in stored]
    if picked:
        drop = [c for c in jobs.TIER_COLUMNS if c in columns]
        keep = f"r.* EXCLUDE ({', '.join(drop)})" if drop else "r.*"
        con.execute(f"CREATE VIEW v0 AS SELECT {keep}, " + ", ".join(f"t.{jobs.ident(c + '__' + suffix)} AS {c}" for c in picked)
                    + f" FROM r JOIN read_parquet({lit(tiers)}) t USING (file_row_number)")
    elif weights:
        con.execute(f"CREATE VIEW v0 AS {jobs.scored_sql('r', weights, list(columns), trait, d)}")
    else:
        con.execute("CREATE VIEW v0 AS SELECT * FROM r")
    where = results._where(results.filters(results.selection_request(results.selection(d)), _columns(con, "v0"), weights)
                           + [m for m in [results.manual(d)] if m]) if selected else ""  # the − rows stay out
    con.execute(f"CREATE VIEW v AS SELECT * FROM v0 {where}")
    view = "v"
    chipped = results.chip_view(con, d, "v", weights)
    if chipped:
        con.execute(f"CREATE VIEW vc AS {chipped}")
        view = "vc"
    return con, view, _columns(con, view)


def chip_info(d):
    """chip.json of the job's chip ({} without one): label, synthetic, kept, rejected, sha256, density, results."""
    return jobs.read_json(d / "chip.json") if (d / "chip.parquet").exists() else {}


def _synthetic(job, chip_used=False):
    return bool(job.get("synthetic_input") or job.get("synthetic_layers") or chip_used)


def _meta(job, trait, synthetic, filters=None, panel=None, command=None):
    """Provenance fields for lib.export (never SNPs or file names)."""
    meta = {"tool": "salmobase functional SNP portal", "preset": trait, "filters": filters or {}, "panel": panel,
            "synthetic": synthetic, "created_utc": job.get("created_utc"), "input_sha256": job.get("input_sha256"),
            "manifest_sha256": job.get("manifest_sha256"), "weights_sha256": job.get("weights_sha256")}
    if command:
        meta["command"] = command
    return meta


def _provenance(d, job, trait, synthetic, **extra):
    weights = d / "weights.yaml"
    return snp_export.provenance(d / "manifest.json", weights if weights.exists() else None, _meta(job, trait, synthetic, **extra))


def _bp(x):
    """A distance as text: 850 bp, 12.5 kb, 3.20 Mb."""
    if x is None:
        return "–"
    return f"{x:,.0f} bp" if x < 1000 else f"{x / 1000:,.1f} kb" if x < 1e6 else f"{x / 1e6:,.2f} Mb"


def _cm(x):
    return "–" if x is None else f"{x:.2f} cM"


def _nice(x):
    """x rounded down to 1, 2 or 5 times a power of ten."""
    if x <= 0:
        return 1.0
    p = 10 ** math.floor(math.log10(x))
    return next(m * p for m in (5, 2, 1) if m * p <= x)


def _number(text, cast, lo, hi, default):
    try:
        value = cast(text)
    except (TypeError, ValueError):
        return default
    return value if lo <= value <= hi else default


def _chroms(d, extra=()):
    """[(chrom, length)] in karyotype order: the job's manifest chrom_sizes, plus any chromosome in `extra`."""
    sizes = {k: int(v) for k, v in (jobs.manifest(d).get("chrom_sizes") or {}).items()}
    for chrom, end in extra:
        sizes[chrom] = max(sizes.get(chrom, 0), int(end))
    return sorted(sizes.items(), key=lambda x: results._chrom_key(x[0]))


# ---- figures ----

def coverage(chroms, marks, title, desc="", synthetic=False, gaps=(), density=None, counts=None, legend=(), link=None):
    """Chromosomes to scale with tick marks, highlighted gaps and an optional density lane (plain data -> SVG).
    chroms [(chrom, length)]; marks [(chrom, start, end, fill, tooltip)], at least 1.5 px wide; gaps [(chrom, start,
    end, tooltip)]; density [(chrom, start, end, share 0-1, tooltip)] in a thin lane above the marks; counts {chrom: n}
    printed on the right; legend [(fill, label)]; link(chrom, start, end) -> href for a gap."""
    left, track, right, top = 34, 560, 64, 26
    lane = 8 if density is not None else 0
    row = 16 + lane
    width = left + track + right
    longest = max([size for _, size in chroms] + [1])
    scale = track / longest
    y_of = {c: top + i * row for i, (c, _) in enumerate(chroms)}
    _, warn_bg, warn_border = palette.STATUS["warn"]
    parts = [figures._text(left - 8, 12, "Mb", "end", fill=palette.GREY[700], font_size=10)]
    for mb in range(0, int(longest / 1e6) + 1, 20):
        x = left + mb * 1e6 * scale
        parts.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="16" y2="{top + len(chroms) * row - 4}" stroke="{palette.GREY[200]}"/>'
                     + figures._text(x, 12, mb, "middle", fill=palette.GREY[700], font_size=10))
    for chrom, size in chroms:
        y = y_of[chrom]
        parts.append(figures._text(left - 6, y + lane + 10, chrom, "end", font_size=11))
        if lane:
            parts.append(f'<rect x="{left}" y="{y + 1}" width="{size * scale:.1f}" height="{lane - 2}" fill="{palette.WHITE}" '
                         f'stroke="{palette.GREY[300]}"/>')
        parts.append(f'<rect x="{left}" y="{y + lane + 1}" width="{size * scale:.1f}" height="11" rx="2" fill="{palette.WHITE}" '
                     f'stroke="{palette.GREY[300]}"/>')
        if counts is not None:
            parts.append(figures._text(width - 4, y + lane + 10, f"{counts.get(chrom, 0):,}", "end", font_size=11))
    for chrom, a, b, tip in gaps:
        if chrom in y_of:
            parts.append(figures._rect(left + a * scale, y_of[chrom], max((b - a) * scale, 2), lane + 13, warn_bg, tip,
                                       link and link(chrom, a, b), f' stroke="{warn_border}" fill-opacity="0.85"'))
    for chrom, a, b, share, tip in density or ():
        if chrom in y_of:
            parts.append(figures._rect(left + a * scale, y_of[chrom] + 1, max((b - a) * scale, 1), lane - 2,
                                       figures.mix(palette.GREY[200], palette.GREY[700], share), tip))
    for chrom, a, b, fill, tip in marks:
        if chrom in y_of:
            parts.append(figures._rect(left + a * scale, y_of[chrom] + lane + 1, max((b - a) * scale, 1.5), 11, fill, tip))
    y = top + len(chroms) * row + 6
    parts.append(figures._legend(legend, left, y) if legend else "")
    return figures.svg(width, y + 18, title, desc, "".join(parts), synthetic)


def _tier_fill(tier):
    return figures.IDEOGRAM_TIER4 if tier in (None, 4) else palette.TIERS.get(int(tier), palette.TIERS[4])[0]


def _gap_legend(label):
    return (palette.STATUS["warn"][1], label)


def _fig_coverage(c, link, desc):
    p = c["panel"]
    ident = "id::VARCHAR" if "id" in _columns(c["con"], p["rel"]) else "NULL::VARCHAR"  # lists without ids have no id column
    rows = c["con"].execute(f"""SELECT chrom, pos // {BIN} * {BIN} AS b, min(tier), count(*), min(panel_rank), min(pos), any_value({ident})
                                FROM {p['rel']} GROUP BY ALL ORDER BY ALL""").fetchall()
    marks = [(chrom, b, b + BIN, _tier_fill(t), f"rank {rank}: {name or f'{chrom}:{pos:,}'}, tier {t}" if n == 1 else
              f"{chrom}:{b / 1e6:.2f}–{(b + BIN) / 1e6:.2f} Mb: {n} markers (best tier {t})") for chrom, b, t, n, rank, pos, name in rows]
    ends = c["con"].execute(f"SELECT chrom, count(*), max(pos) FROM {p['rel']} GROUP BY 1").fetchall()
    counts = {chrom: n for chrom, n, _ in ends}
    gap = p["gap_bp"]
    gaps = [(g["chrom"], g["start"], g["end"], f"{g['chrom']}:{g['start']:,}–{g['end']:,}: {_bp(g['size'])} without a marker")
            for g in p["gaps"] if g["size"] > gap]
    href = (lambda chrom, a, b: link(chrom=chrom, start=a, end=b)) if link else None
    legend = [(_tier_fill(t), figures.TIER_NAMES[t]) for t in (1, 2, 3, 4)] + [_gap_legend(f"gap > {gap / 1e6:g} Mb")]
    svg = coverage(_chroms(c["d"], [(chrom, end) for chrom, _, end in ends]), marks, f"Panel markers along the genome, {c['preset']}",
                   desc, c["synthetic"], gaps, counts=counts, legend=legend, link=href)
    tsv = c["con"].execute(f"SELECT panel_rank, chrom, pos, {ident}, tier, selection_reason FROM {p['rel']} ORDER BY panel_rank").fetchall()
    return svg, ["panel_rank", "chrom", "pos", "id", "tier", "selection_reason"], tsv


def _fig_chip(c, link, desc):
    chip = c["chip"]
    res = chip["results"][_chip_tag(c["d"], c["trait"])]
    top = max([n for _, _, n in chip["density"]] + [1])
    density = [(chrom, mb * 1_000_000, (mb + 1) * 1_000_000, n / top, f"{chrom}:{mb}–{mb + 1} Mb: {n:,} chip markers")
               for chrom, mb, n in chip["density"]]
    marks = [(chrom, b, b + BIN, _tier_fill(t), f"{chrom}:{b / 1e6:.2f}–{(b + BIN) / 1e6:.2f} Mb: {n:,} novel functional SNPs "
              f"(best tier {t})") for chrom, b, t, n in res["novel_bins"]]
    gaps = [(g["chrom"], g["start"], g["end"], f"Chip gap {g['chrom']}:{g['start']:,}–{g['end']:,} ({_bp(g['size'])})"
             + (f"; best SNP {g['filler']['chrom']}:{g['filler']['pos']:,}, tier {g['filler']['tier']} ({g['filler']['source']})"
                if g["filler"] else "; no SNP to fill it")) for g in res["gaps"]]
    counts, ends = {}, {}
    for chrom, mb, n in chip["density"]:
        counts[chrom], ends[chrom] = counts.get(chrom, 0) + n, max(ends.get(chrom, 0), mb * 1_000_000 + 1)
    href = (lambda chrom, a, b: link(chrom=chrom, start=a, end=b)) if link else None
    legend = [(figures.mix(palette.GREY[200], palette.GREY[700], 0.6), "chip markers per Mb"),
              (palette.TIERS[1][0], "novel functional, tier 1"), (palette.TIERS[2][0], "tier 2"),
              _gap_legend(f"chip gap > {res['summary']['gap_bp'] / 1e6:g} Mb")]
    svg = coverage(_chroms(c["d"], ends.items()), marks, f"Chip coverage and novel functional SNPs, {c['preset']}",
                   desc, c["synthetic"], gaps, density, counts, legend, href)
    tsv = [(g["chrom"], g["start"], g["end"], g["size"], *((g["filler"][k] for k in ("chrom", "pos", "id", "tier", "source"))
                                                         if g["filler"] else ("",) * 5)) for g in res["gaps"]]
    return svg, ["chrom", "from", "to", "length", "best_chrom", "best_pos", "best_id", "best_tier", "best_source"], tsv


FIGURES = {  # name -> (card title, (i) definition, builder(context, link or None, desc) -> (svg, header, rows) or None)
    "panel-coverage": ("Panel markers along the genome", "Chromosomes to scale (Ssal_v3.1). A tick per marker (per 250 kb "
                       "when they are close), coloured by tier; the number on the right is the markers per chromosome. "
                       "Highlighted: gaps longer than the threshold under Advanced settings. Click a gap to list the SNPs "
                       "in it.", _fig_coverage),
    "chip-coverage": ("Chip coverage and new functional SNPs", "Top lane: the chip's markers per 1 Mb (darker = more). "
                      "Ticks: your tier 1–2 SNPs with no chip marker nearby (novel functional). Highlighted: chip gaps "
                      "over 1 Mb. Click a gap to list your SNPs in it.", _fig_chip),
}


def figure_card(c, name, built):
    url = reverse("snpportal:tool_figure", args=[c["key"], name])
    query = urlencode({"trait": c["trait"], **({"panel": c["panel"]["hash"], "gap_mb": f"{c['panel']['gap_bp'] / 1e6:g}"}
                                                 if name.startswith("panel") else {})})
    return {"name": name, "title": FIGURES[name][0], "info": FIGURES[name][1], "svg": mark_safe(built[0]),
            "svg_url": f"{url}?{query}", "tsv_url": f"{url}?{query}&format=tsv"}


def _figures(c, names, link):
    out = {}
    for name in names:
        built = FIGURES[name][2](c, link, FIGURES[name][1])
        if built:
            out[name.split("-", 1)[1]] = figure_card(c, name, built)
    return out


@private
def figure(request, key, name):
    """A Panel-tab figure as a standalone SVG (provenance in <desc>, no links) or, with ?format=tsv, its data; ?plain=1
    drops the '#' lines. Panel figures need ?panel=<hash> of a panel of this job; the chip figure needs its chip."""
    job = _views().finished(key)
    if name not in FIGURES:
        raise Http404("No such figure")
    d, weights = jobs.folder(key), jobs.weights(jobs.folder(key))
    trait = "all"  # tiers always count all 21 conditions
    con, view, types = _open(d, trait, weights, selected=True)
    c = _context(key, job, d, trait, con)
    if name.startswith("panel"):
        h = request.GET.get("panel", "")
        info = _saved(d, h)
        if info is None:
            raise Http404("No such panel")
        gap = _number(request.GET.get("gap_mb"), float, 0.01, 1000, None)
        c.update(panel=_panel_view(d, info, gap * 1e6 if gap else None), synthetic=_synthetic(job, info.get("chip_synthetic")))
    else:
        chip = chip_info(d)
        if not chip:
            raise Http404("No chip")
        chip = _compared(con, d, trait, weights, chip)
        c.update(chip=chip, synthetic=_synthetic(job, chip.get("synthetic")))
    lines = [] if request.GET.get("plain") else _provenance(d, job, trait, c["synthetic"], panel=c.get("panel", {}).get("hash"))
    built = FIGURES[name][2](c, None, "\n".join(lines) or FIGURES[name][1])
    if built is None:
        raise Http404("No such figure")
    svg, header, rows = built
    trailer = f"_{c['panel']['hash']}" if name.startswith("panel") else ""
    if request.GET.get("format") == "tsv":
        body = "\n".join(lines + ["\t".join(header)] + ["\t".join("" if x is None else str(x) for x in r) for r in rows]) + "\n"
        response = HttpResponse(body, content_type="text/tab-separated-values; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{name}_{trait}{trailer}.tsv"'
        return response
    response = HttpResponse(svg, content_type="image/svg+xml")
    response["Content-Disposition"] = f'attachment; filename="{name}_{trait}{trailer}.svg"'
    return response


def _selection_key(d):
    """The Table selection's filters (not its sort, page size or columns), for the panel and chip caches."""
    q = results.selection_request(results.selection(d)).GET
    return urlencode(sorted((k, v) for k in q for v in q.getlist(k) if k not in ("sort", "desc", "size", "cols", "col")))


def _chip_tag(d, trait):
    """chip.json's key for the comparison of the Table selection under `trait`."""
    return f"{trait}|{_selection_key(d)}" if _selection_key(d) else trait


def _context(key, job, d, trait, con):
    return {"key": key, "job": job, "d": d, "trait": trait, "preset": jobs.trait_label(trait), "con": con,
            "synthetic": _synthetic(job)}


# ---- the panel designer ----

def _params(data, weights, types, ids=()):
    """Design parameters from the designer's fields in `data` (the URL's GET parameters, or the form's POST) and the
    must-include `ids` (the POST's only): blank or out-of-range values give the release's 'design' defaults. Before the
    form is first sent (no design=1) the default checkboxes are ticked. The Assay select (assay=, as on the Table) sets
    require_assay_pass and the LORe exclusion; assay_pass=1 and exclude=lore of older links still work."""
    get = data.get
    purpose = get("purpose") if get("purpose") in snp_panel.presets(weights) else None  # I8: the preset's numbers are the defaults
    default = snp_panel.settings(weights, purpose)
    sent = get("design") == "1"
    allowed = [f for f in EXCLUDE if f in types]
    if sent:
        choice = get("assay") if get("assay") in results.ASSAY_FILTERS else "pass" if get("assay_pass") == "1" else \
            "ok_nolore" if "lore" in data.getlist("exclude") else "ok"
        flags = {f for f in data.getlist("exclude") if f != "lore"} | ({"lore"} if choice == "ok_nolore" else set())
    else:
        flags = set(default["exclude_flags"])
        choice = "pass" if default["require_assay_pass"] else "ok_nolore" if "lore" in flags else "ok"
    p = {
        "n_target": _number(get("n"), int, 1, MAX_TARGET, min(int(default["n_target"]), MAX_TARGET)),
        "min_spacing": round(1000 * _number(get("spacing_kb"), float, 0, 100_000, default["min_spacing"] / 1000)),
        "min_maf": _number(get("maf"), float, 0, 0.5, float(default["min_maf"])),
        "backbone_fraction": _number(get("backbone"), float, 0, 1, float(default["backbone_fraction"])),
        "max_per_gene": _number(get("per_gene"), int, 1, 100_000, int(default["max_per_gene"])),
        "max_per_element": _number(get("per_element"), int, 1, 100_000, int(default["max_per_element"])),
        "require_assay_pass": choice == "pass",
        "exclude_flags": sorted(f for f in flags if f in allowed),
        "must_include": sorted(set(ids))[:MAX_MUST],
    }
    if purpose:  # only then in the parameters, so other panels keep their hash
        p["purpose"] = purpose
        mixed = snp_panel.presets(weights)[purpose].get("mix")
        if mixed:  # each part designs with its own purpose's numbers: only Markers and must-include apply
            p["mix"] = [[k, float(v)] for k, v in mixed.items()]
    if {"cm_female", "cm_male"} <= set(types):  # R5: also keep markers this many cM apart (blank or 0: bp only)
        cm = _number(get("spacing_cm"), float, 0, 1000, None if sent else default.get("min_spacing_cm"))
        if cm:  # only then in the parameters, so bp-only panels keep their hash
            p.update(min_spacing_cm=cm, cm_map=get("cm_map") if get("cm_map") in CM_MAPS else default.get("cm_map") or "mean")
    return p


def _state(p, weights, gap):
    """The designer's form state for parameters p: the Assay choice and how many Advanced settings are not the defaults."""
    default = snp_panel.settings(weights, p.get("purpose"))
    choice = "pass" if p["require_assay_pass"] else "ok_nolore" if "lore" in p["exclude_flags"] else "ok"
    changed = sum([p["min_maf"] != float(default["min_maf"]), p["backbone_fraction"] != float(default["backbone_fraction"]),
                   p["max_per_gene"] != int(default["max_per_gene"]), p["max_per_element"] != int(default["max_per_element"]),
                   p.get("min_spacing_cm") != default.get("min_spacing_cm"), bool(gap),
                   set(p["exclude_flags"]) - {"lore"} != set(default["exclude_flags"]) - {"lore"}])
    return choice, changed


def _fields(p, types, gap_mb):
    """The form's number inputs as (visible, under 'Advanced settings'): dicts of name, label, value, min, max, step,
    help, gated on the columns they need."""
    maf = jobs.maf_sql(types)[0]
    cm = {"cm_female", "cm_male"} <= set(types)
    fields = [
        ("n", "Markers", p["n_target"], 1, MAX_TARGET, 1, "Number of SNPs to choose"),
        ("spacing_kb", "Min spacing (kb)", f"{p['min_spacing'] / 1000:g}", 0, 100_000, "any", "No two markers closer than this"),
        ("backbone", "Backbone share", f"{p['backbone_fraction']:g}", 0, 1, 0.05,
         "Share of the panel spread evenly over the genome (the best SNP per genome-length bin); the rest is chosen by design score"),
        ("maf", "Min MAF", f"{p['min_maf']:g}", 0, 0.5, 0.01, "Your maf/af column, else the MAF of 504 public fish (pooled; "
         "your strain can differ). SNPs with no MAF pass") if maf else None,
        ("per_gene", "Max per gene", p["max_per_gene"], 1, 100_000, 1, "Per nearest gene") if "gene_id" in types else None,
        ("per_element", "Max per element", p["max_per_element"], 1, 100_000, 1, "Per AQUA-FAANG peak") if "chromatin_id" in types else None,
        ("spacing_cm", "Min spacing (cM)", f"{p['min_spacing_cm']:g}" if p.get("min_spacing_cm") else "", 0, 1000, "any",
         "Also no two markers closer than this on the Brekke et al. 2023 genetic map (blank: bp only)") if cm else None,
        ("gap_mb", "Highlight gaps over (Mb)", f"{gap_mb:g}", 0.01, 1000, "any", "Display only: gaps this long are highlighted in the figure"),
    ]
    fields = [dict(zip(("name", "label", "value", "min", "max", "step", "help"), f)) for f in fields if f]
    fields[0]["list"] = "sp-sizes"  # the target sizes (I8) as suggestions
    if p.get("mix"):  # a mix: each part has its purpose's settings, so only Markers (and the gap highlight) apply
        return fields[:1], [f for f in fields if f["name"] == "gap_mb"]
    return fields[:2], fields[2:]


def _saved(d, h):
    """A saved panel's .json, or None (h must be a hash of this job's panels)."""
    if not re.fullmatch(r"[0-9a-f]{16}", h or "") or not (d / "panels" / f"{h}.parquet").exists():
        return None
    return jobs.read_json(d / "panels" / f"{h}.json") or None


def _design(con, view, d, trait, p, weights, chip):
    """panels/<hash>.parquet and .json for the parameters: made once, as the same parameters give the same panel."""
    key = {"v": 1, "preset": trait, **p, "weights": jobs.sha256(d / "weights.yaml") if (d / "weights.yaml").exists() else None,
           "chip": chip.get("sha256"), **({"selection": _selection_key(d)} if _selection_key(d) else {})}
    h = snp_panel.params_hash(key)
    folder = d / "panels"
    if (folder / f"{h}.parquet").exists():
        return jobs.read_json(folder / f"{h}.json")
    folder.mkdir(mode=0o700, exist_ok=True)
    tmp = folder / f".tmp-{uuid.uuid4().hex}.parquet"
    try:
        r = snp_panel.design(con, trait, p["n_target"], p["min_spacing"], p["min_maf"], p["backbone_fraction"], p["max_per_gene"],
                             p["max_per_element"], p["require_assay_pass"], p["exclude_flags"], p["must_include"], weights=weights,
                             chrom_sizes=jobs.manifest(d).get("chrom_sizes"), table=view, out=tmp,
                             **{k: p[k] for k in ("min_spacing_cm", "cm_map", "purpose") if k in p})
        info = {"hash": h, "selection_hash": r["hash"], "preset": trait, "params": p, "summary": r["summary"], "table": _selection_key(d),
                "chip": chip.get("label"), "chip_synthetic": bool(chip.get("synthetic")), "created_utc": jobs.utc()}
        jobs._write_json(folder / f"{h}.json", info)
        os.chmod(tmp, 0o600)
        os.replace(tmp, folder / f"{h}.parquet")
    finally:
        tmp.unlink(missing_ok=True)
    return jobs.read_json(folder / f"{h}.json")  # as later visits read it (JSON keys are strings)


def _panel_view(d, info, gap_bp=None):
    """What the panel figures need: the parquet relation, the summary, its largest gaps and the gap threshold."""
    s = info["summary"]
    total = sum(n for _, n in _chroms(d)) or 1
    gap = gap_bp or _nice(3 * total / max(s["n_selected"], 1) / 1e6) * 1e6
    return {"hash": info["hash"], "rel": f"read_parquet({lit(d / 'panels' / (info['hash'] + '.parquet'))})", "summary": s,
            "params": info["params"], "gaps": s.get("largest_gaps") or [], "gap_bp": gap, "info": info}


def vendor_checks(con, rel):
    """snpscore's panel-level vendor checks of the SNPs in `rel`: {infinium_bins, close_pairs, warnings, bins (text)}.
    Illumina Infinium bins (A/T, C/G and the rest) need at least 100 (I) or 1,000 (II) SNPs each, markers within 60 bp
    interfere (lib.panel.vendor_checks; vendor rules, docs/RESEARCH.md section 5)."""
    cols, alleles = _columns(con, rel), []
    for i, c in enumerate(("ref", "alt")):  # the list's alleles, else those of the assay flank (the public ones), as vendor files
        found = ([f"nullif({c}::VARCHAR, '')"] if c in cols else []) + (
            [f"nullif(regexp_extract(assay_flank, '\\[(\\w+)/(\\w+)\\]', {i + 1}), '')"] if "assay_flank" in cols else [])
        alleles.append(f"coalesce({', '.join(found)}) AS {c}" if found else f"NULL AS {c}")
    out = snp_panel.vendor_checks(con.execute(f"SELECT chrom, pos, {', '.join(alleles)} FROM {rel}").fetchall())
    b = out["infinium_bins"]
    out["bins"] = (f"Infinium I bin A (A/T) {b['A']:,}, bin B (C/G) {b['B']:,}; Infinium II bin C {b['C']:,}"
                   + (f"; alleles unknown {b['unknown']:,}" if b["unknown"] else ""))
    return out


def _short(s):
    """Why a panel has fewer markers than wanted, or None."""
    if s["n_selected"] >= s["n_target"]:
        return None
    b = s.get("binding") or ""
    b = BINDING.get(b, b.replace("min_maf", "min MAF").replace("exclude_flags", "exclusions")) or "the filters"
    return f"Only {s['n_selected']:,} of the {s['n_target']:,} markers could be chosen: the binding constraint is {b}."


def panel_name(info, time=False):
    """'28 markers · maturation · 6 Oct' (with the UTC time if `time`): a panel named by the markers actually chosen."""
    when = info.get("created_utc") or ""
    try:
        when = datetime.strptime(when, "%Y-%m-%d %H:%M UTC")
        when = f"{when.day} {when:%b}" + (f" {when:%H:%M}" if time else "")
    except ValueError:
        pass
    purpose = (info.get("params") or {}).get("purpose")
    label = (purpose_label(purpose) if purpose else None) or jobs.trait_label(info.get("preset") or "all")
    return " · ".join(x for x in [f"{info['summary']['n_selected']:,} markers", label, when] if x)


def panel_params(p):
    """A designed panel's parameters in one line (its purpose first, I8), for the report and the export provenance."""
    parts = [f"purpose {purpose_label(p['purpose']) or p['purpose']}"] if p.get("purpose") else []
    if p.get("mix"):
        total = sum(v for _, v in p["mix"]) or 1
        return "; ".join(parts + [f"{int(p['n_target']):,} markers: " + ", ".join(
            f"{v / total:.0%} {purpose_label(k) or k}" for k, v in p["mix"]) + ", each with its purpose's settings"])
    parts += [f"{int(p['n_target']):,} markers", f"at least {_bp(p['min_spacing'])} apart"
              + (f" and {p['min_spacing_cm']:g} cM" if p.get("min_spacing_cm") else ""), f"MAF ≥ {p['min_maf']:g}",
              f"backbone {p['backbone_fraction']:g}", f"≤ {p['max_per_gene']} per gene", f"≤ {p['max_per_element']} per element",
              "assay pass only" if p.get("require_assay_pass") else "no assay fail"]
    if p.get("exclude_flags"):
        parts.append("excluding " + ", ".join(p["exclude_flags"]))
    return "; ".join(parts)


def tools_mix_line(p):
    """'90% Genomic selection, 10% Trait panel' for the designer's Purpose line."""
    total = sum(v for _, v in p["mix"]) or 1
    return ", ".join(f"{v / total:.0%} {purpose_label(k) or k}" for k, v in p["mix"])


def purpose_label(name, weights=None):
    """A design purpose's label (weights.yaml design.presets, I8), or None."""
    return (snp_panel.presets(weights or jobs.weights()).get(name) or {}).get("label")


def panel_line(s):
    """The panel's key numbers in one line: tier 1-2 and assay-pass shares, median spacing, largest gap."""
    n = s["n_selected"]
    tiers, assay, gaps = s.get("tiers", {}), s.get("assay_status") or {}, s.get("largest_gaps") or []
    parts = [f"{results.pct(int(tiers.get('1', 0)) + int(tiers.get('2', 0)), n)} tier 1–2"]  # the heading names the markers
    if assay:
        parts.append(f"{results.pct(assay.get('pass', 0), n - assay.get('not_checked', 0) - assay.get('null', 0))} assay pass")
    parts.append(f"median spacing {_bp((s.get('spacing') or {}).get('median'))}")
    if s.get("spacing_cm"):
        parts.append(f"median {_cm(s['spacing_cm'].get('median'))}")
    if gaps:
        parts.append(f"largest gap {_bp(gaps[0]['size'])} (chr {gaps[0]['chrom']})")
    return " · ".join(parts)


def _listed(con, info, d, trait, key, limit):
    """The first `limit` selected SNPs in rank order, display-ready."""
    rel = f"read_parquet({lit(d / 'panels' / (info['hash'] + '.parquet'))})"
    cols = _columns(con, rel)
    maf = jobs.maf_sql(cols)[0]
    want = [c for c in ("source_row", "panel_rank", "selection_reason", "chrom", "pos", "id", "ref", "alt", "tier", "gene_name",
                        "gene_id", "gene_ortholog_human", "region_class", "coding_consequence", "coding_hgvsp", "coding_transcript",
                        "coding_note", "assay_status", "assay_reasons", "on_chip") if c in cols]
    cur = con.execute(f"SELECT {', '.join(map(jobs.ident, want))}{f', {maf} AS _maf' if maf else ''} FROM {rel} "
                      f"ORDER BY panel_rank LIMIT {int(limit)}")
    names = [x[0] for x in cur.description]
    q = urlencode({"trait": trait})
    out = []
    for r in (dict(zip(names, x)) for x in cur.fetchall()):
        g = r.get
        status = g("assay_status") or ("not_checked" if "assay_status" in r else None)
        gene = results.gene_label(g("gene_name"), g("gene_id"), g("gene_ortholog_human"))
        out.append({"rank": g("panel_rank"), "url": f"{reverse('snpportal:card', args=[key, g('source_row')])}?{q}",
                    "name": g("id") if g("id") not in (None, ".") else f"{g('chrom')}:{g('pos')}",
                    "alleles": f"{g('ref')}>{g('alt')}" if g("ref") and g("alt") else "", "tier": g("tier"),
                    "reason": REASONS.get(g("selection_reason"), (g("selection_reason"), ""))[0],
                    "reason_tip": REASONS.get(g("selection_reason"), ("", ""))[1],
                    "gene": gene, "gene_tip": results.UNNAMED if gene.startswith("~") else g("gene_id") or "",
                    "region": results.region_text(g), "region_tip": results.coding_tip(g),
                    "maf": "" if g("_maf") is None else f"{g('_maf'):.2f}",
                    "assay": (results.ASSAY.get(status, ("?", "not_checked")) + (status.replace("_", " "), results.reasons_text(g("assay_reasons"))))
                    if status else None, "on_chip": g("on_chip")})
    return out


def assay_readiness(con, types, synthetic, link):
    """The Panel tab's 'Assay readiness' card for the Table selection (view v): one bar of pass / warn / fail / not
    checked (each links to those SNPs in the table) and the reasons SNPs warn or fail, each with a 'hide in table' link."""
    if "assay_status" not in types:
        return None
    counts = dict(con.execute("SELECT coalesce(assay_status, 'not_checked'), count(*) FROM v GROUP BY 1").fetchall())
    if not counts:
        return None
    s = {"assay_reasons": {}}
    if "assay_reasons" in types:  # as jobs.summarise counts them
        for reason, status, k in con.execute("""
                SELECT trim(regexp_replace(regexp_replace(x, '^[0-9]+ ', ''), '( +[0-9.+-]+)+$', '')), status, count(*) FROM (
                    SELECT unnest(string_split(assay_reasons, '; ')) AS x, coalesce(assay_status, 'not_checked') AS status
                    FROM v WHERE assay_reasons IS NOT NULL AND coalesce(assay_status, '') <> 'pass') GROUP BY ALL ORDER BY ALL""").fetchall():
            s["assay_reasons"].setdefault(reason, {})[status] = k
    n = sum(counts.values())
    statuses = [st for st in ("pass", "warn", "fail", "not_checked") if st in counts or st != "not_checked"]
    parts = [(st.replace("_", " "), counts.get(st, 0), palette.STATUS[results.ASSAY[st][1]][2], link(assay=st)) for st in statuses]
    svg = figures.bar(parts, "Assay readiness", "SNPs per assay status of the probe-flank check", synthetic)
    line = " · ".join(f"{counts.get(st, 0):,} {st.replace('_', ' ')}" + (f" ({results.pct(counts.get(st, 0), n)})" if st == "pass" else "")
                      for st in statuses)
    reasons = sorted(((results.REASONS.get(r, r), sum(by.values()), link(hide_reason=r)) for r, by in (s.get("assay_reasons") or {}).items()),
                     key=lambda x: -x[1])
    return {"svg": mark_safe(svg), "line": line, "reasons": reasons}


def panel(request, key, job):
    """Context for the Panel tab: the compact designer (Advanced settings open when any is changed), the panel's name,
    shortfall alert, key numbers, coverage figure and first markers, the Assay readiness card and the chip comparison.
    The default panel is designed on the first visit; every parameter set is cached in the job folder."""
    d = jobs.folder(key)
    weights = jobs.weights(d)
    trait = "all"  # tiers always count all 21 conditions
    con, view, types = _open(d, trait, weights, selected=True)
    chip = chip_info(d)
    c = _context(key, job, d, trait, con)
    link = results.table_link(trait)
    saved = _saved(d, request.GET.get("panel"))  # a panel the form designed, with its must-include ids (never in the URL)
    p = saved["params"] if saved else _params(request.GET, weights, types)  # another trait: the same parameters for it
    info = _design(con, view, d, trait, p, weights, chip)
    gap = _number(request.GET.get("gap_mb"), float, 0.01, 1000, None)
    choice, changed = _state(p, weights, request.GET.get("gap_mb"))
    pv = _panel_view(d, info, gap * 1e6 if gap else None)
    c.update(panel=pv, synthetic=_synthetic(job, info.get("chip_synthetic")))
    s = info["summary"]
    every = request.GET.get("show") == "all"
    more = request.GET.copy()
    more["show"] = "all"
    visible, advanced = _fields(p, types, pv["gap_bp"] / 1e6)
    picked = results.filters(results.selection_request(results.selection(d)), _columns(con, "v0"), weights)
    designer = {
        "selection": {"n": con.execute("SELECT count(*) FROM v").fetchone()[0], "total": con.execute("SELECT count(*) FROM r").fetchone()[0],
                      "filters": [label for _, label, _ in picked], "table": f"?{results.selection(d)}&tab=table"},
        "fields": visible, "advanced": advanced, "n_advanced": changed, "must": " ".join(p["must_include"]),
        "too_many_ids": request.GET.get("must_capped") == "1", "max_must": MAX_MUST, "url": reverse("snpportal:panel_design", args=[key]),
        "assay": [(k, label, k == choice) for k, (label, _) in results.ASSAY_FILTERS.items()
                  if k != "ok_nolore" or "lore" in types] if "assay_status" in types else [],
        "cm_maps": [(k, label, k == p.get("cm_map", "mean")) for k, label in CM_MAPS.items()] if {"cm_female", "cm_male"} <= set(types) else [],
        "checks": [(f, EXCLUDE[f], f in p["exclude_flags"]) for f in EXCLUDE if f in types and f != "lore"],
        "name": panel_name(info), "short": _short(s), "missing": s.get("missing_must_include") or [], "line": panel_line(s),
        "fig": _figures(c, ["panel-coverage"], link).get("coverage"),
        "rows": _listed(con, info, d, trait, key, LISTED if every else SHOWN), "n_rows": s["n_selected"], "listed": LISTED,
        "show_all": None if every or s["n_selected"] <= SHOWN else "?" + more.urlencode(),
        "export_link": "?" + urlencode({"tab": "export", "trait": trait, "scope": f"panel-{pv['hash']}"}),
        "reset": "?" + urlencode({"tab": "panel", "trait": trait, **({"purpose": p["purpose"]} if p.get("purpose") else {})}),
        "purposes": [("", "General", "The release's design defaults", not p.get("purpose"))] + [
            (k, x.get("label") or k, x.get("help") or "", k == p.get("purpose")) for k, x in snp_panel.presets(weights).items()],
        "purpose": p.get("purpose"), "sizes": snp_panel.target_sizes(weights), "mix": tools_mix_line(p) if p.get("mix") else None,
    }
    if p.get("mix"):  # each part has its purpose's settings: no controls that wouldn't apply
        designer.update(assay=[], cm_maps=[], checks=[])
    return {"designer": designer, "readiness": assay_readiness(con, types, _synthetic(job), link),
            "chip": _chip_context(request, key, job, d, trait, con, weights, chip, link)}


@private
def design(request, key):
    """POST of the panel designer: designs the panel (cached by its parameters' hash) and redirects to the Panel tab
    showing it by that hash, so the must-include ids reach no URL, server log or browser history."""
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    _views().finished(key)
    d = jobs.folder(key)
    weights = jobs.weights(d)
    trait = "all"  # tiers always count all 21 conditions
    con, view, types = _open(d, trait, weights, selected=True)
    ids = MUST.findall(request.POST.get("must", "")[:20_000])
    info = _design(con, view, d, trait, _params(request.POST, weights, types, ids), weights, chip_info(d))
    query = {"tab": "panel", "trait": trait, "panel": info["hash"], "gap_mb": request.POST.get("gap_mb", "")[:20],
             "must_capped": "1" if len(set(ids)) > MAX_MUST else ""}
    return redirect(f"{reverse('snpportal:results', args=[key])}?{urlencode({k: v for k, v in query.items() if v})}#designer")


# ---- chip comparison ----

def _compared(con, d, trait, weights, chip):
    """chip.json with the comparison for `trait` (cached there): counts, chip gaps with the best SNP of the list or the
    release pool, and the novel functional SNPs per BIN for the figure."""
    tag = _chip_tag(d, trait)
    if tag in chip.get("results", {}):
        return chip
    pool = jobs.release() / "pool" / "pool.parquet"
    res = snp_panel.compare(con, d / "chip.parquet", trait, weights=weights, chrom_sizes=jobs.manifest(d).get("chrom_sizes"),
                            pool=pool if pool.exists() else None, table="v")
    listed = [g["filler"] for g in res["gaps"] if g["filler"] and g["filler"]["source"] == "list"]
    if listed:  # card links for the fillers from the list
        values = ", ".join(f"({lit(f['chrom'])}, {int(f['pos'])})" for f in listed)
        rows = dict(((c, p), r) for c, p, r in con.execute(
            f"SELECT v.chrom, v.pos, min(v.file_row_number) FROM v JOIN (VALUES {values}) g(chrom, pos) "
            "ON v.chrom = g.chrom AND v.pos = g.pos GROUP BY ALL").fetchall())
        for f in listed:
            f["row"] = rows.get((f["chrom"], f["pos"]))
    res["novel_bins"] = [list(x) for x in con.execute(  # vc: v with the chip columns (see _open)
        f"SELECT chrom, pos // {BIN} * {BIN}, min(tier), count(*) FROM vc WHERE novel_functional GROUP BY ALL ORDER BY ALL").fetchall()]
    chip.setdefault("results", {})[tag] = res
    jobs._write_json(d / "chip.json", chip)
    return chip


def _chip_context(request, key, job, d, trait, con, weights, chip, link):
    """Context for _chip.html: the upload form, or the comparison (KPIs, figure, gaps table)."""
    demo = jobs.release() / "demo" / "chip_demo_SYNTHETIC.tsv"
    error = CHIP_ERRORS.get(request.GET.get("chip_error"), "").format(cap=f"{chip_cap():,}")
    out = {"url": reverse("snpportal:chip", args=[key]), "demo": demo.is_file(), "error": error or None,
           "window": _bp(snp_panel.settings(weights)["chip_window"]), "info": chip}
    if not chip:
        return out
    chip = _compared(con, d, trait, weights, chip)
    res = chip["results"][_chip_tag(d, trait)]
    s = res["summary"]
    c = _context(key, job, d, trait, con)
    c.update(chip=chip, synthetic=_synthetic(job, chip.get("synthetic")))
    q = urlencode({"trait": trait})
    gaps = []
    for g in res["gaps"][:TOP_GAPS]:
        f = g["filler"]
        gaps.append({**g, "size_text": _bp(g["size"]), "table": link(chrom=g["chrom"], start=g["start"], end=g["end"]),
                     "card": f"{reverse('snpportal:card', args=[key, f['row']])}?{q}" if f and f.get("row") is not None else None})
    fig = _figures(c, ["chip-coverage"], link).get("coverage")
    out.update(info=chip, synthetic=c["synthetic"], gaps=gaps, n_gaps=len(res["gaps"]), top=TOP_GAPS, gaps_tsv=fig and fig["tsv_url"],
               heading=f"Your selection compared with the {(chip.get('label') or 'chip').lower()}",
               kpis=[{"value": f"{s['chip_snps']:,}", "label": "chip markers", "note": f"{sum(n for _, n in chip.get('rejected', {}).items()):,} "
                      "rows left out" if chip.get("rejected") else "all on chromosomes 1–29"},
                     {"value": f"{s['shared']:,}", "label": "shared", "note": f"{results.pct(s['shared'], s['total'])} of your SNPs are on the chip"},
                     {"value": f"{s['novel_functional']:,}", "label": "novel functional",
                      "note": f"tier 1–2, no chip marker within {_bp(s['window_bp'])}"},
                     {"value": f"{s['other']:,}", "label": "other", "note": "near the chip, or tier 3–4"},
                     {"value": f"{s['gaps']:,}", "label": "chip gaps", "note": f"over {_bp(s['gap_bp'])}"}], fig=fig)
    return out


def chip_cap():
    """Most chip markers read: SNPPORTAL_MAX_CHIP_SNPS (MAX_CHIP), never more than SNPPORTAL_MAX_SNPS. Reading 1M rows
    takes about a second, so the chip is read in the request; longer lists are refused (a small .gz can hold billions)."""
    return min(int(jobs.setting("SNPPORTAL_MAX_CHIP_SNPS", MAX_CHIP)), int(jobs.setting("SNPPORTAL_MAX_SNPS", 3_000_000)))


def _chip_redirect(key, trait, error=None):
    query = {"tab": "panel", "trait": trait, **({"chip_error": error} if error else {})}
    return redirect(f"{reverse('snpportal:results', args=[key])}?{urlencode(query)}#chip")


@csrf_exempt  # so the upload handler can be set before the body is read; _chip() checks the CSRF token
@private
def chip(request, key):
    """POST a chip (any snpscore input layout), the demo chip (demo=1) or remove=1. The upload streams into the
    results dir like a SNP list; the chip is read through the release's chromosome aliases into chip.parquet."""
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    views = _views()
    views.finished(key)
    max_mb = float(jobs.setting("SNPPORTAL_MAX_UPLOAD_MB", 300))
    try:
        length = int(request.META.get("CONTENT_LENGTH") or 0)
    except ValueError:
        length = 0
    if length > max_mb * 2 ** 20:
        return _chip_redirect(key, request.GET.get("trait", "all"), "size")
    handler = views.UploadToResults(request)
    request.upload_handlers = [handler]
    try:
        return _chip(request, key)
    except Exception:
        request._files = MultiValueDict()  # keep uploaded file names out of error reports
        raise
    finally:
        handler.discard()


@csrf_protect
@sensitive_post_parameters()
def _chip(request, key):
    d = jobs.folder(key)
    trait = "all"  # tiers always count all 21 conditions
    if request.POST.get("remove"):
        for path in [d / "chip.parquet", d / "chip.json", *d.glob("chip_rows_*.parquet")]:
            path.unlink(missing_ok=True)
        return _chip_redirect(key, trait)
    upload, demo = request.FILES.get("chip"), jobs.release() / "demo" / "chip_demo_SYNTHETIC.tsv"
    if request.POST.get("demo") and demo.is_file():
        src, label, synthetic = demo, "Demo chip", True
    elif upload and upload.size:
        suffix = _views().accepted_suffix(upload.name)
        if suffix is None:
            return _chip_redirect(key, trait, "type")
        src, label, synthetic = d / f".chip-input{suffix}", "Uploaded chip", "SYNTHETIC" in upload.name
        os.replace(upload.path, src)
    else:
        return _chip_redirect(key, trait, "missing")
    new, cap = d / ".chip-new.parquet", chip_cap()
    try:
        report = snp_panel.read_chip(src, jobs.release(), new, max_snps=cap)
    except (snpscore.InputError, duckdb.Error) as e:
        new.unlink(missing_ok=True)
        many = getattr(snpscore, "TooMany", None)  # over max_snps (an older snpscore: an InputError that says so)
        return _chip_redirect(key, trait, "rows" if (isinstance(e, many) if many else f"more than {cap:,}" in str(e)) else "format")
    finally:
        if src != demo:
            src.unlink(missing_ok=True)
    if not report.get("snps_kept"):
        new.unlink(missing_ok=True)
        return _chip_redirect(key, trait, "empty")
    con = jobs.connect([d], d)
    density = [list(x) for x in con.execute(f"SELECT chrom, (pos - 1) // 1000000, count(*) FROM read_parquet({lit(new)}) "
                                            "GROUP BY ALL ORDER BY ALL").fetchall()]
    os.chmod(new, 0o600)
    for path in d.glob("chip_rows_*.parquet"):  # the old chip's per-SNP columns (results.chip_view makes the new ones)
        path.unlink(missing_ok=True)
    os.replace(new, d / "chip.parquet")
    rejected = {k: v for k, v in (report.get("rejected") or {}).items() if v}
    jobs._write_json(d / "chip.json", {"label": label, "synthetic": synthetic, "kept": report["snps_kept"],
                                       "rows": report.get("rows_read"), "rejected": rejected, "format": report.get("format"),
                                       "sha256": jobs.sha256(d / "chip.parquet"), "created_utc": jobs.utc(),
                                       "density": density, "results": {}})
    return _chip_redirect(key, trait)


# ---- the Export tab and downloads ----

def credible_rows(request, key):
    """Row numbers of a GWAS job's SNPs in a 95% credible set under either prior (association.analyse)."""
    from . import association  # association imports views, which imports this module
    a = association.analyse(request, key)
    if not a["loci"]:
        return []
    return [r for r, in a["con"].execute("SELECT DISTINCT file_row_number FROM fm WHERE cs_uniform OR cs_functional ORDER BY 1").fetchall()]


def _scope(request, key, d, con, view, types, weights, job, scope=None):
    """(view to export, tag for the file name, filters {name: value}, panel hash, synthetic) for ?scope= (or `scope`):
    all, filtered (the Table tab's filters in the URL), panel-<hash> or credible (a GWAS job's credible-set SNPs)."""
    scope = scope or request.GET.get("scope", "all")
    if scope == "credible" and job.get("input_kind") == "gwas":
        rows = ", ".join(str(int(r)) for r in credible_rows(request, key)) or "NULL"
        con.execute(f"CREATE OR REPLACE VIEW f AS SELECT * FROM {view} WHERE file_row_number IN ({rows})")
        return "f", "credible", {"credible_set": "95%, either prior"}, None, _synthetic(job)
    if scope.startswith("panel-"):
        info = _saved(d, scope[6:])
        if info is None:
            raise Http404("No such panel")
        con.execute(f"CREATE OR REPLACE VIEW p AS SELECT source_row AS file_row_number, * EXCLUDE (source_row) "
                    f"FROM read_parquet({lit(d / 'panels' / (info['hash'] + '.parquet'))})")
        return "p", f"panel-{info['hash']}", {}, info["hash"], _synthetic(job, info.get("chip_synthetic"))
    synthetic = _synthetic(job, view == "vc" and chip_info(d).get("synthetic"))
    conds = results.filters(request, types, weights) + [m for m in [results.manual(d)] if m] if scope == "filtered" else []
    if not conds:
        return view, None, {}, None, synthetic
    con.execute(f"CREATE OR REPLACE VIEW f AS SELECT * FROM {view} WHERE " + " AND ".join(f"({sql})" for _, _, sql in conds))
    chosen = {k: v for params, _, _ in conds for k, v in params.items()}
    return "f", "filtered", chosen, None, synthetic


def _command(job, trait, tag, fmt="<format>"):
    name = jobs.cli_trait(trait) or "all"  # snpscore's name for these conditions (others: all, and the portal's tiers differ)
    base = f"snpscore annotate <your list> --release <release {job.get('release')}> --trait {name} -o annotated.parquet"
    if tag and tag.startswith("panel-") and fmt != "priors":
        return base + f"; python -m snpportal.lib.cli panel annotated.parquet --release <release {job.get('release')}> --preset {name} (parameters in panels/{tag[6:]}.json of the job)"
    return base + f"; python -m snpportal.lib.cli export annotated.parquet --release <release {job.get('release')}> --preset {name} --format {fmt}"


def export(request, key, job, fmt):
    """The download view's formats beyond the table's TSV: tsv, parquet, bed, illumina, axiom, kasp or bundle of the
    whole result, the Table selection (?scope=filtered plus its filters, as the Export tab links) or a panel (?scope=panel-<hash>).
    TSV and BED start with snpscore's provenance lines (?plain=1 drops them); vendor files hold none, so
    ?format=<vendor>.provenance or .lookup gives the sidecar snpscore writes next to them (provenance; ids, TOP/BOT and
    assay status). Vendor rows that fail the assay check or are not checked are left out unless ?include_failed=1."""
    fmt, _, part = fmt.partition(".")
    if fmt not in EXPORTS or part not in ("", "provenance", "lookup") or part and fmt not in VENDORS:
        raise Http404("Unknown export format")
    d = jobs.folder(key)
    weights = jobs.weights(d)
    trait = "all"  # tiers always count all 21 conditions
    con, view, types = _open(d, trait, weights)
    table, tag, filters, panel_hash, synthetic = _scope(request, key, d, con, view, types, weights, job,
                                                        "all" if fmt == "priors" else None)  # priors: every SNP
    n = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
    cap = int(jobs.setting("SNPPORTAL_MAX_VENDOR_SNPS", 50_000))
    if fmt in VENDORS and n > cap:
        return render(request, "snpportal/stub.html", {"nav": "score", "title": "Too many SNPs for a vendor file", "message":
                      f"Vendor files are for panels: this export has {n:,} SNPs, more than {cap:,}. Filter the Table "
                      "first, or add a selection to your Design panel, which makes vendor files for it."}, status=400)
    formats = ["tsv", "bed"] + (list(VENDORS) if n <= cap else [])
    notes = {"vendor_files": f"left out above {cap:,} SNPs"} if fmt == "bundle" and n > cap else {}
    meta = _meta(job, trait, synthetic, {**filters, **notes}, panel_hash, _command(job, trait, tag, fmt))
    saved = _saved(d, panel_hash) if panel_hash else None
    if saved and saved.get("params"):
        meta["panel_params"] = panel_params(saved["params"])
    if fmt == "bundle" and job.get("input_kind") == "gwas":  # methods.txt gains the fine-mapping paragraph and Wakefield 2009
        from . import association  # association imports views, which imports this module
        meta["finemap"] = association.finemap_used(association.analyse(request, key))
    manifest, wfile = d / "manifest.json", d / "weights.yaml"
    wfile = wfile if wfile.exists() else None
    name = snp_export.filename(fmt, job.get("release") or "release", trait, tag,
                               **({"synthetic": synthetic} if "synthetic" in inspect.signature(snp_export.filename).parameters else {}))
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".export-", suffix="." + name.rsplit(".", 1)[1])
    os.close(fd)
    sidecars = {"provenance": tmp + ".provenance.txt", "lookup": tmp + ".lookup.tsv"}  # written next to vendor files
    try:
        if fmt == "bundle":
            snp_export.bundle_zip(tmp, con, jobs.release(), trait, meta, formats, _bundle_svgs(key, job, d, trait, con, panel_hash, synthetic),
                                  request.GET.get("include_failed") == "1", table=table, manifest=manifest, weights=wfile)
            if n <= cap and jobs.manifest(d).get("genome"):  # the Export tab's per-file checks travel with the files
                notes = _vendor_notes(con, table, n)
                with zipfile.ZipFile(tmp, "a") as z:
                    z.writestr("vendor_checks.txt", "".join(f"{fmt}: {'; '.join(x for x in lines if x)}\n" for fmt, lines in notes.items()))
        else:
            snp_export.export(con, fmt, tmp, jobs.release(), trait, meta, request.GET.get("include_failed") == "1",
                              request.GET.get("plain") == "1", table=table, manifest=manifest, weights=wfile)
        if part and not os.path.exists(sidecars[part]):
            raise Http404("This snpscore writes no sidecar files")
        f = open(sidecars[part] if part else tmp, "rb")
    except snpscore.InputError as e:  # e.g. a release without the genome sequence: snpscore's message is safe to show
        return render(request, "snpportal/stub.html", {"nav": "score", "title": "Export not possible", "message": str(e)}, status=400)
    finally:
        for path in [tmp, *sidecars.values()]:  # open handles keep the data until the response is closed; nothing is left behind
            if os.path.exists(path):
                os.unlink(path)
    if part:
        return FileResponse(f, as_attachment=True, filename=name + sidecars[part][len(tmp):],
                            content_type="text/plain; charset=utf-8" if part == "provenance" else MIME["tsv"])
    return FileResponse(f, as_attachment=True, filename=name, content_type=MIME[fmt])


def _bundle_svgs(key, job, d, trait, con, panel_hash, synthetic):
    """{name: SVG} for the bundle: the panel's figures for a panel, else the Overview figures (and the chip's)."""
    lines = "\n".join(_provenance(d, job, trait, synthetic, panel=panel_hash))
    c = _context(key, job, d, trait, con)
    c["synthetic"] = synthetic
    out = {}
    if panel_hash:
        c["panel"] = _panel_view(d, _saved(d, panel_hash))
        names = [n for n in FIGURES if n.startswith("panel")]
    else:
        rc = results._figure_context(key, job, trait, results.summary_of(d), d)
        for name, (_, _, build) in results.FIGURES.items():
            built = build(rc, None, lines)
            if built:
                out[name] = built[0]
        chip = chip_info(d)
        names = []
        if chip:
            c["chip"] = _compared(con, d, trait, jobs.weights(d), chip)
            names = ["chip-coverage"]
    for name in names:
        built = FIGURES[name][2](c, None, lines)
        if built:
            out[name] = built[0]
    return out


def _panels(d):
    """The job's saved panels, newest first (when their .json was written; created_utc is to the minute): [info]."""
    found = [p for p in (d / "panels").glob("*.json") if p.with_suffix(".parquet").exists()] if (d / "panels").is_dir() else []
    found.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [x for x in map(jobs.read_json, found) if x]


def recent_panels(d, trait, keep=None, n=3):
    """The Export tab's panels of `trait`: the newest of each distinct parameter set (another chip or weights.yaml gives
    another hash for the same parameters), newest first, at most n, plus the panel `keep` (a hash) when not among them."""
    found, out, seen = [x for x in _panels(d) if x.get("preset") == trait], [], set()
    for info in found:
        params = json.dumps(info.get("params"), sort_keys=True)
        if params not in seen:
            seen.add(params)
            out.append(info)
    return out[:n] + [x for x in found if x["hash"] == keep and x not in out[:n]]


def _vendor_notes(con, rel, n):
    """{format: [text]} for the Export tab's vendor rows: how many of the n SNPs the file includes (assay fail, not
    checked and unknown alleles are left out, as lib.export does) and that file's own checks of what it holds."""
    ok = f"(SELECT * FROM {rel} WHERE coalesce(assay_status, '') NOT IN ('fail', 'not_checked'))" if "assay_status" in _columns(con, rel) else rel
    left = n - con.execute(f"SELECT count(*) FROM {ok}").fetchone()[0]
    c = vendor_checks(con, ok)
    b, close = c["infinium_bins"], c["close_pairs"]
    why = [x for x in [f"{left:,} assay fail or not checked" if left else "", f"{b['unknown']:,} alleles unknown" if b["unknown"] else ""] if x]
    included = f"{n - left - b['unknown']:,} of {n:,} included" + (f" ({', '.join(why)})" if why else "")
    within = f"{close:,} SNPs within 60 bp of another" if close else ""
    bins = f"Infinium bins: A/T {b['A']:,}, C/G {b['B']:,}, other {b['C']:,}" + (" (below Illumina's minimums)" if any(
        "Infinium" in w for w in c["warnings"]) else "")
    return {"kasp": [included], "illumina": [included, bins, within], "axiom": [included, within],
            "agena": [included, "layout not yet checked against Agena's template"],
            "primer3": [included, "for primer design: the SNP as target, PCR settings to set with the lab"]}


def exports(request, key, job):
    """Context for the Export tab: one scope choice (the Table selection when it has filters, else the latest panel,
    else all SNPs), five download rows with each vendor file's counts and checks, and 'More formats'. GWAS jobs lead
    with their association files and one KASP row for the credible-set SNPs."""
    d = jobs.folder(key)
    weights = jobs.weights(d)
    trait = "all"  # tiers always count all 21 conditions
    con, view, types = _open(d, trait, weights)
    gwas = job.get("input_kind") == "gwas"
    settings = results.gwas_settings(request) if gwas else {}  # the loci and credible sets of the Association page's settings
    conds = results.filters(results.selection_request(results.selection(d)), types, weights) + [m for m in [results.manual(d)] if m]
    chosen = {k: v for params, _, _ in conds for k, v in params.items()}
    chip = chip_info(d)
    wanted = request.GET.get("scope")
    old = _saved(d, wanted[6:]) if not gwas and (wanted or "").startswith("panel-") else None
    if old and old.get("preset") != trait:  # a panel of another trait (the Trait changed): its parameters for this trait
        wanted = "panel-" + _design(con, view, d, trait, old["params"], weights, chip)["hash"]
    scopes = []  # (value, label, SNPs, relation, a synthetic chip contributes)
    total = con.execute("SELECT count(*) FROM r").fetchone()[0]
    if gwas:
        rows = ", ".join(str(int(r)) for r in credible_rows(request, key)) or "NULL"
        rel = f"(SELECT * FROM {view} WHERE file_row_number IN ({rows}))"
        scopes.append(("credible", "Credible-set SNPs", con.execute(f"SELECT count(*) FROM {rel}").fetchone()[0], rel, False))
    else:
        if conds:
            rel = f"(SELECT * FROM {view} WHERE {' AND '.join(f'({sql})' for _, _, sql in conds)})"
            scopes.append(("filtered", "Table selection", con.execute(f"SELECT count(*) FROM {rel}").fetchone()[0], rel,
                           view == "vc" and chip.get("synthetic")))
        panels = recent_panels(d, trait, (wanted or "")[6:] if (wanted or "").startswith("panel-") else None)
        names = [panel_name(x) for x in panels]
        for info in panels:  # two panels with the same name get their times
            scopes.append((f"panel-{info['hash']}", panel_name(info, names.count(panel_name(info)) > 1), info["summary"]["n_selected"],
                           f"read_parquet({lit(d / 'panels' / (info['hash'] + '.parquet'))})", info.get("chip_synthetic")))
        scopes.append(("all", "All SNPs", total, view, view == "vc" and chip.get("synthetic")))
    value, label, n, rel, chip_synthetic = next((x for x in scopes if x[0] == wanted), scopes[0])
    cap = int(jobs.setting("SNPPORTAL_MAX_VENDOR_SNPS", 50_000))
    genome = bool(jobs.manifest(d).get("genome"))  # vendor files need the genome
    query = {"trait": trait, "scope": value, **chosen, **settings}
    url = reverse("snpportal:download", args=[key])

    def href(fmt, **extra):
        return f"{url}?{urlencode({**query, 'format': fmt, **extra})}"
    notes = _vendor_notes(con, rel, n) if genome and 0 < n <= cap else {}
    vendor = [f for f in VENDORS if genome]
    rows = []  # (label, [notes], download URL or None)
    if gwas:
        gwas_url = reverse("snpportal:association_download", args=[key])
        rows = [("Fine-mapping (TSV)", ["Every SNP in a locus with tier score and PIP under both priors."],
                 f"{gwas_url}?{urlencode({'trait': trait, **settings, 'format': 'finemap'})}" if n else None),
                ("Loci (TSV)", ["One row per locus: lead SNP, p, credible-set sizes."], f"{gwas_url}?{urlencode({'trait': trait, **settings, 'format': 'loci'})}"),
                ("Loci (BED)", ["The locus windows, for genome browsers."], f"{gwas_url}?{urlencode({'trait': trait, **settings, 'format': 'bed'})}"),
                ("All SNPs (TSV)", ["Every annotation column, one row per SNP."], f"{url}?{urlencode({'trait': trait, 'scope': 'all', 'format': 'tsv'})}")]
        if "kasp" in vendor:
            rows.append((f"KASP: credible-set SNPs ({n:,})", [x for x in notes.get("kasp", []) if x] if n else
                         ["No credible sets: no locus could be fine-mapped."], href("kasp") if notes else None))
    else:
        for fmt, name, about in FORMATS:
            if fmt in VENDORS and fmt not in vendor:
                continue
            text = [x for x in notes.get(fmt, [about]) if x]
            if fmt in VENDORS and n > cap:
                text = [f"Vendor files hold at most {cap:,} SNPs: filter the table or design a panel."]
            rows.append((name, text, None if fmt in VENDORS and not notes else href(fmt)))
    more = [(name.replace("priors", f"priors, all {total:,} SNPs") if fmt == "priors" else name, about,
             href(fmt, **({"scope": "all"} if fmt == "priors" else {})))  # priors need every genotyped SNP: never a subset
            for fmt, name, about in MORE_FORMATS if fmt != "priors" or fmt in getattr(snp_export, "FORMATS", ())] + [("Table without # lines (TSV)", "for scripts", href("tsv", plain="1"))]
    if notes:
        more += [(f"{fmt.upper() if fmt == 'kasp' else fmt.capitalize()}: keep SNPs that fail the assay check or are not checked, flagged", "",
                  href(fmt, include_failed="1")) for fmt in (("kasp",) if gwas else vendor)]
        if "sidecars" in inspect.signature(snp_export.export).parameters:
            more += [(f"{fmt.upper() if fmt == 'kasp' else fmt.capitalize()} {part} file", tip, href(f"{fmt}.{part}"))
                     for fmt in (("kasp",) if gwas else vendor) for part, tip in (("provenance", "how it was made"), ("lookup", "your ids, TOP/BOT and assay status"))]
    return {"query": urlencode({"trait": trait, **chosen, **settings}),
            "exports": {
        "scopes": [(v, f"{lab} ({k:,})" if v != "credible" else lab, v == value) for v, lab, k, _, _ in scopes], "gwas": gwas,
        "trait": trait, "hidden": sorted(chosen.items()), "rows": rows, "more": more, "n": n,
        "synthetic": bool(chip_synthetic) and not _synthetic(job), "panel_link": "?" + urlencode({"tab": "panel", "trait": trait}),
    }}
