"""SVG for the locus browser and the evidence card: pure functions from plain data (lib.locus dicts, signal
values, tracks.yaml entries, annotated rows) to standalone SVG strings. Colours are literal hex values from
palette.py; figures.svg() adds role="img", <title>, <desc> and the SYNTHETIC watermark. No Django imports."""
from __future__ import annotations

import math
import re
import textwrap
from html import escape

from . import figures, palette

WIDTH, GUTTER, RIGHT = 1200, 170, 14
TISSUE_ORDER = ("Brain", "Gonad", "Liver", "Muscle")
COLUMNS = (("Immature", "Female", "Imm F"), ("Immature", "Male", "Imm M"), ("Mature", "Female", "Mat F"), ("Mature", "Male", "Mat M"))
STAGES = figures.STAGE_LABELS
REGBUILD = {"promoter": "Active_TSS", "enhancer": "Active_enhancer", "open_chromatin_region": "Accessible_chromatin"}  # -> state colour
TERMS = {  # tier_terms term -> (state name or colour, label) for the 'why this tier' bar
    "active": ("Active_enhancer", "active in a condition"),
    "active_elsewhere": ("Flanking_upstream", "active elsewhere"),
    "weak": ("Primed_enhancer", "weak state"),
    "coding": (palette.TIERS[1][0], "CDS"),
    "synonymous": (palette.TIERS[1][0], "synonymous CDS"),
    "splice": (palette.TIERS[2][0], "splice region"),
    "utr": (palette.TIERS[3][0], "UTR"),
    "constrained": (palette.GREY[700], "GERP constrained"),
    "regbuild": (palette.REGBUILD, "Ensembl regulatory"),
    "molqtl": (palette.TISSUES["Gonad"], "molQTL lead (display only)"),
    "motif": (palette.MOTIF, "TF motif change"),
}
EVIDENCE = {  # published-association marker by evidence kind (explore.evidence_kind): (colour, label)
    "missense": (palette.GREY[900], "missense"), "gwas": (palette.ACCENT, "GWAS lead"),
    "marker": (palette.STATUS["warn"][2], "QTL marker or candidate"), "region": (palette.GREY[500], "gene region, not a SNP")}
SIGNAL_UNIT = "RPM"  # nf-core ATAC bigWigs are scaled to 1M mapped reads
STATE_ORDER = ("Active_TSS", "Flanking_upstream", "Flanking_downstream", "Active_enhancer", "Primed_enhancer",
               "Poised_enhancer_1", "Poised_enhancer_2", "Accessible_chromatin", "Bivalent", "Repressed_polycomb",
               "ZNF_genes_and_repeats", "Unknown_1")  # strongest first; stacked bottom to top; Quiescent is not drawn


def _colour(name):
    """A state's colour in the active palette, or the colour itself."""
    return palette.STATES[name][0] if name in palette.STATES else name
LORE = palette.STATUS["warn"][2]
G = palette.GREY


def _t(x, y, text, size=10.5, fill=G[900], anchor="start", weight="", extra=""):
    w = f' font-weight="{weight}"' if weight else ""
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{fill}" text-anchor="{anchor}"{w}{extra}>'
            f"{escape(str(text))}</text>")


def _hatch(uid, name, colour, angle=45):
    return (f'<pattern id="{uid}-{name}" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate({angle})">'
            f'<line x1="0" y1="0" x2="0" y2="6" stroke="{colour}" stroke-width="2"/></pattern>')


def condition_label(condition):
    """('Brain', 'Imm F') for Brain_Immature_Female, ('Embryo', 'Blastula') for LateBlastulation."""
    parts = condition.split("_")
    if len(parts) == 3:
        return parts[0], f"{parts[1][:3]} {parts[2][0]}"
    return "Embryo", STAGES.get(condition, condition)


def fmt_bp(n):
    return f"{n / 1e6:.2f} Mb" if n >= 1e6 else f"{n / 1e3:.1f} kb" if n >= 1e3 else f"{n} bp"


