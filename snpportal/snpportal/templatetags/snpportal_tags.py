"""Template helpers: the palette as CSS, the current release, number formatting, versioned asset URLs."""
import os
import time

from django import template
from django.contrib.staticfiles import finders
from django.templatetags.static import static
from django.utils.safestring import mark_safe

from .. import jobs, palette

register = template.Library()


@register.simple_tag
def asset(path):
    """A static file's URL with its modification time (?v=), so browsers fetch portal.css or portal.js again when they
    change instead of keeping a stale copy."""
    found = finders.find(path)
    return f"{static(path)}?v={int(os.path.getmtime(found))}" if found else static(path)


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
