"""Template helpers: the palette as CSS, the current release, number formatting."""
import time

from django import template
from django.utils.safestring import mark_safe

from .. import jobs, palette

register = template.Library()


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
        return jobs.release_info()
    except (AttributeError, OSError, ValueError):  # no or unreadable release configured
        return {"version": "none", "assembly": "Ssal_v3.1"}


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
