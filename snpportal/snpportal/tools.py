"""Breeder tools on a finished job (ROADMAP P6.3, P6.4, P6.6): the Panel tab (compare with a chip, then design a
panel), the Export tab and its downloads, and the figures of both.

snpscore.panel and snpscore.export do the work. This module turns whitelisted URL parameters into their arguments,
keeps each panel as panels/<hash>.parquet (+ .json) and the chip as chip.parquet (+ chip.json) in the job folder (they
expire with the job), and draws the figures. The hash is of the parameters, so the same URL gives the same file.
Design defaults, the chip window W and the assay rules come from the job's weights.yaml snapshot: all PROVISIONAL."""
from __future__ import annotations

import inspect
import math
import os
import re
import tempfile
import uuid
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
from snpscore import export as snp_export, panel as snp_panel
from snpscore.formats import lit

from . import figures, jobs, palette, results

EXPORTS = ("tsv", "parquet", "bed", "illumina", "axiom", "kasp", "bundle")  # ?format= of the download URL
VENDORS = ("illumina", "axiom", "kasp")
MAX_TARGET = 20_000  # largest panel the form designs
MAX_MUST = 200  # must-include ids per panel
LISTED = 500  # selected SNPs listed on the page (the downloads have all)
BIN = 250_000  # bp per tick in the coverage strips (about one pixel of the longest chromosome)
TOP_GAPS = 20  # chip gaps listed on the page (the figure's TSV has all)
EXCLUDE = {  # panel exclusion checkbox = a result column -> label
    "blacklist": "blacklisted region", "lore": "LORe region", "strand_ambiguous": "A/T or C/G alleles",
    "flank_variants": "public variants within 35 bp", "near_chip": "near a chip marker (within W)"}
REASONS = {"must_include": "must include", "backbone": "backbone (best per genome bin)",
           "functional": "functional fill (tier 1–3)", "fill": "fill (tier 4)"}
BINDING = {"min_spacing": "the minimum spacing", "min_spacing_cm": "the minimum spacing in cM", "max_per_gene": "the per-gene cap",
           "max_per_element": "the per-element cap"}
CM_MAPS = {"mean": "sex-averaged", "female": "female", "male": "male"}  # snpscore.panel.CM_MAPS
SPACING = [(0, "<20k"), (20_000, "20k"), (50_000, "50k"), (100_000, "100k"), (200_000, "200k"), (500_000, "500k"),
           (1_000_000, "1M"), (2_000_000, "2M"), (5_000_000, "5M"), (10_000_000, "10M+")]  # (lower edge bp, label)
FORMATS = [  # (format, label, contents) for the Export tab
    ("tsv", "TSV table", "Every annotation column, one row per SNP, after '#' provenance lines."),
    ("parquet", "Parquet", "The same columns for DuckDB, R (arrow) or pandas; provenance in the file's key-value metadata."),
    ("bed", "BED", "chrom, pos − 1, pos and the SNP name, for genome browsers and bedtools."),
    ("illumina", "Illumina-style design file", "Locus_Name, Sequence (60 bp + [A/B] + 60 bp) with the TOP/BOT strand, "
     "Chromosome, Coordinate, Genome_Build_Version and the other design-input columns."),
    ("axiom", "Axiom-style probe file", "35 bp + [ref/alt] + 35 bp with public neighbours as IUPAC codes; A/T and C/G SNPs "
     "flagged as needing two probes."),
    ("kasp", "KASP / Agena file", "Name and 50 bp flanks in [A/G] notation."),
    ("bundle", "Zip bundle", "TSV, BED and the three vendor files, with manifest.json, the weights.yaml snapshot, "
     "methods.txt, provenance.txt, a README and the figures as SVG."),
]
MIME = {"tsv": "text/tab-separated-values; charset=utf-8", "bed": "text/plain; charset=utf-8", "parquet": "application/vnd.apache.parquet",
        "bundle": "application/zip", **{v: "text/csv; charset=utf-8" for v in VENDORS}}
CHIP_ERRORS = {  # ?chip_error= -> message (codes only: no file content or names in URLs)
    "missing": "Choose a chip file, or use the demo chip.",
    "type": "This file type isn't accepted for a chip. Upload a manifest or table (.csv, .tsv, .txt, optionally gzipped), "
            "a VCF or a PLINK .bim/.map file.",
    "size": "The chip file is too large. Compress it with gzip, or keep only the chromosome and position columns.",
    "format": "The chip file could not be read. It needs chromosome and position columns (e.g. Chr/MapInfo, CHROM/POS) or "
              "a VCF, PLINK or Illumina/Axiom manifest layout: see Help for the accepted formats.",
    "empty": "None of the chip's positions are on Ssal_v3.1 chromosomes 1–29. Are they on another assembly (ICSASG_v2)?",
}
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


