# salmo-snpportal

Django app for salmobase.org: score a SNP list against AQUA-FAANG functional maps and tier it for a trait, then explore
the result (overview, filterable table, evidence card per SNP), design a genotyping panel, compare it with an existing
chip, export it (TSV, Parquet, BED, Illumina-, Axiom- and KASP-style files, genomic-prediction priors, or a zip bundle) and
print a one-page report.
GWAS summary statistics get an Association page (Manhattan, tier-stratified QQ, loci, regional plot and fine-mapping
with a functional prior). Without a list: search (genes, NCBI LOC symbols, rs IDs, positions), gene pages, a locus
browser with live salmobase signal, published associations and molQTL leads, the known-loci catalogue (36 published SNPs
and a gene region across 8 traits, with evidence badges) and a guided tour (an illustrated slide show). All annotation logic lives in the sibling repo
[salmo-snpscore](../salmo-snpscore); this app handles upload, jobs, display and export.

## Run locally

```bash
pip install -r requirements.txt                       # also installs ../salmo-snpscore (editable)
cd ../salmo-snpscore
snpscore fetch                                        # the public inputs, into data/raw
bash prep/make_demo.sh                                # the examples (layers.yaml 'demo'): 50K public sites, the
                                                      # SYNTHETIC demo chip and the SYNTHETIC maturation GWAS
snpscore build --out release/dev                      # copies the examples that exist into release/dev/demo/
cd ../salmo-snpportal
python manage.py runserver                            # http://127.0.0.1:8000/snp/
python manage.py test snpportal                       # builds a release from salmo-snpscore's fixture
```

`snpscore build` copies only the examples that exist, so run it again after making them. To try the portal, use the
'Try it' box at the top of the Score page (the release's `demo/` inputs: known loci, the SYNTHETIC demo chip and the
SYNTHETIC maturation GWAS; `example=public_50k` still works but is not offered), paste a few positions or rs IDs, upload
`../salmo-snpscore/tests/fixture/snps.vcf`, or follow the guided tour (`/snp/tour/`). The Score card's tabs (Upload SNPs,
Paste positions, Genes or regions, GWAS) open with `?input=file|paste|regions|gwas` (or `#gwas`). On a results page,
the Panel tab's 'Use the demo chip' button compares the list with the SYNTHETIC demo chip.
`python manage.py tour_images [--base http://localhost:8000/snp/]` retakes the tour's screenshots (`static/snpportal/tour/`)
from a running portal with headless Chrome (`--chrome` or `CHROME` if it is not in the usual place).

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
| `chip_rows_<sha>.parquet` | `file_row_number`, `on_chip`, `dist_to_chip`, `near_chip` of every SNP for that chip (`results.chip_view`, made once from chrom and pos); pages that use the chip columns join it by row number (`novel_functional` = tier 1-2 and not near the chip) |
| `sumstats.parquet`, `gwas.parquet`, `gwas.json` | GWAS jobs (`input_kind` gwas): the summary statistics as read, harmonised to Ssal_v3.1, and the upload QC report (see snpscore README "GWAS") |
| `loci/<hash>.json`, `.parquet` | GWAS jobs: the loci (the `association.MAX_LOCI` = 200 strongest, and how many there are) and the fine-mapping table of one trait and settings; hash = `params_hash` of the trait and settings, so each page reads them instead of clumping again |

A job whose heartbeat is older than 5 minutes (server restarted) is marked failed; more than 10 queued jobs give 503.
`jobs.create_from_rows(rows, label)` makes a job from `(chrom, pos, id, ref, alt)` tuples (gene and interval lists). `job.json` `input_kind` is `snps`, `gwas` or `from_rows`.

Pages (under `/snp/`; view state lives in whitelisted URL parameters, so every view can be bookmarked):

