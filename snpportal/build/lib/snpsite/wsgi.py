"""WSGI entry point of the snpsite project (gunicorn on the NREC demo: deploy/nrec.sh)."""
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "snpsite.settings")
application = get_wsgi_application()