class Axis:
    """Maps BED coordinates of the window start-end onto x0-x1 pixels."""

    def __init__(self, start, end, x0, x1):
        self.start, self.end, self.x0, self.x1 = start, end, x0, x1
        self.scale = (x1 - x0) / max(1, end - start)

    def x(self, pos):
        return self.x0 + (min(max(pos, self.start), self.end) - self.start) * self.scale

    def span(self, s, e, least=1.0):
        a, b = self.x(s), self.x(e)
        return a, max(least, b - a)

    def ticks(self, n=9):
        span = self.end - self.start
        k = 10 ** math.floor(math.log10(max(1, span / n)))
        step = next(m * k for m in (1, 2, 5, 10) if span / (m * k) <= n)
        return range(-(-self.start // step) * step, self.end + 1, step)


def locus(data, *, title="", desc="", caption="", snps=(), snp_note="", signal=None, hmm=None, chosen=(),
          mark=None, gene_url=None, width=WIDTH, gutter=GUTTER, compact=False, synthetic=False, uid="lc", gwas=None, legend_on=True,
          lanes=None, heading=True):
    """The locus figure. data: lib.locus.locus() dict. snps: [{pos, id, tier, tier_score, title, url}] (the user's
    SNPs, drawn at render time). signal: {title, start, rung, rows: [{track, label, values or None}], note, scale}.
    hmm: [{condition, segments or None}] to draw the genome-wide ChromHMM segmentation instead of states in peaks.
    chosen: preset conditions (highlighted). mark: a 1-based position to mark. gene_url(gene_id) links genes.
    gwas: a GWAS job's regional association lane, drawn on top (see gwas_lane). legend_on=False leaves the legend out
    (the landing page's thumbnail). lanes: the optional lanes to draw ('published', 'molqtl', 'regbuild', 'gerp',
    'variants'), None = all. heading=False leaves the title line out (it stays the SVG's <title>)."""
    show = lambda lane: lanes is None or lane in lanes
    ax = Axis(data["start"], data["end"], gutter, width - RIGHT)
    defs = [_hatch(uid, "bl", G[700]), _hatch(uid, "lore", LORE, -45), _hatch(uid, "na", G[500])]
    back, body, legend = [], [], {}  # bands behind everything; lanes; legend items {group: [(swatch svg, label)]}
    y = 4
    if title and heading:
        body.append(_t(8, y + 13, title, 13.5, weight="600"))
        y += 22

    # ideogram and ruler
    size = data.get("size") or data["end"]
    ideo = Axis(0, size, gutter, width - RIGHT)
    vx, vw = ideo.span(data["start"], data["end"], 2)
    body.append(_t(gutter - 10, y + 9, f"chr{data['chrom']} ({fmt_bp(size)})", 11, G[700], "end")
                + f'<rect x="{gutter}" y="{y + 1}" width="{width - RIGHT - gutter}" height="8" rx="4" fill="{G[200]}"/>'
                f'<rect x="{vx - 1:.1f}" y="{y - 1}" width="{vw + 2:.1f}" height="12" fill="none" stroke="{palette.ACCENT}" stroke-width="1.5"/>')
    y += 18
    top = y
    body.append(f'<line x1="{gutter}" x2="{width - RIGHT}" y1="{y + 16}" y2="{y + 16}" stroke="{G[500]}"/>')
    for t in ax.ticks(6 if compact else 8):
        x, half = ax.x(t), 3.4 * len(f"{t:,}")
        anchor = "start" if x - half < ax.x0 else "end" if x + half > ax.x1 else "middle"
        body.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{y + 11}" y2="{y + 16}" stroke="{G[500]}"/>'
                    + _t(x, y + 8, f"{t:,}", 11, G[900], anchor))
    body.append(_t(gutter - 10, y + 15, fmt_bp(data["end"] - data["start"]), 11, G[700], "end"))
    y += 24

    small = 10 if compact else 9  # compact figures (the card's, the landing's) are small: no text below 10 px there

    def lane_label(text, yy, sub=""):
        body.append(_t(gutter - 10, yy, text, 10.5, G[900], "end", "600"))
        if sub and 5.5 * len(sub) < gutter - 14:  # subtitles that don't fit a narrow gutter are left out
            body.append(_t(gutter - 10, yy + 11, sub, small, G[700], "end"))

    if gwas:  # P7.3: -log10 p of a GWAS job's SNPs, on top (AGENT gwas)
        y = gwas_lane(body, ax, gwas, y, legend)

    # the user's SNPs: tier-coloured lollipops, stem height = tier_score
    if snps:
        top_score = max([s.get("tier_score") or 0 for s in snps] + [1])
        lane_label("Your SNPs", y + 18, snp_note)
        for s in sorted(snps, key=lambda s: -(s.get("tier") or 4)):  # best tiers on top
            fill = palette.TIERS.get(s.get("tier") or 4, palette.TIERS[4])[0]
            x, h = ax.x(s["pos"] - 0.5), 8 + 26 * (s.get("tier_score") or 0) / top_score
            dot = (f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{y + 40}" y2="{y + 40 - h:.1f}" stroke="{G[500]}"/>'
                   f'<circle cx="{x:.1f}" cy="{y + 40 - h:.1f}" r="4" fill="{fill}" stroke="{G[900]}" stroke-width="0.6">'
                   f'<title>{escape(s.get("title") or "")}</title></circle>')
            body.append(f'<a href="{escape(s["url"])}">{dot}</a>' if s.get("url") else dot)
        legend["Tiers"] = [(_swatch(palette.TIERS[t][0], round_=True), f"tier {t}") for t in sorted({s.get("tier") or 4 for s in snps})]
        y += 46

    # published associations (the known-loci catalogue): diamonds by evidence kind, filled when the effect allele is stated
    if data.get("known") and show("published"):
        y = _published(body, ax, data["known"], y, lane_label, legend)

    # molQTL lead SNPs (nf-RASQUAL, 12 fish): a triangle per lead, in the colour of its first tissue
    if data.get("molqtl") and show("molqtl"):
        lane_label("molQTL leads", y + 11, "nf-RASQUAL")
        for m in data["molqtl"]:
            x = ax.x(m["pos"] - 0.5)
            tissue = (m.get("tissues") or "").split(",")[0]
            body.append(f'<path d="M{x:.1f} {y + 2} l5 9 l-10 0z" fill="{palette.TISSUES.get(tissue, G[700])}" stroke="{G[900]}" '
                        f'stroke-width="0.5"><title>{escape(m.get("title") or "")}</title></path>')
        tissues = sorted({t for m in data["molqtl"] for t in (m.get("tissues") or "").split(",") if t})
        legend["molQTL leads (first tissue)"] = [(f'<path d="M6 0 l5 9 l-10 0z" fill="{palette.TISSUES.get(t, G[700])}"/>', t) for t in tissues]
        y += 22

    # gene models
    y = _genes(body, ax, data.get("genes", []), y, gene_url, 4 if compact else 8, lane_label)
    if any(g["label"].startswith("~") for g in data.get("genes", [])):
        legend.setdefault("Genes", []).append(("", "~NAME = unnamed in Ensembl 116, named by its human (else zebrafish) ortholog"))

    # chromatin: 21 condition rows, states inside robust peaks (or the ChromHMM segmentation)
    y, present, chosen = _chromatin(body, ax, data, y, chosen, hmm, compact, gutter, uid, lane_label)
    states = [(_swatch(palette.STATES[s][0]), f"{s.replace('_', ' ')} ({palette.STATES[s][1]})") for s in palette.STATES if s in present]
    if chosen:
        states.append((f'<path d="M2 0 l6 5 l-6 5z" fill="{palette.ACCENT}"/>', "a chosen condition"))
    legend["Chromatin state" + ("" if hmm else " (inside AQUA-FAANG robust peaks only)")] = states

    # regulatory build and GERP
    if show("regbuild") and (data.get("regbuild") or not compact):
        lane_label("Ensembl regulatory", y + 10)
        for r in data.get("regbuild", []):
            x, w = ax.span(r["start"], r["end"])
            body.append(f'<rect x="{x:.1f}" y="{y + 2}" width="{w:.1f}" height="10" fill="{_colour(REGBUILD.get(r.get("type"), G[500]))}">'
                        f'<title>{escape(str(r.get("type", "")).replace("_", " "))} {escape(str(r.get("id") or ""))}'
                        f'{escape(" (" + r["gene_id"] + ")" if r.get("gene_id") else "")}</title></rect>')
        if not data.get("regbuild"):
            body.append(_t(ax.x0, y + 11, "none in this window", 9, G[700]))
        types = sorted({r.get("type") for r in data.get("regbuild", [])} & set(REGBUILD))
        if types:
            legend["Regulatory build"] = [(_swatch(_colour(REGBUILD[t])), t.replace("_", " ")) for t in types]
        y += 16
    if show("gerp") and (data.get("gerp") or not compact):
        lane_label("GERP constrained", y + 10)
        top_gerp = max([g.get("score") or 0 for g in data.get("gerp", [])] + [1])
        for g in data.get("gerp", []):
            x, w = ax.span(g["start"], g["end"])
            body.append(f'<rect x="{x:.1f}" y="{y + 2}" width="{w:.1f}" height="10" fill="{G[700]}" '
                        f'fill-opacity="{0.35 + 0.65 * (g.get("score") or 0) / top_gerp:.2f}">'
                        f'<title>GERP constrained element (65 fish), score {g.get("score")}</title></rect>')
        if not data.get("gerp"):
            body.append(_t(ax.x0, y + 11, "none in this window", 9, G[700]))
        y += 16

    # public variants, tick height = minor allele frequency
    if show("variants"):
        lane_label("Public variants", y + 14, "504 fish, height = MAF")
        body.append(f'<line x1="{gutter}" x2="{width - RIGHT}" y1="{y + 30}" y2="{y + 30}" stroke="{G[300]}"/>')
        if not data.get("variants"):
            body.append(_t(ax.x0, y + 26, "none in this window", 9, G[700]))
        for v in data.get("variants", []):
            x, h = ax.x(v["pos"] - 0.5), 3 + 24 * min(0.5, v.get("maf") or 0) / 0.5
            tip = (f"{data['chrom']}:{v['pos']:,} {v.get('ref')}>{v.get('alt')} · 504-fish panel: MAF {_num(v.get('maf'))}, alt AF {_num(v.get('af'))}"
                   + (f" · AQUA-FAANG 12 fish: alt AF {_num(v.get('aquafaang12_af'))}, DR2 {_num(v.get('aquafaang12_dr2'))}"
                      if v.get("aquafaang12_af") is not None else ""))
            body.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{y + 30}" y2="{y + 30 - h:.1f}" stroke="{G[700]}">'
                        f"<title>{escape(tip)}</title></line>")
        y += 36

    # live signal rows
    if signal is not None:
        y = _signal(body, ax, signal, y, gutter, uid, lane_label, compact)

    # blacklist and LORe: hatched bands behind every lane, explained in the legend
    for b in data.get("blacklist", []):
        x, w = ax.span(b["start"], b["end"])
        back.append(f'<rect x="{x:.1f}" y="{top}" width="{w:.1f}" height="{y - top}" fill="url(#{uid}-bl)" fill-opacity="0.35">'
                    f'<title>AQUA-FAANG blacklist {b["start"] + 1:,}-{b["end"]:,}: no peak here means "cannot tell"</title></rect>')
    for b in data.get("lore", []):
        x, w = ax.span(b["start"], b["end"])
        back.append(f'<rect x="{x:.1f}" y="{top}" width="{w:.1f}" height="{y - top}" fill="url(#{uid}-lore)" fill-opacity="0.25">'
                    f'<title>LORe region {escape(str(b.get("label") or ""))}: near-identical Ss4R ohnologs</title></rect>')
    if data.get("blacklist") or data.get("lore"):
        legend["Bands"] = ([(_swatch(f"url(#{uid}-bl)"), "AQUA-FAANG blacklist")] if data.get("blacklist") else []) + (
            [(_swatch(f"url(#{uid}-lore)"), "LORe (late-rediploidized) region")] if data.get("lore") else [])
    if mark:
        x = ax.x(mark - 0.5)
        back.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{top}" y2="{y}" stroke="{palette.ACCENT}" stroke-dasharray="3 2"/>')
    if data.get("truncated"):
        body.append(_t(gutter, y + 10, "Some lanes are cut short in this wide window: zoom in to see all of "
                       + ", ".join(data["truncated"]), 9.5, palette.STATUS["warn"][0]))
        y += 14

    y = _legend(body, legend, y + 4, width, gutter) if legend_on else y + 4
    for line in caption.splitlines():
        for part in textwrap.wrap(line, int((width - 16) / (0.58 * small))):
            body.append(_t(8, y + 11, part, small, G[700]))
            y += small + 3
    return figures.svg(width, y + 6, title or "Locus", desc or caption, f'<defs>{"".join(defs)}</defs>' + "".join(back + body),
                       synthetic)


