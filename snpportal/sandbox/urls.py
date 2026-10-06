from django.urls import include, path

urlpatterns = [path("snp/", include("snpportal.urls"))]
