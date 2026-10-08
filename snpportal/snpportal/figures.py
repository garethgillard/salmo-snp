"""Figures: pure functions from plain data to SVG strings, for pages and downloads.

Conventions every figure follows:
- svg() wraps the body: role="img" with <title> and <desc>; the provenance caption goes in <desc> for downloads.
- Colours are literal hex values from palette.py, never var(--...), so saved SVG and PNG files keep their colours.
- Every label goes through html.escape. Tooltips are SVG <title> elements.
- Marks link to the results table when given a link (an href string, or a function returning one); downloads
  leave links out.
- Figures built from synthetic data carry a watermark that can't be switched off.
- No Django imports, so this module can move into snpscore later.
"""
from __future__ import annotations

import math
from html import escape

from . import palette

FONT = "system-ui, -apple-system, 'Segoe UI', Roboto, Arial, sans-serif"
TIER_NAMES = {1: "tier 1", 2: "tier 2", 3: "tier 3", 4: "tier 4 (no evidence)"}
STAGE_LABELS = {"LateBlastulation": "Blastula", "MidGastrulation": "Gastrula", "EarlySomitogenesis": "E somit.",  # the one
                "MidSomitogenesis": "M somit.", "LateSomitogenesis": "L somit."}  # short name of each embryo stage
IDEOGRAM_TIER4 = palette.GREY[300]  # #F0F0F0 would vanish on the white chromosome
IDEOGRAM_OTHER = palette.GREY[300]  # bins whose SNPs are all in tier 3-4


def svg(width, height, title, desc, body, synthetic=False):
    """A complete standalone SVG document. A synthetic figure gets a faint SYNTHETIC watermark under its marks (so it
    never hides a label) and, below the figure, a line saying so that nothing covers."""
    mark = ""
    if synthetic:
        mark = (f'<text x="{width / 2:.0f}" y="{height / 2:.0f}" text-anchor="middle" dominant-baseline="middle" '
                f'font-size="{min(48, height // 2)}" font-weight="700" fill="{palette.SYNTHETIC[0]}" opacity="0.18" '
                f'transform="rotate(-12 {width / 2:.0f} {height / 2:.0f})" pointer-events="none">SYNTHETIC</text>')
        body += _text(4, height + 11, "SYNTHETIC test data: not real results", font_size=10, font_weight=600, fill=palette.SYNTHETIC[0])
        height += 16
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
            f'role="img" font-family="{escape(FONT)}" font-size="12" fill="{palette.GREY[900]}">'
            f'<title>{escape(title)}</title><desc>{escape(desc)}</desc>{mark}{body}</svg>')


def share_label(n, total):
    """n of total as a percentage for labels: '<1%' rather than '0%' for a few, so a small count never reads as none."""
    x = 100 * n / total if total else 0
    return "0%" if not n else "<1%" if x < 1 else f"{x:.0f}%"


def _a(href, inner):
    return f'<a href="{escape(href)}">{inner}</a>' if href else inner


def _rect(x, y, w, h, fill, tip=None, href=None, extra=""):
    tip = f"<title>{escape(tip)}</title>" if tip else ""
    return _a(href, f'<rect x="{x:.1f}" y="{y:.1f}" width="{max(w, 0):.1f}" height="{h:.1f}" fill="{fill}"{extra}>{tip}</rect>')


def _text(x, y, text, anchor="start", **attrs):
    extra = "".join(f' {k.replace("_", "-")}="{v}"' for k, v in attrs.items())
    return f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}"{extra}>{escape(str(text))}</text>'


def _legend(items, x, y):
    """Swatches with labels in one row: items [(fill, label)]."""
    out = []
    for fill, label in items:
        out.append(f'<rect x="{x}" y="{y}" width="11" height="11" fill="{fill}" stroke="{palette.GREY[500]}"/>'
                   + _text(x + 16, y + 9.5, label, font_size=11))
        x += 30 + 6.2 * len(label)
    return "".join(out)


def _tier_fill(tier):
    return palette.TIERS.get(int(tier), palette.TIERS[4])


def mix(a, b, t):
    """The colour t (0-1) of the way from palette colour a to b, for sequential scales."""
    t = min(max(t, 0.0), 1.0)
    return "#" + "".join(f"{round(int(a[i:i + 2], 16) * (1 - t) + int(b[i:i + 2], 16) * t):02X}" for i in (1, 3, 5))