def _num(v):
    return "n/a" if v is None else f"{v:.2f}"


def _edge(fill):
    """stroke attributes outlining a near-white fill (AQUA-FAANG's Quiescent), else ''."""
    colour = palette.edge(fill)
    return f' stroke="{colour}" stroke-width="0.5"' if colour else ""


def _published(body, ax, known, y, lane_label, legend):
    """The published-associations lane: a diamond per catalogue row (dict with pos, id, locus, trait, evidence,
    effect, effect_allele, caveat, kind), filled by evidence kind when the effect allele is stated, hollow when not;
    the id as a label beside the marker where it fits, else centred under it, else only in the tooltip. Returns the new y."""
    lane_label("Published", y + 11, "known loci")
    known = sorted(known, key=lambda k: int(k["pos"]))
    xs = [ax.x(int(k["pos"]) - 0.5) for k in known]
    free, under = 0, ax.x0  # where the next label beside, or under, the markers may start
    for i, (k, x) in enumerate(zip(known, xs)):
        fill = EVIDENCE.get(k.get("kind"), EVIDENCE["gwas"])[0]
        allele = bool(k.get("effect_allele"))
        tip = " · ".join(v for v in [k.get("id", ""), k.get("locus"), (k.get("trait") or "").replace("_", " "), k.get("evidence"),
                                     k.get("effect"), f"effect allele {k['effect_allele']}" if allele else "allele not stated",
                                     k.get("caveat")] if v)
        body.append(f'<path d="M{x:.1f} {y + 2} l5 6 l-5 6 l-5 -6z" fill="{fill if allele else palette.WHITE}" stroke="{fill}" '
                    f'stroke-width="1.4"><title>{escape(tip)}</title></path>')
        w = 6.2 * len(k.get("id", ""))
        left = x + 7 + w > ax.x1  # near the right edge: label to the left of the marker
        a, b = (x - 7 - w, x - 7) if left else (x + 7, x + 7 + w)
        if a >= free and not any(a - 5 < other < b + 5 for j, other in enumerate(xs) if j != i):
            body.append(_t(b if left else a, y + 12, k.get("id", ""), 10.5, G[900], "end" if left else "start"))
            free = b + 6
        elif under <= x - w / 2 and x + w / 2 <= ax.x1:  # e.g. vgll3_Met54Thr, 2 kb from vgll3_Asn323Lys
            body.append(_t(x, y + 25, k.get("id", ""), 10.5, G[900], "middle"))
            under = x + w / 2 + 6
    kinds = sorted({k.get("kind") if k.get("kind") in EVIDENCE else "gwas" for k in known}, key=list(EVIDENCE).index)
    legend["Published"] = [(f'<path d="M6 0 l5 6 l-5 6 l-5 -6z" fill="{EVIDENCE[kind][0]}"/>', EVIDENCE[kind][1]) for kind in kinds] + (
        [(f'<path d="M6 0 l5 6 l-5 6 l-5 -6z" fill="{palette.WHITE}" stroke="{G[700]}" stroke-width="1.4"/>', "effect allele not stated")]
        if not all(k.get("effect_allele") for k in known) else [])
    return y + (40 if under > ax.x0 else 26)


def _swatch(fill, round_=False):
    if round_:
        return f'<circle cx="6" cy="5" r="4.5" fill="{fill}" stroke="{G[900]}" stroke-width="0.6"/>'
    return f'<rect x="0" y="0" width="12" height="10" fill="{fill}" stroke="{G[500]}" stroke-width="0.5"/>'


def _legend(body, groups, y, width, gutter):
    """Legend groups as rows of swatches and labels, wrapping at the figure width."""
    for name, items in groups.items():
        if not items:
            continue
        body.append(_t(gutter - 10, y + 10, name.split(" (")[0], 10.5, G[900], "end", "600"))
        x = gutter
        if " (" in name:
            body.append(_t(x, y + 10, "(" + name.split(" (", 1)[1], 9.5, G[700]))
            x += 6 * len(name.split(" (", 1)[1]) + 12
        for swatch, label in items:
            w = (16 if swatch else 0) + 5.6 * len(label) + 14
            if x + w > width - RIGHT:
                x, y = gutter, y + 15
            if swatch:
                body.append(f'<g transform="translate({x:.1f},{y + 2})">{swatch}</g>')
            body.append(_t(x + (16 if swatch else 0), y + 10, label, 9.5, G[700]))
            x += w
        y += 16
    return y


