# snpportal

The salmo-snp web portal (a Django app, linked from salmobase.org): score a SNP list against AQUA-FAANG functional maps and tier it by its evidence in all 21
sample conditions, then explore the result (overview, a table filtered on its columns, an evidence card per SNP in the
table's drawer), collect selections in a Design panel, compare it with an existing chip, export it (TSV, Parquet, BED, Illumina-, Axiom- and KASP-style files, genomic-prediction priors, or a zip bundle) and
print a one-page report.
GWAS summary statistics get an Association page (Manhattan, tier-stratified QQ, loci, regional plot and fine-mapping
with a functional prior). Without a list: search (genes, NCBI LOC symbols, rs IDs, positions), gene pages, a locus
browser with live salmobase signal, published associations and molQTL leads, the known-loci catalogue (39 published SNPs
and a gene region across 8 traits, with evidence badges) and a guided tour (an illustrated slide show). Scoring lives in
[snpscore/](../snpscore) and the release it reads is built by [snpdata/](../snpdata) (same repository); this app handles
upload, jobs, display and export, with its plain-Python parts in `snpportal/lib/`.

## Run locally

```bash
pip install -r requirements.txt -e ../snpdata        # also installs ../snpscore (editable); snpdata for the build and tests
cd ../snpdata
snpdata fetch                                         # the public inputs, into data/raw
bash prep/make_demo.sh                                # the examples (layers.yaml 'demo'): 50K public sites, the
                                                      # SYNTHETIC demo chip and the SYNTHETIC maturation GWAS
snpdata build --out release/dev                       # copies the examples that exist into release/dev/demo/
snpscore pool --release release/dev --background data/raw/12_samples_genotype_filtered_on_504.vcf.gz
cd ../snpportal
python manage.py runserver                            # http://127.0.0.1:8000/snp/
python -m pytest -q tests                             # snpportal.lib
SNPPORTAL_WORKERS=0 python manage.py test snpportal   # the pages; builds a release from snpdata/tests/fixture
```

`snpdata build` copies only the examples that exist, so run it again after making them. To try the portal, use the
Examples on the Score page, which is the home page `/snp/` (the release's `demo/` inputs: known loci, the SYNTHETIC demo chip and the
SYNTHETIC maturation GWAS; `example=public_50k` still works but is not offered), paste a few positions or rs IDs, upload
`../snpdata/tests/fixture/snps.vcf`, or follow the guided tour (`/snp/tour/`). The Score page's tabs (Upload SNPs,
Paste positions, Genes or regions, GWAS) open with `?input=file|paste|regions|gwas` (or `#gwas`). On the Design panel,
'Use the demo chip' compares the panel with the SYNTHETIC demo chip.
`python manage.py tour_images [--base http://localhost:8000/snp/]` retakes the tour's screenshots (`static/snpportal/tour/`)
from a running portal with headless Chrome (`--chrome` or `CHROME` if it is not in the usual place), in one fresh
profile: it scores the examples, adds the known loci to that profile's Design panel with the demo chip, and writes
`tour.css` with each callout's box. Retake them after changing a page the tour shows; `tests_tour` checks every slide has
its image and boxes.

The tab and the Table's filters live in the URL, so a view can be bookmarked or shared; the download follows them.
`SNPPORTAL_TEST_RELEASE=<folder>` makes the tests reuse (a copy of) a release already built from the fixture.
`SNPSCORE_DEV=1` adds a load check: the 1.6M-site public VCF scored on the background pool against release/dev
(about 85 s here; the POST returns at once).

`sandbox/` is a minimal Django project for development only. Its `templates/salmobase/base.html` stands in for
salmobase's real base template. It serves static files while `DEBUG` is on.

## Public demo (NREC)

The demo runs at **https://158.39.75.9/snp/** (also https://158-39-75-9.sslip.io/snp/); redeploy with
`bash deploy/nrec.sh nrec 158.39.75.9 158-39-75-9.sslip.io`. Until 2026-10-28 it was at 158.39.200.140, before the
VM lost its network port and got a new address.

