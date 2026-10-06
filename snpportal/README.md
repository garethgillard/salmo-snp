# salmo-snpportal

Django app for salmobase.org: score a SNP list against AQUA-FAANG functional maps and tier it for a trait, then explore
the result (overview, filterable table, evidence card per SNP), design a genotyping panel, compare it with an existing
chip, export it (TSV, Parquet, BED, Illumina-, Axiom- and KASP-style files, or a zip bundle) and print a one-page report.
GWAS summary statistics get an Association page (Manhattan, tier-stratified QQ, loci, regional plot and fine-mapping
with a functional prior). Without a list: search (genes, NCBI LOC symbols, rs IDs, positions), gene pages, a locus
browser with live salmobase signal, published associations and molQTL leads, the known-loci catalogue (36 published SNPs
and a gene region across 8 traits, with evidence badges) and a guided vgll3 tour. All annotation logic lives in the sibling repo
[salmo-snpscore](../salmo-snpscore); this app handles upload, jobs, display and export.

## Run locally

```bash
pip install -r requirements.txt                       # also installs ../salmo-snpscore (editable)
(cd ../salmo-snpscore && snpscore fetch && snpscore build --out release/dev)
python manage.py runserver                            # http://127.0.0.1:8000/snp/
python manage.py test snpportal                       # builds a release from salmo-snpscore's fixture
```

To try it, use the example buttons at the top of the Score page (the release's `demo/` inputs: known loci, 50K public
sites from the AQUA-FAANG 12-fish VCF, the SYNTHETIC demo chip, and the SYNTHETIC maturation GWAS in the GWAS card), paste
a few positions or rs IDs, upload
`../salmo-snpscore/tests/fixture/snps.vcf`, or follow the guided tour (`/snp/tour/`). On a results page, the Panel tab's
'Use the demo chip' button compares the list with the SYNTHETIC demo chip. For a chip-sized list, cut 50K public SNPs from the
12-fish VCF that `snpscore fetch` downloads:

```bash
gzip -dc ../salmo-snpscore/data/raw/12_samples_genotype_filtered_on_504.vcf.gz | awk -F'\t' -v OFS='\t' '/^#CHROM/ || (!/^#/ && NR % 32 == 0) {print $1,$2,$3,$4,$5,$6,$7,$8}' > /tmp/public_50k.vcf
```

The trait preset, tab and filters live in the URL, so a view can be bookmarked or shared; the download follows them.
`SNPPORTAL_TEST_RELEASE=<folder>` makes the tests reuse (a copy of) a release already built from the fixture.
`SNPSCORE_DEV=1` adds a load check: the 1.6M-site public VCF scored on the background pool against release/dev
(about 85 s here; the POST returns at once).

`sandbox/` is a minimal Django project for development only. Its `templates/salmobase/base.html` stands in for
salmobase's real base template. It serves static files while `DEBUG` is on.

## How it works

Every upload, pasted list, example or candidate list is a **job**: a folder `results/<uuid>/` (mode 0700, files 0600)
annotated by a small thread pool (`jobs.py`). The upload streams straight into the results dir (never memory or the
system temp dir), and the POST redirects to the results URL, which shows a progress panel that htmx polls every second.
The folder holds:

