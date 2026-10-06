from django.urls import path

from . import views

app_name = "snpportal"
urlpatterns = [
    path("", views.upload, name="upload"),
    path("results/<uuid:key>/", views.results, name="results"),
    path("results/<uuid:key>/download/", views.download, name="download"),
]
