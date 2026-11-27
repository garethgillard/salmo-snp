"""Template helpers: the palette as CSS, the current release, number formatting, versioned asset URLs."""
import os
import time

from django import template
from django.contrib.staticfiles import finders
from django.templatetags.static import static
from django.utils.html import escape
from django.utils.safestring import mark_safe

from .. import jobs, palette

register = template.Library()


@register.simple_tag
def asset(path):
    """A static file's URL with its modification time (?v=), so browsers fetch portal.css or portal.js again when they
    change instead of keeping a stale copy."""
    found = finders.find(path)
    return f"{static(path)}?v={int(os.path.getmtime(found))}" if found else static(path)


# The portal's icons: one line set on a 24-unit grid, stroke 2, round ends, drawn in the text colour (salmo-cells' set,
# whose shapes these reuse; the rest drawn to match). Icons name places (the nav) and label icon-only controls; actions
# are words. {% icon 'search' %} is decorative (aria-hidden); {% icon 'search' 'Search' %} names itself for screen readers.
ICONS = {
    "brand": '<path d="M12 17.5s-5.6-5.2-5.6-9.4a5.6 5.6 0 0 1 11.2 0c0 4.2-5.6 9.4-5.6 9.4z"/>'
             '<circle cx="12" cy="8.1" r="2" fill="currentColor"/><path d="M3.5 21h17"/>',  # a pin on a line: a SNP's place
    "score": '<path d="M4 6.5h16M4 12h11M4 17.5h6"/>',
    "panel": '<path d="M10 6.5h10M10 12h10M10 17.5h10"/><path d="M4 6.5l1.2 1.2L7.5 5.4M4 12l1.2 1.2 2.3-2.3M4 17.5l1.2 1.2'
             ' 2.3-2.3"/>',
    "known": '<path d="M12 3.8l2.5 5.1 5.6.8-4 3.9.9 5.6-5-2.6-5 2.6.9-5.6-4-3.9 5.6-.8z"/>',
    "locus": '<path d="M3.5 6.5h17M3.5 17.5h17"/><path d="M5.5 12h4M14 12h4.5"/><path d="M12 3v18"/>',
    "help": '<circle cx="12" cy="12" r="8.5"/><path d="M9.7 9.4a2.4 2.4 0 0 1 4.6 1c0 1.6-2.3 1.9-2.3 3.4M12 16.8v.01"/>',
    "info": '<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5.5M12 7.5v.01"/>',
    "search": '<circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4.4-4.4"/>',
    "download": '<path d="M12 4v11M7 10.5l5 5 5-5"/><path d="M4.5 17.5v2h15v-2"/>',
    "upload": '<path d="M12 15.5V4.5M7 9.5l5-5 5 5"/><path d="M4.5 17.5v2h15v-2"/>',
    "doc": '<path d="M6.5 3.5h8l4 4v13h-12z"/><path d="M14 3.5v4.5h4.5M9.5 12.5h6M9.5 16h4"/>',
    "layers": '<path d="M12 3.5l8.5 4.5-8.5 4.5-8.5-4.5z"/><path d="M3.5 12.5l8.5 4.5 8.5-4.5"/><path d="M3.5 16.5l8.5 4.5 8.5-4.5"/>',
    "gene": '<path d="M8 3c0 5 8 4 8 9s-8 4-8 9"/><path d="M16 3c0 5-8 4-8 9s8 4 8 9"/><path d="M9.5 6h5M9.5 18h5"/>',
    "copy": '<rect x="8.5" y="8.5" width="11" height="11" rx="2"/><path d="M15.5 8.5V6A1.5 1.5 0 0 0 14 4.5H6A1.5 1.5 0 0 0'
            ' 4.5 6v8A1.5 1.5 0 0 0 6 15.5h2.5"/>',
    "external": '<path d="M14 4.5h5.5V10M19.5 4.5L11 13"/><path d="M17 14v5.5H4.5V7H10"/>',
    "close": '<path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/>',
    "check": '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    "warn": '<path d="M12 4.5l8.5 15h-17z"/><path d="M12 10.5v4M12 17.3v.01"/>',
    "fail": '<circle cx="12" cy="12" r="8.5"/><path d="M9.2 9.2l5.6 5.6M14.8 9.2l-5.6 5.6"/>',
    "print": '<path d="M7 9V4h10v5"/><rect x="4" y="9" width="16" height="7" rx="1.5"/><path d="M7 13.5h10V20H7z"/>',
    "chevron-down": '<path d="M6 9l6 6 6-6"/>',
    "chevron-right": '<path d="M9 6l6 6-6 6"/>',
    "chevron-left": '<path d="M15 6l-6 6 6 6"/>',
    "arrow-right": '<path d="M5 12h14M13 6l6 6-6 6"/>',
    "line": '<path d="M12 3v18M3.5 12h4M16.5 12h4M5.5 10l-2 2 2 2M18.5 10l2 2-2 2"/>',
    "play": '<circle cx="12" cy="12" r="8.5"/><path d="M10 8.5l5 3.5-5 3.5z"/>',
    "plus": '<path d="M12 5.5v13M5.5 12h13"/>',
}