`bash deploy/nrec.sh <ssh host> <web name> [<web name> ...]` puts the portal on an NREC VM (GOLD Ubuntu 22.04 on the `dualStack`
network, so it has a public IPv4 address; ports 22, 80 and 443 open). From this Mac it copies snpscore/ and snpportal/ (code only),
`release/dev` and the genome to `/srv/snpportal`; on the VM it installs Django 4.2, DuckDB 1.2.2 and gunicorn in a
venv, Caddy for HTTPS (a site per name: an IPv4 address gets Let's Encrypt's short-lived IP certificate, renewed by
Caddy; a `<ip-with-dashes>.sslip.io` name works too) and systemd units for the app
(`snpportal`) and an hourly `snpportal_cleanup`. Rerun it after a change: results and the secret key are kept. The
sandbox project serves the demo with `DJANGO_DEBUG=0` and the settings in `/srv/snpportal/env`; `SNPSCORE_GENOME`
points snpscore at the VM's genome copy. Logs: `journalctl -u snpportal`.

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
| `panels/<hash>.parquet`, `.json` | each panel designed on the (unlinked) Panel tab (folder 0700): the result columns plus `source_row`, `selection_reason`, `panel_rank`, `design_score` (and the chip columns); the .json holds hash, preset, params, summary, chip label. hash = `snpscore.panel.params_hash` of the preset, parameters, weights sha256 and chip sha256, so the same URL gives the same file |
| `chip.parquet`, `chip.json` | the reference chip of the (unlinked) Panel tab (chrom, pos, id), and its label, SYNTHETIC flag, kept/rejected rows, sha256, density per Mb and the comparison per preset |
| `chip_rows_<sha>.parquet` | `file_row_number`, `on_chip`, `dist_to_chip`, `near_chip` of every SNP for that chip (`results.chip_view`, made once from chrom and pos); pages that use the chip columns join it by row number (`novel_functional` = tier 1-2 and not near the chip) |
| `sumstats.parquet`, `gwas.parquet`, `gwas.json` | GWAS jobs (`input_kind` gwas): the summary statistics as read, harmonised to Ssal_v3.1, and the upload QC report (see snpscore README "GWAS") |
| `loci/<hash>.json`, `.parquet` | GWAS jobs: the loci (the `association.MAX_LOCI` = 200 strongest, and how many there are) and the fine-mapping table of one trait and settings; hash = `params_hash` of the trait and settings, so each page reads them instead of clumping again |

A job whose heartbeat is older than 5 minutes (server restarted) is marked failed; more than 10 queued jobs give 503.
`jobs.create_from_rows(rows, label)` makes a job from `(chrom, pos, id, ref, alt)` tuples (gene and interval lists). `job.json` `input_kind` is `snps`, `gwas` or `from_rows`.

Pages (under `/snp/`; view state lives in whitelisted URL parameters, so every view can be bookmarked):

