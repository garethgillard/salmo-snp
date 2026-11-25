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
- salmobase, being prepared (G, 2026-11-25; ../docs/SALMOBASE.md is the brief for the chat on Orion, which installs
  and updates it): `deploy/server.sh` in a container (`deploy/Dockerfile`) or from a virtual environment, behind
  Apache at /snp/ (it serves its own static files under /snp/static/). `SNPSCORE_SALMOBASE` names the server's
  datafiles folder: settings.py finds the releases folder and the default release there, and snpscore reads tracks,
  genomes and model files from it (`bbi.local`). Nothing may write under it (tests_server.py). In a cloud session
  `dockerd &` starts Docker; build with `--secret id=ca,src=/root/.ccr/ca-bundle.crt --network host` and the proxy
  as build args (HTTPS_PROXY), so pip trusts the session's proxy.
- Run `python -m django ...` from snpportal/ or from outside the repository, never from its root: there the
  `snpportal/` folder hides the installed package, and Django finds no management command (server.sh changes to its
  data folder for this).
- The demo's deploy scripts (2026-11-25): `deploy/update.sh` checks the commit out and then runs that commit's own
  steps (so a change to them needs one deploy, not two), and `deploy/species.sh` fetches only the files of a new
  release that no release on the VM holds with the same sha256, and no genome it has. Both are tried on a mock of
  the VM's folders (tests/test_deploy.py; `SNPPORTAL_ROOT`).
- Old releases on the demo (G, 2026-11-25): at each deploy `deploy/species.sh` removes from /srv/snpportal/releases/
  a release the code no longer names, once no job, Design panel or saved project kept there was made with it; it
  never touches the default release or the genomes, and removes nothing when it could not look (tests/test_deploy.py).
- Health: `/snp/health/` (JSON, no content) and a Django system check (`manage.py check`: the release re-hashed).
- Model predictions (G, 2026-11-25: "that useful track from chrombpnet to show effects"): a release's score layers
  (format variant_scores; the first is the gill ChromBPNet model's) are the Locus browser's 'Predicted allele
  effects' group (browser.scores_group: a tick per scored SNP, up and red where the alt allele is predicted more
  accessible, down and blue where less, `palette.EFFECTS`; height = rank) and the Table's Scores column and the
  card's chip, with an arrow (results.score_text). The words come from the layer's `direction` and `reference` in
  layers.yaml (jobs.score_words); nothing is counted until weights.yaml says so.
- Predictions on demand (G, 2026-11-25): the card's 'Predict' button runs a sequence model for one SNP in this
  process (predict.py; lib/predict.py holds the model's rules, lib/models.yaml the models by assembly). numpy and
  onnxruntime are imported only then and are an optional extra: nothing else may import them, and the pages must
  work without them (the card then says how to get them). A job's SNP is named by job and row in the address,
  never by position. The button undoes the results page's hx-select, which the drawer inherits. README
  "Predictions on demand".
- Tracks AQUA-FAANG publishes after a release (2026: salmon gill ATAC-seq, the ImmunoMap) go live with a deploy:
  `snpdata tracks --added-since <release>/tracks.yaml` (in ../snpdata) regenerates tracks.yaml and writes
  `snpportal/lib/tracks_added.yaml`, which lib/tracks.load_tracks adds to a release registry of the same hub.

## Species
- A release is for one species (manifest `species`). `jobs.species_releases()` gives one release per species: the
  default (`SNPSCORE_RELEASE`), and the newest of each other species under `SNPPORTAL_RELEASES_DIR` (a local
  install's releases/; a server's folder of extra releases, with `SNPSCORE_GENOME_DIR` holding every genome).
- The species bar (base_portal.html, top right; POST /snp/species/ sets the `snp_species` cookie) picks the species
  for new work; job, panel and project pages read their own release whatever the cookie says (`jobs.for_request`).
- Pages and constants are written for salmon. `jobs.wording()` rewrites an HTML or SVG response of another species'
  release in one place: assembly, older assembly, the number of conditions, chromosome names, and the pairs in the
  release's `species.wording`. Write new salmon-specific text plainly, then add a pair there if trout needs another
  wording; things that are data (examples, default locus, searches, samples, citations) come from the manifest.

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
- Structural variants (G, 2026-11-24): SV jobs (`input_kind` sv, `snpscore.annotate_svs`) use the SNP pages; their result
  has `end` and `length` (`results.is_sv`), which the pages check. Write SNP wording plainly: `jobs.sv_wording` turns
  "SNPs" into "SVs" on an SV job's pages (not "published SNP", "SNP chip", the site's name). No panels, vendor files or
  priors for SVs.
- Results tabs: Overview | Table | Export; GWAS jobs: Association | Overview | Table | Export. Tiers always count all 27
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
and its 7-nt seeds (matches with up to 4 mismatches in 35 nt); the user's own tracks (mytracks.py): 50 MB and
1,000,000 intervals a file (`SNPPORTAL_MAX_TRACK_MB`, `SNPPORTAL_MAX_TRACK_ROWS`; G agreed, 2026-11-15), 500 MB
unpacked for a gzipped file (`SNPPORTAL_MAX_TRACK_UNPACKED_MB`), 20 tracks a user, 5,000 intervals drawn per track in a window, in at most 4 lanes.

## Data safety
- Uploaded files are deleted right after scoring; results are deleted on 'Delete now', and on a server after
  `SNPPORTAL_KEEP_HOURS` (24 h). Locally (`SNPPORTAL_LOCAL`) nothing expires.
- A user's own BED tracks (mytracks.py) follow the same rules: the upload is deleted once converted, a track is
  private to the browser that added it on a server (a signed cookie), filters only the results its owner used it on,
  expires with the results, and its names are never logged.
- Job folders 0700, files 0600. Never log SNP contents or file names (log `job_ref`, counts, timings).
- Never put breeder data in tests or fixtures. Synthetic files have SYNTHETIC in the name and are labelled in the UI.

## Commands
```bash
salmo-snp serve                   # as users run it (snpportal/serve.py), with the data of ../tools/get_data.sh
salmo-snp serve --release ../snpdata/release/dev   # or a release you built; the environment: ../AGENTS.md
python manage.py runserver        # with autoreload: needs a release (SNPSCORE_RELEASE or ../snpdata/release/dev)
python -m pytest -q tests         # snpportal.lib
SNPPORTAL_WORKERS=0 python manage.py test snpportal --parallel   # the pages, jobs run inline; a class per core
python manage.py snpportal_cleanup
python manage.py screenshots /snp/ /snp/known-loci/ --out shots   # full-page PNGs of a running portal's pages
```
