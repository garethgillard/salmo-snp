"""The locus browser page (/snp/locus/): tracks in groups on one axis, each track its own SVG beside an HTML label, so a
group opens in place (combined track always, one track per condition when open). Release lanes come from
lib.locus; ChromHMM and the per-condition peaks are read live from salmobase (tracks.yaml) on snpscore's tile
grid; the functional assays (RNA-seq, ATAC-seq, ChIP-seq, means over replicates) load one assay at a time when their
section is opened (/snp/locus/assay/). The ruler names the centre: the SNP the view was opened on, else the middle.
A group's header carries only what is needed to read its tracks (an encoding, what the tiers count); its sources are
the hover text of its title and rows, and the Data page's. ?open= lists the open groups, so a link keeps them. The single-SVG figure (locus_svg.locus) stays the download and
the card's and gene page's views."""
from __future__ import annotations

import math
from html import escape
from urllib.parse import urlencode

from django.http import HttpResponseBadRequest
from django.shortcuts import render
from django.urls import reverse
from django.utils.safestring import mark_safe

from .lib import locus as sl
from snpscore.formats import lit

from . import explore, jobs, locus, locus_svg, mytracks, palette, results
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
TREATMENTS = {"pbs": "PBS", "polyIC": "poly I:C", "vibrio": "Vibrio"}  # ImmunoMap: HeadKidney_<invivo|invitro>_<treatment>
STATE_ORDER = locus_svg.STATE_ORDER  # stacked bottom to top; Quiescent is not drawn
LEGEND_STATES = ("Active_TSS", "Flanking_upstream", "Active_enhancer", "Primed_enhancer", "Poised_enhancer_1",
                 "Accessible_chromatin", "Bivalent", "Repressed_polycomb", "ZNF_genes_and_repeats", "Quiescent")
IMMUNOMAP_STATES = ("Active_TSS_or_enhancer", "Flanking_TSS_or_poised_enhancer", "Bivalent_or_mixed_active/polycomb")
TROUT_IMMUNOMAP_STATES = ("Weak_accessible_chromatin", "Bivalent_or_mixed_active/polycomb")  # one model per treatment
ASSAYS = {"RNA": ("RNA-seq", "expression; + strand up, &#8722; down; conditions on a log scale"), "ATAC": ("ATAC-seq", "open chromatin"),
          "H3K27ac": ("ChIP-seq H3K27ac", "active enhancers and promoters"), "H3K4me3": ("ChIP-seq H3K4me3", "active promoters"),
          "H3K4me1": ("ChIP-seq H3K4me1", "enhancers, active and primed"), "H3K27me3": ("ChIP-seq H3K27me3", "polycomb repression"),
          "CTCF": ("ChIP-seq CTCF", "insulators")}
