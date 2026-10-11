"""The locus browser page (/snp/locus/): tracks in groups on one axis, each track its own SVG beside an HTML label, so a
group opens in place (combined track always, one track per condition when open). Release lanes come from
snpscore.locus; ChromHMM and the per-condition peaks are read live from salmobase (tracks.yaml) on snpscore's tile
grid; the functional assays (RNA-seq, ATAC-seq, ChIP-seq, means over replicates) load one assay at a time when their
section is opened (/snp/locus/assay/). A red band marks the centre: the SNP the view was opened on, else the middle.
?open= lists the open groups, so a link keeps them. The single-SVG figure (locus_svg.locus) stays the download and
the card's and gene page's views."""
from __future__ import annotations

import math
from html import escape
from urllib.parse import urlencode

from django.http import HttpResponseBadRequest
from django.shortcuts import render
from django.urls import reverse
from django.utils.safestring import mark_safe

from snpscore import locus as sl
from snpscore.formats import lit

from . import explore, jobs, locus, locus_svg, palette
from .views import private

W = 1000  # SVG user units across the track column, drawn 1:1 so text never stretches
G = palette.GREY
TISSUE_ORDER = ("Brain", "Gonad", "Liver", "Muscle", "Gill", "HeadKidney", "DistalIntestine", "Embryo")
TISSUE_NAMES = {"HeadKidney": "Head kidney", "DistalIntestine": "Distal intestine"}
STAGES = {"LateCleavage": "L cleavage", "EarlyBlastulation": "E blastula", "MidBlastulation": "M blastula",
          "LateBlastulation": "L blastula", "EarlyGastrulation": "E gastrula", "MidGastrulation": "M gastrula",
          "LateGastrulation": "L gastrula", "EarlySomitogenesis": "E somit.", "EarlyMidSomitogenesis": "EM somit.",
          "MidSomitogenesis": "M somit.", "MidLateSomitogenesis": "ML somit.", "LateSomitogenesis": "L somit.",
          "EarlyEyed": "E eyed", "LateEyed": "L eyed"}  # embryo stages in developmental order
STATE_ORDER = locus_svg.STATE_ORDER  # stacked bottom to top; Quiescent is not drawn
LEGEND_STATES = ("Active_TSS", "Flanking_upstream", "Active_enhancer", "Primed_enhancer", "Poised_enhancer_1",
                 "Accessible_chromatin", "Bivalent", "Repressed_polycomb", "ZNF_genes_and_repeats", "Quiescent")
ASSAYS = {"RNA": ("RNA-seq", "expression; + strand up, &#8722; down; conditions on a log scale"), "ATAC": ("ATAC-seq", "open chromatin"),
          "H3K27ac": ("ChIP-seq H3K27ac", "active enhancers and promoters"), "H3K4me3": ("ChIP-seq H3K4me3", "active promoters"),
          "H3K4me1": ("ChIP-seq H3K4me1", "enhancers, active and primed"), "H3K27me3": ("ChIP-seq H3K27me3", "polycomb repression"),
          "CTCF": ("ChIP-seq CTCF", "insulators")}
SKIP_TISSUES = {"Sperm"}  # sperm ChIP is left out (salmobase answers 403 for its files)
GROUPS = ("peaks", "hmm", "assays", *ASSAYS)  # the groups ?open= may list


# ---- view state, links and the centre ----

def opened(request):
    """The open groups of ?open= (comma-separated, known names only)."""
    return [g for g in request.GET.get("open", "").split(",") if g in GROUPS]


def query(s, open_, **changes):
    """URL parameters of view s with its open groups; changes as in locus.query (start/end in BED coordinates)."""
    start, end = changes.pop("start", s["start"]), changes.pop("end", s["end"])
    params = {"r": locus.region_text(s["chrom"], start, end), "key": s["key"] or "", "trait": s["trait"], "open": ",".join(open_),
              **s.get("gwas", {}), **changes}
    return urlencode({k: v for k, v in params.items() if v not in ("", None, "all")})