def _genes(body, ax, genes, y, gene_url, max_rows, lane_label):
    """Gene models packed into at most max_rows rows (labels dropped when that does not fit), '+N more' after. A gene
    dict may carry dup = {text, url, title}: its Ss4R duplicate, linked after the label (the locus browser's)."""
    if not genes:
        lane_label("Genes", y + 12)
        body.append(_t(ax.x0, y + 12, "no Ensembl gene in this window", 9.5, G[700]))
        return y + 20

    def pack(with_labels):
        rows, placed, hidden = [], [], 0
        for g in sorted(genes, key=lambda g: g["start"]):
            x0, x1 = ax.x(g["start"]), ax.x(g["end"])
            text = len(g["label"]) + 2 + (len(g["dup"]["text"]) + 1 if g.get("dup") else 0)
            right = max(x1, x0 + 6.2 * text) if with_labels else x1
            row = next((i for i, end in enumerate(rows) if end + 8 < x0), None)
            if row is None:
                if len(rows) == max_rows:
                    hidden += 1
                    continue
                rows.append(0)
                row = len(rows) - 1
            rows[row] = right
            placed.append((row, g))
        return placed, hidden, len(rows)

    placed, hidden, n = pack(True)
    labels = not hidden
    if hidden:
        placed, hidden, n = pack(False)
    lane_label("Genes", y + 12, "Ensembl 116")
    for row, g in placed:
        yy = y + row * 26 + (12 if labels else 4)
        coding = g.get("biotype") == "protein_coding"
        colour = G[900] if coding else G[500]
        t = (g.get("transcripts") or [None])[0]
        title = (f"{g['label']} ({g['id']}) · {g.get('biotype') or ''} · {g.get('strand')} strand · "
                 f"{g['start'] + 1:,}-{g['end']:,}" + (f" · transcript {t['transcript_id']}" + (" (canonical)" if t["canonical"] else "")
                                                        if t else "")
                 + (f" · human {g['human']}" if g.get("human") else "") + (f" · zebrafish {g['zebrafish']}" if g.get("zebrafish") else "")
                 + (f" · {g['description']}" if g.get("description") else ""))
        parts = [f"<title>{escape(title)}</title>"]
        s, e = (t["start"], t["end"]) if t else (g["start"], g["end"])
        x0, w = ax.span(s, e)
        parts.append(f'<line x1="{x0:.1f}" x2="{x0 + w:.1f}" y1="{yy + 6}" y2="{yy + 6}" stroke="{colour}"/>')
        arrow = 1 if g.get("strand") == "+" else -1
        for cx in range(int(x0) + 10, int(x0 + w) - 4, 28):  # strand chevrons along the intron line
            parts.append(f'<path d="M{cx - 2 * arrow} {yy + 3} l{3 * arrow} 3 l{-3 * arrow} 3" fill="none" stroke="{colour}" stroke-width="0.9"/>')
        blocks = (t or {}).get("parts") or [{"start": g["start"], "end": g["end"], "part": "exon"}]
        has_cds = any(p["part"] == "CDS" for p in blocks)
        for p in blocks:
            if has_cds and p["part"] == "exon":
                continue
            px, pw = ax.span(p["start"], p["end"])
            h = 12 if p["part"] in ("CDS", "exon") else 6
            parts.append(f'<rect x="{px:.1f}" y="{yy + 6 - h / 2}" width="{pw:.1f}" height="{h}" fill="{colour}"/>')
        if labels:
            name = f"{g['label']} →" if arrow == 1 else f"← {g['label']}"
            parts.append(_t(max(ax.x0, x0), yy - 3, name, 10, G[900], extra=' font-style="italic"' if g.get("name") else ""))
        group = "".join(parts)
        body.append(f'<a href="{escape(gene_url(g["id"]))}">{group}</a>' if gene_url else f"<g>{group}</g>")
        if labels and g.get("dup"):  # after the gene's own link, as links can't nest
            dx = max(ax.x0, x0) + 6.3 * (len(g["label"]) + 2) + 6  # after the name and its strand arrow
            dup = _t(dx, yy - 3, g["dup"]["text"], 9.5, G[700]).replace("</text>", f'<title>{escape(g["dup"]["title"])}</title></text>')
            body.append(f'<a href="{escape(g["dup"]["url"])}">{dup}</a>' if g["dup"].get("url") else dup)
    y += n * 26 + (8 if labels else 4)
    if hidden:
        body.append(_t(ax.x0, y + 8, f"+{hidden} more genes: zoom in", 9.5, G[700]))
        y += 12
    elif not labels:
        body.append(_t(ax.x0, y + 8, "gene names hidden in this crowded view: zoom in or hover", 9.5, G[700]))
        y += 12
    return y + 4


def _chromatin(body, ax, data, y, chosen, hmm, compact, gutter, uid, lane_label):
    """21 condition rows, grouped by tissue (embryo stages last). Returns (y, states present, conditions marked)."""
    conditions = data.get("conditions") or []
    rows = {r["condition"]: r["segments"] for r in hmm} if hmm is not None else None
    h, gap = (5, 1) if compact else (9, 1)
    lane_label("Chromatin states" if hmm is None else "ChromHMM segmentation", y + 10,
               "AQUA-FAANG, robust peaks" if hmm is None else "AQUA-FAANG, genome-wide")
    y += 26
    chosen = set(chosen) if len(set(chosen) & set(conditions)) < len(conditions) else set()  # 'all': nothing to point out
    present, last_group, first_y = set(), None, y
    for c in conditions:
        group, label = condition_label(c)
        if group != last_group and last_group is not None:
            y += 4
        if group != last_group:
            body.append(f'<rect x="{gutter - 6}" y="{y}" width="3" height="{(h + gap) * sum(condition_label(x)[0] == group for x in conditions) - gap}" '
                        f'fill="{palette.TISSUES.get(group, G[500])}"/>')
            body.append(_t(8, y + h + (3 if compact else 0), group, 11 if compact else 9.5, G[900], weight="600"))
        last_group = group
        if c in chosen:
            body.append(f'<path d="M{gutter - 15} {y} l5 {h / 2} l-5 {h / 2}z" fill="{palette.ACCENT}"><title>a chosen condition</title></path>')
        if not compact:
            body.append(_t(gutter - (17 if c in chosen else 10), y + h - 1, label, 8.5, G[900] if c in chosen else G[700], "end",
                           "600" if c in chosen else ""))
        name = f"{group} {label}" if group != "Embryo" else label
        if rows is not None:
            segs = rows.get(c)
            if segs is None:
                body.append(f'<rect x="{ax.x0}" y="{y}" width="{ax.x1 - ax.x0}" height="{h}" fill="url(#{uid}-na)" fill-opacity="0.5">'
                            f"<title>{escape(name)}: ChromHMM segmentation unavailable</title></rect>")
            for s, e, state in segs or ():
                x, w = ax.span(s, e, 0.5)
                present.add(state)
                body.append(f'<rect x="{x:.1f}" y="{y}" width="{w:.1f}" height="{h}" fill="{palette.state(state)[0]}"{_edge(palette.state(state)[0])}>'
                            f"<title>{escape(name)}: {escape(state.replace('_', ' '))} {s + 1:,}-{e:,}</title></rect>")
        else:
            for p in data.get("peaks", []):
                state = p["states"].get(c)
                if not state:
                    continue
                x, w = ax.span(p["start"], p["end"])
                present.add(state)
                fill, _, abbr = palette.state(state)
                body.append(f'<rect x="{x:.1f}" y="{y}" width="{w:.1f}" height="{h}" fill="{fill}"{_edge(fill)}>'
                            f"<title>{escape(name)}: {escape(state.replace('_', ' '))} ({abbr}) · peak {escape(p['id'])}</title></rect>")
        y += h + gap
    if rows is not None:  # robust peaks outlined over the segmentation
        for p in data.get("peaks", []):
            x, w = ax.span(p["start"], p["end"])
            body.append(f'<rect x="{x:.1f}" y="{first_y - 1}" width="{w:.1f}" height="{y - first_y + 1}" fill="none" '
                        f'stroke="{G[900]}" stroke-width="0.7"><title>robust ATAC peak {escape(p["id"])}</title></rect>')
    return y + 6, present, chosen


