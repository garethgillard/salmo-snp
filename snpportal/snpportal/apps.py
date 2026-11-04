from django.apps import AppConfig
from django.conf import settings


class SnpportalConfig(AppConfig):
    name = "snpportal"

    def ready(self):
        """settings.SNPPORTAL_STATE_PALETTE: the chromatin-state colours, 'portal' (default) or 'aquafaang' (AQUA-FAANG's
        itemRgb), G to choose. A viewer's cookie overrides it per request (palette.middleware, in settings.MIDDLEWARE)."""
        from . import palette
        palette.use_states(getattr(settings, "SNPPORTAL_STATE_PALETTE", "portal"))
