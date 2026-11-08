# snpportal: notes

The web portal: a Django app that runs scoring jobs with ../snpscore against a release built by ../snpdata, shows the
result and exports it. Users run it locally (`salmo-snp serve`, snpportal/serve.py); the live site goes on salmobase
later, linked from salmobase by a button (G, 2026-11-03). Read
../AGENTS.md first (plan, rules, biology decisions); README "How it works" describes job folders and modules.
`snpportal/lib/` is plain Python with no Django (locus data, panel design, exports, the track registry); its pytest
tests are in `tests/`, the Django ones in `snpportal/tests*.py`.

## Where it runs
- On users' own computers, the main product (G, 2026-11-03): `salmo-snp serve` (serve.py) sets `SNPPORTAL_LOCAL`, so
  results stay until deleted and the Score, Help, Design panel and Run locally pages say they are on this computer.
- The public demo (no password) on an NREC VM, https://158.39.75.9/snp/ (G, 2026-10-12): gunicorn behind Caddy, 24 h
  retention. Code goes there only when G says so (G, 2026-11-06; ../AGENTS.md "Deploying the NREC demo"): the
  manual `deploy` workflow runs the tests, then `deploy/update.sh` on the VM, and sends a public pool built on GitHub's
  runner when the VM's is stale (README "Deploying the demo"); merging to main deploys nothing. A new data release goes up with `bash deploy/nrec.sh nrec
  158.39.75.9 158-39-75-9.sslip.io`, which needs G's Mac (the VM's SSH key and the release folder); always pass the IP
  address, as the script rewrites the Caddy sites and allowed hosts from the names it is given.
- salmobase later: a container installing a tagged version (../AGENTS.md plan 4): `deploy/Dockerfile`, README
  "salmobase container" (Apache proxies /snp/ to it; it serves its own static files under /snp/static/). In a cloud
  session `dockerd &` starts Docker; build with `--secret id=ca,src=/root/.ccr/ca-bundle.crt` and the proxy as build
  args (HTTPS_PROXY), so pip trusts the session's proxy.
- Health: `/snp/health/` (JSON, no content) and a Django system check (`manage.py check`: the release re-hashed).

## Look like salmobase
- Pages extend `snpportal/base_portal.html` (which extends `salmobase/base.html` and fills its blocks `head`, `content`, `scripts`). Bootstrap 5.1.3 and jQuery are already loaded there.
- Interactivity with htmx (one script tag, with SRI); no frontend build step, no chart libraries: figures are server-rendered SVG from `figures.py`.
- Python 3.11 or newer, Django 5.2 LTS and DuckDB 2 (../AGENTS.md "Rules"); the portal gets its own container on
  salmobase, not merged into its Django (G, 2026-10-28).

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
Thresholds and defaults live in snpscore's weights.yaml (`assay`, `design`, `finemap` blocks, copied into each job),
in tracks.yaml `defaults`, or in a named constant; Methods, the report and every download say they are provisional. Portal-side ones:
`SNPPORTAL_MAX_VENDOR_SNPS` (50,000 per vendor file), `SNPPORTAL_MAX_CHIP_SNPS` (1,000,000 chip markers), the panel gap highlight (3x the mean spacing, rounded), the
candidate flank (50 kb around a gene), the Manhattan thinning (p > 0.01 thinned to the top SNP per 50 kb),
the regional plot window (lead +- credible set + 20 kb, 50-250 kb), the GWAS loci cap (`association.MAX_LOCI`: the 200
strongest loci are listed and fine-mapped) and the settings form's suggestive-p ceiling (0.01); Push 3: the probe
uniqueness check's cap (`panel.UNIQUENESS_MAX`, 5,000 SNPs), its 50 kb margin and 2 Mb region cap (lib/uniqueness.py)
and its 7-nt seeds (matches with up to 4 mismatches in 35 nt).

## Data safety
- Uploaded files are deleted right after scoring; results are deleted on 'Delete now', and on a server after
  `SNPPORTAL_KEEP_HOURS` (24 h). Locally (`SNPPORTAL_LOCAL`) nothing expires.
- Job folders 0700, files 0600. Never log SNP contents or file names (log `job_ref`, counts, timings).
- Never put breeder data in tests or fixtures. Synthetic files have SYNTHETIC in the name and are labelled in the UI.

## Commands
```bash
salmo-snp serve                   # as users run it (snpportal/serve.py), with the data of ../tools/get_data.sh
salmo-snp serve --release ../snpdata/release/dev   # or a release you built; the environment: ../AGENTS.md
python manage.py runserver        # with autoreload: needs a release (SNPSCORE_RELEASE or ../snpdata/release/dev)
python -m pytest -q tests         # snpportal.lib
SNPPORTAL_WORKERS=0 python manage.py test snpportal   # the pages, jobs run inline
python manage.py snpportal_cleanup
python manage.py screenshots /snp/ /snp/known-loci/ --out shots   # full-page PNGs of a running portal's pages
```
