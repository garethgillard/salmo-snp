# Notes for Claude

Django app that will be copied into the salmobase repo (gitlab.com/elixir-nmbu/salmobase) as `snpportal`.
Annotation logic lives in the sibling repo `salmo-snpscore` (see its README "Release format" and TRACKER.md, which covers both repos).
This app only uploads SNP lists, shows the annotated result, and exports it.

## Current phase: local prototype
Everything runs locally on test data: `tests/fixture` and the public inputs from `snpscore fetch`.
No Docker, Apache, server, deployment or hosting work until the prototype works and G says it's time to go online.

## Match salmobase
- Templates extend `salmobase/base.html` and fill its blocks `head`, `content`, `scripts`. Bootstrap 5.1.3 and jQuery are already loaded there.
- Interactivity with htmx (one script tag); no frontend build step.
- For genome views, reuse salmobase's existing `jbrowse_react` bundle instead of adding a new JS build.
- Must keep working on Python 3.8, Django 4.2 and DuckDB 1.2.2 (salmobase's Docker image).

## Keep it small
- Few files, little code, readable. Don't add tests for every edge case.
- No Django models or database until there's something to save (e.g. saved panels).
- Ask before adding a dependency.

## Data safety
- Uploaded files are deleted right after scoring; results are temporary.
- Never log SNP contents. Never put breeder data in tests or fixtures.

## Commands
```bash
pip install -r requirements.txt
python manage.py runserver        # needs a release: SNPSCORE_RELEASE or ../salmo-snpscore/release/dev
python manage.py test snpportal
```
