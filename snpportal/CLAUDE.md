# Notes for Claude

Django app that will be copied into the salmobase repo (gitlab.com/elixir-nmbu/salmobase) as `snpportal`.
Annotation logic lives in `../snpscore` (see its README "Release format", ROADMAP.md and TRACKER.md, which cover the whole salmo-snp repository).
This app runs scoring jobs, shows the annotated result, and exports it. README "How it works" describes job folders and modules.

## Current phase: public demo
G said go (2026-10-12): a public demo (no password) on an NREC VM at https://158.39.75.9/snp/, deployed with
`bash deploy/nrec.sh nrec 158.39.75.9 158-39-75-9.sslip.io` (sandbox project, gunicorn, Caddy). Always pass the
IP address: the script rewrites the Caddy sites and allowed hosts from the names it is given. Merging into salmobase (Docker, Apache) waits until G says so.

## Match salmobase
- Pages extend `snpportal/base_portal.html` (which extends `salmobase/base.html` and fills its blocks `head`, `content`, `scripts`). Bootstrap 5.1.3 and jQuery are already loaded there.
- Interactivity with htmx (one script tag, with SRI); no frontend build step, no chart libraries: figures are server-rendered SVG from `figures.py`.
- For genome views, reuse salmobase's existing `jbrowse_react` bundle (deep links) instead of adding a new JS build.
- Must keep working on Python 3.8, Django 4.2 and DuckDB 1.2.2 until the portal's Dockerfile sets the versions (G, 2026-10-28: own container, not merged into salmobase).

## Keep it small
- Few files, little code, readable. Don't add tests for every edge case.
- No Django models or database until there's something to save (e.g. saved panels): state lives in job folders.
- Ask before adding a dependency.
- After changing a page the guided tour shows, retake its screenshots: `python manage.py tour_images` (a running portal).

## Design system
- Every colour lives in `palette.py`; templates and `portal.css` use classes and `var(--sp-*)` only (tested). SVGs embed literal hex.
- New pages extend `base_portal.html`; figures use the `_figure.html` card (title, (i) definition, one SVG/PNG/TSV download menu; provenance only in the SVG `<desc>` and downloads).
- No prototype caveat line on the pages (removed 2026-10-11: a dev version); Methods, the report and every download still
  say the rules are provisional. No PROVISIONAL or SYNTHETIC badges: a synthetic job's title says so.
- Panels, filters, card sections and export columns render only when their column exists in the result.
- `hx-boost` only on links and forms that stay on the same page (a boosted file or other-page link swaps in nothing; tested).
- Results tabs: Overview | Table | Export; GWAS jobs: Association | Overview | Table | Export. Tiers always count all 21
  conditions (no trait picker); the curated panel is its own page (Design panel, `panel.py`; `?tab=panel` is unlinked).
  View state lives in whitelisted GET parameters (GWAS links keep the fine-mapping settings); derived files are
  cached in the job folder by a hash of their parameters (`panels/<hash>.parquet`, `loci/<hash>.parquet`), so the
  same URL gives the same file. User SNP names (must-include ids) are POSTed, never put in a URL.

## Provisional (G to confirm)
Thresholds and defaults live in the release's weights.yaml (`assay`, `design`, `finemap` blocks, copied into each job),
in tracks.yaml `defaults`, or in a named constant; Methods, the report and every download say they are provisional. Portal-side ones:
`SNPPORTAL_MAX_VENDOR_SNPS` (50,000 per vendor file), `SNPPORTAL_MAX_CHIP_SNPS` (1,000,000 chip markers), the panel gap highlight (3x the mean spacing, rounded), the
candidate flank (50 kb around a gene), the Manhattan thinning (p > 0.01 thinned to the top SNP per 50 kb),
the regional plot window (lead +- credible set + 20 kb, 50-250 kb), the GWAS loci cap (`association.MAX_LOCI`: the 200
strongest loci are listed and fine-mapped) and the settings form's suggestive-p ceiling (0.01).

## Data safety
- Uploaded files are deleted right after scoring; results are deleted after `SNPPORTAL_KEEP_HOURS` (24 h) or on 'Delete now'.
- Job folders 0700, files 0600. Never log SNP contents or file names (log `job_ref`, counts, timings).
- Never put breeder data in tests or fixtures. Synthetic files have SYNTHETIC in the name and are labelled in the UI.

## Commands
```bash
pip install -r requirements.txt
python manage.py runserver        # needs a release: SNPSCORE_RELEASE or ../snpscore/release/dev
python manage.py test snpportal   # jobs run inline (SNPPORTAL_WORKERS=0)
python manage.py snpportal_cleanup
```
