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

from html import escape

from . import palette

FONT = "system-ui, -apple-system, 'Segoe UI', Roboto, Arial, sans-serif"
TIER_NAMES = {1: "tier 1", 2: "tier 2", 3: "tier 3", 4: "tier 4 (no evidence)"}
STAGE_LABELS = {"LateBlastulation": "Blastula", "MidGastrulation": "Gastrula", "EarlySomitogenesis": "E somit.",  # the one
                "MidSomitogenesis": "M somit.", "LateSomitogenesis": "L somit."}  # short name of each embryo stage
IDEOGRAM_TIER4 = palette.GREY[300]  # #F0F0F0 would vanish on the white chromosome


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


def tier_legend(x, y, tier4=None):
    return _legend([(tier4 if t == 4 and tier4 else _tier_fill(t)[0], TIER_NAMES[t]) for t in (1, 2, 3, 4)], x, y)


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


def summary(head, rows, title, desc="", synthetic=False):
    """The Overview's summary: a headline of key numbers, then one stacked bar per way of grouping the SNPs, each with
    its legend (count and share) underneath. head: [(number, text, href)]; rows: [{label, parts: [(name, n, fill,
    href)]}]. Parts and legend entries with an href link to the table filtered to them."""
    width, left, bar_w = 960, 112, 840
    out, x = [], 0
    for number, text, href in head:
        out.append(_a(href, f'<text x="{x:.0f}" y="24"><tspan font-size="24" font-weight="700">{escape(number)}</tspan>'
                            f'<tspan dx="6" font-size="13" fill="{palette.GREY[700]}">{escape(text)}</tspan></text>'))
        x += 14 * len(number) + 6.3 * len(text) + 40
    y = 44
    for r in rows:
        total = sum(n for _, n, _, _ in r["parts"]) or 1
        out.append(_text(left - 10, y + 15, r["label"], "end", font_weight=600))
        x = left
        for name, n, fill, href in r["parts"]:
            w = bar_w * n / total
            out.append(_rect(x, y, w, 22, fill, f"{r['label']}: {name}, {n:,} SNP{'' if n == 1 else 's'} ({share_label(n, total)})", href,
                             f' stroke="{palette.WHITE}"'))
            if w > 7.5 * len(f"{n:,}") + 8:
                out.append(_text(x + w / 2, y + 15.5, f"{n:,}", "middle", fill=palette.text_on(fill), font_weight=600,
                                 pointer_events="none"))
            x += w
        lx, ly = left, y + 30
        for name, n, fill, href in r["parts"]:
            label = f"{name}: {n:,} ({share_label(n, total)})"
            w = 24 + 6.2 * len(label)
            if lx > left and lx + w > left + bar_w:
                lx, ly = left, ly + 17
            out.append(_a(href, f'<rect x="{lx:.0f}" y="{ly}" width="11" height="11" fill="{fill}" stroke="{palette.GREY[500]}"/>'
                                + _text(lx + 16, ly + 9.5, label, font_size=11)))
            lx += w
        y = ly + 28
    return svg(width, y - 12, title, desc, "".join(out), synthetic)


def ideogram(chroms, bins, chrom_tiers, title, desc="", synthetic=False, link=None, chip=None, chip_label="chip"):
    """Chromosomes to scale with 1 Mb bins coloured by the best tier in them (grey: tier 4 only), and on the right
    each chromosome's SNPs split by tier. chroms: [(chrom, length)]; bins: [[chrom, bin, n1, n2, n3, n4]];
    chrom_tiers: {chrom: {tier: n}}; link(chrom, start, end) -> href for a bin (end = None: whole chromosome);
    chip: [[chrom, mb, n]] markers of a reference chip per 1 Mb bin, drawn as ticks under each chromosome."""
    left, track, gap, stack, right = 34, 500, 14, 110, 64
    width, top, row = left + track + gap + stack + right, 26, 15
    longest = max([size for _, size in chroms] + [1])
    scale = track / longest
    y_of = {c: top + i * row for i, (c, _) in enumerate(chroms)}
    parts = [_text(left - 8, 12, "Mb", "end", fill=palette.GREY[700], font_size=10)]
    for mb in range(0, int(longest / 1e6) + 1, 20):
        x = left + mb * 1e6 * scale
        parts.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="16" y2="{top + len(chroms) * row - 4}" stroke="{palette.GREY[200]}"/>'
                     + _text(x, 12, mb, "middle", fill=palette.GREY[700], font_size=10))
    for chrom, size in chroms:
        y = y_of[chrom]
        parts.append(_a(link and link(chrom, None, None), _text(left - 6, y + 9, chrom, "end", font_size=11))
                     + f'<rect x="{left}" y="{y + 1}" width="{size * scale:.1f}" height="9" rx="2" fill="{palette.WHITE}" '
                       f'stroke="{palette.GREY[300]}"/>')
        counts = {int(t): n for t, n in (chrom_tiers.get(chrom) or {}).items()}
        total, x = sum(counts.values()), left + track + gap
        for t in (1, 2, 3, 4):
            w = stack * counts.get(t, 0) / (total or 1)
            if w:
                parts.append(_rect(x, y + 1, w, 9, _tier_fill(t)[0], f"Chromosome {chrom}: {counts[t]:,} SNPs in {TIER_NAMES[t]}",
                                   extra=f' stroke="{palette.GREY[500]}" stroke-width="0.3"' if t == 4 else ""))
                x += w
        parts.append(_text(width - 4, y + 9, f"{total:,}", "end", font_size=11))
    w = max(1e6 * scale, 1.0)
    for chrom, b, *n in bins:
        if chrom not in y_of:
            continue
        best = next((t for t in (1, 2, 3, 4) if n[t - 1]), 4)
        fill = IDEOGRAM_TIER4 if best == 4 else _tier_fill(best)[0]
        tip = (f"{chrom}:{b}-{b + 1} Mb: {sum(n):,} SNPs (" + ", ".join(f"tier {t}: {k:,}" for t, k in zip((1, 2, 3, 4), n) if k) + ")")
        parts.append(_rect(left + b * 1e6 * scale, y_of[chrom] + 1, w, 9, fill, tip,
                           link and link(chrom, int(b * 1e6), int((b + 1) * 1e6))))
    for chrom, mb, n in chip or ():
        if chrom in y_of:
            parts.append(_rect(left + mb * 1e6 * scale, y_of[chrom] + 11, w, 3, palette.GREY[700],
                               f"{chrom}:{mb}-{mb + 1} Mb: {n:,} {chip_label} markers"))
    y = top + len(chroms) * row + 6
    parts.append(tier_legend(left, y, IDEOGRAM_TIER4)
                 + _text(width - 4, y + 9.5, "SNPs by tier", "end", font_size=11, fill=palette.GREY[700]))
    if chip:
        y += 18
        parts.append(f'<rect x="{left}" y="{y + 4}" width="11" height="3" fill="{palette.GREY[700]}"/>'
                     + _text(left + 16, y + 9.5, f"{chip_label}: 1 Mb bins with markers", font_size=11))
    return svg(width, y + 18, title, desc, "".join(parts), synthetic)


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
