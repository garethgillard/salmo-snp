"""WSGI entry point of the sandbox project (gunicorn on the NREC demo: deploy/nrec.sh)."""
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "sandbox.settings")
application = get_wsgi_application()
