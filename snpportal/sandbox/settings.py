"""Minimal Django project for developing the snpportal app outside salmobase. Not used in production."""
import os
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
STATIC_URL = "/static/"

# Release folder built by salmo-snpscore (`snpscore build --out release/dev`)
SNPSCORE_RELEASE = os.environ.get("SNPSCORE_RELEASE", str(BASE_DIR.parent / "salmo-snpscore" / "release" / "dev"))