def moves(s, open_):
    """(label, query, title) for zoom out and in (x3) and moving half a window, as locus.moves."""
    w, mid = s["end"] - s["start"], (s["start"] + s["end"]) // 2
    span = lambda width, centre=mid: sl.clamp(centre - width // 2, centre + width - width // 2, s.get("size"), sl.MIN_WINDOW, sl.MAX_WINDOW)  # noqa: E731
    out = []
    for label, (a, b), title in [("−", span(w * 3), "Zoom out 3x"), ("+", span(w // 3), "Zoom in 3x"),
                                 ("◀", span(w, mid - w // 2), "Move left half a window"),
                                 ("▶", span(w, mid + w // 2), "Move right half a window")]:
        out.append((label, query(s, open_, start=a, end=b) if (a, b) != (s["start"], s["end"]) else None, title))
    return out


def centre(s):
    """The 1-based position the view centres on: the SNP it was opened on, else the window's middle base."""
    return s["mark"] or (s["start"] + s["end"] + 1) // 2


def trk(h, body):
    """One track: an SVG on the shared axis (class sp-ax: portal.js draws the mouse line through these)."""
    return mark_safe(f'<svg class="sp-trk-svg sp-ax" viewBox="0 0 {W} {h}" width="{W}" height="{h}" role="img">{body}</svg>')


def plain(h, body):
    """A row that isn't on the axis (no mouse line)."""
    return mark_safe(f'<svg class="sp-trk-svg" viewBox="0 0 {W} {h}" width="{W}" height="{h}" role="img">{body}</svg>')


def row(label, svg, sub="", tissue=None, dense=False):
    return {"label": label, "sub": sub, "tissue": tissue, "svg": svg, "dense": dense}


def group(gid, title, note, rows, more=(), more_label="", open_=(), legend=None, kind="grp"):
    return {"id": gid, "title": title, "note": mark_safe(note), "rows": rows, "more": list(more), "more_label": more_label,
            "open": gid in open_, "legend": legend or [], "kind": kind}


def tissue_of(condition):
    return "Embryo" if condition in STAGES or "_" not in condition else condition.split("_")[0]


def short(condition):
    """'Brain Imm F', 'Head kidney Mat M', 'L blastula'."""
    if "_" not in condition:
        return STAGES.get(condition, condition)
    t, m, x = condition.split("_")
    return f"{TISSUE_NAMES.get(t, t)} {m[:3]} {x[0]}"


def order(condition):
    """Tissues in TISSUE_ORDER, then immature F, M, mature F, M; embryo stages in developmental order."""
    t = tissue_of(condition)
    return (TISSUE_ORDER.index(t) if t in TISSUE_ORDER else len(TISSUE_ORDER),
            list(STAGES).index(condition) if condition in STAGES else 0, condition)


# ---- the chromosome and the ruler ----

def release_rows(name, sql_where, params):
    path = jobs.release() / f"{name}.parquet"
    if not path.exists():
        return []
    cur = jobs.connect([jobs.release()]).execute(f"SELECT * FROM read_parquet({lit(path)}) WHERE {sql_where}", params)
    names = [d[0] for d in cur.description]
    return [dict(zip(names, r)) for r in cur.fetchall()]


def chromosome(s):
    """The whole chromosome with the window boxed, the Ss4R duplicate block around the window (grey, its partner named;
    hover: both regions and the AORe/LORe pair counts) and LORe hatching where it touches that block or the window."""
    size, h, y = s.get("size") or s["end"], 14, 3
    sx = lambda pos: pos / size * W  # noqa: E731
    blocks = release_rows("synteny", "chrom = ? AND start < ? AND \"end\" > ?", [s["chrom"], s["end"], s["start"]])
    near = [(s["start"], s["end"])] + [(b["start"], b["end"]) for b in blocks]
    lores = [r for r in release_rows("lore", "chrom = ?", [s["chrom"]]) if any(r["start"] < e and r["end"] > a for a, e in near)]
    out = [f'<defs><clipPath id="sp-chr"><rect x="0" y="{y}" width="{W}" height="{h}" rx="{h / 2}"/></clipPath>'
           f'<pattern id="sp-chr-lore" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(-45)">'
           f'<line x1="0" y1="0" x2="0" y2="6" stroke="{locus_svg.LORE}" stroke-width="2.4"/></pattern></defs>',
           f'<g clip-path="url(#sp-chr)"><rect x="0" y="{y}" width="{W}" height="{h}" fill="{G[100]}"/>']
    for b in blocks:
        w = sx(b["end"]) - sx(b["start"])
        tip = (f"Ss4R duplicate block chr{s['chrom']}:{b['start'] / 1e6:.1f}-{b['end'] / 1e6:.1f} Mb = chr{b['partner']}:"
               f"{b['partner_start'] / 1e6:.1f}-{b['partner_end'] / 1e6:.1f} Mb · {b['pairs']} duplicate gene pairs ({b['aore']} AORe, {b['lore']} LORe)")
        out.append(f'<rect x="{sx(b["start"]):.1f}" y="{y}" width="{max(w, 1):.1f}" height="{h}" fill="{G[300]}" stroke="{palette.WHITE}" '
                   f'stroke-width="1.5"><title>{escape(tip)}</title></rect>'
                   + (locus_svg._t(sx(b["start"]) + 8, y + 10.5, f"Ss4R block, duplicated on chr{b['partner']}", 9.5, G[900],
                                   extra=' pointer-events="none"') if w > 170 else ""))
    for r in lores:
        x0, x1 = sx(r["start"]), sx(r["end"])
        out.append(f'<rect x="{x0:.1f}" y="{y}" width="{x1 - x0:.1f}" height="{h}" fill="url(#sp-chr-lore)" fill-opacity="0.55">'
                   f'<title>LORe region {escape(str(r.get("label") or ""))}: the duplicate copies are still nearly identical '
                   f'(late rediploidisation)</title></rect>')
    a, e = sx(s["start"]), sx(s["end"])
    out.append(f'</g><rect x="0" y="{y}" width="{W}" height="{h}" rx="{h / 2}" fill="none" stroke="{G[500]}" stroke-width="0.8"/>'
               f'<rect x="{a - 2:.1f}" y="{y - 3}" width="{max(4, e - a) + 4:.1f}" height="{h + 6}" fill="none" stroke="{palette.ACCENT}" '
               f'stroke-width="2" rx="2"><title>this window</title></rect>')
    return plain(h + 6, "".join(out))


def ruler(ax, s):
    """Positions along the window, the centre's in red."""
    body = [f'<line x1="0" x2="{W}" y1="30" y2="30" stroke="{G[500]}"/>',
            locus_svg._t(ax.x(centre(s) - 0.5), 9, f"{centre(s):,}", 10.5, palette.CENTRE, "middle", "600")]
    for t in ax.ticks(8):
        x = ax.x(t)
        half = 3.3 * len(f"{t:,}")
        anchor = "start" if x - half < 0 else "end" if x + half > W else "middle"
        body.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="25" y2="30" stroke="{G[500]}"/>' + locus_svg._t(x, 21, f"{t:,}", 11, G[900], anchor))
    return trk(34, "".join(body))


# ---- genes and variants ----

def duplicates(genes):
    """Each gene's Ss4R duplicate (release ss4r layer) as the gene label's link: {text, url, title}."""
    found = explore.ss4r([g["id"] for g in genes])
    for g in genes:
        dup = found.get(g["id"]) or {}
        copy = (dup.get("copies") or [None])[0]
        if not copy:
            continue
        lore = dup.get("class") == "LORe"
        g["dup"] = {"text": f"· duplicate chr{copy['chrom']}:{copy['start'] / 1e6:.2f} Mb" + (" (LORe)" if lore else ""),
                    "url": f"{reverse('snpportal:locus')}?r={copy['chrom']}:{max(1, copy['start'] + 1 - 5000)}-{copy['end'] + 5000}",
                    "title": f"Ss4R duplicate {copy['label']} on chr{copy['chrom']}:{copy['start'] + 1:,}-{copy['end']:,} · "
                             + ("LORe: the copies are still nearly identical" if lore else "AORe: the copies diverged after the duplication")}


def genes_group(request, s, ax, data):
    rows = []
    gwas = None
    if s["key"]:
        from . import association  # a GWAS job draws its association lane; a SNP list its tier lollipops
        gwas = association.browser_lane(request, s["key"], s["chrom"], s["start"], s["end"])
    noop = lambda *a, **k: None  # noqa: E731 (labels live in the HTML column)
    if gwas:
        body = []
        h = locus_svg.gwas_lane(body, ax, gwas, 0, None, height=120)
        rows.append(row("", trk(h, "".join(body))))
    snps = [] if gwas else locus.user_snps(request, s)
    if snps:
        top = max([p.get("tier_score") or 0 for p in snps] + [1])
        body = []
        for p in sorted(snps, key=lambda p: -(p.get("tier") or 4)):  # best tiers on top
            fill = palette.TIERS.get(p.get("tier") or 4, palette.TIERS[4])[0]
            x, h = ax.x(p["pos"] - 0.5), 8 + 26 * (p.get("tier_score") or 0) / top
            dot = (f'<line x1="{x:.1f}" x2="{x:.1f}" y1="40" y2="{40 - h:.1f}" stroke="{G[500]}"/>'
                   f'<circle cx="{x:.1f}" cy="{40 - h:.1f}" r="4" fill="{fill}" stroke="{G[900]}" stroke-width="0.6"><title>{escape(p["title"])}</title></circle>')
            body.append(f'<a href="{escape(p["url"])}">{dot}</a>' if p.get("url") else dot)
        rows.append(row("Your SNPs", trk(44, "".join(body)), f"tiers: {s['trait'].replace('_', ' ')}"))
    if data.get("known"):
        body = []
        h = locus_svg._published(body, ax, data["known"], 0, noop, {})
        rows.append(row("Published loci", trk(h, "".join(body))))
    if data.get("molqtl"):
        body = []
        for m in data["molqtl"]:
            x = ax.x(m["pos"] - 0.5)
            tissue = (m.get("tissues") or "").split(",")[0]
            body.append(f'<path d="M{x:.1f} 2 l5 9 l-10 0z" fill="{palette.TISSUES.get(tissue, G[700])}" stroke="{G[900]}" '
                        f'stroke-width="0.5"><title>{escape(m.get("title") or "")}</title></path>')
        rows.append(row("molQTL leads", trk(13, "".join(body)), "nf-RASQUAL, 12 fish"))
    duplicates(data.get("genes", []))
    body = []
    h = locus_svg._genes(body, ax, data.get("genes", []), 0, lambda gid: reverse("snpportal:gene", args=[gid]), 8, noop)
    lore = "".join(f'<rect x="{ax.x(b["start"]):.1f}" y="0" width="{ax.x(b["end"]) - ax.x(b["start"]):.1f}" height="{h}" '
                   f'fill="url(#sp-lore)" fill-opacity="0.25"><title>LORe region {escape(str(b.get("label") or ""))}: the duplicate '
                   'copies are still nearly identical</title></rect>' for b in data.get("lore", []))
    defs = locus_svg._hatch("sp", "lore", locus_svg.LORE, -45) if lore else ""  # id sp-lore
    rows.append(row("Genes", trk(h, (f"<defs>{defs}</defs>" if defs else "") + lore + "".join(body)), "Ensembl 116"))
    body = [f'<line x1="0" x2="{W}" y1="26" y2="26" stroke="{G[300]}"/>']
    for v in data.get("variants", []):
        x, h = ax.x(v["pos"] - 0.5), 3 + 22 * min(0.5, v.get("maf") or 0) / 0.5
        tip = (f"{s['chrom']}:{v['pos']:,} {v.get('ref')}>{v.get('alt')} · 504-fish panel: MAF {locus_svg._num(v.get('maf'))}, "
               f"alt AF {locus_svg._num(v.get('af'))}" + (f" · AQUA-FAANG 12 fish: alt AF {locus_svg._num(v.get('aquafaang12_af'))}, "
                                                          f"DR2 {locus_svg._num(v.get('aquafaang12_dr2'))}" if v.get("aquafaang12_af") is not None else ""))
        body.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="26" y2="{26 - h:.1f}" stroke="{G[700]}"><title>{escape(tip)}</title></line>')
    if not data.get("variants"):
        body.append(locus_svg._t(4, 20, "none in this window", 9.5, G[700]))
    rows.append(row("Public variants", trk(28, "".join(body)), "504 fish, height = MAF"))
    return group("genes", "Genes and variants", "", rows)


# ---- regulatory elements and chromatin states ----

def state_rect(ax, a, e, y, h, state, label):
    quiet = state == "Quiescent"  # light and see-through, so the centre band shows across quiet stretches
    fill = f'fill="{G[100]}" fill-opacity="0.55"' if quiet else f'fill="{palette.state(state)[0]}"'
    return (f'<rect x="{ax.x(a):.1f}" y="{y}" width="{max(0.6, ax.x(e) - ax.x(a)):.1f}" height="{h}" {fill}>'
            f'<title>{escape(label)}: {escape(state.replace("_", " "))} {a + 1:,}-{e:,}</title></rect>')


def live_segments(s, entries, prefix, deadline):
    """{condition: segments or None} of tracks.yaml bigBed entries, on snpscore's tile grid (read-only tiles for jobs)."""
    if not entries or s["end"] - s["start"] > sl.MAX_SIGNAL:
        return {}
    found = sl.segments(entries, s["chrom"], s["start"], s["end"], locus.tile_cache(read_only=bool(s["key"])), prefix, deadline)
    return {t["condition"]: f for t, f in zip(entries, found)}


def blacklist(ax, data, h):
    return "".join(f'<rect x="{ax.x(b["start"]):.1f}" y="0" width="{ax.x(b["end"]) - ax.x(b["start"]):.1f}" height="{h}" '
                   f'fill="{G[300]}" fill-opacity="0.5"><title>AQUA-FAANG blacklist {b["start"] + 1:,}-{b["end"]:,}: no peak here '
                   'means "cannot tell"</title></rect>' for b in data.get("blacklist", []))


def peaks_group(s, ax, data, cfg, prefix, deadline, open_, notes):
    conditions = data.get("conditions") or []
    body = [blacklist(ax, data, 32)]
    for p in data.get("peaks", []):
        states = p["states"]
        n = sum(1 for v in states.values() if v)
        best = locus_svg.strongest(states.values())
        x0, x1 = ax.x(p["start"]), ax.x(p["end"])
        body.append(f'<rect x="{x0:.1f}" y="3" width="{max(2, x1 - x0):.1f}" height="14" fill="{palette.state(best)[0]}" stroke="{G[900]}" '
                    f'stroke-width="0.5"><title>robust peak {p["start"] + 1:,}-{p["end"]:,} · called in {n} of {len(conditions)} conditions · '
                    f'strongest state: {best.replace("_", " ")}</title></rect>'
                    + locus_svg._t((x0 + x1) / 2, 29, f"{n}/{len(conditions)}", 9.5, G[700], "middle"))
    if not data.get("peaks"):
        body.append(locus_svg._t(4, 14, "no robust peak in this window", 9.5, G[700]))
    found = live_segments(s, (cfg or {}).get("peaks", []), prefix, deadline)
    more = []
    for c in sorted(found, key=order):
        segs = found[c]
        parts = [state_rect(ax, a, e, 2, 9, st, short(c)) for a, e, st in segs or ()] if segs is not None else [
            f'<rect x="0" y="2" width="{W}" height="9" fill="{G[200]}"><title>{escape(short(c))}: peaks unavailable</title></rect>']
        more.append(row(short(c), trk(13, "".join(parts)), tissue=tissue_of(c), dense=True))
    if any(v is None for v in found.values()):
        notes.append("Some per-condition peak tracks did not load in time (grey rows); reload to try again.")
    return group("peaks", "Regulatory elements", "AQUA-FAANG robust ATAC peaks, coloured by chromatin state",
                 [row("Combined", trk(32, "".join(body)), f"n/{len(conditions)}: conditions with the peak")],
                 more, f"{len(more)} conditions", open_)


def hmm_group(s, ax, data, cfg, prefix, deadline, open_, notes):
    """The stacked count of conditions per state (Quiescent left out) and one row per condition: the genome-wide ChromHMM
    segmentation when salmobase answers, else the states inside the robust peaks."""
    found = live_segments(s, (cfg or {}).get("chromhmm", []), prefix, deadline)
    conditions = sorted(found, key=order) if found else sorted(data.get("conditions") or [], key=order)
    if found:
        segs = {c: [(a, e, st) for a, e, st in (found[c] or [])] for c in conditions}
        note = "ChromHMM, genome-wide"
        if any(v is None for v in found.values()):
            notes.append("ChromHMM did not load in time for some conditions (grey rows); reload to try again.")
    else:
        segs = {c: [(p["start"], p["end"], p["states"][c]) for p in data.get("peaks", []) if p["states"].get(c)] for c in conditions}
        note = "AQUA-FAANG, inside robust peaks" + (f" (ChromHMM is read in windows up to {sl.MAX_SIGNAL // 1000} kb)"
                                                    if s["end"] - s["start"] > sl.MAX_SIGNAL else "")
    h, total = 60, max(1, len(conditions))
    body = [blacklist(ax, data, h), f'<line x1="0" x2="{W}" y1="{h}" y2="{h}" stroke="{G[300]}"/>']
    body += locus_svg.state_stack(ax, segs, 250, 0, h, total)
    more = []
    for c in conditions:
        if found and found.get(c) is None:
            parts = [f'<rect x="0" y="1" width="{W}" height="11" fill="{G[200]}"><title>{escape(short(c))}: ChromHMM unavailable</title></rect>']
        else:
            parts = [state_rect(ax, a, e, 1, 11, st, short(c)) for a, e, st in segs.get(c) or ()]
        more.append(row(short(c), trk(13, "".join(parts)), tissue=tissue_of(c), dense=True))
    legend = [(f"st-{x}", x.replace("_", " ").replace(" 1", "")) for x in LEGEND_STATES]
    return group("hmm", "Chromatin states", note, [row("Combined", trk(h + 2, "".join(body)), f"conditions per state, 0–{total}")],
                 more, f"{len(more)} conditions", open_, legend)


# ---- functional assays (RNA-seq, ATAC-seq, ChIP-seq): one request per assay ----

def polygon(xs, top, base, fill, opacity=1.0):
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, top)) + " " + " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(reversed(xs), reversed(base)))
    return f'<polygon points="{pts}" fill="{fill}" fill-opacity="{opacity}"/>'


def means(s, tracks, key, deadline):
    """{key(track): (mean over replicates per bin, replicates read)} for bigWig tracks, and the bins' x positions."""
    read = sl.signal(tracks, s["chrom"], s["start"], s["end"], locus.tile_cache(read_only=bool(s["key"])),
                     f"snpportal:{(jobs.release_info().get('sha256') or 'release')[:12]}", deadline)
    ax = locus_svg.Axis(s["start"], s["end"], 0, W)
    n = max((len(v) for v in read["values"] if v), default=0)
    xs = [ax.x(read["start"] + (i + 0.5) * read["rung"]) for i in range(n)]
    groups, failed = {}, 0
    for t, v in zip(tracks, read["values"]):
        if v is None:
            failed += 1
            continue
        groups.setdefault(key(t), []).append(v)
    return {k: ([sum((x[i] or 0) for x in vs) / len(vs) for i in range(n)], len(vs)) for k, vs in groups.items()}, xs, failed


def assay_group(s, assay, open_):
    """One functional assay: tissue means stacked (RNA-seq: + strand up, - down) and one row per condition."""
    title, what = ASSAYS[assay]
    cfg = locus.registry() or {}
    tracks = [t for t in cfg.get("tracks", []) if t.get("assay") == assay and t.get("kind") == "bigWig" and t.get("tissue") not in SKIP_TISSUES]
    ax = locus_svg.Axis(s["start"], s["end"], 0, W)
    if not tracks:
        return group(assay, title, what, [row("", plain(14, locus_svg._t(4, 11, "no tracks for this assay in tracks.yaml", 9.5, G[700])))])
    if s["end"] - s["start"] > sl.MAX_SIGNAL:
        return group(assay, title, what, [row("", plain(14, locus_svg._t(4, 11, f"zoom in to {sl.MAX_SIGNAL // 1000} kb or less to see signal", 9.5, G[700])))])
    deadline = float(jobs.setting("SNPPORTAL_ASSAY_DEADLINE", 15.0))
    rna = assay == "RNA"
    found, xs, failed = means(s, tracks, (lambda t: (t["condition"], t.get("strand") or "+")), deadline)
    tissue = {t["condition"]: tissue_of(t["condition"]) for t in tracks}
    conditions = sorted({c for c, _ in found}, key=order)
    strands = ("+", "-") if rna else ("+",)
    tissues = [t for t in TISSUE_ORDER if any(tissue[c] == t for c in conditions)]
    tm = {}
    for t in tissues:
        for st in strands:
            vs = [found[c, st][0] for c in conditions if tissue[c] == t and (c, st) in found]
            if vs:
                tm[t, st] = [sum(v[i] for v in vs) / len(vs) for i in range(len(xs))]
    total = max([sum(tm[t, st][i] for t in tissues if (t, st) in tm) for st in strands for i in range(len(xs))] + [1e-9])
    half = 32 if rna else 56
    body = []
    for st in strands:
        base = [0.0] * len(xs)
        for t in tissues:
            if (t, st) not in tm:
                continue
            top = [b + v for b, v in zip(base, tm[t, st])]
            if rna:
                sign = -1 if st == "+" else 1
                ys, bs = [half + sign * min(half, half * v / total) for v in top], [half + sign * min(half, half * v / total) for v in base]
            else:
                ys, bs = [half - min(half, half * v / total) for v in top], [half - min(half, half * v / total) for v in base]
            body.append(f'<g><title>{TISSUE_NAMES.get(t, t)}{f", {st} strand" if rna else ""}: mean of '
                        f'{sum(1 for c in conditions if tissue[c] == t)} conditions</title>{polygon(xs, ys, bs, palette.TISSUES.get(t, G[700]), 0.9)}</g>')
            base = top
    if rna:
        body.append(f'<line x1="0" x2="{W}" y1="{half}" y2="{half}" stroke="{G[500]}"/>' + locus_svg._t(W - 2, 9, "+", 9.5, G[700], "end")
                    + locus_svg._t(W - 2, 2 * half - 2, "−", 9.5, G[700], "end"))
        combined_h = 2 * half
    else:
        body.append(f'<line x1="0" x2="{W}" y1="{half}" y2="{half}" stroke="{G[300]}"/>')
        combined_h = half
    vmax = max([max(v) for v, _ in found.values() if v] + [1e-9])
    more = []
    for c in conditions:
        parts = []
        for st in strands:
            if (c, st) not in found:
                continue
            v = found[c, st][0]
            colour = palette.TISSUES.get(tissue[c], G[700])
            if rna:  # expression spans orders of magnitude: a shared log scale
                sign, mid = (-1 if st == "+" else 1), 12
                ys = [mid + sign * 11 * math.log1p(x) / math.log1p(vmax) for x in v]
                parts.append(polygon(xs, ys, [mid] * len(xs), colour))
            else:
                parts.append(polygon(xs, [22 - 21 * min(1, x / vmax) for x in v], [22] * len(xs), colour))
        parts.append(f'<line x1="0" x2="{W}" y1="{12 if rna else 22}" y2="{12 if rna else 22}" stroke="{G[300]}" stroke-width="0.6"/>')
        reps = max(found[c, st][1] for st in strands if (c, st) in found)
        more.append(row(short(c), trk(24, "".join(parts)), tissue=tissue[c]))
        more[-1]["title"] = f"mean of {reps} replicate{'s' if reps > 1 else ''}"
    scale = f"conditions on a log scale, 0–{vmax:.0f} RPM" if rna else f"conditions 0–{vmax:.2f} RPM"
    note = f"{what.split(';')[0]}{'; + strand up, &#8722; down' if rna else ''} · {scale}"
    if failed:
        note += f" · {failed} of {len(tracks)} files did not load in time"
    sub = f"0–{total:.1f} RPM per strand" if rna else f"0–{total:.2f} RPM"
    g = group(assay, title, note, [row("Combined", trk(combined_h + 2, "".join(body)), sub)], more,
              f"{len(more)} conditions", open_)
    g["failed"] = failed
    return g


# ---- other annotation ----

def other_group(s, ax, data):
    body = []
    for r in data.get("regbuild", []):
        x0, x1 = ax.x(r["start"]), ax.x(r["end"])
        fill = locus_svg._colour(locus_svg.REGBUILD.get(r.get("type"), G[500]))
        body.append(f'<rect x="{x0:.1f}" y="2" width="{max(2, x1 - x0):.1f}" height="9" fill="{fill}"><title>{escape(str(r.get("type", "")).replace("_", " "))} '
                    f'{escape(str(r.get("id") or ""))}</title></rect>')
    if not data.get("regbuild"):
        body.append(locus_svg._t(4, 10, "none in this window", 9.5, G[700]))
    gerp = []
    top = max([g.get("score") or 0 for g in data.get("gerp", [])] + [1])
    for g in data.get("gerp", []):
        x0, x1 = ax.x(g["start"]), ax.x(g["end"])
        gerp.append(f'<rect x="{x0:.1f}" y="2" width="{max(1, x1 - x0):.1f}" height="9" fill="{G[700]}" '
                    f'fill-opacity="{0.35 + 0.65 * (g.get("score") or 0) / top:.2f}"><title>GERP constrained element (65 fish), score {g.get("score")}</title></rect>')
    if not data.get("gerp"):
        gerp.append(locus_svg._t(4, 10, "none in this window", 9.5, G[700]))
    return group("other", "Other annotation", "", [row("Ensembl regulatory", trk(13, "".join(body)), "build 116"),
                                                   row("GERP constrained", trk(13, "".join(gerp)), "65 fish")])


# ---- the page ----

def tissue_legend():
    return [(f"sp-tissue-{t} sp-tbg", TISSUE_NAMES.get(t, t)) for t in TISSUE_ORDER]


def context(request, s, layout):
    """Context for locus.html."""
    open_ = opened(request)
    ctx = {"nav": "explore", "title": "Locus browser", "layout": layout, "s": s, "open": ",".join(open_)}
    if not s["chrom"]:
        ctx["region_text"] = request.GET.get("r") or request.GET.get("region") or ""
        return ctx
    ctx["region_text"] = locus.region_text(s["chrom"], s["start"], s["end"], commas=True)
    if s["too_wide"]:
        mid = (s["start"] + s["end"]) // 2
        ctx["centre_query"] = query(s, open_, start=mid - sl.MAX_WINDOW // 2, end=mid + sl.MAX_WINDOW // 2)
        return ctx
    info, cfg = jobs.release_info(), locus.registry()
    data = locus.lanes(s["chrom"], s["start"], s["end"])
    ax = locus_svg.Axis(s["start"], s["end"], 0, W)
    prefix = f"snpportal:{(info.get('sha256') or 'release')[:12]}"
    deadline = float(jobs.setting("SNPPORTAL_SIGNAL_DEADLINE", 4.0))
    notes = []
    groups = [genes_group(request, s, ax, data), peaks_group(s, ax, data, cfg, prefix, deadline, open_, notes),
              hmm_group(s, ax, data, cfg, prefix, deadline, open_, notes)]
    synthetic = bool(info.get("synthetic")) or any(locus.synthetic_track(t) for t in (cfg or {}).get("tracks", []))
    if s["key"]:
        job = jobs.read(s["key"])
        synthetic = synthetic or bool(job.get("synthetic_input") or job.get("synthetic_layers"))
    a, b = s["start"] + 1, s["end"]
    ctx.update(
        chromosome=chromosome(s), ruler=ruler(ax, s), groups=[g for g in groups if g], other=other_group(s, ax, data), notes=notes,
        synthetic=synthetic, moves=moves(s, open_), query=query(s, open_), assays=[(k, v[0]) for k, v in ASSAYS.items()],
        assays_open="assays" in open_, tissue_legend=tissue_legend(), size_text=locus_svg.fmt_bp(s.get("size") or 0),
        width_text=locus_svg.fmt_bp(s["end"] - s["start"]), truncated=data.get("truncated"),
        jbrowse=locus.JBROWSE.format(chrom=s["chrom"], start=a, end=b), ensembl=locus.ENSEMBL.format(chrom=s["chrom"], start=a, end=b),
        download=f"{reverse('snpportal:locus_svg')}?{locus.query(s)}&download=1")
    return ctx


@private
def page(request):
    """The locus browser page; ?embed=1: without the site's chrome, for the Table's card drawer (base_embed.html)."""
    layout = "snpportal/base_embed.html" if request.GET.get("embed") == "1" else "snpportal/base_portal.html"
    return render(request, "snpportal/locus.html", context(request, locus.view_state(request), layout))


@private
def assay(request):
    """/snp/locus/assay/?<view>&assay=RNA: one functional assay's group, for the opened section to fetch."""
    name = request.GET.get("assay")
    if name not in ASSAYS:
        return HttpResponseBadRequest("unknown assay")
    s = locus.view_state(request)
    if not s["chrom"] or s["too_wide"]:
        return HttpResponseBadRequest("no region")
    g = assay_group(s, name, opened(request))
    if g.get("failed") and not request.GET.get("retry"):  # e.g. a cold start: what did load is cached, so one more try reads the rest
        g["retry"] = f"{request.path}?{request.GET.urlencode()}&retry=1"
    return render(request, "snpportal/_browser_group.html", {"g": g})