| File | What |
| --- | --- |
| `job.json` | state (queued/running/done/failed), stage, n_rows, heartbeat, timings, error_code, input kind/format/sha256, release, manifest and weights sha256, snpscore and DuckDB versions, created_utc, preset (written atomically) |
| `input.<ext>` | the uploaded list, deleted as soon as annotation ends |
| `result.parquet` | `snpscore.annotate` output |
| `tiers.parquet` | `file_row_number` + `tier__<preset>`, `tier_score__<preset>`, `tier_evidence__<preset>`, `tier_terms__<preset>` for every preset, so switching presets never rescores |
| `summary.json` | everything the overview draws (tiers, bins, conditions, regions, terms, MAF, assay status and reasons, known-locus and molQTL counts, gaps per preset): see `jobs.summarise` |
| `validation.json`, `rejects.tsv` | snpscore's upload QC and dropped rows (shown on the results page; rejects downloadable) |
| `weights.yaml`, `manifest.json` | snapshot of the release: editing the release never changes an existing job, and a banner says when it changed |
| `panels/<hash>.parquet`, `.json` | each panel designed on the Panel tab (folder 0700): the result columns plus `source_row`, `selection_reason`, `panel_rank`, `design_score` (and the chip columns); the .json holds hash, preset, params, summary, chip label. hash = `snpscore.panel.params_hash` of the preset, parameters, weights sha256 and chip sha256, so the same URL gives the same file |
| `chip.parquet`, `chip.json` | the reference chip of the Panel tab (chrom, pos, id), and its label, SYNTHETIC flag, kept/rejected rows, sha256, density per Mb and the comparison per preset |
| `sumstats.parquet`, `gwas.parquet`, `gwas.json` | GWAS jobs (`input_kind` gwas): the summary statistics as read, harmonised to Ssal_v3.1, and the upload QC report (see snpscore README "GWAS") |

A job whose heartbeat is older than 5 minutes (server restarted) is marked failed; more than 10 queued jobs give 503.
`jobs.create_from_rows(rows, label)` makes a job from `(chrom, pos, id, ref, alt)` tuples (gene and interval lists, the
tour example). `job.json` `input_kind` is `snps`, `gwas` or `from_rows`.

Pages (under `/snp/`; view state lives in whitelisted URL parameters, so every view can be bookmarked):

