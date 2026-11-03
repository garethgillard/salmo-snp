"""Minimal Django project for running the snpportal app outside salmobase: development on a laptop, and the public demo
on NREC (deploy/nrec.sh sets the DJANGO_* variables below; salmobase itself uses its own settings)."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",")
CSRF_TRUSTED_ORIGINS = [f"https://{h}" for h in ALLOWED_HOSTS if h != "*"]
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")  # behind Caddy on the demo server
STATIC_ROOT = os.environ.get("DJANGO_STATIC_ROOT")  # collectstatic's target; Caddy serves it when DEBUG is off
INSTALLED_APPS = ["django.contrib.staticfiles", "snpportal"]
MIDDLEWARE = ["django.middleware.common.CommonMiddleware", "django.middleware.csrf.CsrfViewMiddleware"]
ROOT_URLCONF = "snpsite.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [Path(__file__).resolve().parent / "templates"],
    "APP_DIRS": True,
}]
DATABASES = {}
STATIC_URL = "/static/"  # served by runserver (and snpsite/urls.py) while DEBUG is on

# Release folder built by snpdata (`snpdata build --out release/dev`)
SNPSCORE_RELEASE = os.environ.get("SNPSCORE_RELEASE", str(BASE_DIR.parent / "snpdata" / "release" / "dev"))

# Portal settings (defaults shown). Results live in SNPPORTAL_RESULTS_DIR (default: <system temp>/snpportal).
if os.environ.get("SNPPORTAL_RESULTS_DIR"):
    SNPPORTAL_RESULTS_DIR = os.environ["SNPPORTAL_RESULTS_DIR"]
SNPPORTAL_WORKERS = int(os.environ.get("SNPPORTAL_WORKERS", 1))  # background job threads; 0 = run inline (tests)
SNPPORTAL_KEEP_HOURS = float(os.environ.get("SNPPORTAL_KEEP_HOURS", 24))
SNPPORTAL_LOCAL = os.environ.get("SNPPORTAL_LOCAL") == "1"  # salmo-snp serve: nothing expires, the pages say it is local
SNPPORTAL_MAX_UPLOAD_MB = 300  # checked on Content-Length before the body is read
SNPPORTAL_MAX_SNPS = 3_000_000
SNPPORTAL_DUCKDB_THREADS = int(os.environ.get("SNPPORTAL_DUCKDB_THREADS", 2))  # per job; deploy/nrec.sh sizes them to the VM
SNPPORTAL_DUCKDB_MEMORY = os.environ.get("SNPPORTAL_DUCKDB_MEMORY", "2GB")
SNPPORTAL_STATE_PALETTE = os.environ.get("SNPPORTAL_STATE_PALETTE", "portal")  # or 'aquafaang' (AQUA-FAANG itemRgb); G to choose
DATA_UPLOAD_MAX_MEMORY_SIZE = 2_621_440  # form fields such as the paste box (Django's default); files stream to disk
CACHES = {  # 'snpportal_tiles': public signal tiles of the locus browser (keys never hold a user's position)
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
    # in memory here; a server shares Redis or Memcached. Not the file-based cache: it lists its folder on every write,
    # and one locus browser view with the functional assays open writes ~3,000 tiles (~2 KB each)
    "snpportal_tiles": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "snpportal-tiles",
                        "TIMEOUT": 7 * 86400, "OPTIONS": {"MAX_ENTRIES": 100_000}},
}

LOGGING = {  # event names, job_ref hashes, counts and timings only: never SNPs or file names
    "version": 1,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {"snpportal": {"handlers": ["console"], "level": "INFO"}},
}
