"""Template helpers: the palette as CSS, the current release, number formatting."""
from django import template
from django.utils.safestring import mark_safe

from .. import jobs, palette

register = template.Library()


@register.simple_tag
def palette_css():
    return mark_safe(palette.css())


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
def get(mapping, key):
    return mapping.get(key) if hasattr(mapping, "get") else None