| URL | What |
| --- | --- |
| `results/<key>/?tab=overview\|table\|panel\|export&trait=` | the results tabs. `trait` is a weights.yaml preset or an Active-in key (tissues joined by `+`, then `.Immature`/`.Mature` and `.Female`/`.Male`, e.g. `Brain+Gonad.Mature`), which the Table's Active in sets (its form sends `active_set`, `tissue`, `maturity`, `sex`, `act`); in the Table, a trait other than `all` also keeps only SNPs in an element of at least one of its conditions (`act=peak`, the default: an ATAC peak; `act=active`: an active TSS or enhancer state); a key with a preset's conditions becomes that preset, any other is scored on first view (`tiers_<key>.parquet`, `summary_<key>.json` in the job folder). Table filters (`tier`, `region`, `chrom/start/end`, `gene`, `min_maf`, `assay`, `known`, `active` (one condition), `hide_*`; `tier`, `region`, `assay` and `term` take several values, comma-joined or repeated: any of them; `region` is the Consequence column's filter: missense (protein-changing), synonymous, cds, splice, utr5, utr3, exon, intron, intergenic, and the Overview's groups coding and UTR) are the Table's selection, kept per job (`selection.json`): the Table tab link returns to it, the Panel designs from it and compares it with a chip, the Export tab offers it ('Table selection'); the Overview always shows the whole list with tiers for all conditions, and its links start a new selection. Each filter sits on its column (a funnel in the header, `_dd.html`); filters of hidden columns form the bar above the table. The selector column (+/−) takes single SNPs out of the selection by hand (`exclude=<row>`, `include=<row>`, `include_all=1`; kept in `unselected.json`): the Table still lists them, dimmed (`picked=in|out` shows only + or only −), and the Panel, Export, downloads and Add to panel leave them out. `&snp=<row>` opens the SNP's card in the Table's drawer; GWAS jobs have Association, Overview, Table and Export (no Panel), and every link of theirs keeps the fine-mapping settings (`sig`, `sugg`, `window`, `prior_sd`, `lam`, `trait_sd`) |
| `results/<key>/?tab=panel&design=1&n=&spacing_kb=&spacing_cm=&cm_map=&backbone=&maf=&per_gene=&per_element=&assay=&exclude=&gap_mb=` | panel designer as a link (blank or invalid values fall back to weights.yaml `design`; `spacing_cm` and `cm_map` (mean, female, male) only with the `cm` columns) |
| `results/<key>/panel/` (POST) | the designer's form, the same fields plus `must` (must-include ids, which never go in a URL): designs the panel and redirects to `?tab=panel&panel=<hash>`, which shows a saved panel with its parameters (for another trait: the same parameters) |
| `results/<key>/chip/` (POST) | `chip` file, `demo=1` or `remove=1` |
| `results/<key>/download/?format=tsv\|parquet\|bed\|illumina\|axiom\|kasp\|bundle\|priors&scope=all\|filtered\|panel-<hash>` | exports with provenance (`&plain=1` drops it, `&include_failed=1` keeps assay failures in vendor files); vendor files hold no comment lines, so `format=<vendor>.provenance` and `.lookup` give snpscore's sidecars; `format=rejects` gives the dropped rows |
| `panel/`, `panel/change/` (POST), `panel/download/?format=tsv\|kasp\|illumina\|axiom[&scope=new]`, `results/<key>/add-to-panel/` (POST) | Design panel: a curated panel of whole Table selections from any results ('Add to panel', the cart), compared with an existing chip, its assay readiness and vendor files (all, or the SNPs not on the chip). One browser's only (an HttpOnly cookie names its folder `results/panel-<uuid>`, never a URL), deleted 24 hours after it was started (its `created` marker); its TSV, scored again, brings it back |
| `score/current/` | the nav's Score: the results this browser last opened (a cookie), else the Score page |
| `results/<key>/report/?trait=[&filters][&panel=<hash>]` | one-page printable report (two A4 pages) |
| `results/<key>/figure/<name>.svg`, `results/<key>/tools/<name>.svg` | overview and Panel-tab figures (`&format=tsv` for their data) |
| `results/<key>/association/` (+ `<name>.svg`, `download/`, `region/`) | GWAS jobs: QC, Manhattan, QQ, loci, fine-mapping, regional plot |
| `results/<key>/snp/<row>/`, `variant/<chrom>-<pos>[-ref-alt]/`, `locus/?r=[&key=]`, `gene/<id>/` | a job's SNP (opens its card in the Table's drawer, `?snp=`), variant page, locus browser (with a GWAS job's key it draws the association lane), gene page |
| `score/`, `score/gwas/`, `candidates/`, `tour/`, `known-loci/`, `search/`, `about/data/`, `about/methods/`, `help/`, `run-locally/` | the other pages |
| `colours/?name=portal\|aquafaang` | the locus browser's chromatin-colour toggle (Display options): sets the `snpportal_palette` cookie, back to the (same-site) referring page |

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
  direction, citation and licence note), a Table column and the 'molQTL lead SNPs' filter (`molqtl=1`) and a
  locus-browser lane (read from `molqtl.parquet`). Weight 0: never counted in tiers.