SKIP_TISSUES = {"Sperm"}  # sperm ChIP is left out (salmobase answers 403 for its files)
GROUPS = ("genes", "public", "peaks", "hmm", "assays", *ASSAYS)  # the groups ?open= may list
NCBI_GENE = "https://www.ncbi.nlm.nih.gov/gene/{}"  # NCBI isoforms link to their gene there
ISOFORM_ROWS = 40  # rows of the expanded isoform tracks before '+N more transcripts: zoom in'
EMPTY = locus_svg.EMPTY  # what every empty lane says
TEXT = locus_svg.TEXT  # the smallest text drawn in a track, as the HTML labels beside it
SNP_SETS = [  # (set, row label, the row's hover text) of the public SNP datasets, in row order; colours: palette.SNP_SETS
    ("public_af", "504-fish panel", "wild and farmed, pooled"), ("aquafaang12", "AQUA-FAANG 12 fish", "imputed"),
    ("synchrosmolt_af", "Synchrosmolt", "parents, WGS"), ("axiom", "Axiom array", "CGD study, 1,710 fish")]


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
    """(label, query, title, icon) for zoom out and in (x3) and moving half a window (an icon each); portal.js presses
    them for the keys by their title."""
    w, mid = s["end"] - s["start"], (s["start"] + s["end"]) // 2
    span = lambda width, centre=mid: sl.clamp(centre - width // 2, centre + width - width // 2, s.get("size"), sl.MIN_WINDOW, sl.MAX_WINDOW)  # noqa: E731
    out = []
    for label, (a, b), title, icon in [("−", span(w * 3), "Zoom out 3x", ""), ("+", span(w // 3), "Zoom in 3x", ""),
                                       ("", span(w, mid - w // 2), "Move left half a window", "chevron-left"),
                                       ("", span(w, mid + w // 2), "Move right half a window", "chevron-right")]:
        out.append((label, query(s, open_, start=a, end=b) if (a, b) != (s["start"], s["end"]) else None, title, icon))
    return out


def centre(s):
    """The 1-based position the view centres on: the SNP it was opened on, else the window's middle base."""
    a, b = s.get("shown") or (s["start"], s["end"])
    return s["mark"] or (a + b + 1) // 2


MARGIN = 0.5  # of the window, drawn beyond each edge and hidden until the mouse moves the tracks (portal.js)


def drawn(s):
    """(the view widened by MARGIN each side, its axis): what the tracks draw, so that a drag shows what lies beyond
    the edge at once. The window itself stays on 0-W; the margin stops at the chromosome's ends and at MAX_WINDOW
    in all. `shown` keeps the window (width(), centre()); the functional assays' signal is read for the window only."""
    w = s["end"] - s["start"]
    m = max(0, min(int(w * MARGIN), (sl.MAX_WINDOW - w) // 2))
    lo, hi = max(0, s["start"] - m), min(s.get("size") or s["end"] + m, s["end"] + m)
    ax = locus_svg.Axis(lo, hi, (lo - s["start"]) / w * W, (hi - s["start"]) / w * W)
    ax.left = 0
    return {**s, "start": lo, "end": hi, "shown": (s["start"], s["end"])}, ax


def width(s):
    """The window's width in bp (not the margin's): what decides how much detail a track draws."""
    a, b = s.get("shown") or (s["start"], s["end"])
    return b - a


def trk(h, body):
    """One track: an SVG on the shared axis (class sp-ax: portal.js draws the marker line through these and moves them with the mouse)."""
    return mark_safe(f'<svg class="sp-trk-svg sp-ax" viewBox="0 0 {W} {h}" width="{W}" height="{h}" role="img">{body}</svg>')


def plain(h, body):
    """A row that isn't on the axis (no marker line)."""
    return mark_safe(f'<svg class="sp-trk-svg" viewBox="0 0 {W} {h}" width="{W}" height="{h}" role="img">{body}</svg>')


def row(label, svg, sub="", tissue=None, dense=False, title=""):
    """A track row: its name, a short second line only where it is needed to read the track (sub), its source (title:
    hover text) and its SVG."""
    return {"label": label, "sub": sub, "tissue": tissue, "svg": svg, "dense": dense, "title": title}


def empty(x, y):
    """The note of a lane with nothing in this window."""
    return locus_svg._t(x, y, EMPTY, TEXT, G[700])


def separated(rows):
    """`rows` with sep set on each row whose tissue differs from the row above (BodyMap tissues, the ImmunoMap's head
    kidney, the DevMap's embryo stages): a thin line above it (G, 2026-11-20)."""
    for above, r in zip([None] + rows, rows):
        r["sep"] = above is not None and r["tissue"] != above["tissue"]
    return rows


def group(gid, title, note, rows, more=(), more_label="", open_=(), legend=None, kind="grp", about=""):
    """A track group. note: what is needed to read its tracks, beside its title; about: its sources, the title's hover
    text."""
    return {"id": gid, "title": title, "note": mark_safe(note), "rows": rows, "more": list(more), "more_label": more_label,
            "open": gid in open_, "legend": legend or [], "kind": kind, "about": about}


def tissue_of(condition):
    return "Embryo" if condition in STAGES or "_" not in condition else condition.split("_")[0]


def immuno(condition):
    """(in vitro, treatment) of an ImmunoMap condition (HeadKidney_invivo_pbs), else None."""
    _, _, rest = condition.partition("HeadKidney_inv")
    where, _, treatment = rest.partition("_")
    return (where == "itro", treatment) if where in ("ivo", "itro") else None


def short(condition):
    """'Brain Imm F', 'Head kidney Mat M', 'L blastula'; ImmunoMap: 'HK poly I:C' (in vivo), 'HK cells PBS' (in vitro)."""
    if "_" not in condition:
        return STAGES.get(condition, condition)
    if im := immuno(condition):
        return f"HK {'cells ' if im[0] else ''}{TREATMENTS.get(im[1], im[1])}"
    t, m, x = condition.split("_")
    return f"{TISSUE_NAMES.get(t, t)} {m[:3]} {x[0]}"


def long(condition, assay):
    """A row's hover text for the ImmunoMap and the gill ATAC-seq of 2026 (assay ATAC, states or peaks); else empty."""
    if im := immuno(condition):
        return (f"ImmunoMap: head kidney {'leukocytes in vitro' if im[0] else 'in vivo'}, "
                f"{TREATMENTS.get(im[1], im[1])}{' (control)' if im[1] == 'pbs' else ''}")
    if not condition.startswith("Gill_") or assay not in ("ATAC", "states", "peaks"):
        return ""
    text = "Gill ATAC-seq re-made in 2026: weaker than the other tissues"
    if condition == "Gill_Immature_Female" and assay != "ATAC":  # the AQUA-FAANG README's note 3
        text += "; these states use an H3K4me1 library mixed with another fish's gonad H3K4me3 (a fix will follow)"
    return text


def order(condition):
    """Tissues in TISSUE_ORDER, then immature F, M, mature F, M; embryo stages in developmental order; ImmunoMap
    after the BodyMap head kidney, in vivo before in vitro, PBS first."""
    t, im = tissue_of(condition), immuno(condition)
    return (TISSUE_ORDER.index(t) if t in TISSUE_ORDER else len(TISSUE_ORDER),
            list(STAGES).index(condition) if condition in STAGES else 0,
            (1 + im[0], list(TREATMENTS).index(im[1]) if im[1] in TREATMENTS else 9) if im else (0, 0), condition)


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
    size, h, y = s.get("size") or s["end"], 15, 3
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
                   + (locus_svg._t(sx(b["start"]) + 8, y + 11.5, f"Ss4R block, duplicated on chr{b['partner']}", TEXT, G[900],
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
    """Positions along the window; the centre's above them in bold, with a tick (ink: red belongs to the data)."""
    c = ax.x(centre(s) - 0.5)
    body = [f'<line x1="{-W}" x2="{2 * W}" y1="30" y2="30" stroke="{G[500]}"/>',
            f'<line x1="{c:.1f}" x2="{c:.1f}" y1="12" y2="30" stroke="{G[900]}" stroke-width="1.5"/>',
            locus_svg._t(c, 9, f"{centre(s):,}", TEXT, G[900], "middle", "600",
                         f' stroke="{palette.WHITE}" stroke-width="4" paint-order="stroke"')]
    for t in ax.ticks(round(8 * (ax.x1 - ax.x0) / W)):
        x = ax.x(t)
        half = 3.3 * len(f"{t:,}")
        anchor = "start" if x - half < 0 else "end" if x + half > W else "middle"
        body.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="25" y2="30" stroke="{G[500]}"/>' + locus_svg._t(x, 21, f"{t:,}", 11, G[900], anchor))
    return trk(34, "".join(body))


# ---- the user's own tracks ----

def tracks_group(request, s, ax):
    """'Your tracks' (mytracks: the user's own BED files on this assembly, those not hidden), one row each, above the
    release's groups: intervals in the file's own colours, else one colour; hover: the interval's name. None without
    tracks. Read at render time and never cached, as the user's SNPs are."""
    rows = []
    for m in mytracks.mine(request, jobs.manifest().get("assembly", "Ssal_v3.1")):
        if not m.get("shown", True):
            continue
        found = mytracks.rows(m, s["chrom"], s["start"], s["end"], s.get("shown"))
        h, body = mytracks.draw(m, ax, s["chrom"], found, W)
        cut = f"{mytracks.DRAWN:,} drawn here: zoom in" if len(found) > mytracks.DRAWN else ""
        rows.append(row(mytracks.asis(m.get("name") or "Track"), trk(h, body), cut, title=f"{m.get('n', 0):,} intervals"))
    if not rows:
        return None
    g = group("tracks", "Your tracks", "never scored", rows,
              about="Your own BED files: shown here and offered as a Table filter, never scored")
    g["link"] = (reverse("snpportal:tracks"), "Manage tracks")
    return g


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


def genes_group(request, s, ax, data, open_=()):
    rows = []
    gwas = None
    if s["key"]:
        from . import association  # a GWAS job draws its association lane; a SNP list its tier lollipops
        gwas = association.browser_lane(request, s["key"], s["chrom"], *s.get("shown", (s["start"], s["end"])))
    noop = lambda *a, **k: None  # noqa: E731 (labels live in the HTML column)
    if gwas:
        body = []
        h = locus_svg.gwas_lane(body, locus_svg.Axis(*s.get("shown", (s["start"], s["end"])), 0, W), gwas, 0, None, height=120)  # its y axis: no margin
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
        rows.append(row("Your SNPs", trk(44, "".join(body)), "colour = tier, height = score"))
    if data.get("known"):
        body = []
        h = locus_svg._published(body, ax, data["known"], 0, noop, {})
        rows.append(row("Known loci", trk(h, "".join(body)), title="Published loci of the known-loci catalogue; filled: the "
                        "effect allele is stated"))
    if data.get("molqtl"):
        body, a, b = [], *s.get("shown", (s["start"], s["end"]))
        for m in data["molqtl"]:
            x = ax.x(m["pos"] - 0.5)
            tissue = (m.get("tissues") or "").split(",")[0]
            body.append(f'<path d="M{x:.1f} 2 l5 9 l-10 0z" fill="{palette.TISSUES.get(tissue, G[700])}" stroke="{G[900]}" '
                        f'stroke-width="0.5"><title>{escape(m.get("title") or "")}</title></path>')
        if not any(a < m["pos"] <= b for m in data["molqtl"]):  # only beyond the edges, shown when the tracks move
            body.append(empty(4, 11))
        rows.append(row("molQTL leads", trk(14, "".join(body)), "12 fish", title="nf-RASQUAL lead SNPs of eQTLs and caQTLs "
                        "in 12 fish, coloured by their first tissue; shown, never counted"))
    duplicates(data.get("genes", []))
    gene_page = lambda gid: reverse("snpportal:gene", args=[gid])  # noqa: E731
    ensembl = []
    h = locus_svg._genes(ensembl, ax, data.get("genes", []), 0, gene_page, 8, noop)
    ensembl = (ensembl, h, "Ensembl 116", "Ensembl 116 gene models, one isoform each; a gene opens its gene page")
    ncbi = sl.ncbi_genes(jobs.release(), s["chrom"], s["start"], s["end"])  # the default lane (G, 2026-11-20)
    if ncbi is not None:
        body = []
        h = locus_svg._genes(body, ax, ncbi, 0, NCBI_GENE.format, 8, noop, sl.ISOFORMS["ncbi"][1])
        default = (body, h, "NCBI RefSeq", "NCBI RefSeq gene models, one isoform each (the most coding bases); a gene opens "
                   "its NCBI page. Open the group for the Ensembl genes and every isoform")  # its version: the isoform row
    else:
        default = ensembl
    body, h, sub, about = default
    lore = "".join(f'<rect x="{ax.x(b["start"]):.1f}" y="0" width="{ax.x(b["end"]) - ax.x(b["start"]):.1f}" height="{h}" '
                   f'fill="url(#sp-lore)" fill-opacity="0.25"><title>LORe region {escape(str(b.get("label") or ""))}: the duplicate '
                   'copies are still nearly identical</title></rect>' for b in data.get("lore", []))
    defs = locus_svg._hatch("sp", "lore", locus_svg.LORE, -45) if lore else ""  # id sp-lore
    rows.append(row("Genes", trk(h, (f"<defs>{defs}</defs>" if defs else "") + lore + "".join(body)), sub, title=about))
    # opened: the Ensembl genes (their gene pages and Ss4R duplicates) under the NCBI lane, then every isoform of both
    more = [row("Ensembl genes", trk(ensembl[1], "".join(ensembl[0])), ensembl[2], title=ensembl[3])] if default is not ensembl else []
    links = {"ensembl": lambda gid: reverse("snpportal:gene", args=[gid]), "ncbi": NCBI_GENE.format}
    for key, models in sl.isoforms(jobs.release(), s["chrom"], s["start"], s["end"], data.get("genes", [])).items():
        body = []
        h = locus_svg._genes(body, ax, models, 0, links[key], ISOFORM_ROWS, noop, sl.ISOFORMS[key][1], "transcripts")
        more.append(row(f"{'Ensembl' if key == 'ensembl' else 'NCBI RefSeq'} isoforms", trk(h, "".join(body)),
                        f"{sl.ISOFORMS[key][1]}, {len(models)} transcript{'s' * (len(models) != 1)}"))
    return group("genes", "Genes and variants", "", rows, more, "Ensembl genes and all isoforms" if ncbi is not None else "All isoforms", open_)


# ---- public SNPs ----

def snp_sets(s, data):
    """{set: [(pos, maf, tip)]} of the public SNP datasets in the window: the 504-fish panel and its 12 AQUA-FAANG fish
    (public_af), the Synchrosmolt parents and the Axiom array (lib.locus PUBLIC_SNPS)."""
    num, out = locus_svg._num, {}

    def add(key, v, maf, text):
        tip = f"{s['chrom']}:{v['pos']:,} {v.get('ref')}>{v.get('alt')} · {dict((k, l) for k, l, _ in SNP_SETS)[key]}: {text}"
        out.setdefault(key, []).append((v["pos"], maf, tip))
    for v in data.get("variants", []):
        add("public_af", v, v.get("maf"), f"MAF {num(v.get('maf'))}, alt AF {num(v.get('af'))}")
        af = v.get("aquafaang12_af")
        if af is not None:
            add("aquafaang12", v, min(af, 1 - af), f"alt AF {num(af)}, imputation DR2 {num(v.get('aquafaang12_dr2'))}")
    for v in data.get("synchrosmolt_af", []):
        add("synchrosmolt_af", v, v.get("maf"), f"MAF {num(v.get('maf'))}, alt AF {num(v.get('af'))} ({v.get('ns')} fish)")
    for v in data.get("axiom", []):
        add("axiom", v, v.get("maf"), f"{v.get('probe') or 'probe'}, MAF {num(v.get('maf'))} ({v.get('ns'):,} fish)")
    return out


def public_group(s, ax, data, open_):
    """Public SNPs: one combined row (at each site a segment per dataset that has it, like the chromatin states'
    count of conditions) and, opened, a row per dataset with height = MAF."""
    found, seg = snp_sets(s, data), 7
    sets = [x for x in SNP_SETS if x[0] in found]
    h = seg * max(1, len(sets)) + 2
    at = {}
    for key, *_ in sets:
        for pos, _, tip in found[key]:
            at.setdefault(pos, []).append((key, tip))
    body = [f'<line x1="{-W}" x2="{2 * W}" y1="{h}" y2="{h}" stroke="{G[300]}"/>']
    for pos, hits in sorted(at.items()):
        x = ax.x(pos - 0.5)
        bars = "".join(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{h - i * seg:.1f}" y2="{h - (i + 1) * seg + 1:.1f}" '
                       f'stroke="{palette.SNP_SETS[key]}" stroke-width="1.6"/>' for i, (key, _) in enumerate(hits))
        body.append(f'<g><title>{escape(" · ".join([hits[0][1]] + [t.split(" · ", 1)[1] for _, t in hits[1:]]))}</title>{bars}</g>')
    if not at:
        h = 14
        body.append(empty(4, 11))
    more = []
    for key, label, about in sets:
        rows = [f'<line x1="{-W}" x2="{2 * W}" y1="26" y2="26" stroke="{G[300]}"/>']
        for pos, maf, tip in found[key]:
            x, t = ax.x(pos - 0.5), 3 + 22 * min(0.5, maf or 0) / 0.5
            rows.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="26" y2="{26 - t:.1f}" stroke="{palette.SNP_SETS[key]}">'
                        f'<title>{escape(tip)}</title></line>')
        more.append(row(label, trk(28, "".join(rows)), "height = MAF", title=f"{label}: {about}"))
    legend = [(f"sp-set-{key}", label) for key, label, _ in sets]
    return group("public", "Public SNPs", "", [row("Combined", trk(h + 1, "".join(body)), "datasets with the SNP")],
                 more, f"{len(more)} datasets", open_, legend,
                 about="Sites in public datasets: one row each when open, its tick height the minor allele frequency")


# ---- regulatory elements and chromatin states ----

def state_rect(ax, a, e, y, h, state, label):
    quiet = state == "Quiescent"  # light and see-through, so the centre band shows across quiet stretches
    fill = f'fill="{G[100]}" fill-opacity="0.55"' if quiet else f'fill="{palette.state(state)[0]}"'
    return (f'<rect x="{ax.x(a):.1f}" y="{y}" width="{max(0.6, ax.x(e) - ax.x(a)):.1f}" height="{h}" {fill}>'
            f'<title>{escape(label)}: {escape(state.replace("_", " "))} {a + 1:,}-{e:,}</title></rect>')


def live_segments(s, entries, prefix, deadline):
    """{condition: segments or None} of tracks.yaml bigBed entries, on snpscore's tile grid (read-only tiles for jobs)."""
    if not entries or width(s) > sl.MAX_SIGNAL:
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
                    + locus_svg._t((x0 + x1) / 2, 30, f"{n}/{len(conditions)}", TEXT, G[700], "middle"))
    if not data.get("peaks"):
        body.append(empty(4, 14))
    found = live_segments(s, (cfg or {}).get("peaks", []), prefix, deadline)
    more = []
    for c in sorted(found, key=order):
        segs = found[c]
        parts = [state_rect(ax, a, e, 2, 9, st, short(c)) for a, e, st in segs or ()] if segs is not None else [
            f'<rect x="{-W}" y="2" width="{3 * W}" height="9" fill="{G[200]}"><title>{escape(short(c))}: peaks unavailable</title></rect>']
        more.append(row(short(c), trk(13, "".join(parts)), tissue=tissue_of(c), dense=True, title=long(c, "peaks")))
    if any(v is None for v in found.values()):
        notes.append("Some per-condition peak tracks did not load in time (grey rows); reload to try again.")
    note = "robust ATAC peaks, coloured by their strongest chromatin state"
    extra = [short(c) for c in found if c not in conditions]  # rows of newer tracks that this release's tiers don't count
    if extra:
        note += (f" · Combined: the {len(conditions)} conditions the tiers count; shown only: "
                 + (", ".join(extra) if len(extra) <= 6 else f"{len(extra)} other rows"))
    return group("peaks", "Regulatory elements", note,
                 [row("Combined", trk(33, "".join(body)), f"n/{len(conditions)}: conditions with the peak")],
                 separated(more), f"{len(more)} conditions", open_,
                 about="AQUA-FAANG robust ATAC-seq peaks (unified peaks of the release), each coloured by the strongest of its "
                       "conditions' chromatin states; open for the peaks of each condition, read live from salmobase")


def motifs_group(s, ax, data):
    """TF motifs: the public SNPs in robust peaks whose alleles change a JASPAR 2024 motif match (motif_row); only
    when the release has the motif layer."""
    if not (jobs.release() / "motif.parquet").exists():
        return None
    return group("motifs", "TF motifs", "changed by public SNPs in robust ATAC peaks", [motif_row(s, ax, data)],
                 about="JASPAR 2024 vertebrate motifs (CORE, non-redundant) whose match one allele of a public SNP makes and "
                       "the other breaks, inside a robust ATAC peak")


LOGO_BP = 150  # the motif row draws logos (and the sequence) in windows up to this wide; ticks in wider ones


def motif_row(s, ax, data):
    """Public SNPs in a robust peak whose alleles change a JASPAR 2024 motif match (the scored rule). Up to LOGO_BP
    wide: each changed motif's logo on the + strand where it sits (stacked in lanes), the SNP's column outlined, and
    the reference sequence under them; wider: a tick per SNP, height = the largest score change. Hover: the TFs and
    the allele that matches."""
    found = data.get("motif", [])
    if found and width(s) <= LOGO_BP:
        return motif_logo_row(s, ax, found)
    body = [f'<line x1="{-W}" x2="{2 * W}" y1="20" y2="20" stroke="{G[300]}"/>']
    for v in found:
        x, h = ax.x(v["pos"] - 0.5), 4 + 14 * min(12, v.get("delta") or 0) / 12
        tip = (f"{s['chrom']}:{v['pos']:,} {v.get('ref')}>{v.get('alt')} · changes {v.get('n')} motif"
               f"{'s' * ((v.get('n') or 0) != 1)}: {v.get('tfs')} · largest change {locus_svg._num(v.get('delta'))} bits")
        body.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="20" y2="{20 - h:.1f}" stroke="{palette.MOTIF}" stroke-width="1.6">'
                     f'<title>{escape(tip)}</title></line>')
    if not found:
        body.append(empty(4, 15))
        return row("Motif changes", trk(22, "".join(body)), "height = score change")
    h = popouts(s, ax, found, body, 22)
    return row("Motif changes", trk(h, "".join(body)), "height = score change")


def popouts(s, ax, found, body, y, n=2, gap=24):
    """Under the ticks, the motif logos of the `n` SNPs with the largest change, enlarged in a wedge from each SNP
    (as the card draws them); a note when more SNPs change a motif. Appends to body; returns the row's height."""
    top = sorted(found, key=lambda v: (-(v.get("delta") or 0), v["pos"]))[:n]
    slot = (W - gap * (len(top) - 1)) / len(top)
    shown = []
    for i, v in enumerate(sorted(top, key=lambda v: v["pos"])):
        hits, seq, w = locus.motif_hits(s["chrom"], v["pos"], v.get("ref"), v.get("alt"))
        if hits:
            shown.append((i, v, locus_svg.motif_logos(hits, seq, w, v["ref"].upper(), v["alt"].upper(), width=slot, row=34)))
    y0, tallest = y + 14, 0
    for i, v, (panel, pw, ph, sx) in shown:
        px = i * (slot + gap) + (slot - pw) / 2
        x = ax.x(v["pos"] - 0.5)
        body.insert(0, f'<path d="M{x:.1f} {y - 1} L{px + 72:.1f} {y0} L{px + pw - 136:.1f} {y0}Z" fill="{G[100]}"/>')  # under the ticks
        body.append(f'<g transform="translate({px:.1f} {y0})">{panel}</g>')
        tallest = max(tallest, ph)
    if len(found) > len(shown):
        body.append(locus_svg._t(W - 4, 10, f"enlarged: the {len(shown)} SNP{'s' * (len(shown) != 1)} with the largest change of "
                                             f"{len(found)}; zoom in to {LOGO_BP} bp for all of them", TEXT, G[700], "end"))
    return y0 + tallest + 4 if shown else y


def motif_logo_row(s, ax, found, lane_h=30):
    """motif_row at base resolution: logos in lanes, the SNPs' columns, the reference sequence."""
    cw = ax.x(s["start"] + 1) - ax.x(s["start"])
    placed, lanes = [], []  # (lane, x0, x1, hit, snp)
    for v in found:
        hits, _, w = locus.motif_hits(s["chrom"], v["pos"], v.get("ref"), v.get("alt"))
        for h in hits:
            first = v["pos"] - w + h["start"]  # 1-based position of the motif's first base on the + strand
            x0, x1 = ax.x(first - 1), ax.x(first - 1 + len(h["probs"]))
            lane = next((i for i, end in enumerate(lanes) if end <= x0 - 4), None)
            if lane is None:
                lanes.append(0)
                lane = len(lanes) - 1
            lanes[lane] = x1
            placed.append((lane, x0, x1, h, v))
    h_all = lane_h * max(1, len(lanes))
    body = []
    for v in found:  # the SNPs' columns, under everything
        x = ax.x(v["pos"] - 1)
        body.append(f'<rect x="{x:.1f}" y="0" width="{cw:.1f}" height="{h_all + 14}" fill="{palette.MOTIF}" fill-opacity="0.12" '
                    f'stroke="{palette.MOTIF}"/>')
    for lane, x0, x1, h, v in placed:
        y = lane * lane_h
        tip = (f"{h['tf']} ({h['id']}, {h['strand']} strand) at {s['chrom']}:{v['pos']:,}: {h['allele']} matches; "
               f"{v.get('ref')} {h['ref_score']:.1f}, {v.get('alt')} {h['alt_score']:.1f} bits, a match needs {h['cut']:.1f}")
        cols = "".join("".join(locus_svg.logo_column(x0 + i * cw, y + lane_h - 2, cw, lane_h - 12, probs))
                       for i, probs in enumerate(locus_svg.strand_rows(h)))
        body.append(f'<g><title>{escape(tip)}</title>{locus_svg._t(x0, y + 9, h["tf"] + (" (−)" if h["strand"] == "-" else ""), TEXT, G[900], weight="600")}'
                    f'{cols}</g>')
    seq = locus.reference(s["chrom"], s["start"], s["end"])
    for i, b in enumerate(seq):  # the reference sequence, + strand
        body.append(locus_svg._t(ax.x(s["start"] + i) + cw / 2, h_all + 11, b, min(10, cw * 1.3), palette.BASES.get(b, G[700]), "middle", "600"))
    return row("Motif changes", trk(h_all + 14, "".join(body)), "logos at the SNPs, + strand")


def hmm_group(s, ax, data, cfg, prefix, deadline, open_, notes):
    """The stacked count of conditions per state (Quiescent left out) and one row per condition: the genome-wide ChromHMM
    segmentation when salmobase answers, else the states inside the robust peaks."""
    found = live_segments(s, (cfg or {}).get("chromhmm", []), prefix, deadline)
    conditions = sorted(found, key=order) if found else sorted(data.get("conditions") or [], key=order)
    if found:
        segs = {c: [(a, e, st) for a, e, st in (found[c] or [])] for c in conditions}
        note, about = "", "AQUA-FAANG ChromHMM states, genome-wide, read live from salmobase"
        if any(v is None for v in found.values()):
            notes.append("ChromHMM did not load in time for some conditions (grey rows); reload to try again.")
    else:
        segs = {c: [(p["start"], p["end"], p["states"][c]) for p in data.get("peaks", []) if p["states"].get(c)] for c in conditions}
        note = "states inside robust peaks only" + (f" (genome-wide in windows up to {sl.MAX_SIGNAL // 1000} kb)"
                                                    if width(s) > sl.MAX_SIGNAL else "")
        about = "AQUA-FAANG chromatin states of the release, inside its robust ATAC peaks"
    h, total = 60, max(1, len(conditions))
    body = [blacklist(ax, data, h), f'<line x1="{-W}" x2="{2 * W}" y1="{h}" y2="{h}" stroke="{G[300]}"/>']
    body += locus_svg.state_stack(ax, segs, 250, 0, h, total)
    more = []
    for c in conditions:
        if found and found.get(c) is None:
            parts = [f'<rect x="{-W}" y="1" width="{3 * W}" height="11" fill="{G[200]}"><title>{escape(short(c))}: ChromHMM unavailable</title></rect>']
        else:
            parts = [state_rect(ax, a, e, 1, 11, st, short(c)) for a, e, st in segs.get(c) or ()]
        more.append(row(short(c), trk(13, "".join(parts)), tissue=tissue_of(c), dense=True, title=long(c, "states")))
    legend = [(f"st-{x}", x.replace("_", " ").replace(" 1", "")) for x in LEGEND_STATES]
    own = []  # tissues with state models of their own: visible, as they explain the legend's extra colours
    if any(immuno(c) for c in conditions):  # the ImmunoMap's models have labels of their own: salmon's 6-state model
        # three combined ones, trout's (one model for each treatment) a weak accessible state
        salmon = jobs.species()["key"] == jobs.SALMON["key"]
        legend += [("", "Head kidney:")] + [(f"st-{x}", x.replace("_", " ")) for x in (IMMUNOMAP_STATES if salmon else TROUT_IMMUNOMAP_STATES)]
        own.append("head kidney")
        about += "; head kidney (HK): the ImmunoMap's own " + ("6-state model" if salmon else "models, one for each treatment")
    if any(c.startswith("Gill_") for c in conditions):
        own.append("gill")
        about += "; gill: its own model of weaker 2026 data"
    if own:
        note += (" · " if note else "") + " and ".join(own) + ": state models of their own"
    return group("hmm", "Chromatin states", note, [row("Combined", trk(h + 2, "".join(body)), f"conditions per state, 0–{total}")],
                 separated(more), f"{len(more)} conditions", open_, legend, about=about)


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
    if not tracks:
        return group(assay, title, what, [row("", plain(14, locus_svg._t(4, 11, "no tracks for this assay in this release", TEXT, G[700])))])
    if s["end"] - s["start"] > sl.MAX_SIGNAL:
        return group(assay, title, what, [row("", plain(14, locus_svg._t(4, 11, f"zoom in to {sl.MAX_SIGNAL // 1000} kb or less to see signal", TEXT, G[700])))])
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
        body.append(f'<line x1="{-W}" x2="{2 * W}" y1="{half}" y2="{half}" stroke="{G[500]}"/>' + locus_svg._t(W - 2, 10, "+", TEXT, G[700], "end")
                    + locus_svg._t(W - 2, 2 * half - 2, "−", TEXT, G[700], "end"))
        combined_h = 2 * half
    else:
        body.append(f'<line x1="{-W}" x2="{2 * W}" y1="{half}" y2="{half}" stroke="{G[300]}"/>')
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
        parts.append(f'<line x1="{-W}" x2="{2 * W}" y1="{12 if rna else 22}" y2="{12 if rna else 22}" stroke="{G[300]}" stroke-width="0.6"/>')
        reps = max(found[c, st][1] for st in strands if (c, st) in found)
        more.append(row(short(c), trk(24, "".join(parts)), tissue=tissue[c],
                        title=" · ".join(x for x in (long(c, assay), f"mean of {reps} {'fish' if immuno(c) else 'replicate' + ('s' if reps > 1 else '')}") if x)))
    scale = f"conditions on a log scale, 0–{vmax:.0f} RPM" if rna else f"conditions 0–{vmax:.2f} RPM"
    note = f"{what.split(';')[0]}{'; + strand up, &#8722; down' if rna else ''} · {scale}"
    if failed:
        note += f" · {failed} of {len(tracks)} files did not load in time"
    sub = f"0–{total:.1f} RPM per strand" if rna else f"0–{total:.2f} RPM"
    g = group(assay, title, note, [row("Combined", trk(combined_h + 2, "".join(body)), sub)], more,
              f"{len(more)} conditions", open_, about=f"AQUA-FAANG {title} signal, read live from salmobase: the mean of each "
              "condition's replicates; the combined track stacks the tissue means")
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
        body.append(empty(4, 11))
    gerp = []
    top = max([g.get("score") or 0 for g in data.get("gerp", [])] + [1])
    for g in data.get("gerp", []):
        x0, x1 = ax.x(g["start"]), ax.x(g["end"])
        gerp.append(f'<rect x="{x0:.1f}" y="2" width="{max(1, x1 - x0):.1f}" height="9" fill="{G[700]}" '
                    f'fill-opacity="{0.35 + 0.65 * (g.get("score") or 0) / top:.2f}"><title>GERP constrained element (65 fish), score {g.get("score")}</title></rect>')
    if not data.get("gerp"):
        gerp.append(empty(4, 11))
    rows = [row("Ensembl regulatory", trk(14, "".join(body)), title="Ensembl regulatory build 116: promoters, enhancers and open "
                "chromatin, in the state colours"),
            row("GERP constrained", trk(14, "".join(gerp)), "darker = higher score", title="GERP constrained elements of the "
                "Ensembl Compara alignment of 65 fish")]
    if "pike" in data:  # sequence that aligns to northern pike, in releases with the layer
        pike = "".join(f'<rect x="{ax.x(p["start"]):.1f}" y="2" width="{max(1, ax.x(p["end"]) - ax.x(p["start"])):.1f}" height="9" '
                       f'fill="{G[700]}"><title>Aligns to northern pike: {p["end"] - p["start"]:,} bp</title></rect>' for p in data["pike"])
        rows.append(row("Aligns to pike", trk(14, pike or empty(4, 11)),
                        title="Sequence that aligns to northern pike (AQUA-FAANG salmon-trout-pike alignment, gaps of up to "
                              "50 bp closed)"))
    return group("other", "Other annotation", "", rows)


def scores_group(s, ax, data):
    """Predicted allele effects: one row per score layer of the release (layers.yaml format variant_scores, such as
    a ChromBPNet model), one tick per scored variant in the window, its height the score's rank. Where the layer has
    the signed effect of the alt allele, the tick points up in red when the model's prediction rises with it
    (ChromBPNet: more accessible) and down in blue when it falls, as the scorer's own browser track colours them;
    without one it is a grey tick up. None in a release without score layers."""
    rows, legend, mid, reach = [], [], 17, 15
    for label, layer in (data.get("scores") or {}).items():
        signed = any(e is not None for *_, e in layer["sites"])
        ticks = [f'<line x1="{-W}" x2="{2 * W}" y1="{mid}" y2="{mid}" stroke="{G[300]}" stroke-width="0.6"/>'] if signed else []
        base = mid if signed else 2 * mid - 1
        for pos, ref, alt, score, p, effect in layer["sites"]:
            h = max(2, reach * p * (1 if signed else 2))
            down = signed and (effect or 0) < 0
            colour = G[700] if not effect else palette.EFFECTS["down" if down else "up"]
            x, w = ax.x(pos - 1), max(2.2, ax.x(pos) - ax.x(pos - 1))
            tip = f"{label} {results.score_number(score)} ({ref}>{alt})" + (
                f": the alt allele is predicted {layer['down'] if down else layer['up']} "
                f"(effect {results.score_number(effect, sign=True)})" if effect else "")
            ticks.append(f'<rect x="{x:.1f}" y="{base if down else base - h:.1f}" width="{w:.1f}" height="{h:.1f}" fill="{colour}">'
                         f'<title>{escape(tip)}; higher than {100 * p:.1f}% of {escape(layer["reference"])}</title></rect>')
        if not layer["sites"]:
            ticks.append(empty(4, mid - 4))
        n = len(layer["sites"])
        rows.append(row(label, trk(2 * mid, "".join(ticks)), f"{n:,} scored variant{'' if n == 1 else 's'} here",
                        title=f"{label}: the model's prediction for each variant it scored; height = its rank among "
                              f"{layer['reference']}"))
        if signed and not legend:
            legend = [("sp-effect-up", f"up: alt allele {layer['up']}"), ("sp-effect-down", f"down: alt allele {layer['down']}")]
    if not rows:
        return None
    return group("scores", "Predicted allele effects", "height = rank", rows, legend=legend,
                 about="Sequence-model predictions for the variants each model scored (a release's score layers)")


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
    v, ax = drawn(s)  # the tracks draw the window and its margin; the controls and links keep the window
    data = locus.lanes(v["chrom"], v["start"], v["end"])
    prefix = f"snpportal:{(info.get('sha256') or 'release')[:12]}"
    deadline = float(jobs.setting("SNPPORTAL_SIGNAL_DEADLINE", 4.0))
    notes = []
    groups = [tracks_group(request, v, ax), genes_group(request, v, ax, data, open_), public_group(v, ax, data, open_), motifs_group(v, ax, data),
              scores_group(v, ax, data),
              peaks_group(v, ax, data, cfg, prefix, deadline, open_, notes),
              hmm_group(v, ax, data, cfg, prefix, deadline, open_, notes)]
    synthetic = bool(info.get("synthetic")) or any(locus.synthetic_track(t) for t in (cfg or {}).get("tracks", []))
    if s["key"]:
        job = jobs.read(s["key"])
        synthetic = synthetic or bool(job.get("synthetic_input") or job.get("synthetic_layers"))
    a, b = s["start"] + 1, s["end"]
    ctx.update(
        chromosome=chromosome(s), ruler=ruler(ax, v), groups=[g for g in groups if g], other=other_group(v, ax, data), notes=notes,
        synthetic=synthetic, moves=moves(s, open_), query=query(s, open_), limits=(sl.MIN_WINDOW, sl.MAX_WINDOW), assays=[(k, v[0]) for k, v in ASSAYS.items()],
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
