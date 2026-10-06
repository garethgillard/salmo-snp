from django.urls import path

from . import about, explore, search, tools, views
from . import locus  # AGENT locus (stage 2)
from . import report  # AGENT tour (stage 3)
from . import association  # AGENT gwas (stage 3)

app_name = "snpportal"
urlpatterns = [
    path("", explore.landing, name="landing"),
    path("score/", views.score, name="upload"),
    path("search/", search.search, name="search"),
    path("search/suggest/", search.suggest, name="suggest"),
    path("tour/", explore.tour, name="tour"),
    path("locus/", locus.locus, name="locus"),  # AGENT locus (stage 2)
    path("locus/svg/", locus.locus_svg_view, name="locus_svg"),  # AGENT locus (stage 2)
    path("gene/<str:gene_id>/", explore.gene, name="gene"),
    path("variant/<str:spec>/", locus.variant, name="variant"),  # AGENT locus (stage 2)
    path("about/data/", about.data, name="about_data"),
    path("about/methods/", about.methods, name="methods"),
    path("help/", about.help_page, name="help"),
    path("run-locally/", about.run_locally, name="run_locally"),
    path("results/<uuid:key>/", views.results, name="results"),
    path("results/<uuid:key>/status/", views.status, name="status"),
    path("results/<uuid:key>/snp/<int:row>/", locus.card, name="card"),  # AGENT locus (stage 2)
    path("results/<uuid:key>/snp/<int:row>/locus.svg", locus.card_locus, name="card_locus"),  # AGENT locus (stage 2)
    path("results/<uuid:key>/figure/<slug:name>.svg", views.figure, name="figure"),
    path("results/<uuid:key>/download/", views.download, name="download"),
    path("results/<uuid:key>/chip/", tools.chip, name="chip"),
    path("results/<uuid:key>/delete/", views.delete, name="delete"),
    # AGENT explore (stage 2): known-loci catalogue page; POST genes/intervals -> candidate job
    path("known-loci/", explore.known_loci, name="known_loci"),
    path("candidates/", explore.candidate_job, name="candidates"),
    # AGENT tour (stage 3): printable one-page report of a job
    path("results/<uuid:key>/report/", report.report, name="report"),
    path("results/<uuid:key>/tools/<slug:name>.svg", tools.figure, name="tool_figure"),  # AGENT breeder (stage 3): Panel-tab figures
    # AGENT gwas (stage 3): GWAS summary statistics -> Association page, figures, downloads, regional plot
    path("score/gwas/", association.score, name="gwas_score"),
    path("results/<uuid:key>/association/", association.association, name="association"),
    path("results/<uuid:key>/association/<slug:name>.svg", association.figure, name="association_figure"),
    path("results/<uuid:key>/association/download/", association.download, name="association_download"),
    path("results/<uuid:key>/association/region/", association.region, name="association_region"),
]