| URL | What |
| --- | --- |
| `results/<key>/?tab=overview\|table\|export` | the results tabs (`tab=panel`, the automatic designer, still works but is no longer linked: the Design panel page is the curated panel). Tiers always count all 21 conditions (no Active in, no condition picker; an older link's `trait` is ignored): the Table only filters after scoring. Table filters (`tier`, `region`, `chrom/start/end`, `gene`, `min_maf`, `assay`, `known`, `min_score` (the Score column's slider), `hide_*`; Chromatin: `tissue` (several), `maturity`, `sex` and `act=active`, SNPs in a robust ATAC peak (or an active state) in at least one of those conditions, a filter only; `tier`, `region`, `assay` and `term` take several values, comma-joined or repeated: any of them; `region` is the Consequence column's filter: missense (protein-changing), synonymous, cds, splice, utr5, utr3, exon, intron, intergenic, and the Overview's groups coding and UTR) are the Table's selection, kept per job (`selection.json`): the Table tab link returns to it, the Panel designs from it and compares it with a chip, the Export tab offers it ('Table selection'); the Overview always shows the whole list with tiers for all conditions, and its links start a new selection. Each filter sits on its column (a funnel in the header, `_dd.html`); a hidden column has no filter (Columns shows it) and a filtered column always shows; Flags is a default column. The selector column (+/−) takes single SNPs out of the selection by hand (`exclude=<row>`, `include=<row>`, `include_all=1`; kept in `unselected.json`): the Table shows only the + rows unless asked (`picked=out`: only −; `picked=all`: both, the − dimmed), and the Panel, Export, downloads and Add to panel leave them out. `&snp=<row>` opens the SNP's card in the Table's drawer: a bar with its +/− switch (key x) and the previous and next rows of the table (keys k and j, across pages), then one top row (+/−, tier, SNP, gene, copy, previous/next), the score (a block per evidence term, as wide as its points, largest first, labelled like a chip, with dashed lines at the tier cut-offs and = score on the right), the key facts under it (not what a block or the heading says; a GWAS job's p, beta and PIP), caveats and foldable sections: the functional evidence at the locus (a mini locus browser of the SNP +- 10 kb: your SNPs (faded when not selected), genes, public variants, GERP and robust ATAC peaks, with the SNP's peak per condition in a wedge under it), TF motifs (when the SNP changes a JASPAR 2024 motif: up to three logos on the + strand where they sit, the reference sequence with the SNP's column outlined and its alt allele under it, both alleles' scores against the match cut-off; `locus.motif_hits` recomputes them from the release's motif.meme and the genome), as a marker (its header: the assay check, GC, MAF, LORe, A/T or C/G; the flank in a box (a copy icon beside it) with long runs underlined and public variants' offset, alleles and MAF on hover; one duplicate-copy line; the Design panel and its chip), and context; a SNP taken out stays in the table while its card is open; 'Open locus browser' widens the drawer over the page to the browser at that SNP (20 kb), and 'Back to the card', Esc or the browser's Back return to the card and table as they were (a lollipop of another SNP opens its card; other pages open in a new tab); GWAS jobs have Association, Overview, Table and Export, and every link of theirs keeps the fine-mapping settings (`sig`, `sugg`, `window`, `prior_sd`, `lam`, `trait_sd`) |
| `results/<key>/?tab=panel&design=1&n=&spacing_kb=&spacing_cm=&cm_map=&backbone=&maf=&per_gene=&per_element=&assay=&exclude=&gap_mb=` | panel designer as a link (blank or invalid values fall back to weights.yaml `design`; `spacing_cm` and `cm_map` (mean, female, male) only with the `cm` columns) |
| `results/<key>/panel/` (POST) | the designer's form, the same fields plus `must` (must-include ids, which never go in a URL): designs the panel and redirects to `?tab=panel&panel=<hash>`, which shows a saved panel with its parameters (for another trait: the same parameters) |
| `results/<key>/chip/` (POST) | `chip` file, `demo=1` or `remove=1` |
| `results/<key>/download/?format=tsv\|parquet\|bed\|illumina\|axiom\|kasp\|bundle\|priors&scope=all\|filtered\|panel-<hash>` | exports with provenance (`&plain=1` drops it, `&include_failed=1` keeps assay failures in vendor files); vendor files hold no comment lines, so `format=<vendor>.provenance` and `.lookup` give snpscore's sidecars; `format=rejects` gives the dropped rows |
| `panel/`, `panel/change/` (POST), `panel/download/?format=tsv\|kasp\|illumina\|axiom[&scope=new]`, `results/<key>/add-to-panel/` (POST) | Design panel: a curated panel of whole Table selections from any results ('Add to panel', the cart), compared with an existing chip, its assay readiness and vendor files (all, or the SNPs not on the chip). One browser's only (an HttpOnly cookie names its folder `results/panel-<uuid>`, never a URL), deleted 24 hours after it was started (its `created` marker); its TSV, scored again, brings it back. Two equal columns (sources, chip and downloads; at a glance and the genome figure), then the SNP list: 50 rows (`show=all`: up to 2,000), problems first (assay fail/warn, MAF below the designer's minimum, LORe, a kept neighbour within the minimum spacing) or by genome (`order=genome`); with a chip, its status per SNP (on the chip, near and how far, new) and `chip=new` for the new ones only; +/- drops a SNP by hand or puts it back (POST `drop`/`keep`, kept in panel.json 'dropped'): dropped SNPs stay in the list, dimmed, and leave the counts, figure and downloads |
| `current/` | the results this browser last opened (a cookie), else the Score page |
| `` (the home page) | the Score page: 'Your results' (a green box, only when there are any), the examples and one tab per input, each with the same hint line and Score button; beside them the tour (a screenshot of a SNP's card); it sends `no-store` when it lists results. Delete and Clear panel ask in a small dialog (`data-confirm` on the form, portal.js). 'Your results': the results this browser opened (an HttpOnly cookie, newest first; named by the uploaded file, or 'Pasted' and the time), each with its SNPs, time, a link and Delete (`results/<key>/delete/` with `next=score` comes back here) |
| `results/<key>/report/?[filters][&panel=<hash>]` | one-page printable report (two A4 pages): the Overview's numbers and the top 20 SNPs of the Table's selection, tiers for all 21 conditions |
| `results/<key>/figure/<name>.svg`, `results/<key>/tools/<name>.svg` | Overview and (unlinked) Panel-tab figures (`&format=tsv` for their data) |
| `results/<key>/association/` (+ `<name>.svg`, `download/`, `region/`) | GWAS jobs: QC, Manhattan, QQ, loci, fine-mapping, regional plot |
| `results/<key>/snp/<row>/`, `variant/<chrom>-<pos>[-ref-alt]/`, `locus/?r=[&key=]`, `gene/<id>/` | a job's SNP (opens its card in the Table's drawer, `?snp=`), variant page, locus browser (with a GWAS job's key it draws the association lane; `&embed=1`: without the site's chrome and with no Back steps, as the card drawer shows it), gene page |
| `tour/?slide=N` | the guided tour: 8 slides (overview, Score, Table, card, locus browser, Design panel, GWAS, browse and help), each a card with a screenshot and numbered callouts, between two large arrows; a click on the slide's right half goes on, on its left half back, and the arrow keys and dots work too (the last arrow is 'Start scoring', and 'Back to Score' sits by the dots) |
| `gwas/` (POST), `candidates/`, `known-loci/`, `search/`, `about/data/`, `about/methods/`, `help/`, `run-locally/` | the other pages (Run locally gives the `--trait all` command, as the portal's tiers) |
| `colours/?name=portal\|aquafaang` | the locus browser's chromatin-colour toggle (Display options): sets the `snpportal_palette` cookie, back to the (same-site) referring page |

Search (`search.py`): positions and regions, rs IDs (the catalogue's, else `snpscore.rsid` on the release's EVA release 9
table, with the ICSASG_v2 position in the hit), ICSASG_v2 positions (`ICSASG_v2 25:28656101`, `v2 ssa25:...` or a v2
GenBank accession such as `CM003303.1:28656101`: the Ssal_v3.1 variant of the rs ID at that v2 position in `rsid.parquet`),
genes by Ensembl id or name, catalogue name, NCBI LOC symbol (only where Ensembl's description cites the NCBI gene id:
about 1,700 of 59,000 genes), ortholog symbol or description. Help documents rs-ID-only uploads (`#format-rsid`).

Locus browser groups, top to bottom: Genes and variants (your SNPs, published loci, molQTL leads, genes), Public SNPs
(a combined row with a segment per dataset at each site; opened, one row per dataset with height = MAF: the 504-fish
panel, its 12 AQUA-FAANG fish, the Synchrosmolt parents; colours in `palette.SNP_SETS`), TF motifs (public SNPs in
robust peaks that change a motif match: ticks, the two largest changes enlarged in wedges below them, and from 150 bp
every changed motif's logo over the reference sequence; windows go down to 60 bp), Regulatory elements, Chromatin
states, Functional assays and Other annotation.

Public data on the pages (R1, R3-R8 of docs/ROADMAP.md 'Push 2'):
- Public allele frequencies are the 504-fish reference panel's (`public_af_af`, `_maf`, `_ac`, `_an`, `_ns`); the 12
  AQUA-FAANG fish's AF and DR2 are shown apart, labelled 'AQUA-FAANG 12 fish'. The card's scope line quotes the
  manifest's `population`. Gene pages and candidate lists name their site source (the release pool's VCF, else the panel).
- Known loci (`catalog/known_loci.tsv`): the Known loci page groups the rows by trait, with evidence badges (missense,
  GWAS lead, QTL marker, gene region; effect allele; caveats such as suggestive, strain-specific or position inferred,
  from the catalogue's evidence and caveat text). The card lists the nearest row and every other row within the
  catalogue window; the locus browser draws them in a 'Published' lane (filled diamond = effect allele stated).
- molQTL (`molqtl` columns): a card section (tissue, eQTL or caQTL, gene or peak, eigenMT-adjusted p, pi without a
  direction, citation and licence note), a Table column with its 'molQTL lead SNPs' filter (`molqtl=1`) and a
  locus-browser lane (read from `molqtl.parquet`). Weight 0: never counted in tiers.
- Genetic map: the card shows female and male cM, the Table a 'cM (F/M)' column, and the (unlinked) Panel tab's designer a 'Min spacing
  (cM)' field with the map to use (`snpscore.panel.design(min_spacing_cm=, cm_map=)`; a median cM spacing KPI), when the
  `cm` columns exist.
- Vendor checks (`tools.vendor_checks` = `snpscore.panel.vendor_checks`): each Export-tab vendor row shows its own
  include count and checks (Illumina Infinium bins, markers within 60 bp, alleles unknown), and the zip adds
  `vendor_checks.txt`; alleles are the list's, else the assay flank's (public) ones, as in the vendor files. Help
  (`#exports`) explains the `Ssa<chrom>p<pos>` locus names, the bins' error 111 / warning 604 minimums and the
  `.provenance.txt` and `.lookup.tsv` sidecars.
- Coding consequences (`coding_*` columns, snpscore's VEP-lite): the Table's and the Panel's Region cell shows the
  consequence (missense, synonymous, stop gained, splice donor, ..., tooltip `p.Thr46Met · <transcript>`; a bare CDS
  says 'amino-acid effect not computed: <reason>' in its tooltip); the Consequence column's filter adds
  `region=missense` ('protein-changing': missense, stop and start changes) and `region=synonymous`; the card's score
  block labels it (`missense +3`; `results.tier_parts` gives the long form, `Missense p.Thr46Met (ENSSSAT00000230965;
  published as Met54Thr) +3`, the published label when the catalogue's residue or direction differs, one- or
  three-letter, on hover) and the card's closed Details add the transcript and codons; the variant
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
  accepted; the Design panel's At a glance labels snpscore's assay reasons.
- Data page: layer population and licence, the AQUA-FAANG samples (ENA projects, BodyMap fish) and a 'How to cite'
  block (wording PROVISIONAL). Gene pages, cards and the Known loci page link to SalmoBase gene pages.
- State colours: `palette.STATE_PALETTES` has the portal palette and AQUA-FAANG's itemRgb colours;
  `SNPPORTAL_STATE_PALETTE = 'aquafaang'` makes AQUA-FAANG's the default for every page and figure (G to choose), and
  the locus browser's Display options switch it per viewer (a cookie read on `request_started`, kept in a
  `ContextVar` for that request; apps.py). Methods shows the colours in its chromatin-state table.

Modules: `views.py` (score page, job status, results shell, downloads, delete), `results.py` (overview, table and
filters, figures), `locus.py` (locus browser, evidence card, variant page; `locus_svg.py` draws them), `explore.py`
(gene pages, known loci, candidate jobs, tour), `search.py` (resolver), `about.py` (data, methods, help, run
locally), `panel.py` (the Design panel: Add to panel, sources, chip, SNP list, downloads), `tools.py` (the unlinked Panel
tab's designer and chip comparison; Export tab and every export format, via `snpscore.panel` and `snpscore.export`), `report.py` (printable report), `association.py` (GWAS upload, Association
page, regional plot), `figures.py` (pure functions data -> SVG), `palette.py` (every colour). Templates extend `base_portal.html` and use the partials `_page_header`,
`_figure`, `_badges` and `_footer`; styles are in `static/snpportal/portal.css`, small enhancements in `portal.js`.

**Design rules.** Colours come only from `palette.py`: HTML gets CSS custom properties, SVGs embed literal hex (so
saved files keep their colours). No colours or inline styles in templates (a test checks). No prototype caveat
line on the pages and no PROVISIONAL or SYNTHETIC badges (a synthetic job's title says so; Methods, the report and every
download say the rules are provisional); figure cards show a title, an (i) and one download menu, with provenance only in the SVG's `<desc>` and the
downloads. Every SVG has `role="img"`,
`<title>` and `<desc>`; text colours pass WCAG AA (a test checks); focus is always visible. Checked for colour blindness
(deuteranopia, protanopia, tritanopia; no tier or portal-palette pair collides only under CVD; 'Ensembl regulatory' in
the card's score blocks is `palette.REGBUILD`, Okabe-Ito sky blue). Below 992 px, figures drawn 1200 px wide keep 0.8x
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

## Breeder tools: assay QC, panel designer, chip comparison, exports

All defaults are PROVISIONAL and live in weights.yaml (`assay` and `design` blocks, listed in manifest `provisional`).

`snpportal.lib.panel.design(source, preset='all', n_target, min_spacing_bp, min_maf, backbone_fraction, max_per_gene,
max_per_element, require_assay_pass, exclude_flags, must_include, weights=, chrom_sizes=, table='v', out=None,
coordinate=None)`: `source` is an annotate/pool parquet (or TSV) path, or a DuckDB connection with a table or view
`table`. Parameters left None come from `weights['design']`. Steps: must-include ids first; a backbone of
round(n_target x backbone_fraction) SNPs, the best per genome-length-proportional bin; then the rest by
`design_score` = score.tier x tier_score / max + score.assay x (pass 1, warn 0.5) + score.maf x MAF / 0.5. Every pick
keeps `min_spacing_bp` (bisect per chromosome; `coordinate(chrom, pos)` can map bp to cM later), at most
`max_per_gene` per `gene_id` and `max_per_element` per `chromatin_id`. Filters: MAF (your `maf`/`af` column, else
`public_af_maf`; unknown passes), assay (`fail` dropped, or all but `pass` with require_assay_pass), and
`exclude_flags` (columns true or > 0, e.g. blacklist, lore, strand_ambiguous, flank_variants, near_chip). Tiers come
from `tier__<preset>` when present (pool, the portal's tiers.parquet); a parquet/TSV path without them holds the
tiers of the preset it was annotated with, so its tier columns are recomputed for `preset` with `weights` (the CLI
passes the release's; `synthetic=` names the layers that never count), and a connection's `tier` is used as it is. A
TSV/CSV source reads `chrom`, `id`, `ref`, `alt` and `genome_base` as text. Ties go to the lower row number.
Returns {`params`, `hash` (same input and params -> same hash and parquet sha256), `summary`, `selected`}; `out` gets
the source columns plus `source_row` (0-based row in the source), `selection_reason` (`must_include`, `backbone`,
`functional` = tier 1-3, `fill` = tier 4), `panel_rank` and `design_score`, ordered by panel_rank. `summary`:
`n_target`, `n_selected`, `n_rows`, `n_candidates`, `reasons`, `tiers`, `per_chromosome` [{chrom, n, length}],
`spacing` {min, median, max}, `largest_gaps` [{chrom, start, end, size}] (chromosome ends included),
`region_class`, `assay_status`, `missing_must_include`, and `binding` (why fewer than n_target were found).
`python -m snpportal.lib.cli panel` also writes `<out stem>.summary.json`.

`snpportal.lib.panel.compare_sql(rel, chip, window_bp, tier='tier')` adds `on_chip`, `dist_to_chip` (bp to the nearest
chip SNP on the chromosome), `near_chip` (<= window_bp) and `novel_functional` (tier 1-2 and not near_chip).
`compare(source, chip, preset, window_bp, gap_bp, pool=, weights=, chrom_sizes=)` returns `summary` {total, shared,
novel_functional, other (the three add up to total), chip_snps, window_bp, gap_bp, gaps} and `gaps` [{chrom, start,
end, size, filler: {chrom, pos, id, tier, source: list | pool} or None}] for chip gaps over gap_bp (design
`chip_window` 10 kb and `chip_gap` 1 Mb). `read_chip(path, release, out, max_snps=CHIP_MAX)` reads any input layout
through the aliases into chrom, pos, id, and stops with InputError past `max_snps` rows (3,000,000).

`snpportal.lib.export`: `provenance(manifest, weights, meta)` -> '# ' lines (release, manifest and weights sha256,
versions, preset, filters, panel, PROVISIONAL rules, SYNTHETIC when synthetic data contributes, the equivalent
command); `methods_text(manifest, weights, preset, release_dir, finemap=None)` -> methods paragraphs and references
(layer citations, each '; '-separated part once and 'DOI to add' where it has no doi:, GERP++, the catalogue's DOIs;
with `finemap`, the GWAS settings used, a loci and fine-mapping paragraph and Wakefield 2009); `export(source, fmt, out,
release_dir, preset, meta, include_failed, plain, flank=, template=, sidecars=True)` for tsv, parquet (provenance in
the KV metadata), bed, and the vendor layouts (`illumina`, `axiom`, `kasp`; columns per template version in
`TEMPLATES`, each 'layout to confirm against the vendor's current template'). A path source's tiers are recomputed
for `preset` as in design(). Rows keep the source's order (a connection's view is written in sorted `_row` ranges).
- Vendor files hold one row per SNP and no comment lines. `Sequence` is `<flank>[REF/ALT]<flank>` on the forward (+)
  strand, upper case, neighbouring public variants as IUPAC codes (N for indels); REF/ALT are the input's alleles
  (complemented for `strand_flip`), else the public site's. Flanks: illumina 60 bp (60-200), axiom 35 bp, kasp 50 bp
  (50-100). Columns: illumina (designstudio-2026) `Locus_Name, Target_Type, Sequence, Chromosome, Coordinate,
  Genome_Build_Version, Source, Source_Version, Sequence_Orientation, Plus_Minus, Species, Force_Infinium_I,
  Replication_Count` (iselect-2016 also available); axiom `SNP_ID, Chromosome, Position, Strand, Sequence`; kasp
  `SNP ID, Sequence, Position`. Locus names are `Ssa<chromosome>p<position>` (chromosome 0 off 1-29).
- Next to each vendor file: `<file>.provenance.txt` (the '# ' provenance, template, flank, left-out counts and panel
  warnings) and `<file>.lookup.tsv` (`locus_name, id, chrom, pos, ref, alt, topbot, allele_a, allele_b, two_probes,
  assay_status, assay_reasons, export_notes`: TOP/BOT by Illumina's rules incl. the sequence walk for A/T and C/G,
  with Illumina's A/B alleles).
- Left out: SNPs without known biallelic alleles or a full flank, and unless include_failed (then kept, with the
  reason in `export_notes`) assay fail and not_checked SNPs and, for illumina, SNPs whose TOP/BOT strand cannot be
  determined (code 103).

`--format priors` (`export.priors(source, out, release_dir, preset, meta, categories=None)`) writes a zip of
genomic-prediction prior files: `bayesrc_classes.txt` (SNP<TAB>class, no header, input order), `sets/<category>.txt`
(GFBLUP/MultiBLUP sets, which overlap), `ldak_partitions/partition1..K` (disjoint, covering every SNP), `annot.tsv`
(CHR, BP, SNP, a 0/1 column per category, tier_score, `active_<condition>` for the 21 conditions), `snp_lookup.tsv`
(only when some ids are missing: names `Ssa<chrom>p<pos>`), `README.txt` (provenance, category definitions and counts,
a methods paragraph, references) and `methods.txt`. Categories: tier1_2, active, coding (non-synonymous
`coding_consequence`, else region_class CDS), constrained, regulatory, none; a SNP's class is the first category it is
in, in the PROVISIONAL weights.yaml `priors: order`.

`bundle_zip(out, source, release_dir, preset, meta, formats, svgs)` zips the exports, manifest.json,
weights.yaml, methods.txt, provenance.txt, README.txt and figures/*.svg. `filename(fmt, release, preset, tag)` names
files `snpscore_<release>_<preset>[_<tag>][_<vendor>].<ext>`.

## Locus views and remote tracks

`snpportal.lib.locus` serves the portal's locus browser, card and variant page from the release (BED coordinates; SNP `pos`
1-based): `locus(release, chrom, start, end)` returns every lane of a window up to 2 Mb (gene models, peaks with their
21 states, regbuild, GERP, blacklist, LORe, public variants, known loci); `parse_region(text, release)` reads
`25:28,980,000-29,010,000`, `ssa25:28.98-29.01Mb` or `25:28996360` (aliases through alias.parquet);
`signal(tracks, chrom, start, end, cache=)` and `segments(...)` read bigWig/bigBed tracks from `tracks.yaml` on a fixed
public tile grid (cache keys never hold a user's position; a track that misses the 4 s deadline is None);
`annotate_position(release, chrom, pos, ref, alt, trait)` annotates one position on the fly (same row as a full
annotate). Remote files are read with HTTP range requests by `snpscore.bbi` and `snpscore.fasta`, https only and
only on allowlisted hosts (`SNPSCORE_ALLOWED_HOSTS`, default salmobase.org and ftp.ensembl.org); set
`SNPSCORE_CA_FILE` when Python lacks CA certificates. `snpdata tracks` regenerates `tracks.yaml` from the
salmobase track hubs.