def _signal(body, ax, signal, y, gutter, uid, lane_label, compact):
    """Signal rows: stepped area per track on a shared (or per-track) scale; hatched 'signal unavailable' rows."""
    lane_label(signal.get("title", "Signal"), y + 10, signal.get("subtitle", ""))
    y += 22 if signal.get("subtitle") else 16
    if signal.get("note"):
        body.append(_t(ax.x0, y - 4, signal["note"], 9.5, G[700]))
    rows = signal.get("rows", [])
    peak = max([v for r in rows for v in (r["values"] or []) if v is not None] + [0])
    h = 18 if compact else 28
    r_bp, first = signal.get("rung", 1), signal.get("start", ax.start)
    for r in rows:
        track = r["track"]
        colour = palette.TISSUES.get(track.get("tissue"), G[700])
        body.append(f'<rect x="{gutter - 6}" y="{y}" width="3" height="{h}" fill="{colour}"/>'
                    + _t(gutter - 10, y + 11, r["label"], 10.5, G[900], "end"))
        body.append(f'<line x1="{ax.x0}" x2="{ax.x1}" y1="{y + h}" y2="{y + h}" stroke="{G[300]}"/>')
        if r["values"] is None:
            body.append(f'<rect x="{ax.x0}" y="{y}" width="{ax.x1 - ax.x0}" height="{h}" fill="url(#{uid}-na)" fill-opacity="0.45"/>'
                        + _t((ax.x0 + ax.x1) / 2, y + h / 2 + 4, "signal unavailable (salmobase did not answer in time)", 10, G[900], "middle"))
            y += h + 4
            continue
        top = max([v for v in r["values"] if v is not None] + [0]) if signal.get("scale") == "track" else peak
        if not compact:
            body.append(_t(gutter - 10, y + 24, f"0–{top:.3g} {SIGNAL_UNIT}", 10, G[700], "end"))
        path, prev = [f"M{ax.x0:.1f} {y + h}"], None
        for i, v in enumerate(r["values"]):
            s = first + i * r_bp
            if s + r_bp <= ax.start or s >= ax.end:
                continue
            hy = y + h - (h - 1) * min(1.0, (v or 0) / top) if top else y + h
            if hy != prev:
                path.append(f"L{ax.x(s):.1f} {hy:.1f}")
                prev = hy
            path.append(f"L{ax.x(s + r_bp):.1f} {hy:.1f}")
        path.append(f"L{ax.x1:.1f} {y + h}Z")
        body.append(f'<path d="{"".join(path)}" fill="{colour}" fill-opacity="0.85"><title>{escape(r["label"])}: '
                    f'{escape(track.get("assay", ""))} {escape(track.get("replicate") or "")}, max {top:.3g} {SIGNAL_UNIT} in view</title></path>')
        y += h + 4
    if rows and not compact:
        body.append(_t(ax.x0, y + 9, f"y axis: mean signal in {SIGNAL_UNIT} (reads per million mapped reads), "
                       f"{'each row on its own scale' if signal.get('scale') == 'track' else 'one scale for all rows'}, bins of {r_bp:,} bp",
                       10, G[700]))
        y += 12
    return y + 4


# ---- evidence card figures ----

def _fit(text, px, size):
    """text cut to about px wide at font size `size`, with an ellipsis."""
    n = int(px / (size * 0.58))
    return text if len(text) <= n else text[: max(1, n - 1)] + "…"


def score_blocks(parts, cutoffs, score, synthetic=False, unit=66, width=590):
    """The card's score: one block per evidence term, as wide as its points (largest first, notched at each point like
    a ruler), its label as short as a chip (with +points when it fits; the full text on hover), dashed lines at the tier cut-offs (tier 3, 2 and 1 at
    cutoffs[2], [1] and [0] points) to show which the blocks reach, and '= score' just after the bar. A label too long for its block drops ' in', then all but its first word. parts: [(label, weight,
    colour, full text)]."""
    span = max(sum(p[1] for p in parts), cutoffs[0])
    u = min(unit, (width - 50) / max(span, 1))
    body, words, x = [], [], 0  # blocks, then the cut-off lines, then the words on top
    for label, w, colour, tip in parts:
        bw, ink = w * u - 4, palette.text_on(colour)
        body.append(f'<rect x="{x:.1f}" y="14" width="{bw:.1f}" height="28" rx="4" fill="{colour}"><title>{escape(tip)}</title></rect>'
                    + "".join(f'<path d="M{x + i * u - 2:.1f} 14v5M{x + i * u - 2:.1f} 42v-5" stroke="{palette.WHITE}" stroke-width="1.5" '
                              'stroke-opacity="0.8" pointer-events="none"/>' for i in range(1, w)))  # a ruler: a notch per point
        text = next((t for t in (label, label.replace(" in ", " "), label.split(" ")[0]) if 6.2 * len(t) <= bw - 12), label)
        halo = f' stroke="{colour}" stroke-width="3" paint-order="stroke"'  # hides the cut-off lines behind the letters
        words.append(f'<g pointer-events="none">{_t(x + 6, 32, _fit(text, bw - 12, 10.5), 10.5, ink, "start", "600", halo)}'
                     + (_t(x + bw - 6, 32, f"+{w}", 10.5, ink, "end", "700", halo) if bw - 12 - 6.2 * len(text) > 20 else "") + "</g>")
        x += w * u
    if not parts:
        words.append(_t(4, 32, "no evidence found (not evidence of no effect)", 10.5, G[700], "start", "",
                        f' stroke="{palette.WHITE}" stroke-width="4" paint-order="stroke"'))
    for i, c in enumerate(cutoffs):  # the cut-offs over the blocks: after c points
        cx = c * u - 2
        body.append(f'<line x1="{cx:.1f}" x2="{cx:.1f}" y1="14" y2="42" stroke="{palette.WHITE}" stroke-width="3" stroke-opacity="0.6"/>'  # seen on dark blocks
                    f'<line x1="{cx:.1f}" x2="{cx:.1f}" y1="12" y2="44" stroke="{G[900]}" stroke-dasharray="3 2"/>'
                    + _t(cx, 9, f"T{i + 1}", 9, G[700], "middle").replace("</text>", f"<title>tier {i + 1}: {c} points or more</title></text>"))
    body += words + [_t(span * u + 8, 33, f"= {score}", 14, G[900], "start", "700")]  # just after the bar
    desc = "; ".join(p[3] for p in parts) or "no evidence counted"
    return figures.svg(round(span * u + 50), 46, f"Score {score}", f"{desc}. Weights and tier cut-offs are provisional.", "".join(body), synthetic)


GRID = {"cw": 58, "ch": 22, "gap": 4, "left": 70, "top": 18}  # the tiles: cell size, gap, label column, header row