def _trait(request, weights):
    trait = request.GET.get("trait") or request.POST.get("trait") or "all"
    return trait if trait in (weights or {}).get("presets", {}) else "all"


def _open(d, trait, weights):
    """Sandboxed connection that reads the job folder and the release (genome neighbours, pool) and writes only the
    job folder, with view v = the result plus the tiers of `trait` (as on the Table tab) and, when the job has a chip,
    view vc = v plus on_chip, dist_to_chip, near_chip and novel_functional. Returns (con, view name, its column types)."""
    con = jobs.connect([d, jobs.release()], d)
    con.execute(f"CREATE VIEW r AS SELECT * FROM read_parquet({lit(d / 'result.parquet')}, file_row_number=true)")
    columns = _columns(con, "r")
    tiers = d / "tiers.parquet"
    stored = _columns(con, f"read_parquet({lit(tiers)})") if tiers.exists() else {}
    picked = [c for c in jobs.TIER_COLUMNS if f"{c}__{trait}" in stored]
    if picked:
        drop = [c for c in jobs.TIER_COLUMNS if c in columns]
        keep = f"r.* EXCLUDE ({', '.join(drop)})" if drop else "r.*"
        con.execute(f"CREATE VIEW v AS SELECT {keep}, " + ", ".join(f"t.{jobs.ident(c + '__' + trait)} AS {c}" for c in picked)
                    + f" FROM r JOIN read_parquet({lit(tiers)}) t USING (file_row_number)")
    elif weights:
        con.execute(f"CREATE VIEW v AS {jobs.scored_sql('r', weights, list(columns), trait, d)}")
    else:
        con.execute("CREATE VIEW v AS SELECT * FROM r")
    view = "v"
    if (d / "chip.parquet").exists():
        window = int(snp_panel.settings(weights)["chip_window"])
        con.execute(f"CREATE VIEW vc AS {snp_panel.compare_sql('v', _chip_rel(d), window)}")
        view = "vc"
    return con, view, _columns(con, view)


def _chip_rel(d):
    return f"read_parquet({lit(d / 'chip.parquet')})"


def chip_info(d):
    """chip.json of the job's chip ({} without one): label, synthetic, kept, rejected, sha256, density, results."""
    return jobs.read_json(d / "chip.json") if (d / "chip.parquet").exists() else {}


def _synthetic(job, chip_used=False):
    return bool(job.get("synthetic_input") or job.get("synthetic_layers") or chip_used)


def _meta(job, trait, synthetic, filters=None, panel=None, command=None):
    """Provenance fields for snpscore.export (never SNPs or file names)."""
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
    svg = coverage(_chroms(c["d"], [(chrom, end) for chrom, _, end in ends]), marks, f"Panel markers along the genome, {c['preset']} preset",
                   desc, c["synthetic"], gaps, counts=counts, legend=legend, link=href)
    tsv = c["con"].execute(f"SELECT panel_rank, chrom, pos, {ident}, tier, selection_reason FROM {p['rel']} ORDER BY panel_rank").fetchall()
    return svg, ["panel_rank", "chrom", "pos", "id", "tier", "selection_reason"], tsv


def _fig_tiers(c, link, desc):
    counts = {t: n for t, n in c["panel"]["summary"].get("tiers", {}).items() if t.isdigit()}
    if not counts:
        return None
    return figures.tier_bar(counts, f"Tier mix of the panel, {c['preset']} preset", desc, c["synthetic"]), \
        ["tier", "markers"], sorted(counts.items())


def _fig_composition(c, link, desc):
    p = c["panel"]
    found = {}
    for reason, tier, n in c["con"].execute(f"SELECT selection_reason, tier, count(*) FROM {p['rel']} GROUP BY ALL").fetchall():
        found.setdefault(reason, {})[str(tier)] = n
    total = sum(sum(x.values()) for x in found.values())
    rows = [{"label": REASONS.get(r, r), "note": f"{sum(found[r].values()):,} ({results.pct(sum(found[r].values()), total)})",
             "segments": results._tier_segments(found[r], total, REASONS.get(r, r), None)}
            for r in list(REASONS) + sorted(set(found) - set(REASONS)) if r in found]
    if not rows:
        return None
    svg = figures.hbars(rows, f"Why each marker was chosen, {c['preset']} preset", desc, c["synthetic"],
                        [(palette.TIERS[t][0], figures.TIER_NAMES[t]) for t in (1, 2, 3, 4)], unit="markers")
    return svg, ["selection_reason", "tier", "markers"], [(r, t, n) for r in found for t, n in sorted(found[r].items())]