def bar(parts, title, desc="", synthetic=False, marks=None):
    """One horizontal bar split into parts [(label, n, fill, href)], with a legend of counts and shares in two columns;
    marks: short text printed inside each wide enough part (e.g. the tier number). Text has class sp-lg, which
    portal.css enlarges on phones, where the 640-wide figure is drawn at about half size."""
    total = sum(n for _, n, _, _ in parts) or 1
    width, x, body = 640, 0.0, []
    for i, (name, n, fill, href) in enumerate(parts):
        w = width * n / total
        label = f"{name}: {n:,} ({share_label(n, total)})"
        body.append(_rect(x, 0, w, 28, fill, label, href, f' stroke="{palette.WHITE}"'))
        if marks and w > 24:
            body.append(_text(x + w / 2, 18.5, marks[i], "middle", fill=palette.text_on(fill), font_weight=600,
                              pointer_events="none", **{"class": "sp-lg"}))
        lx, ly = (i % 2) * 320, 40 + (i // 2) * 24
        body.append(f'<rect x="{lx}" y="{ly}" width="12" height="12" fill="{fill}" stroke="{palette.GREY[500]}"/>'
                    + _text(lx + 18, ly + 10.5, label, **{"class": "sp-lg"}))
        x += w
    return svg(width, 40 + (len(parts) + 1) // 2 * 24, title, desc, "".join(body), synthetic)


def summary(head, groups, title, desc="", synthetic=False, width=580):
    """The Overview's summary, drawn to sit beside the ideogram: key numbers, then one stacked bar per way of grouping
    the SNPs, with its title and note above and a two-column legend of counts and shares below. head: [(number,
    label, note, href)]; groups: [{title, note, parts: [(name, n, fill, href)], background: [(name, share, fill)] or
    None}]. A background is a thin bar under the SNPs' bar: the same split for public sites. Parts with an href link
    to the table filtered to them."""
    out, col = [], width / max(len(head), 1)
    for i, (number, label, note, href) in enumerate(head):
        x = i * col
        out.append(_a(href, _text(x, 28, number, font_size=28, font_weight=700) + _text(x, 46, label, font_size=12.5)))
        if note:
            out.append(_text(x, 62, note, font_size=11, fill=palette.GREY[700]))
    y = 88
    for g in groups:
        total = sum(n for _, n, _, _ in g["parts"]) or 1
        out.append(_text(0, y, g["title"], font_size=12.5, font_weight=600)
                   + _text(width, y, g["note"], "end", font_size=11, fill=palette.GREY[700]))
        x, y = 0.0, y + 7
        for name, n, fill, href in g["parts"]:
            w = width * n / total
            out.append(_rect(x, y, w, 26, fill, f"{g['title']}: {name}, {n:,} SNP{'' if n == 1 else 's'} ({share_label(n, total)})",
                             href, f' stroke="{palette.WHITE}"'))
            if w > 7.5 * len(f"{n:,}") + 8:
                out.append(_text(x + w / 2, y + 17.5, f"{n:,}", "middle", fill=palette.text_on(fill), font_weight=600,
                                 pointer_events="none"))
            x += w
        y += 26
        if g.get("background"):
            x = 0.0
            for name, share, fill in g["background"]:
                out.append(_rect(x, y + 3, width * share, 6, fill, f"Public sites: {name}, {share_label(share, 1)}",
                                 extra=f' stroke="{palette.WHITE}" stroke-width="0.5"'))
                x += width * share
            y += 9
        for i, (name, n, fill, href) in enumerate(g["parts"]):
            lx, ly = (i % 2) * width / 2, y + 10 + (i // 2) * 16
            out.append(_a(href, f'<rect x="{lx:.0f}" y="{ly}" width="11" height="11" fill="{fill}" stroke="{palette.GREY[500]}"/>'
                                + _text(lx + 16, ly + 9.5, f"{name}: {n:,} ({share_label(n, total)})", font_size=11)))
        y += 10 + (len(g["parts"]) + 1) // 2 * 16 + 24
    return svg(width, y - 18, title, desc, "".join(out), synthetic)


def ideogram(chroms, bins, chrom_tiers, title, desc="", synthetic=False, link=None, chip=None, chip_label="chip", width=580):
    """Chromosomes to scale, each 1 Mb bin that holds SNPs shaded: grey when none is in tier 1-2, else blue, darker
    with more tier 1-2 SNPs (a log scale up to the busiest bin); on the right each chromosome's SNP count and its tier
    1-2 SNPs as a bar. chroms: [(chrom, length)]; bins: [[chrom, bin, n1, n2, n3, n4]]; chrom_tiers: {chrom: {tier: n}};
    link(chrom, start, end, tier) -> href (start None: the whole chromosome); chip: [[chrom, mb, n]] markers of a
    reference chip per 1 Mb bin, drawn as ticks under each chromosome."""
    left, gap, count_w, bar_w, number_w = 24, 10, 44, 64, 42
    track = width - left - gap - count_w - 10 - bar_w - number_w
    top, row = 34, 16
    longest = max([size for _, size in chroms] + [1])
    scale = track / longest
    y_of = {c: top + i * row for i, (c, _) in enumerate(chroms)}
    top12 = {c: sum(int((chrom_tiers.get(c) or {}).get(t, 0)) for t in ("1", "2")) for c, _ in chroms}
    most_bin = max([n[0] + n[1] for _, _, *n in bins] + [1])
    most_chrom = max(list(top12.values()) + [1])
    cx, bx = left + track + gap + count_w, left + track + gap + count_w + 10

    def shade(k):  # tier 1-2 SNPs in a bin -> a blue from light (1) to the darkest tier blue (the busiest bin)
        return mix(palette.TIERS[3][0], palette.TIERS[1][0], 0.45 + 0.55 * math.log1p(k) / math.log1p(most_bin))

    parts = [_text(left - 6, 12, "Mb", "end", fill=palette.GREY[700], font_size=10),
             _text(cx, 26, "SNPs", "end", fill=palette.GREY[700], font_size=10.5),
             _text(bx, 26, "tier 1–2", fill=palette.GREY[700], font_size=10.5)]
    for mb in range(0, int(longest / 1e6) + 1, 20):
        x = left + mb * 1e6 * scale
        parts.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="16" y2="{top + len(chroms) * row - 4}" stroke="{palette.GREY[200]}"/>'
                     + _text(x, 12, mb, "middle", fill=palette.GREY[700], font_size=10))
    for chrom, size in chroms:
        y = y_of[chrom]
        total = sum(int(n) for n in (chrom_tiers.get(chrom) or {}).values())
        parts.append(_a(link and link(chrom, None, None, None), _text(left - 6, y + 9.5, chrom, "end", font_size=11))
                     + f'<rect x="{left}" y="{y + 1}" width="{size * scale:.1f}" height="10" rx="3" fill="{palette.WHITE}" '
                       f'stroke="{palette.GREY[300]}"/>'
                     + _text(cx, y + 9.5, f"{total:,}", "end", font_size=11, fill=palette.GREY[700 if total else 500]))
        k = top12[chrom]
        if k:
            parts.append(_rect(bx, y + 2, max(1.0, bar_w * k / most_chrom), 8, palette.TIERS[2][0],
                               f"Chromosome {chrom}: {k:,} of {total:,} SNPs in tier 1–2", link and link(chrom, None, None, "1-2")))
        parts.append(_text(bx + bar_w + number_w, y + 9.5, f"{k:,}", "end", font_size=11, fill=palette.GREY[900 if k else 500]))
    w = max(1e6 * scale, 2.5)  # a lone SNP's bin stays visible
    for chrom, b, *n in sorted(bins, key=lambda x: x[2] + x[3]):  # blue bins over grey ones
        if chrom not in y_of:
            continue
        k = n[0] + n[1]
        tip = (f"{chrom}:{b}-{b + 1} Mb: {sum(n):,} SNPs (" + ", ".join(f"tier {t}: {m:,}" for t, m in zip((1, 2, 3, 4), n) if m) + ")")
        parts.append(_rect(left + b * 1e6 * scale, y_of[chrom] + 1, w, 10, shade(k) if k else IDEOGRAM_OTHER, tip,
                           link and link(chrom, int(b * 1e6), int((b + 1) * 1e6), None)))
    for chrom, mb, n in chip or ():
        if chrom in y_of:
            parts.append(_rect(left + mb * 1e6 * scale, y_of[chrom] + 12, w, 3, palette.GREY[700],
                               f"{chrom}:{mb}-{mb + 1} Mb: {n:,} {chip_label} markers"))
    y = top + len(chroms) * row + 8
    steps = sorted({1, most_bin} | ({round(math.sqrt(most_bin))} if most_bin > 3 else set()))
    legend = [f'<rect x="{left}" y="{y}" width="11" height="11" fill="{IDEOGRAM_OTHER}" stroke="{palette.GREY[500]}"/>'
              + _text(left + 16, y + 9.5, "SNPs, none in tier 1–2", font_size=11)]
    x = left + 170
    legend.append(_text(x, y + 9.5, "tier 1–2 SNPs per Mb:", font_size=11))
    x += 124
    for s in steps:
        legend.append(f'<rect x="{x}" y="{y}" width="11" height="11" fill="{shade(s)}"/>' + _text(x + 15, y + 9.5, f"{s:,}", font_size=11))
        x += 24 + 7 * len(f"{s:,}")
    parts += legend
    if chip:
        y += 18
        parts.append(f'<rect x="{left}" y="{y + 4}" width="11" height="3" fill="{palette.GREY[700]}"/>'
                     + _text(left + 16, y + 9.5, f"{chip_label}: 1 Mb bins with markers", font_size=11))
    return svg(width, y + 16, title, desc, "".join(parts), synthetic)


def heatmap(rows, title, desc="", synthetic=False, link=None, scale_max=None):
    """Share of SNPs active per condition, one row per tissue (plus the embryo stages), with the fold over the
    background printed when known. rows: [(group, colour, [(label, condition, share, fold or None, in preset)])];
    link(condition) -> href. Darker = higher share; outlined = one of the trait's conditions."""
    left, cw, ch, pad, top = 76, 66, 40, 5, 6
    ncol = max([len(cells) for _, _, cells in rows] + [1])
    width = left + ncol * (cw + pad)
    top_share = scale_max or max([share for _, _, cells in rows for _, _, share, _, _ in cells] + [0.01])
    parts = []
    for i, (group, colour, cells) in enumerate(rows):
        y = top + i * (ch + pad)
        parts.append(f'<circle cx="8" cy="{y + ch / 2:.1f}" r="5" fill="{colour}"/>' + _text(18, y + ch / 2 + 4, group))
        for j, (label, condition, share, fold, chosen) in enumerate(cells):
            x = left + j * (cw + pad)
            fill = mix(palette.GREY[50], palette.TIERS[1][0], share / top_share)
            ink = palette.text_on(fill)
            tip = f"{group} {label}: {100 * share:.1f}% of SNPs active" + (f", {fold:.1f}× the public background" if fold else "") \
                + (" (a condition of the trait)" if chosen else "")
            stroke = (f' stroke="{palette.GREY[900]}" stroke-width="2.5"' if chosen else f' stroke="{palette.GREY[200]}"')
            cell = _rect(x, y, cw, ch, fill, tip, extra=stroke) + "".join([
                _text(x + cw / 2, y + 11, label, "middle", fill=ink, font_size=9.5, pointer_events="none"),
                _text(x + cw / 2, y + 24, f"{100 * share:.1f}%", "middle", fill=ink, font_weight=600, pointer_events="none"),
                _text(x + cw / 2, y + 35, f"{fold:.1f}×" if fold else "", "middle", fill=ink, font_size=9.5, pointer_events="none")])
            parts.append(_a(link and link(condition), cell))
    y = top + len(rows) * (ch + pad) + 4
    steps = [i / 4 for i in range(5)]
    for k, t in enumerate(steps):
        parts.append(f'<rect x="{left + k * 22}" y="{y}" width="22" height="10" fill="{mix(palette.GREY[50], palette.TIERS[1][0], t)}"/>')
    parts.append(_text(left - 4, y + 9, "0%", "end", font_size=10) + _text(left + 5 * 22 + 4, y + 9, f"{100 * top_share:.1f}%", font_size=10)
                 + _text(left, y + 26, "Outlined: the trait's conditions. ×: fold over the public background.", font_size=10, fill=palette.GREY[700]))
    return svg(width, y + 32, title, desc, "".join(parts), synthetic)


def hbars(rows, title, desc="", synthetic=False, legend=None, unit="SNPs"):
    """Horizontal bars, optionally stacked, with an optional tick per row (e.g. the background's expected value).
    rows: [{label, segments: [(value, fill, tooltip, href)], tick: (value, tooltip) or None, note: text after the
    bar (default: the total), href: link for the label}]. legend: [(fill, label)]."""
    left = 14 + 6.6 * max([len(r["label"]) for r in rows] + [8])  # room for the longest label
    bar_w, right, row, top = 400, 90, 22, 4
    width = round(left + bar_w + right)
    top_value = max([sum(s[0] for s in r["segments"]) for r in rows] + [(r.get("tick") or (0,))[0] for r in rows] + [1])
    parts = []
    for i, r in enumerate(rows):
        y = top + i * row
        parts.append(_a(r.get("href"), _text(left - 8, y + 12, r["label"], "end")))
        x = left
        for value, fill, tip, href in r["segments"]:
            w = bar_w * value / top_value
            if w > 0:
                edge = f' stroke="{palette.GREY[500]}" stroke-width="0.4"' if fill in (palette.TIERS[4][0], palette.WHITE) else ""
                parts.append(_rect(x, y + 2, max(w, 0.8), 14, fill, tip, href, edge))
                x += w
        total = sum(s[0] for s in r["segments"])
        parts.append(_text(x + 5, y + 13, r.get("note", f"{total:,}"), font_size=11, fill=palette.GREY[700]))
        if r.get("tick"):
            value, tip = r["tick"]
            tx = left + bar_w * value / top_value
            parts.append(f'<line x1="{tx:.1f}" x2="{tx:.1f}" y1="{y}" y2="{y + 18}" stroke="{palette.GREY[900]}" stroke-width="2">'
                         f'<title>{escape(tip)}</title></line>')
    y = top + len(rows) * row + 6
    parts.append(f'<line x1="{left}" x2="{left}" y1="{top}" y2="{y - 6}" stroke="{palette.GREY[300]}"/>')
    if legend:
        parts.append(_legend(legend, left, y))
        y += 18
    return svg(width, y + 2, title, desc, "".join(parts), synthetic)


def histogram(bars, title, desc="", synthetic=False, axis=None):
    """Vertical bars: bars [(label, value, fill, tooltip, href, tick value or None)], with a gap before a bar
    labelled 'none'; a tick marks e.g. the count expected from a background. axis: the x-axis caption."""
    left, top, height, bw, gap = 54, 10, 140, 40, 6
    width = left + len(bars) * (bw + gap) + 30
    top_value = nice_ceiling(max([b[1] for b in bars] + [b[5] or 0 for b in bars] + [1]))
    parts = [f'<line x1="{left - 4}" x2="{width - 10}" y1="{top + height}" y2="{top + height}" stroke="{palette.GREY[500]}"/>']
    for v in (0, top_value // 2, top_value) if top_value >= 2 else (0, top_value):  # integer counts on a 1-2-5 grid
        y = top + height - height * v / top_value
        parts.append(f'<line x1="{left - 4}" x2="{left}" y1="{y:.1f}" y2="{y:.1f}" stroke="{palette.GREY[500]}"/>'
                     + _text(left - 8, y + 3.5, f"{v:,}", "end", font_size=10, fill=palette.GREY[700]))
    x = left
    for label, value, fill, tip, href, tick in bars:
        if label == "none":
            x += 14
        h = height * value / top_value
        parts.append(_rect(x, top + height - h, bw, max(h, 0.5), fill, tip, href)
                     + _text(x + bw / 2, top + height + 14, label, "middle", font_size=10))
        if tick is not None:
            ty = top + height - height * tick / top_value
            parts.append(f'<line x1="{x - 2:.1f}" x2="{x + bw + 2:.1f}" y1="{ty:.1f}" y2="{ty:.1f}" stroke="{palette.GREY[900]}" '
                         f'stroke-width="2" pointer-events="none"/>')
        x += bw + gap
    if axis:
        parts.append(_text(left, top + height + 32, axis, font_size=11, fill=palette.GREY[700]))
    return svg(width, top + height + 40, title, desc, "".join(parts), synthetic)


def nice_ceiling(x):
    """The smallest 1, 2 or 5 x 10^k (an int) at least x: axis maxima such as 10,000 instead of 8,117.64."""
    k = 1
    while True:
        for m in (1, 2, 5):
            if m * k >= x:
                return m * k
        k *= 10


def placeholder(width, height, title, message):
    """A labelled empty frame for figures that arrive in a later step."""
    body = (f'<rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" fill="{palette.GREY[50]}" '
            f'stroke="{palette.GREY[300]}" stroke-dasharray="4 3"/>'
            f'<text x="{width / 2:.0f}" y="{height / 2:.0f}" text-anchor="middle" fill="{palette.GREY[700]}">{escape(message)}</text>')
    return svg(width, height, title, message, body)