def chromatin_grid(states, chosen=(), blacklisted=False, synthetic=False, uid="cg", legend=True):
    """Tissue rows x immature/mature female/male columns, plus an embryo row: the state of each of the 21 conditions
    at one SNP. states: {condition: state or None}. Preset cells are outlined; blacklisted cells without a state are
    hatched 'n/a'. legend=False: no legend of its own (the card shares one with its mini browser)."""
    cw, ch, gap, left = GRID["cw"], GRID["ch"], GRID["gap"], GRID["left"]
    defs = f"<defs>{_hatch(uid, 'na', G[500])}</defs>"
    parts, y, present = [], GRID["top"], set()
    for i, (_, _, short) in enumerate(COLUMNS):
        parts.append(_t(left + i * (cw + gap) + cw / 2, 12, short, 9.5, G[700], "middle"))

    def cell(x, yy, condition, label, cw=cw):
        state = states.get(condition)
        tip = state.replace("_", " ") if state else "blacklisted: cannot tell" if blacklisted else "no peak"  # the rows and columns say where
        out = [f"<title>{escape(tip)}</title>"]
        if state:
            fill, text, abbr = palette.state(state)
            present.add(state)
            out.append(f'<rect x="{x}" y="{yy}" width="{cw}" height="{ch}" rx="2" fill="{fill}"{_edge(fill)}/>' + _t(x + cw / 2, yy + 15, abbr, 10, text, "middle", "600"))
        elif blacklisted:
            out.append(f'<rect x="{x}" y="{yy}" width="{cw}" height="{ch}" rx="2" fill="url(#{uid}-na)" stroke="{G[500]}"/>'
                       + _t(x + cw / 2, yy + 15, "n/a", 9.5, G[900], "middle"))
        else:
            out.append(f'<rect x="{x + 0.5}" y="{yy + 0.5}" width="{cw - 1}" height="{ch - 1}" rx="2" fill="{palette.NO_PEAK[0]}" stroke="{palette.NO_PEAK[1]}"/>')
        if condition in chosen:
            out.append(f'<rect x="{x - 1.5}" y="{yy - 1.5}" width="{cw + 3}" height="{ch + 3}" rx="3" fill="none" stroke="{G[900]}" stroke-width="2"/>')
        if label:
            out.append(_t(x + cw / 2, yy + ch + 10, label, 8.5, G[700], "middle"))
        return f"<g>{''.join(out)}</g>"

    for tissue in TISSUE_ORDER:
        parts.append(_t(4, y + 15, tissue, 10.5))
        for i, (maturity, sex, _) in enumerate(COLUMNS):
            parts.append(cell(left + i * (cw + gap), y, f"{tissue}_{maturity}_{sex}", ""))
        y += ch + gap
    y += 4
    parts.append(_t(4, y + 15, "Embryo", 10.5))
    ew = (4 * (cw + gap) - gap - 4 * gap) / 5
    for i, stage in enumerate(STAGES):
        parts.append(cell(round(left + i * (ew + gap), 1), y, stage, STAGES[stage], round(ew, 1)))
    y += ch + 18
    x = 4
    for s in palette.STATES if legend else ():
        if s in present:
            label = f"{palette.STATES[s][1]} {s.replace('_', ' ')}"
            if x + 16 + 5.4 * len(label) > left + 4 * (cw + gap):
                x, y = 4, y + 14
            parts.append(f'<rect x="{x}" y="{y}" width="12" height="10" fill="{palette.STATES[s][0]}" stroke="{G[500]}" stroke-width="0.5"/>'
                         + _t(x + 16, y + 9, label, 9, G[700]))
            x += 16 + 5.4 * len(label) + 10
    if legend:
        y += 14 if present else 0
        parts.append(_t(4, y + 10, "outlined = the chosen conditions; empty = no AQUA-FAANG peak" + ("; n/a = blacklisted" if blacklisted else ""), 9, G[700]))
    else:
        y -= 16
    width = left + 4 * (cw + gap) + 4
    desc = "; ".join(f"{c}: {s}" for c, s in states.items() if s) or "No AQUA-FAANG peak in any condition."
    return figures.svg(width, y + 16, "Chromatin state per condition", desc, defs + "".join(parts), synthetic)


def state_stack(ax, segs, n, y, h, total):
    """Chromatin states stacked per bin: in each of n bins across the axis, the number of conditions in each state
    (bottom to top in STATE_ORDER, Quiescent left out), scaled so `total` conditions fill y to y + h. segs: {condition:
    [(start, end, state)] or None}. The locus browser's combined chromatin track."""
    start, end = ax.start, ax.end
    counts = [{} for _ in range(n)]
    for rows in segs.values():
        for a, e, st in rows or ():
            if st == "Quiescent":
                continue
            for b in range(max(0, int((a - start) * n / (end - start))), min(n, int(math.ceil((e - start) * n / (end - start))))):
                if a <= start + (b + 0.5) * (end - start) / n < e:
                    counts[b][st] = counts[b].get(st, 0) + 1
    out, bw = [], (ax.x1 - ax.x0) / n
    for b, cnt in enumerate(counts):
        top = y + h
        for st in STATE_ORDER:
            k = cnt.get(st, 0)
            if k:
                hh = h * k / total
                top -= hh
                out.append(f'<rect x="{ax.x0 + b * bw:.2f}" y="{top:.2f}" width="{bw + 0.3:.2f}" height="{hh:.2f}" fill="{palette.state(st)[0]}">'
                           f'<title>{k} of {total} conditions: {st.replace("_", " ")}</title></rect>')
    return out


def strongest(states):
    """A robust peak's strongest state of its conditions' states (first in STATE_ORDER): its colour in the browsers."""
    return next((x for x in STATE_ORDER if x in states), "Accessible_chromatin")


def _letter(base, x, bottom, cw, h):
    """One logo letter cw wide and h tall, standing on `bottom` (a monospace glyph scaled to the box)."""
    return (f'<text transform="translate({x:.2f} {bottom:.2f}) scale({cw / 6:.3f} {h / 7.3:.3f})" font-family="Menlo, Consolas, '
            f'monospace" font-weight="700" font-size="10" fill="{palette.BASES[base]}">{base}</text>')


def logo_column(x, bottom, cw, height, probs):
    """The stacked letters of one motif position (probabilities in A, C, G, T order): heights = probability x
    information content, `height` for 2 bits, the most likely base on top."""
    ic = 2 + sum(p * math.log2(p) for p in probs if p > 0)
    out, y = [], bottom
    for p, base in sorted(zip(probs, "ACGT")):
        h = height * p * ic / 2
        if h >= 0.5:
            out.append(_letter(base, x, y, cw, h))
            y -= h
    return out


def strand_rows(hit):
    """A hit's probability rows as they sit on the + strand (a - strand motif is reverse-complemented)."""
    return hit["probs"] if hit["strand"] == "+" else [row[::-1] for row in hit["probs"][::-1]]