def _fig_spacing(c, link, desc):
    edges = [e for e, _ in SPACING] + [None]
    sql = ", ".join(f"count(*) FILTER (WHERE d >= {lo}" + (f" AND d < {hi})" if hi else ")") for lo, hi in zip(edges, edges[1:]))
    counts = c["con"].execute(f"""SELECT {sql} FROM (SELECT lead(pos) OVER (PARTITION BY chrom ORDER BY pos) - pos AS d
                                  FROM {c['panel']['rel']}) WHERE d IS NOT NULL""").fetchone()
    if not sum(counts):
        return None
    spacing = c["panel"]["params"]["min_spacing"]
    bars = [(label, n, palette.ACCENT, f"{label}{'' if label.endswith('+') or label.startswith('<') else ' or more'}: {n:,} "
             f"neighbouring pairs", None, None) for (_, label), n in zip(SPACING, counts)]
    svg = figures.histogram(bars, "Spacing between neighbouring markers", desc, c["synthetic"],
                            f"Distance to the next marker (bin lower edge, bp); min spacing {_bp(spacing)}")
    return svg, ["from_bp", "to_bp", "pairs"], [(lo, hi or "", n) for (lo, hi), n in zip(zip(edges, edges[1:]), counts)]


def _fig_gaps(c, link, desc):
    gaps = c["panel"]["gaps"]
    if not gaps:
        return None
    rows = []
    for g in gaps:
        chrom, a, b = g["chrom"], g["start"], g["end"]
        tip = f"{chrom}:{a:,}–{b:,}: {_bp(b - a)} without a marker"
        rows.append({"label": f"chr {chrom}: {a / 1e6:.1f}–{b / 1e6:.1f} Mb", "note": _bp(b - a),
                     "segments": [(b - a, palette.ACCENT, tip, link(chrom=chrom, start=a, end=b) if link else None)]})
    svg = figures.hbars(rows, "Largest gaps in the panel", desc, c["synthetic"], unit="bp")
    return svg, ["chrom", "from", "to", "length"], [(g["chrom"], g["start"], g["end"], g["size"]) for g in gaps]


def _fig_chip(c, link, desc):
    chip = c["chip"]
    res = chip["results"][c["trait"]]
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
    svg = coverage(_chroms(c["d"], ends.items()), marks, f"Chip coverage and novel functional SNPs, {c['preset']} preset",
                   desc, c["synthetic"], gaps, density, counts, legend, href)
    tsv = [(g["chrom"], g["start"], g["end"], g["size"], *((g["filler"][k] for k in ("chrom", "pos", "id", "tier", "source"))
                                                         if g["filler"] else ("",) * 5)) for g in res["gaps"]]
    return svg, ["chrom", "from", "to", "length", "best_chrom", "best_pos", "best_id", "best_tier", "best_source"], tsv


FIGURES = {  # name -> (card title, (i) definition, builder(context, link or None, desc) -> (svg, header, rows) or None)
    "panel-coverage": ("Panel markers along the genome", "Chromosomes to scale (Ssal_v3.1). A tick per marker (per 250 kb "
                       "when they are close), coloured by tier; the number on the right is the markers per chromosome. "
                       "Highlighted: gaps longer than the threshold in the form. Click a gap to list the SNPs in it.",
                       _fig_coverage),
    "panel-tiers": ("Tier mix of the panel", "Markers per tier for the preset (tier rules PROVISIONAL).", _fig_tiers),
    "panel-composition": ("Why each marker was chosen", "must include: your ids; backbone: the best SNP in each "
                          "genome-length bin, so the panel spreads over every chromosome; functional fill: the rest by "
                          "design score (tier score, assay status and MAF; PROVISIONAL weights).", _fig_composition),
    "panel-spacing": ("Spacing between neighbouring markers", "Distances between consecutive markers on each chromosome. "
                      "None is below the minimum spacing.", _fig_spacing),
    "panel-gaps": ("Largest gaps in the panel", "The longest stretches without a marker (chromosome ends count). Click a "
                   "bar to list the SNPs in the gap.", _fig_gaps),
    "chip-coverage": ("Chip coverage and novel functional SNPs", "Top lane: the chip's markers per 1 Mb (darker = more). "
                      "Ticks: your tier 1–2 SNPs with no chip marker within W (novel functional). Highlighted: chip "
                      "gaps over 1 Mb (PROVISIONAL). Click a gap to list your SNPs in it.", _fig_chip),
}