| URL | What |
| --- | --- |
| `results/<key>/?tab=overview\|table\|panel\|export&trait=` | the results tabs; Table filters (`tier`, `region`, `chrom/start/end`, `gene`, `min_maf`, `assay`, `known`, `active`, `term`, `hide_*`) carry over to the Export tab; GWAS jobs add an Association tab |
| `results/<key>/?tab=panel&design=1&n=&spacing_kb=&spacing_cm=&cm_map=&backbone=&maf=&per_gene=&per_element=&assay_pass=1&exclude=&must=&gap_mb=` | panel designer (blank or invalid values fall back to weights.yaml `design`; `spacing_cm` and `cm_map` (mean, female, male) only with the `cm` columns) |
| `results/<key>/chip/` (POST) | `chip` file, `demo=1` or `remove=1` |
| `results/<key>/download/?format=tsv\|parquet\|bed\|illumina\|axiom\|kasp\|bundle&scope=all\|filtered\|panel-<hash>` | exports with provenance (`&plain=1` drops it, `&include_failed=1` keeps assay failures in vendor files); vendor files hold no comment lines, so `format=<vendor>.provenance` and `.lookup` give snpscore's sidecars; `format=rejects` gives the dropped rows |
| `results/<key>/report/?trait=[&filters][&panel=<hash>]` | one-page printable report (two A4 pages) |
| `results/<key>/figure/<name>.svg`, `results/<key>/tools/<name>.svg` | overview and Panel-tab figures (`&format=tsv` for their data) |
| `results/<key>/association/` (+ `<name>.svg`, `download/`, `region/`) | GWAS jobs: QC, Manhattan, QQ, loci, fine-mapping, regional plot |
| `results/<key>/snp/<row>/`, `variant/<chrom>-<pos>[-ref-alt]/`, `locus/?r=[&key=]`, `gene/<id>/` | evidence card, variant page, locus browser (with a GWAS job's key it draws the association lane), gene page |
| `score/`, `score/gwas/`, `candidates/`, `tour/`, `known-loci/`, `search/`, `about/data/`, `about/methods/`, `help/`, `run-locally/` | the other pages |
| `colours/?name=portal\|aquafaang` | the footer's chromatin-colour toggle: sets the `snpportal_palette` cookie, back to the (same-site) referring page |

Search (`search.py`): positions and regions, rs IDs (the catalogue's, else `snpscore.rsid` on the release's EVA release 9
table, with the ICSASG_v2 position in the hit), ICSASG_v2 positions (`ICSASG_v2 25:28656101`, `v2 ssa25:...` or a v2
GenBank accession such as `CM003303.1:28656101`: the Ssal_v3.1 variant of the rs ID at that v2 position in `rsid.parquet`),
genes by Ensembl id or name, catalogue name, NCBI LOC symbol (only where Ensembl's description cites the NCBI gene id:
about 1,700 of 59,000 genes), ortholog symbol or description. Help documents rs-ID-only uploads (`#format-rsid`).

Public data on the pages (R1, R3-R8 of salmo-snpscore's ROADMAP 'Push 2'):
- Public allele frequencies are the 504-fish reference panel's (`public_af_af`, `_maf`, `_ac`, `_an`, `_ns`); the 12
  AQUA-FAANG fish's AF and DR2 are shown apart, labelled 'AQUA-FAANG 12 fish'. The card's scope line quotes the
  manifest's `population`. Gene pages and candidate lists name their site source (the release pool's VCF, else the panel).
- Known loci (`catalog/known_loci.tsv`): the Known loci page groups the rows by trait, with evidence badges (missense,
  GWAS lead, QTL marker, gene region; effect allele; caveats such as suggestive, strain-specific or position inferred,
  from the catalogue's evidence and caveat text). The card lists the nearest row and every other row within the
  catalogue window; the locus browser draws them in a 'Published' lane (filled diamond = effect allele stated).
- molQTL (`molqtl` columns): a card section (tissue, eQTL or caQTL, gene or peak, eigenMT-adjusted p, pi without a
  direction, citation and licence note), a Table column and the 'molQTL lead SNPs' filter (`molqtl=1`), an Overview
  KPI and a locus-browser lane (read from `molqtl.parquet`). Weight 0: never counted in tiers.
- Genetic map: the card shows female and male cM, the Table a 'cM (F/M)' column, and the panel designer a 'Min spacing
  (cM)' field with the map to use (`snpscore.panel.design(min_spacing_cm=, cm_map=)`; a median cM spacing KPI), when the
  `cm` columns exist.
- Vendor checks (`tools.vendor_checks` = `snpscore.panel.vendor_checks`): the Panel tab, the report's panel summary and
  every Export-tab scope that vendor files can be written for show the Illumina Infinium bins (A/T, C/G, the rest) and
  their error 111 / warning 604 minimums, and markers within 60 bp; alleles are the list's, else the assay flank's
  (public) ones, as in the vendor files. The Export tab explains the `Ssa<chrom>p<pos>` locus names and the
  `.provenance.txt` and `.lookup.tsv` sidecars.
- Upload QC: chromosome-name warnings (e.g. `HG993277.1`, an older chromosome 18) as alerts; `.2` GenBank names are
  accepted; the assay-reasons figure labels snpscore's reasons.
- Data page: layer population and licence, the AQUA-FAANG samples (ENA projects, BodyMap fish) and a 'How to cite'
  block (wording PROVISIONAL). Gene pages, cards and the Known loci page link to SalmoBase gene pages.
- State colours: `palette.STATE_PALETTES` has the portal palette and AQUA-FAANG's itemRgb colours;
  `SNPPORTAL_STATE_PALETTE = 'aquafaang'` makes AQUA-FAANG's the default for every page and figure (G to choose), and
  the footer's 'Chromatin colours' links switch it per viewer (a cookie read on `request_started`, kept in a
  `ContextVar` for that request; apps.py). Help shows both side by side.

Modules: `views.py` (score page, job status, results shell, downloads, delete), `results.py` (overview, table and
filters, figures), `locus.py` (locus browser, evidence card, variant page; `locus_svg.py` draws them), `explore.py`
(landing, gene pages, known loci, candidate jobs, tour), `search.py` (resolver), `about.py` (data, methods, help, run
locally), `tools.py` (Panel tab: panel designer and chip comparison; Export tab and every export format, via
`snpscore.panel` and `snpscore.export`), `report.py` (printable report), `association.py` (GWAS upload, Association
page, regional plot), `figures.py` (pure functions data -> SVG), `palette.py` (every colour). Templates extend `base_portal.html` and use the partials `_page_header`,
`_figure`, `_badges` and `_footer`; styles are in `static/snpportal/portal.css`, small enhancements in `portal.js`.

**Design rules.** Colours come only from `palette.py`: HTML gets CSS custom properties, SVGs embed literal hex (so
saved files keep their colours). No colours or inline styles in templates (a test checks). Every SVG has `role="img"`,
`<title>` and `<desc>`; text colours pass WCAG AA (a test checks); focus is always visible.

**Privacy.** Results pages (also their 404s) send `Cache-Control: no-store, private` and `Referrer-Policy: same-origin`;
error reports from them and from the Score page carry no POST values, uploaded file names, local variables or DuckDB
message text; outbound links use `rel="noreferrer"`. Failed jobs are locked down (0600) like finished ones. Log lines carry an event
name, `job_ref` (a hash of the key), counts and timings: never SNPs or file names. Exports are written to a temp file
in the job folder that is removed as soon as it is opened. Every export carries provenance (release, manifest and
weights sha256, preset, filters, panel hash, PROVISIONAL rules, SYNTHETIC inputs or chip, the equivalent `snpscore`
command): `#` lines in text files (`?plain=1` drops them), Parquet key-value metadata, `provenance.txt` in the bundle.
Vendor files say 'layout to confirm against the vendor's current template'.

## Merging into salmobase

1. Copy `snpportal/` into `salmobase/salmobase/`.
2. `settings.py`: add `"snpportal"` to `INSTALLED_APPS` and `SNPSCORE_RELEASE = getenv("SNPSCORE_RELEASE")`. Optional
   settings (defaults): `SNPPORTAL_RESULTS_DIR` (`<system temp>/snpportal`), `SNPPORTAL_KEEP_HOURS` (24),
   `SNPPORTAL_WORKERS` (1 background thread per process; 0 runs jobs inline), `SNPPORTAL_MAX_UPLOAD_MB` (300, checked
   before the body is read), `SNPPORTAL_MAX_SNPS` (3,000,000), `SNPPORTAL_DUCKDB_THREADS` (2), `SNPPORTAL_DUCKDB_MEMORY` (2GB),
   `SNPPORTAL_TRACKS` (a tracks.yaml overriding the release's), `SNPPORTAL_STATE_PALETTE` (`portal`, or `aquafaang`
   for AQUA-FAANG's own state colours; viewers can switch), `SNPPORTAL_SIGNAL_DEADLINE` (4.0 s for live signal
   rows), `SNPPORTAL_MAX_VENDOR_SNPS` (50,000 SNPs per Illumina/Axiom/KASP file or bundle; larger requests get a 400) and a `CACHES['snpportal_tiles']` entry for the locus browser's public tiles (else a per-process LocMemCache;
   `sandbox/settings.py` shows a FileBasedCache).
3. `urls.py`: `path('snp/', include('snpportal.urls'))`. Run `collectstatic` for `snpportal/portal.css` and `portal.js`.
4. `requirements.txt`: add `duckdb` and `snpscore @ git+<salmo-snpscore repo URL>`.
5. Put a release under `/datafiles` (e.g. `/datafiles/snpscore/v0.1`) and set `SNPSCORE_RELEASE` in docker-compose.
6. Cron: `python manage.py snpportal_cleanup` (hourly). Results pages also clean up as they are viewed.

The job queue and heartbeats are per process (fine under mod_wsgi or gunicorn for the prototype).
salmobase's Docker image uses Python 3.8, which limits DuckDB to 1.2.2 and Django to 4.2. Both are tested and work.