def motif_logos(hits, seq, w, ref, alt, width=640, row=34):
    """The motifs a SNP changes, over the stretch of its window they cover: one row each (the TF on the left; its
    logo on the + strand; the two alleles' scores against the match cut-off on the right), then the reference
    sequence, with the SNP's column outlined and its alt allele under it. Returns (svg body, panel width, height,
    x of the SNP column's centre) drawn from 0,0; hits: snpscore.motif.hits()."""
    lo = min([h["start"] for h in hits] + [w - 6])
    hi = max([h["start"] + len(h["probs"]) for h in hits] + [w + 7])
    left, right, n = 64, 132, hi - lo
    cw = max(4.0, min(12.0, (width - left - right) / n))
    body, y = [], 0
    for h in hits:
        x0 = left + (h["start"] - lo) * cw
        for i, probs in enumerate(strand_rows(h)):
            body += logo_column(x0 + i * cw, y + row - 2, cw, row - 4, probs)
        other = alt if h["allele"] == ref else ref
        tip = (f"{h['tf']} ({h['id']}, {h['strand']} strand): {h['allele']} matches ({max(h['ref_score'], h['alt_score']):.1f} bits), "
               f"{other} does not ({min(h['ref_score'], h['alt_score']):.1f}); a match needs {h['cut']:.1f} bits (p < 1e-5)")
        tx = left + n * cw + 8
        body.append(f'<g><title>{escape(tip)}</title><rect x="0" y="{y}" width="{left + n * cw + right:.1f}" height="{row}" fill="{G[50]}" fill-opacity="0.01"/>'
                    + _t(left - 6, y + row / 2, h["tf"], 10, G[900], "end", "600")
                    + _t(left - 6, y + row / 2 + 11, f"{h['strand']} strand", 9, G[700], "end")
                    + _t(tx, y + row / 2, f"{ref} {h['ref_score']:.1f} · {alt} {h['alt_score']:.1f} bits", 9.5, G[900])
                    + _t(tx, y + row / 2 + 11, f"a match needs {h['cut']:.1f}", 9, G[700])
                    + "</g>")
        y += row
    for i, b in enumerate(seq[lo:hi]):  # the reference sequence, + strand
        body.append(_t(left + (i + 0.5) * cw, y + 10, b, 9, G[700] if lo + i != w else G[900], "middle", "600" if lo + i == w else None))
    sx = left + (w - lo) * cw
    body.insert(0, f'<rect x="{sx:.1f}" y="0" width="{cw:.1f}" height="{y + 22}" fill="{palette.MOTIF}" fill-opacity="0.12" '
                   f'stroke="{palette.MOTIF}" stroke-width="1"/>')
    body.append(_t(sx + cw / 2, y + 21, alt, 9, palette.MOTIF, "middle", "700") + _t(left - 6, y + 10, "+ strand", 9, G[700], "end")
                + _t(left - 6, y + 21, "alt", 9, G[700], "end"))
    return "".join(body), left + n * cw + right, y + 24, sx + cw / 2


def mini_browser(data, pos, snps=(), gene_url=None, synthetic=False, width=640, tiles=None):
    """The card's mini locus browser: the locus browser's lanes in one SVG: the list's SNPs (unnamed; tier colour,
    height = score, faded when not in the selection), genes, public variants (height = MAF), GERP constrained elements
    and the robust ATAC peaks (coloured by their strongest state; n/21 under each: the conditions with the peak). Lane
    names explain themselves on hover, a peak shows its state; variants and GERP show nothing. No ruler: the window's
    ends are marked beside the SNP's label. The SNP is a line through the lanes and its own peak is outlined; `tiles`
    (chromatin_grid without a legend) hang under the SNP in a wedge from it: that peak per condition. data: locus.lanes(); snps:
    locus.user_snps(), with `out` for SNPs not selected."""
    ax = Axis(data["start"], data["end"], 4, width - 4)
    body, y = [], 14

    def lane(name, tip):
        body.append(_t(ax.x0, y + 8, name, 9.5, G[900], weight="600").replace("</text>", f"<title>{escape(tip)}</title></text>"))
        return y + 12

    if snps:
        best = max([p.get("tier_score") or 0 for p in snps] + [1])
        for p in sorted(snps, key=lambda p: -(p.get("tier") or 4)):  # best tiers on top
            x, h = ax.x(p["pos"] - 0.5), 6 + 20 * (p.get("tier_score") or 0) / best
            fill, fade = palette.TIERS.get(p.get("tier") or 4, palette.TIERS[4])[0], ' opacity="0.3"' if p.get("out") else ""
            dot = (f'<g{fade}><line x1="{x:.1f}" x2="{x:.1f}" y1="{y + 26}" y2="{y + 26 - h:.1f}" '
                   f'stroke="{G[500]}"/><circle cx="{x:.1f}" cy="{y + 26 - h:.1f}" r="3.5" fill="{fill}" stroke="{G[900]}" stroke-width="0.6">'
                   f'<title>{escape(p["title"])}{" · not in the selection" if p.get("out") else ""}</title></circle></g>')
            body.append(f'<a href="{escape(p["url"])}">{dot}</a>' if p.get("url") else dot)
        y += 30
    y = lane("Genes", "Ensembl 116 gene models")
    y = _genes(body, ax, data.get("genes", []), y, gene_url, 3, lambda *a, **k: None)
    y = lane("Public variants", "504-fish public panel; tick height = MAF")
    body.append(f'<line x1="{ax.x0}" x2="{ax.x1}" y1="{y + 16}" y2="{y + 16}" stroke="{G[300]}"/>')
    for v in data.get("variants", []):
        x = ax.x(v["pos"] - 0.5)
        body.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{y + 16}" y2="{y + 14 - 13 * min(0.5, v.get("maf") or 0) / 0.5:.1f}" stroke="{G[700]}"/>')
    y += 22
    y = lane("GERP", "GERP constrained elements (65 fish); darker = higher score")
    top = max([g.get("score") or 0 for g in data.get("gerp", [])] + [1])
    for g in data.get("gerp", []):
        x, w = ax.span(g["start"], g["end"])
        body.append(f'<rect x="{x:.1f}" y="{y}" width="{w:.1f}" height="10" fill="{G[700]}" fill-opacity="{0.35 + 0.65 * (g.get("score") or 0) / top:.2f}"/>')
    if not data.get("gerp"):
        body.append(_t(ax.x0, y + 9, "none here", 9, G[700]))
    y += 16
    y = lane("Regulatory elements", "AQUA-FAANG robust ATAC peaks, coloured by their strongest state")
    for p in data.get("peaks", []):
        best, mine = strongest([v for v in p["states"].values() if v]), p["start"] < pos <= p["end"]
        x0, x1 = ax.x(p["start"]), ax.x(p["end"])
        body.append(f'<rect x="{x0:.1f}" y="{y}" width="{max(2, x1 - x0):.1f}" height="12" fill="{palette.state(best)[0]}" stroke="{G[900]}" '
                    f'stroke-width="{2 if mine else 0.5}"><title>{best.replace("_", " ")}</title></rect>')
    if not data.get("peaks"):
        body.append(_t(ax.x0, y + 9, "none here", 9, G[700]))
    y += 12
    x = ax.x(pos - 0.5)  # the SNP through every lane, labelled on top between the window's ends
    left, right = (pos - 1 - data["start"]) / 1000, (data["end"] - pos) / 1000
    body.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="12" y2="{y}" stroke="{G[900]}" stroke-opacity="0.45"/>' + _t(x, 9, "SNP", 9.5, G[900], "middle", "600")
                + _t(ax.x0, 9, f"−{left:g} kb", 9, G[700]) + _t(ax.x1, 9, f"+{right:g} kb", 9, G[700], "end"))
    if tiles:  # the SNP's peak per condition: the tiles centred under the SNP (their labels to the left), in a wedge
        gw, gh = (float(v) for v in re.search(r' width="([\d.]+)" height="([\d.]+)"', tiles).groups())  # from it to them
        t0, t1 = GRID["left"], GRID["left"] + 4 * (GRID["cw"] + GRID["gap"]) - GRID["gap"]  # the tiles' span in the grid
        gx, gy = min(max(x - (t0 + t1) / 2, 0), width - gw), y + 8
        body.insert(0, f'<path d="M{x:.1f} {y:.1f} L{gx + t1:.1f} {gy + GRID["top"]:.1f} L{gx + t0:.1f} {gy + GRID["top"]:.1f}Z" '
                       f'fill="{G[100]}"/>')  # under everything else
        body.append(tiles.replace("<svg ", f'<svg x="{gx:.1f}" y="{gy:.1f}" ', 1))
        y = gy + gh
    desc = (f"Chromosome {data['chrom']}: {data['start'] + 1:,}-{data['end']:,} around the SNP at {pos:,}: genes, public variants, "
            f"GERP constrained elements and {len(data.get('peaks', []))} robust ATAC peaks" + (", with the SNP's peak per condition." if tiles else "."))
    return figures.svg(width, y + 2, "Mini locus browser", desc, "".join(body), synthetic)