@register.simple_tag
def icon(name, label=""):
    """An inline icon (ICONS) in the text colour, 1.15em square; `label` names it for screen readers."""
    a11y = f'role="img" aria-label="{escape(label)}"' if label else 'aria-hidden="true"'
    return mark_safe(f'<svg class="sp-i" viewBox="0 0 24 24" focusable="false" {a11y}>{ICONS[name]}</svg>')


@register.simple_tag
def favicon():
    """The brand mark as the browser tab's icon (an inline SVG data URL in the accent colour)."""
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{palette.ACCENT}" '
           f'stroke-width="2.2" stroke-linecap="round">{ICONS["brand"]}</svg>')
    return mark_safe('<link rel="icon" href="data:image/svg+xml,' + svg.replace("#", "%23").replace('"', "'")
                     .replace("<", "%3C").replace(">", "%3E") + '">')


@register.simple_tag
def palette_css():
    return mark_safe(palette.css())


@register.simple_tag
def state_palettes():
    """[(name, label, in use)] of the chromatin-state palettes, for the footer's toggle."""
    return [(name, label, name == palette.states_name()) for name, label in palette.STATE_PALETTE_NAMES.items()]


@register.simple_tag
def portal_release():
    """Version, assembly, build date and manifest sha256 of the current release (for the badge and footer)."""
    try:
        return {**jobs.release_info(), "several": jobs.local() and len(jobs.installed()) > 1,  # I17: the badge links the switch
                "species": jobs.species(), "species_choices": jobs.species_choices()}
    except (AttributeError, OSError, ValueError):  # no or unreadable release configured
        return {"version": "none", "assembly": "Ssal_v3.1", "species": jobs.SALMON}


@register.filter
def thousands(value):
    """1234567 -> 1,234,567; anything else unchanged."""
    return f"{value:,}" if isinstance(value, int) and not isinstance(value, bool) else value


@register.filter
def elapsed(started):
    """'1:05' (minutes:seconds) since a job's start (epoch seconds); '' before it starts."""
    if not isinstance(started, (int, float)):
        return ""
    s = max(0, int(time.time() - started))
    return f"{s // 60}:{s % 60:02d}"


@register.filter
def get(mapping, key):
    return mapping.get(key) if hasattr(mapping, "get") else None


@register.filter
def asis(text):
    """User text (a track's name) as the user wrote it, also on another species' pages (mytracks.asis)."""
    from snpportal import mytracks
    return mytracks.asis(text)


@register.filter
def band(tier):
    """A tier's score band as the pages name it: '5+', '3–4', '1–2' or '0' (figures.bands; G, 2026-11-27)."""
    from .. import figures
    try:
        return figures.bands().get(int(tier), "")
    except (TypeError, ValueError):
        return ""
