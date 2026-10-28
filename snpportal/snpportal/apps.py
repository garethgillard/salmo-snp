from django.apps import AppConfig
from django.conf import settings
from django.core.signals import request_started
from django.http import parse_cookie


class SnpportalConfig(AppConfig):
    name = "snpportal"

    def ready(self):
        """settings.SNPPORTAL_STATE_PALETTE: the chromatin-state colours, 'portal' (default) or 'aquafaang' (AQUA-FAANG's
        itemRgb), G to choose. A viewer's cookie (the locus browser's 'Chromatin colours' links) overrides it per request."""
        from . import palette
        palette.use_states(getattr(settings, "SNPPORTAL_STATE_PALETTE", "portal"))

        def viewer_palette(sender, environ=None, scope=None, **kwargs):  # WSGI: the cookie is in environ; ASGI: in scope
            cookie = (environ or {}).get("HTTP_COOKIE") or b"; ".join(
                v for k, v in (scope or {}).get("headers", []) if k == b"cookie").decode("latin-1")
            palette.choose(parse_cookie(cookie).get(palette.COOKIE))
        request_started.connect(viewer_palette, weak=False, dispatch_uid="snpportal_palette")
