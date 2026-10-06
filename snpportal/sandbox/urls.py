from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.urls import include, path

urlpatterns = [path("snp/", include("snpportal.urls"))] + staticfiles_urlpatterns()  # static files only when DEBUG