- Genetic map: the card shows female and male cM, the Table a 'cM (F/M)' column, and the panel designer a 'Min spacing
  (cM)' field with the map to use (`snpscore.panel.design(min_spacing_cm=, cm_map=)`; a median cM spacing KPI), when the
  `cm` columns exist.
- Vendor checks (`tools.vendor_checks` = `snpscore.panel.vendor_checks`): each Export-tab vendor row shows its own
  include count and checks (Illumina Infinium bins, markers within 60 bp, alleles unknown), and the zip adds
  `vendor_checks.txt`; alleles are the list's, else the assay flank's (public) ones, as in the vendor files. Help
  (`#exports`) explains the `Ssa<chrom>p<pos>` locus names, the bins' error 111 / warning 604 minimums and the
  `.provenance.txt` and `.lookup.tsv` sidecars.
- Coding consequences (`coding_*` columns, snpscore's VEP-lite): the Table's and the Panel's Region cell shows the
  consequence (missense, synonymous, stop gained, splice donor, ..., tooltip `p.Thr46Met · <transcript>`; a bare CDS
  says 'amino-acid effect not computed: <reason>' in its tooltip); the Region filter (More filters) adds
  `region=missense` ('protein-changing': missense, stop and start changes) and `region=synonymous`; the card's tier line
  and the Table's drawer name it (`results.tier_parts`: `Missense p.Thr46Met (ENSSSAT00000230965; published as
  Met54Thr) +3`, the published label when the catalogue's residue or direction differs, one- or three-letter), the
  'why this tier' bar labels it (`missense +3`) and the card's closed Details add the transcript and codons; the variant
  page gets the same through `snpscore.locus.annotate_position` (a position only: the 504-fish panel's alleles).
- Genomic-prediction priors: the Export tab's closed 'More formats' offers `format=priors` (snpscore's zip of BayesRC
  classes, GFBLUP/MultiBLUP sets, LDAK partitions and an annotation matrix), always for all SNPs (`scope=all`, whatever
  the selected scope: genomic prediction needs a class for every genotyped SNP).
- Benchmark: with `benchmark_molqtl.tsv` in the release, Methods shows one enrichment figure (log2 axis, 95% intervals)
  for known loci, caQTL and eQTL leads against matched controls, with `?download=benchmark.svg` and
  `benchmark_figure.tsv` (their '#' lines and `<desc>`: provenance, the PROVISIONAL tier rules and the release TSVs'
  own '#' lines), and one line under it: the known loci were partly chosen as missense, so their CDS enrichment is not a
  validation; without it, the one-line 'not yet validated' note stays.
- Upload QC: chromosome-name warnings (e.g. `HG993277.1`, an older chromosome 18) as alerts; `.2` GenBank names are
  accepted; the Panel tab's Assay readiness card labels snpscore's reasons.
- Data page: layer population and licence, the AQUA-FAANG samples (ENA projects, BodyMap fish) and a 'How to cite'
  block (wording PROVISIONAL). Gene pages, cards and the Known loci page link to SalmoBase gene pages.
- State colours: `palette.STATE_PALETTES` has the portal palette and AQUA-FAANG's itemRgb colours;
  `SNPPORTAL_STATE_PALETTE = 'aquafaang'` makes AQUA-FAANG's the default for every page and figure (G to choose), and
  the locus browser's Display options switch it per viewer (a cookie read on `request_started`, kept in a
  `ContextVar` for that request; apps.py). Methods shows the colours in its chromatin-state table.

Modules: `views.py` (score page, job status, results shell, downloads, delete), `results.py` (overview, table and
filters, figures), `locus.py` (locus browser, evidence card, variant page; `locus_svg.py` draws them), `explore.py`
(landing, gene pages, known loci, candidate jobs, tour), `search.py` (resolver), `about.py` (data, methods, help, run
locally), `tools.py` (Panel tab: panel designer and chip comparison; Export tab and every export format, via
`snpscore.panel` and `snpscore.export`), `report.py` (printable report), `association.py` (GWAS upload, Association
page, regional plot), `figures.py` (pure functions data -> SVG), `palette.py` (every colour). Templates extend `base_portal.html` and use the partials `_page_header`,
`_figure`, `_badges` and `_footer`; styles are in `static/snpportal/portal.css`, small enhancements in `portal.js`.

**Design rules.** Colours come only from `palette.py`: HTML gets CSS custom properties, SVGs embed literal hex (so
saved files keep their colours). No colours or inline styles in templates (a test checks). Pages that show tiers
carry one caveat line (`_caveat.html`, starting 'SYNTHETIC data' on synthetic jobs) instead of PROVISIONAL or SYNTHETIC
badges; figure cards show a title, an (i) and one download menu, with provenance only in the SVG's `<desc>` and the
downloads. Every SVG has `role="img"`,
`<title>` and `<desc>`; text colours pass WCAG AA (a test checks); focus is always visible. Checked for colour blindness
(deuteranopia, protanopia, tritanopia; no tier or portal-palette pair collides only under CVD; 'Ensembl regulatory' in
the 'why this tier' bar is `palette.REGBUILD`, Okabe-Ito sky blue). Below 992 px, figures drawn 1200 px wide keep 0.8x
and scroll sideways in their card; at 992-1199 px 'More charts' stack one per row. Print: the card fits one A4 page
(10pt root, closed sections left out), the report two (8.5pt); salmobase's nav, header and footer and Copy buttons
never print. Checked in headless Chrome only (not Safari or Firefox print, not touch tablets).

**Privacy.** Results pages (also their 404s) send `Cache-Control: no-store, private` and `Referrer-Policy: same-origin`;
error reports from them and from the Score page (also its 'Genes or regions' list) carry no POST values, uploaded file
names, local variables or DuckDB message text; outbound links use `rel="noreferrer"`. Must-include ids are POSTed, never
put in a URL. The locus browser opened from a job (`key=`) only reads the tile cache, so the cache (kept for days) never
records where a job's SNPs are. 'Delete now' on a running job removes its job.json at once and the folder when the
worker's DuckDB connection has closed (the folder is its spill directory); the portal's own connections (read-only
ones too) spill into `results/.spill-<uuid>`, removed when they close. Failed jobs are locked down (0600) like finished ones. Log lines carry an event
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
   rows), `SNPPORTAL_MAX_VENDOR_SNPS` (50,000 SNPs per Illumina/Axiom/KASP file or bundle; larger requests get a 400),
   `SNPPORTAL_MAX_CHIP_SNPS` (1,000,000 chip markers, at most `SNPPORTAL_MAX_SNPS`; longer chips are refused) and a `CACHES['snpportal_tiles']` entry for the locus browser's public tiles (Redis or Memcached on a server, not the
   file-based cache, which lists its folder on every write; a view with the functional assays open writes ~3,000 tiles; else a per-process LocMemCache;
   `sandbox/settings.py` shows a FileBasedCache).
3. `urls.py`: `path('snp/', include('snpportal.urls'))`. Run `collectstatic` for `snpportal/portal.css` and `portal.js`.
4. `requirements.txt`: add `duckdb` and `snpscore @ git+<salmo-snpscore repo URL>`.
5. Put a release under `/datafiles` (e.g. `/datafiles/snpscore/v0.1`) and set `SNPSCORE_RELEASE` in docker-compose.
6. Cron: `python manage.py snpportal_cleanup` (hourly). Results pages also clean up as they are viewed.

The job queue and heartbeats are per process (fine under mod_wsgi or gunicorn for the prototype).
salmobase's Docker image uses Python 3.8, which limits DuckDB to 1.2.2 and Django to 4.2. Both are tested and work.