def expression_bars(values, synthetic=False):
    """Mean expression (counts per million) of the gene per tissue: {tissue: cpm}."""
    items = [(t, v) for t, v in values.items() if v is not None]
    top = max([v for _, v in items] + [1e-9])
    parts, y = [], 4
    for tissue, v in items:
        w = 220 * v / top
        parts.append(_t(70, y + 11, tissue, 10, G[900], "end")
                     + f'<rect x="76" y="{y + 2}" width="{max(0.5, w):.1f}" height="11" fill="{palette.TISSUES.get(tissue, G[500])}"/>'
                     + _t(80 + w, y + 11, f"{v:,.1f}", 9.5, G[700]))
        y += 16
    desc = ", ".join(f"{t} {v:.1f} CPM" for t, v in items)
    return figures.svg(360, y + 4, "Expression per tissue (mean CPM)", desc, "".join(parts), synthetic)


# ---- GWAS: the regional association lane (P7.3, AGENT gwas) ----

def _shape(kind, x, y, r, fill, ring, tip):
    """A point of the association lane: 'lead' diamond, 'coding' triangle, else a circle; ring = credible-set outline."""
    edge = f'stroke="{G[900]}" stroke-width="{1.8 if ring else 0.6}"'
    if kind == "lead":
        d = f"M{x:.1f} {y - r - 2:.1f} l{r + 2} {r + 2} l{-r - 2} {r + 2} l{-r - 2} {-r - 2}z"
    elif kind == "coding":
        d = f"M{x:.1f} {y - r - 1:.1f} l{r + 1} {2 * r + 1} l{-2 * r - 2} 0z"
    else:
        return f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r + (0.6 if ring else 0)}" fill="{fill}" {edge}><title>{escape(tip)}</title></circle>'
    return f'<path d="{d}" fill="{fill}" {edge}><title>{escape(tip)}</title></path>'


def gwas_lane(body, ax, gwas, y, legend=None, height=120):
    """-log10 p against position on the locus axis: points coloured by tier, a diamond for the lead SNP, triangles for
    CDS/splice SNPs, a dark ring for credible-set members, the significance line. gwas: {points: [{pos, neglog10p,
    tier, kind ('lead' | 'coding' | ''), cs, title, url}], significant (-log10 p of the line), note}. Appends to
    body; returns the new y."""
    points = gwas.get("points", [])
    sig = gwas.get("significant", -math.log10(5e-8))
    top = max([p["neglog10p"] for p in points] + [sig + 1])
    k = 10 ** math.floor(math.log10(top / 4)) if top > 4 else 1
    step = next(m * k for m in (1, 2, 5, 10) if top / (m * k) <= 5)
    top = math.ceil(top / step) * step
    y0, h = y + 6, height - 24
    sy = lambda v: y0 + h - h * min(v, top) / top
    body.append(_t(ax.x0 - 26, y0 + 10, "Association", 10.5, G[900], "end", "600")  # left of the tick labels
                + _t(ax.x0 - 26, y0 + 21, "-log10 p", 9, G[700], "end"))
    body.append(f'<line x1="{ax.x0}" x2="{ax.x1}" y1="{y0 + h}" y2="{y0 + h}" stroke="{G[500]}"/>')
    for v in range(0, int(top) + 1, int(step) or 1):
        body.append(f'<line x1="{ax.x0 - 4}" x2="{ax.x0}" y1="{sy(v):.1f}" y2="{sy(v):.1f}" stroke="{G[500]}"/>'
                    + _t(ax.x0 - 6, sy(v) + 3, v, 9, G[700], "end"))
    body.append(f'<line x1="{ax.x0}" x2="{ax.x1}" y1="{sy(sig):.1f}" y2="{sy(sig):.1f}" stroke="{palette.STATUS["fail"][0]}" '
                f'stroke-dasharray="5 3"><title>significance line, p = {10 ** -sig:.0e}</title></line>'
                + _t(ax.x1 - 2, sy(sig) - 3, f"p = {10 ** -sig:.0e}", 9, palette.STATUS["fail"][0], "end"))
    order = sorted(points, key=lambda p: ((p.get("kind") == "lead"), bool(p.get("cs")), -(p.get("tier") or 4), p["neglog10p"]))
    for p in order:  # leads, credible-set members and better tiers on top
        fill = palette.TIERS.get(p.get("tier") or 4, palette.TIERS[4])[0]
        mark = _shape(p.get("kind"), ax.x(p["pos"] - 0.5), sy(p["neglog10p"]), 3.5, fill, p.get("cs"), p.get("title") or "")
        body.append(f'<a href="{escape(p["url"])}">{mark}</a>' if p.get("url") else mark)
    if legend is not None and points:
        legend["Association"] = [(_swatch(palette.TIERS[t][0], round_=True), f"tier {t}") for t in sorted({p.get("tier") or 4 for p in points})] + [
            (f'<path d="M6 0 l5 5 l-5 5 l-5 -5z" fill="{G[300]}" stroke="{G[900]}" stroke-width="0.6"/>', "lead SNP"),
            (f'<path d="M6 0 l5 10 l-10 0z" fill="{G[300]}" stroke="{G[900]}" stroke-width="0.6"/>', "CDS or splice"),
            (f'<circle cx="6" cy="5" r="4.5" fill="{G[300]}" stroke="{G[900]}" stroke-width="1.8"/>', "credible set (95%)")] + (
            [("", gwas["note"])] if gwas.get("note") else [])
    return y + height


def gwas_figure(gwas, chrom, start, end, title="", width=WIDTH, gutter=GUTTER, height=120):
    """The association lane alone (`height` px), on the locus browser's x axis, to stack above a locus() figure:
    (body, height)."""
    ax = Axis(start, end, gutter, width - RIGHT)
    body, legend, y = [], {}, 4
    if title:
        body.append(_t(8, y + 13, title, 13.5, weight="600"))
        y += 22

    y = gwas_lane(body, ax, gwas, y, legend, height)
    for t in ax.ticks(9):
        body.append(_t(ax.x(t), y + 2, f"{t:,}", 9, G[700], "middle"))
    y = _legend(body, legend, y + 8, width, gutter)
    return "".join(body), y + 4
