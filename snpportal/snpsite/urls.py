from django.conf import settings
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.urls import include, path, re_path
from django.views.static import serve

# The salmobase container serves its own static files under STATIC_URL (/snp/static/): a few small files, cached by
# the browser by their ?v= URLs, so Django's static view is enough there; elsewhere Caddy (NREC) or runserver serves them.
static = [re_path(rf"^{settings.STATIC_URL.strip('/')}/(?P<path>.*)$", serve, {"document_root": settings.STATIC_ROOT})] \
    if settings.SNPPORTAL_SERVE_STATIC and settings.STATIC_ROOT else []
urlpatterns = static + [path("snp/", include("snpportal.urls"))] + staticfiles_urlpatterns()  # the last only when DEBUG