def figure_card(c, name, built):
    url = reverse("snpportal:tool_figure", args=[c["key"], name])
    query = urlencode({"trait": c["trait"], **({"panel": c["panel"]["hash"], "gap_mb": f"{c['panel']['gap_bp'] / 1e6:g}"}
                                                 if name.startswith("panel") else {})})
    caption = " · ".join(x for x in [
        f"Release {c['job'].get('release')}", f"preset {c['preset']}",
        f"panel {c['panel']['hash']}" if name.startswith("panel") else None,
        "tier rules and design defaults PROVISIONAL", f"job created {c['job'].get('created_utc')}",
        "SYNTHETIC test data" if c["synthetic"] else None] if x)
    return {"name": name, "title": FIGURES[name][0], "info": FIGURES[name][1], "svg": mark_safe(built[0]),
            "svg_url": f"{url}?{query}", "tsv_url": f"{url}?{query}&format=tsv", "caption": caption}


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
    trait = _trait(request, weights)
    con, view, types = _open(d, trait, weights)
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


def _context(key, job, d, trait, con):
    return {"key": key, "job": job, "d": d, "trait": trait, "preset": trait.replace("_", " "), "con": con,
            "synthetic": _synthetic(job)}


# ---- the panel designer ----

def _params(request, weights, types):
    """(design parameters, form state) from the URL: blank or out-of-range values give the weights.yaml 'design'
    default (PROVISIONAL). Before the form is first sent (no design=1) the default checkboxes are ticked."""
    get, default = request.GET.get, snp_panel.settings(weights)
    sent = get("design") == "1"
    allowed = [f for f in EXCLUDE if f in types]
    ids = MUST.findall(get("must", "")[:20_000])
    p = {
        "n_target": _number(get("n"), int, 1, MAX_TARGET, min(int(default["n_target"]), MAX_TARGET)),
        "min_spacing": round(1000 * _number(get("spacing_kb"), float, 0, 100_000, default["min_spacing"] / 1000)),
        "min_maf": _number(get("maf"), float, 0, 0.5, float(default["min_maf"])),
        "backbone_fraction": _number(get("backbone"), float, 0, 1, float(default["backbone_fraction"])),
        "max_per_gene": _number(get("per_gene"), int, 1, 100_000, int(default["max_per_gene"])),
        "max_per_element": _number(get("per_element"), int, 1, 100_000, int(default["max_per_element"])),
        "require_assay_pass": get("assay_pass") == "1" if sent else bool(default["require_assay_pass"]),
        "exclude_flags": sorted({f for f in (request.GET.getlist("exclude") if sent else default["exclude_flags"]) if f in allowed}),
        "must_include": sorted(set(ids))[:MAX_MUST],
    }
    if {"cm_female", "cm_male"} <= set(types):  # R5: also keep markers this many cM apart (blank or 0: bp only)
        cm = _number(get("spacing_cm"), float, 0, 1000, None if sent else default.get("min_spacing_cm"))
        if cm:  # only then in the parameters, so bp-only panels keep their hash
            p.update(min_spacing_cm=cm, cm_map=get("cm_map") if get("cm_map") in CM_MAPS else default.get("cm_map") or "mean")
    return p, {"too_many_ids": len(set(ids)) > MAX_MUST}


def _fields(p, types, gap_mb):
    """The form's number inputs: (name, label, value, min, max, step, help), gated on the columns they need."""
    maf = jobs.maf_sql(types)[0]
    fields = [
        ("n", "Markers", p["n_target"], 1, MAX_TARGET, 1, "Number of SNPs to choose"),
        ("spacing_kb", "Min spacing (kb)", f"{p['min_spacing'] / 1000:g}", 0, 100_000, "any", "No two markers closer than this"),
        ("spacing_cm", "Min spacing (cM)", f"{p['min_spacing_cm']:g}" if p.get("min_spacing_cm") else "", 0, 1000, "any",
         "Also no two markers closer than this on the Brekke et al. 2023 genetic map (blank: bp only); SNPs beyond a "
         "chromosome's first or last map marker take that marker's cM") if {"cm_female", "cm_male"} <= set(types) else None,
        ("backbone", "Backbone share", f"{p['backbone_fraction']:g}", 0, 1, 0.05,
         "Share of the panel spread evenly over the genome (the best SNP per genome-length bin); the rest is chosen by design score"),
        ("maf", "Min MAF", f"{p['min_maf']:g}", 0, 0.5, 0.01, "Your maf/af column, else the public MAF; SNPs with no MAF pass") if maf else None,
        ("per_gene", "Max per gene", p["max_per_gene"], 1, 100_000, 1, "Nearest gene (gene_id)") if "gene_id" in types else None,
        ("per_element", "Max per element", p["max_per_element"], 1, 100_000, 1, "AQUA-FAANG peak (chromatin_id)") if "chromatin_id" in types else None,
        ("gap_mb", "Highlight gaps over (Mb)", f"{gap_mb:g}", 0.01, 1000, "any", "Display only: gaps this long are highlighted in the coverage figure"),
    ]
    return [dict(zip(("name", "label", "value", "min", "max", "step", "help"), f)) for f in fields if f]


