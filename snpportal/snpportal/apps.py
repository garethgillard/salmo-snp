from django.apps import AppConfig
from django.conf import settings


class SnpportalConfig(AppConfig):
    name = "snpportal"

    def ready(self):
        """settings.SNPPORTAL_STATE_COLOURS: 'portal' (default) or 'aquafaang' (AQUA-FAANG's itemRgb), G to choose."""
        from . import palette
        palette.use_states(getattr(settings, "SNPPORTAL_STATE_COLOURS", "portal"))
