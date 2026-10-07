# Notes for Claude

Django app that will be copied into the salmobase repo (gitlab.com/elixir-nmbu/salmobase) as `snpportal`.
Annotation logic lives in the sibling repo `salmo-snpscore` (see its README "Release format", ROADMAP.md and TRACKER.md, which cover both repos).
This app runs scoring jobs, shows the annotated result, and exports it. README "How it works" describes job folders and modules.

## Current phase: local prototype
Everything runs locally on test data: `tests/fixture` and the public inputs from `snpscore fetch`.
No Docker, Apache, server, deployment or hosting work until the prototype works and G says it's time to go online.

## Match salmobase
- Pages extend `snpportal/base_portal.html` (which extends `salmobase/base.html` and fills its blocks `head`, `content`, `scripts`). Bootstrap 5.1.3 and jQuery are already loaded there.
- Interactivity with htmx (one script tag, with SRI); no frontend build step, no chart libraries: figures are server-rendered SVG from `figures.py`.
- For genome views, reuse salmobase's existing `jbrowse_react` bundle (deep links) instead of adding a new JS build.
- Must keep working on Python 3.8, Django 4.2 and DuckDB 1.2.2 (salmobase's Docker image).

## Keep it small
- Few files, little code, readable. Don't add tests for every edge case.
- No Django models or database until there's something to save (e.g. saved panels): state lives in job folders.
- Ask before adding a dependency.

## Design system
- Every colour lives in `palette.py`; templates and `portal.css` use classes and `var(--sp-*)` only (tested). SVGs embed literal hex.
- New pages extend `base_portal.html`; figures use the `_figure.html` card (title, (i) definition, one SVG/PNG/TSV download menu; provenance only in the SVG `<desc>` and downloads).
- Pages that show tiers include `_caveat.html` once (SYNTHETIC prefix on synthetic jobs): no PROVISIONAL or SYNTHETIC badges elsewhere.
- Panels, filters, card sections and export columns render only when their column exists in the result.
- `hx-boost` only on links and forms that stay on the same page (a boosted file or other-page link swaps in nothing; tested).
- Results tabs: Overview | Table | Panel | Export; GWAS jobs: Association | Overview | Table | Export. View state lives in whitelisted GET
  parameters; derived files are cached in the job folder by a hash of their parameters (`panels/<hash>.parquet`), so the
  same URL gives the same file.

## Provisional (G to confirm)
Thresholds and defaults live in the release's weights.yaml (`assay`, `design`, `finemap` blocks, copied into each job),
in tracks.yaml `defaults`, or in a named constant; the UI's caveat line and every download say they are provisional. Portal-side ones:
`SNPPORTAL_MAX_VENDOR_SNPS` (50,000 per vendor file), the panel gap highlight (3x the mean spacing, rounded), the
candidate and tour flank (50 kb around a gene), the Manhattan thinning (p > 0.01 thinned to the top SNP per 50 kb) and
the regional plot window (lead +- credible set + 20 kb, 50-250 kb).

## Data safety
- Uploaded files are deleted right after scoring; results are deleted after `SNPPORTAL_KEEP_HOURS` (24 h) or on 'Delete now'.
- Job folders 0700, files 0600. Never log SNP contents or file names (log `job_ref`, counts, timings).
- Never put breeder data in tests or fixtures. Synthetic files have SYNTHETIC in the name and are labelled in the UI.

## Commands
```bash
pip install -r requirements.txt
python manage.py runserver        # needs a release: SNPSCORE_RELEASE or ../salmo-snpscore/release/dev
python manage.py test snpportal   # jobs run inline (SNPPORTAL_WORKERS=0)
python manage.py snpportal_cleanup
```
