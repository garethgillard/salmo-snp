"""Minimal Django project for developing the snpportal app outside salmobase. Not used in production."""
import os
import tempfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = "dev-only"
DEBUG = True
ALLOWED_HOSTS = ["*"]
INSTALLED_APPS = ["django.contrib.staticfiles", "snpportal"]
MIDDLEWARE = ["django.middleware.common.CommonMiddleware", "django.middleware.csrf.CsrfViewMiddleware"]
ROOT_URLCONF = "sandbox.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "sandbox" / "templates"],
    "APP_DIRS": True,
}]
DATABASES = {}
STATIC_URL = "/static/"  # served by runserver (and sandbox/urls.py) while DEBUG is on

# Release folder built by salmo-snpscore (`snpscore build --out release/dev`)
SNPSCORE_RELEASE = os.environ.get("SNPSCORE_RELEASE", str(BASE_DIR.parent / "salmo-snpscore" / "release" / "dev"))

# Portal settings (defaults shown). Results live in SNPPORTAL_RESULTS_DIR (default: <system temp>/snpportal).
SNPPORTAL_WORKERS = int(os.environ.get("SNPPORTAL_WORKERS", 1))  # background job threads; 0 = run inline (tests)
SNPPORTAL_KEEP_HOURS = 24
SNPPORTAL_MAX_UPLOAD_MB = 300  # checked on Content-Length before the body is read
SNPPORTAL_MAX_SNPS = 3_000_000
SNPPORTAL_STATE_COLOURS = os.environ.get("SNPPORTAL_STATE_COLOURS", "portal")  # or 'aquafaang' (AQUA-FAANG itemRgb); G to choose
DATA_UPLOAD_MAX_MEMORY_SIZE = 2_621_440  # form fields such as the paste box (Django's default); files stream to disk
CACHES = {  # 'snpportal_tiles': public signal tiles of the locus browser (keys never hold a user's position)
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
    "snpportal_tiles": {"BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
                        "LOCATION": os.path.join(tempfile.gettempdir(), "snpportal_tiles"),
                        "TIMEOUT": 7 * 86400, "OPTIONS": {"MAX_ENTRIES": 20_000}},
}

LOGGING = {  # event names, job_ref hashes, counts and timings only: never SNPs or file names
    "version": 1,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {"snpportal": {"handlers": ["console"], "level": "INFO"}},
}
