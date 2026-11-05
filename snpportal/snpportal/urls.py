from django.urls import path

from . import about, association, browser, explore, health, locus, panel, panel_report, projects, report, search, tools, views

app_name = "snpportal"
urlpatterns = [
    path("", views.score, name="upload"),  # the Score page is the home page
    path("current/", views.current, name="current"),
    path("panel/", panel.page, name="design_panel"),
    path("panel/change/", panel.change, name="panel_change"),
    path("panel/download/", panel.download, name="panel_download"),
    path("panel/upgrade/", panel.upgrade, name="panel_upgrade"),
    path("panel/report/", panel_report.report, name="panel_report"),
    path("panel/count/", panel.count, name="panel_count"),
    path("results/<uuid:key>/add-to-panel/", panel.add, name="panel_add"),
    # saved design projects (local installs only): versions, diff, downloads, export and import
    path("panel/save/", projects.save_view, name="panel_save"),
    path("projects/", projects.page, name="projects"),
    path("projects/import/", projects.import_zip, name="project_import"),
    path("projects/<str:name>/export/", projects.export_zip, name="project_export"),
    path("projects/<str:name>/<int:n>/open/", projects.open_view, name="project_open"),
    path("projects/<str:name>/<int:n>/download/", projects.download, name="project_download"),
    path("projects/<str:name>/<int:n>/report/", panel_report.project_report, name="project_report"),
    path("search/", search.search, name="search"),
    path("search/suggest/", search.suggest, name="suggest"),
    path("tour/", explore.tour, name="tour"),
    path("locus/", browser.page, name="locus"),
    path("locus/assay/", browser.assay, name="locus_assay"),
    path("locus/svg/", locus.locus_svg_view, name="locus_svg"),
    path("gene/<str:gene_id>/", explore.gene, name="gene"),
    path("variant/<str:spec>/", locus.variant, name="variant"),
    path("about/data/", about.data, name="about_data"),
    path("about/methods/", about.methods, name="methods"),
    path("help/", about.help_page, name="help"),
    path("run-locally/", about.run_locally, name="run_locally"),
    path("releases/", about.releases, name="releases"),
    path("health/", health.health, name="health"),
    path("colours/", about.state_palette, name="state_palette"),
    path("results/<uuid:key>/", views.results, name="results"),
    path("results/<uuid:key>/status/", views.status, name="status"),
    path("results/<uuid:key>/snp/<int:row>/", locus.card, name="card"),
    path("results/<uuid:key>/figure/<slug:name>.svg", views.figure, name="figure"),
    path("results/<uuid:key>/download/", views.download, name="download"),
    path("results/<uuid:key>/chip/", tools.chip, name="chip"),
    path("results/<uuid:key>/panel/", tools.design, name="panel_design"),
    path("results/<uuid:key>/delete/", views.delete, name="delete"),
    # the known-loci catalogue page; POST genes or intervals -> a candidate job
    path("known-loci/", explore.known_loci, name="known_loci"),
    path("candidates/", explore.candidate_job, name="candidates"),
    # printable one-page report of a job
    path("results/<uuid:key>/report/", report.report, name="report"),
    path("results/<uuid:key>/tools/<slug:name>.svg", tools.figure, name="tool_figure"),  # the (unlinked) Panel tab's figures
    # GWAS summary statistics -> Association page, figures, downloads, regional plot
    path("gwas/", association.score, name="gwas_score"),
    path("results/<uuid:key>/association/", association.association, name="association"),
    path("results/<uuid:key>/association/<slug:name>.svg", association.figure, name="association_figure"),
    path("results/<uuid:key>/association/download/", association.download, name="association_download"),
    path("results/<uuid:key>/association/region/", association.region, name="association_region"),
]