def _saved(d, h):
    """A saved panel's .json, or None (h must be a hash of this job's panels)."""
    if not re.fullmatch(r"[0-9a-f]{16}", h or "") or not (d / "panels" / f"{h}.parquet").exists():
        return None
    return jobs.read_json(d / "panels" / f"{h}.json") or None


def _design(con, view, d, trait, p, weights, chip):
    """panels/<hash>.parquet and .json for the parameters: made once, as the same parameters give the same panel."""
    key = {"v": 1, "preset": trait, **p, "weights": jobs.sha256(d / "weights.yaml") if (d / "weights.yaml").exists() else None,
           "chip": chip.get("sha256")}
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
                             **{k: p[k] for k in ("min_spacing_cm", "cm_map") if k in p})
        info = {"hash": h, "selection_hash": r["hash"], "preset": trait, "params": p, "summary": r["summary"],
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
    interfere (snpscore.panel.vendor_checks; vendor rules, RESEARCH.md section 5)."""
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
    return (f"Only {s['n_selected']:,} of the {s['n_target']:,} markers could be chosen: the binding constraint is "
            f"{BINDING.get(b, b) or 'the filters'}.")


def _panel_kpis(s, assay):
    n = s["n_selected"]
    gaps = s.get("largest_gaps") or []
    tiers = s.get("tiers", {})
    out = [{"value": f"{n:,}", "label": "markers", "note": f"of {s['n_target']:,} wanted"},
           {"value": f"{int(tiers.get('1', 0)) + int(tiers.get('2', 0)):,}", "label": "tier 1–2", "note": results.pct(
               int(tiers.get("1", 0)) + int(tiers.get("2", 0)), n) + " of the panel", "provisional": True},
           {"value": _bp((s.get("spacing") or {}).get("median")), "label": "median spacing",
            "note": f"min {_bp((s.get('spacing') or {}).get('min'))}"},
           *([{"value": _cm(s["spacing_cm"].get("median")), "label": "median spacing (cM)",
               "note": f"min {_cm(s['spacing_cm'].get('min'))}, genetic map"}] if s.get("spacing_cm") else []),
           {"value": _bp(gaps[0]["size"]) if gaps else "–", "label": "largest gap",
            "note": f"chr {gaps[0]['chrom']}, chromosome ends count" if gaps else ""},
           {"value": f"{s['n_candidates']:,}", "label": "candidates", "note": f"of {s['n_rows']:,} SNPs pass the filters"}]
    if assay:
        checked = n - assay.get("not_checked", 0) - assay.get("null", 0)
        out.insert(4, {"value": results.pct(assay.get("pass", 0), checked), "label": "assay pass",
                       "note": f"of {checked:,} checked", "provisional": True})
    return out


def _listed(con, info, d, trait, key):
    """The first LISTED selected SNPs in rank order, display-ready."""
    rel = f"read_parquet({lit(d / 'panels' / (info['hash'] + '.parquet'))})"
    cols = _columns(con, rel)
    maf = jobs.maf_sql(cols)[0]
    want = [c for c in ("source_row", "panel_rank", "selection_reason", "design_score", "chrom", "pos", "id", "ref", "alt", "tier",
                        "gene_name", "gene_id", "gene_ortholog_human", "region_class", "assay_status", "assay_reasons", "on_chip")
            if c in cols]
    cur = con.execute(f"SELECT {', '.join(map(jobs.ident, want))}{f', {maf} AS _maf' if maf else ''} FROM {rel} "
                      f"ORDER BY panel_rank LIMIT {LISTED}")
    names = [x[0] for x in cur.description]
    q = urlencode({"trait": trait})
    out = []
    for r in (dict(zip(names, x)) for x in cur.fetchall()):
        g = r.get
        status = g("assay_status") or ("not_checked" if "assay_status" in r else None)
        out.append({"rank": g("panel_rank"), "url": f"{reverse('snpportal:card', args=[key, g('source_row')])}?{q}",
                    "name": g("id") if g("id") not in (None, ".") else f"{g('chrom')}:{g('pos')}",
                    "position": f"{g('chrom')}:{g('pos')}", "alleles": f"{g('ref')}>{g('alt')}" if g("ref") and g("alt") else "",
                    "tier": g("tier"), "reason": REASONS.get(g("selection_reason"), g("selection_reason")),
                    "gene": results.gene_label(g("gene_name"), g("gene_id"), g("gene_ortholog_human")),
                    "region": results.CLASS_LABELS.get(g("region_class"), g("region_class")) or "intergenic",
                    "maf": "" if g("_maf") is None else f"{g('_maf'):.2f}", "score": f"{g('design_score'):.3f}",
                    "assay": (results.ASSAY.get(status, ("?", "not_checked")) + (status.replace("_", " "), g("assay_reasons") or ""))
                    if status else None, "on_chip": g("on_chip")})
    return out


def panel(request, key, job):
    """Context for the Panel tab: the chip comparison and the panel designer (form, summary, figures, selected SNPs).
    The default panel is designed on the first visit; every parameter set is cached in the job folder."""
    d = jobs.folder(key)
    weights = jobs.weights(d)
    trait = _trait(request, weights)
    con, view, types = _open(d, trait, weights)
    chip = chip_info(d)
    c = _context(key, job, d, trait, con)
    link = results.table_link(trait)
    p, notes = _params(request, weights, types)
    info = _design(con, view, d, trait, p, weights, chip)
    gap = _number(request.GET.get("gap_mb"), float, 0.01, 1000, None)
    pv = _panel_view(d, info, gap * 1e6 if gap else None)
    c.update(panel=pv, synthetic=_synthetic(job, info.get("chip_synthetic")))
    s = info["summary"]
    q = {"trait": trait, "scope": f"panel-{pv['hash']}"}
    cm = {"cm_female", "cm_male"} <= set(types)
    url = reverse("snpportal:download", args=[key])
    designer = {
        "fields": _fields(p, types, pv["gap_bp"] / 1e6), "must": " ".join(p["must_include"]), "too_many_ids": notes["too_many_ids"],
        "max_must": MAX_MUST, "assay": "assay_status" in types, "assay_pass": p["require_assay_pass"],
        "cm_maps": [(k, label, k == p.get("cm_map", "mean")) for k, label in CM_MAPS.items()] if cm else [],
        "vendor": vendor_checks(con, pv["rel"]),
        "checks": [(f, EXCLUDE[f], f in p["exclude_flags"]) for f in EXCLUDE if f in types],
        "window": _bp(snp_panel.settings(weights)["chip_window"]), "synthetic": c["synthetic"], "hash": pv["hash"],
        "short": _short(s), "missing": s.get("missing_must_include") or [], "kpis": _panel_kpis(s, s.get("assay_status")),
        "regions": [(results.CLASS_LABELS.get(k, k), n) for k, n in sorted((s.get("region_class") or {}).items(), key=lambda x: -x[1])],
        "figs": _figures(c, [n for n in FIGURES if n.startswith("panel")], link),
        "rows": _listed(con, info, d, trait, key), "listed": LISTED,
        "downloads": [(label, f"{url}?{urlencode({**q, 'format': fmt})}") for fmt, label in (
            ("tsv", "TSV"), ("illumina", "Illumina"), ("axiom", "Axiom"), ("kasp", "KASP"), ("bundle", "Zip bundle"))
            if fmt not in VENDORS or jobs.manifest(d).get("genome")],
        "export_link": "?" + urlencode({"tab": "export", **q}),
        "report_url": f"{reverse('snpportal:report', args=[key])}?{urlencode({'trait': trait, 'panel': pv['hash']})}",
        "reset": "?" + urlencode({"tab": "panel", "trait": trait}),
    }
    return {"designer": designer, "chip": _chip_context(request, key, job, d, trait, con, weights, chip, link)}


# ---- chip comparison ----

def _compared(con, d, trait, weights, chip):
    """chip.json with the comparison for `trait` (cached there): counts, chip gaps with the best SNP of the list or the
    release pool, and the novel functional SNPs per BIN for the figure."""
    if trait in chip.get("results", {}):
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
    window = int(snp_panel.settings(weights)["chip_window"])
    res["novel_bins"] = [list(x) for x in con.execute(
        f"SELECT chrom, pos // {BIN} * {BIN}, min(tier), count(*) FROM ({snp_panel.compare_sql('v', _chip_rel(d), window)}) "
        "WHERE novel_functional GROUP BY ALL ORDER BY ALL").fetchall()]
    chip.setdefault("results", {})[trait] = res
    jobs._write_json(d / "chip.json", chip)
    return chip


def _chip_context(request, key, job, d, trait, con, weights, chip, link):
    """Context for _chip.html: the upload form, or the comparison (KPIs, figure, gaps table)."""
    demo = jobs.release() / "demo" / "chip_demo_SYNTHETIC.tsv"
    out = {"url": reverse("snpportal:chip", args=[key]), "demo": demo.is_file(), "error": CHIP_ERRORS.get(request.GET.get("chip_error")),
           "window": _bp(snp_panel.settings(weights)["chip_window"]), "info": chip}
    if not chip:
        return out
    chip = _compared(con, d, trait, weights, chip)
    res = chip["results"][trait]
    s = res["summary"]
    c = _context(key, job, d, trait, con)
    c.update(chip=chip, synthetic=_synthetic(job, chip.get("synthetic")))
    q = urlencode({"trait": trait})
    gaps = []
    for g in res["gaps"][:TOP_GAPS]:
        f = g["filler"]
        gaps.append({**g, "size_text": _bp(g["size"]), "table": link(chrom=g["chrom"], start=g["start"], end=g["end"]),
                     "card": f"{reverse('snpportal:card', args=[key, f['row']])}?{q}" if f and f.get("row") is not None else None})
    out.update(info=chip, synthetic=c["synthetic"], gaps=gaps, n_gaps=len(res["gaps"]), top=TOP_GAPS,
               rejected=[(k.replace("_", " "), n) for k, n in (chip.get("rejected") or {}).items()],
               kpis=[{"value": f"{s['chip_snps']:,}", "label": "chip markers", "note": f"{sum(n for _, n in chip.get('rejected', {}).items()):,} "
                      "rows left out" if chip.get("rejected") else "all on chromosomes 1–29"},
                     {"value": f"{s['shared']:,}", "label": "shared", "note": f"{results.pct(s['shared'], s['total'])} of your SNPs are on the chip"},
                     {"value": f"{s['novel_functional']:,}", "label": "novel functional", "provisional": True,
                      "note": f"tier 1–2, no chip marker within {_bp(s['window_bp'])}"},
                     {"value": f"{s['other']:,}", "label": "other", "note": "near the chip, or tier 3–4"},
                     {"value": f"{s['gaps']:,}", "label": "chip gaps", "note": f"over {_bp(s['gap_bp'])}", "provisional": True}],
               fig=_figures(c, ["chip-coverage"], link).get("coverage"))
    return out


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
    trait = _trait(request, jobs.weights(d))
    if request.POST.get("remove"):
        for name in ("chip.parquet", "chip.json"):
            (d / name).unlink(missing_ok=True)
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
    new = d / ".chip-new.parquet"
    try:
        report = snp_panel.read_chip(src, jobs.release(), new)
    except (snpscore.InputError, duckdb.Error):
        return _chip_redirect(key, trait, "format")
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
    os.replace(new, d / "chip.parquet")
    rejected = {k: v for k, v in (report.get("rejected") or {}).items() if v}
    jobs._write_json(d / "chip.json", {"label": label, "synthetic": synthetic, "kept": report["snps_kept"],
                                       "rows": report.get("rows_read"), "rejected": rejected, "format": report.get("format"),
                                       "sha256": jobs.sha256(d / "chip.parquet"), "created_utc": jobs.utc(),
                                       "density": density, "results": {}})
    return _chip_redirect(key, trait)


# ---- the Export tab and downloads ----

def _scope(request, d, con, view, types, weights, job):
    """(view to export, tag for the file name, filters {name: value}, panel hash, synthetic) for ?scope=: all,
    filtered (the Table tab's filters in the URL) or panel-<hash>."""
    scope = request.GET.get("scope", "all")
    if scope.startswith("panel-"):
        info = _saved(d, scope[6:])
        if info is None:
            raise Http404("No such panel")
        con.execute(f"CREATE OR REPLACE VIEW p AS SELECT source_row AS file_row_number, * EXCLUDE (source_row) "
                    f"FROM read_parquet({lit(d / 'panels' / (info['hash'] + '.parquet'))})")
        return "p", f"panel-{info['hash']}", {}, info["hash"], _synthetic(job, info.get("chip_synthetic"))
    synthetic = _synthetic(job, view == "vc" and chip_info(d).get("synthetic"))
    conds = results.filters(request, types, weights) if scope == "filtered" else []
    if not conds:
        return view, None, {}, None, synthetic
    con.execute(f"CREATE OR REPLACE VIEW f AS SELECT * FROM {view} WHERE " + " AND ".join(f"({sql})" for _, _, sql in conds))
    chosen = {k: v for params, _, _ in conds for k, v in params.items()}
    return "f", "filtered", chosen, None, synthetic


def _command(job, trait, tag):
    base = f"snpscore annotate <your list> --release <release {job.get('release')}> --trait {trait} -o annotated.parquet"
    if tag and tag.startswith("panel-"):
        return base + f"; snpscore panel annotated.parquet --release <release {job.get('release')}> --preset {trait} (parameters in panels/{tag[6:]}.json of the job)"
    return base + f"; snpscore export annotated.parquet --release <release {job.get('release')}> --preset {trait} --format <format>"


def export(request, key, job, fmt):
    """The download view's formats beyond the table's TSV: tsv, parquet, bed, illumina, axiom, kasp or bundle of the
    whole result, the filtered table (?scope=filtered plus the Table tab's filters) or a panel (?scope=panel-<hash>).
    TSV and BED start with snpscore's provenance lines (?plain=1 drops them); vendor files hold none, so
    ?format=<vendor>.provenance or .lookup gives the sidecar snpscore writes next to them (provenance; ids, TOP/BOT and
    assay status). Vendor rows that fail the assay check or are not checked are left out unless ?include_failed=1."""
    fmt, _, part = fmt.partition(".")
    if fmt not in EXPORTS or part not in ("", "provenance", "lookup") or part and fmt not in VENDORS:
        raise Http404("Unknown export format")
    d = jobs.folder(key)
    weights = jobs.weights(d)
    trait = _trait(request, weights)
    con, view, types = _open(d, trait, weights)
    table, tag, filters, panel_hash, synthetic = _scope(request, d, con, view, types, weights, job)
    n = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
    cap = int(jobs.setting("SNPPORTAL_MAX_VENDOR_SNPS", 50_000))
    if fmt in VENDORS and n > cap:
        return render(request, "snpportal/stub.html", {"nav": "score", "title": "Too many SNPs for a vendor file", "message":
                      f"Vendor files are for panels: this export has {n:,} SNPs, more than {cap:,}. Design a panel on the "
                      "Panel tab, or filter the table first."}, status=400)
    formats = ["tsv", "bed"] + (list(VENDORS) if n <= cap else [])
    notes = {"vendor_files": f"left out above {cap:,} SNPs"} if fmt == "bundle" and n > cap else {}
    meta = _meta(job, trait, synthetic, {**filters, **notes}, panel_hash, _command(job, trait, tag))
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
    """The job's saved panels, newest first: [info]."""
    found = [jobs.read_json(p.with_suffix(".json")) for p in (d / "panels").glob("*.parquet")] if (d / "panels").is_dir() else []
    return sorted((x for x in found if x), key=lambda x: x.get("created_utc", ""), reverse=True)


def exports(request, key, job):
    """Context for the Export tab: what to export (all, the filtered table, a saved panel), the formats and options."""
    d = jobs.folder(key)
    weights = jobs.weights(d)
    trait = _trait(request, weights)
    con, view, types = _open(d, trait, weights)
    conds = results.filters(request, types, weights)
    chosen = {k: v for params, _, _ in conds for k, v in params.items()}
    total = con.execute("SELECT count(*) FROM r").fetchone()[0]
    scopes = [("all", "All SNPs of the list", total, view)]  # (value, label, SNPs, relation)
    if conds:
        rel = f"(SELECT * FROM {view} WHERE {' AND '.join(f'({sql})' for _, _, sql in conds)})"
        scopes.append(("filtered", "The filtered table: " + "; ".join(label for _, label, _ in conds),
                       con.execute(f"SELECT count(*) FROM {rel}").fetchone()[0], rel))
    for info in _panels(d):
        s, p = info["summary"], info["params"]
        label = [f"Panel {info['hash']}: {s['n_selected']:,} markers", f"{info['preset'].replace('_', ' ')} preset",
                 f"min spacing {_bp(p['min_spacing'])}" + (f" and {p['min_spacing_cm']:g} cM" if p.get("min_spacing_cm") else ""),
                 "excluding " + ", ".join(EXCLUDE.get(f, f) for f in p["exclude_flags"])
                 if p["exclude_flags"] else None, f"with the {info['chip'][0].lower() + info['chip'][1:]}" if info.get("chip") else None]
        scopes.append((f"panel-{info['hash']}", ", ".join(x for x in label if x), s["n_selected"],
                       f"read_parquet({lit(d / 'panels' / (info['hash'] + '.parquet'))})"))
    wanted = request.GET.get("scope") or ("filtered" if conds else "all")
    wanted = wanted if wanted in [s[0] for s in scopes] else "all"
    chip = chip_info(d)
    cap = int(jobs.setting("SNPPORTAL_MAX_VENDOR_SNPS", 50_000))
    genome = bool(jobs.manifest(d).get("genome"))  # vendor files need the genome; checks only where they can be written
    return {"query": urlencode({"trait": trait, **chosen}), "exports": {
        "url": reverse("snpportal:download", args=[key]), "trait": trait, "hidden": sorted(chosen.items()),
        "scopes": [(value, label, n, value == wanted, vendor_checks(con, rel) if genome and 0 < n <= cap else None)
                   for value, label, n, rel in scopes],
        "formats": [f for f in FORMATS if f[0] not in VENDORS or genome],  # vendor files need the genome
        "locus_name": snp_export.locus_name("25", 28996360, {"25"}),
        "vendor_cap": cap, "chip": chip.get("label"),
        "sidecars": VENDORS if "sidecars" in inspect.signature(snp_export.export).parameters else (),
        "synthetic": _synthetic(job, chip.get("synthetic")), "layout_note": snp_export.LAYOUT_NOTE,
        "panel_link": "?" + urlencode({"tab": "panel", "trait": trait}),
    }}
