"""Minimal Django project for running the snpportal app outside salmobase: development on a laptop, and the public demo
on NREC (deploy/nrec.sh sets the DJANGO_* variables below; salmobase itself uses its own settings)."""
import os
from pathlib import Path

from snpportal import serve  # the releases this code names, and where the data is published (no Django in it)

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",")
CSRF_TRUSTED_ORIGINS = [f"https://{h}" for h in ALLOWED_HOSTS if h != "*"]
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")  # behind Caddy on the demo server
# Beside another site on the same host (salmobase's own Django, with the portal at /snp/): the portal's form token has
# a name of its own, so neither site reads or replaces the other's, and with SNPPORTAL_COOKIE_PATH=/snp/ (set by
# deploy/server.sh) its cookies are sent to its own pages only. Its pages may be framed by its own pages alone (the
# Table's drawer frames the Locus browser), and browsers are told not to guess content types.
CSRF_COOKIE_NAME = "snpportal_csrftoken"
SNPPORTAL_COOKIE_PATH = os.environ.get("SNPPORTAL_COOKIE_PATH", "/")
CSRF_COOKIE_PATH = SNPPORTAL_COOKIE_PATH
X_FRAME_OPTIONS = "SAMEORIGIN"
SECURE_CONTENT_TYPE_NOSNIFF = True
STATIC_ROOT = os.environ.get("DJANGO_STATIC_ROOT")  # collectstatic's target; Caddy serves it when DEBUG is off
INSTALLED_APPS = ["django.contrib.staticfiles", "snpportal"]
MIDDLEWARE = ["django.middleware.security.SecurityMiddleware", "django.middleware.common.CommonMiddleware",
              "django.middleware.csrf.CsrfViewMiddleware", "django.middleware.clickjacking.XFrameOptionsMiddleware",
              "snpportal.palette.middleware",  # a viewer's chromatin colours (the locus browser's toggle)
              "snpportal.jobs.middleware"]  # the release each request reads (several releases installed, I17)
ROOT_URLCONF = "snpsite.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [Path(__file__).resolve().parent / "templates"],
    "APP_DIRS": True,
}]
DATABASES = {}
STATIC_URL = os.environ.get("DJANGO_STATIC_URL", "/static/")  # served by runserver (and snpsite/urls.py) while DEBUG is on;
# the salmobase container: /snp/static/, served by the portal itself (SNPPORTAL_SERVE_STATIC=1), as /static/ is salmobase's
SNPPORTAL_SERVE_STATIC = os.environ.get("SNPPORTAL_SERVE_STATIC") == "1"

# On the salmobase server (G, 2026-11-25) the portal reads the published data where it is: SNPSCORE_SALMOBASE names
# the server's datafiles folder (what https://salmobase.org/datafiles/ serves). The releases folder and the default
# release follow from it (the releases this code names: serve.RELEASE and RELEASES), and snpscore reads the tracks,
# the genomes and the models' files from that folder instead of asking the web server (snpscore.bbi.local). Nothing
# is written there: results and the secret key are in the portal's own data folder.
_published = serve.published(os.environ.get("SNPSCORE_SALMOBASE"))

# Release folder built by snpdata (`snpdata build --out release/dev`)
SNPSCORE_RELEASE = os.environ.get("SNPSCORE_RELEASE") or str(
    _published / serve.RELEASE if _published else BASE_DIR.parent / "snpdata" / "release" / "dev")

# Portal settings (defaults shown). Results live in SNPPORTAL_RESULTS_DIR (default: <system temp>/snpportal).
if os.environ.get("SNPPORTAL_RESULTS_DIR"):
    SNPPORTAL_RESULTS_DIR = os.environ["SNPPORTAL_RESULTS_DIR"]
SNPPORTAL_WORKERS = int(os.environ.get("SNPPORTAL_WORKERS", 1))  # background job threads; 0 = run inline (tests)
SNPPORTAL_KEEP_HOURS = float(os.environ.get("SNPPORTAL_KEEP_HOURS", 24 * 30))  # a month for now (G, 2026-11-26)
if os.environ.get("SNPPORTAL_RELEASES_DIR"):  # salmo-snp serve: the data folder's releases/, to switch between (I17)
    SNPPORTAL_RELEASES_DIR = os.environ["SNPPORTAL_RELEASES_DIR"]
elif _published:  # the salmobase server: every published release, each species' named one for new work
    SNPPORTAL_RELEASES_DIR = str(_published)
elif (Path(SNPSCORE_RELEASE).parent / "releases").is_dir():  # a server: the other species' releases beside the default
    SNPPORTAL_RELEASES_DIR = str(Path(SNPSCORE_RELEASE).parent / "releases")  # one (/srv/snpportal/release, releases/)
SNPPORTAL_LOCAL = os.environ.get("SNPPORTAL_LOCAL") == "1"  # salmo-snp serve: nothing expires, the pages say it is local
# where a sequence model's files are kept once fetched (the card's Predict button); default: models/ beside the results
SNPPORTAL_MODELS_DIR = os.environ.get("SNPPORTAL_MODELS_DIR", "")
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
