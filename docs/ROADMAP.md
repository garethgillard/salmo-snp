# Portal roadmap v2

Generated on 2026-10-06 from a multi-perspective design review (breeding R&D, quantitative genetics, functional genomics, scientific UX, platform engineering), then critiqued for gaps and risks.
Checkboxes live in [TRACKER.md](TRACKER.md); this file holds the full spec and acceptance test of every item.

Status (2026-11-04): waves A-D and push 2 are built; the open items are TRACKER's open boxes. Where a spec and the
code differ, the code and the folder READMEs are current: for example the portal counts all 21 conditions with no
trait picker (G, 2026-10-11), the portal-only code moved from snpscore to snpportal/lib (2026-10-28), and a local
install keeps results until deleted (G, 2026-11-03). Push 3 (I1-I20, at the end) is the plan for industry users
(G, 2026-11-04).

Legend: **now** = built in the first push (waves A-C); effort S/M/L; priority must/should/could.

## Vision

A salmobase-hosted functional SNP workbench for Atlantic salmon breeders and geneticists. A user can start from a SNP list, a chip manifest, a PLINK file, a gene, a QTL interval or (in the next push) GWAS summary statistics. The portal takes them to a short list or genotyping panel they can defend, assay and reproduce. The AQUA-FAANG evidence is shown at genome, locus and SNP scale, in a clean server-rendered style like gnomAD and Ensembl:
- ChromHMM states in 21 conditions
- ATAC signal read live from the salmobase trackhub bigWigs
- Ensembl 116 gene models, ortholog names and the regulatory build
- GERP constraint
- expression per tissue
- public allele frequencies
- later, molQTL and LD

Every view and export says which release, rules and data produced it. Rules that belong to G stay visibly provisional and configurable, and synthetic stand-ins are labelled wherever they appear. Confidential lists can be run locally with the same release and commands.

The prototype runs locally on public data plus labelled synthetic data. It adds no Python dependencies and no JS build: server-rendered SVG, Bootstrap 5.1.3 and htmx.

This push (Waves A-C, 29 items) ends with a polished, demonstrable portal:
- a landing page with search
- upload with examples and chip-manifest input
- an overview dashboard and fast table
- an evidence card and variant pages
- a locus browser with live salmobase ATAC
- gene pages and gene/interval candidate lists
- assay QC, a panel designer, vendor exports and chip comparison
- data, methods and run-locally pages
- a guided vgll3 tour

GWAS fine-mapping is fully specified as the next push (Wave D) and needs no rework of anything built now.

## M1 Foundations: safe, traceable, testable, consistent

_Make the upload -> annotate -> view loop safe for any user file, reproducible down to the weights used, testable offline, and visually consistent, so every later feature builds on solid ground._

### P1.1 Sanitise user columns and sandbox DuckDB (confirmed SQL-injection path)

**now** · effort S · must · lenses: engineer

**Spec.** Column handling in snpscore.annotate.read_snps:
- Keep the columns in a module constant RESERVED = (chrom, pos, id, ref, alt, p, log10p, beta, se, z, af, maf, n, a1, a2). P2.6 and P7.1 map header aliases onto these names.
- Rename every other input column to in_<slug>: slug = re.sub('[^A-Za-z0-9_]','_',name)[:40], de-duplicated. At most 50 extra columns are kept; the rest are dropped with a validation note.
- Add a q(ident) helper that doubles '"'. Use it for every data-derived identifier in annotate.py, score.py and the portal views.

snpscore.connect(read_dirs, write_dir, threads=2, memory_limit='2GB'):
- Pass every directory through Path.resolve() first. On macOS /tmp and /var are symlinks, and DuckDB refuses symlinked and '..' paths.
- Then, in this order: SET allowed_directories=[release dir, job dir, ...]; enable_external_access=false; autoinstall_known_extensions=false; autoload_known_extensions=false; memory_limit; threads; temp_directory=write_dir; lock_configuration=true. allowed_directories must be set before external access is turned off.
- annotate(), open_result(), downloads and pool queries all use it.

Errors and temp files:
- Map duckdb.Error to fixed user messages, so no SQL, file paths or input lines reach pages or logs.
- add_sequence_checks writes its temporary TSV into write_dir instead of the system temp dir.

**Data.** public-available-now (fixture SNPs are enough)

**Acceptance.** pytest checks:
- A TSV with headers chromatin_a"b, tier and x'); DROP TABLE snps;-- annotates and returns in_* columns.
- A connection from connect() refuses read_csv('/etc/hosts'), an https read, INSTALL httpfs and SET enable_external_access=true.
- connect() works when the job dir is given as a /tmp symlink path.

Portal: a malformed upload shows a fixed message with no SQL or path.

Existing snpscore and portal tests and the P1.6a golden hash still pass.

### P1.2 Remote bigWig/BGZF reader core: one read per tree node, keep-alive, deadline

**now** · effort M · must · lenses: engineer, functional, ux

**Spec.** Measured today: opening one AQUA-FAANG bigWig takes 32 Range requests and 6-10 s.
- The chromosome B+ tree (3,361 sequences, about 96 KB) is walked one node at a time.
- Each node costs two requests: a 4-byte header, then the items.
- Each request opens a new TLS connection.

Changes in bbi.Source and BBIFile (Fasta reuses Source):
- Read each B+ tree and R-tree node in one request (4 + blockSize x item size). Read the whole chromosome tree in one request when it is under 256 KB.
- Keep one keep-alive http.client connection per thread and host. Use a module-level, persistent ThreadPoolExecutor (at most 8 connections per host), so connections survive between calls. A per-call pool would throw them away.
- Timeouts of 3 s to connect and 5 s to read, with 2 retries on connection errors.
- Require status 206 and a Content-Range matching the request. Never read past the requested bytes. Treat any 3xx as an error (no redirects).
- Allow https only, from a configurable host allowlist (salmobase.org, ftp.ensembl.org).
- Pass SNPSCORE_CA_FILE (falling back to SSL_CERT_FILE) to ssl.create_default_context. Never disable verification.
- Byte-bounded LRU (SNPSCORE_RANGE_CACHE_MB, default 64) keyed by (url, offset, size). Opened BBIFile and Fasta objects are cached per process.
- bins(chrom, start, end, n) reads the coarsest zoom level whose reductionLevel <= bp-per-bin, and raw blocks only below that.
- bins_many(urls, chrom, start, end, n, deadline) returns None for any track that misses the deadline.

Deferred to P8.8: ETag/If-Range, the on-disk header cache, block merging and SNPSCORE_DATAFILES_ROOT.

**Data.** public-available-now: AQUA-FAANG trackhub bigWigs (v4, 10 zoom levels), Ssal_v3.1 bgzipped genome .fai/.gzi. Offline tests use the P1.6a synthetic bigWig and range server.

**Acceptance.** Offline, against tests/range_server.py:
- Opening the synthetic bigWig and reading one window takes 3 requests or fewer.
- A second window in the same block makes 0 requests.
- A wide window is answered from the zoom level, with no raw-block request (counted).
- A server that answers 200 instead of 206 raises an error.
- A slow-mode track returns None from bins_many within deadline + 1 s, while the other tracks return data.
- http:// URLs and non-allowlisted hosts are refused.

Live, behind SNPSCORE_LIVE=1: a test prints cold and warm timings and request counts, for one salmobase ATAC bigWig and for 8 in parallel. These are recorded in TRACKER and are not a gate. With SNPSCORE_CA_FILE set, the Python 3.8 venv reads salmobase without CERTIFICATE_VERIFY_FAILED.

### P1.3 Job folders, background annotation, precomputed tiers with tier_terms, jobs from rows

**now** · effort M · must · lenses: engineer, ux, breeder

**Spec.** Job folder results/<uuid>/ holds:
- job.json
- the input file, deleted after annotation
- result.parquet and tiers.parquet
- summary.json, validation.json and rejects.tsv
- the weights.yaml and manifest.json snapshot (P1.4)

snpportal/jobs.py:
- A module-level ThreadPoolExecutor(SNPPORTAL_WORKERS, default 1). SNPPORTAL_WORKERS=0 runs jobs synchronously, so tests are deterministic.
- Every upload is a job, with no separate inline path. The POST redirects to the results URL, which shows a progress panel polled with hx-trigger='every 1s' until the job is done.
- job.json is written atomically with os.replace. Fields: state (queued/running/done/failed), stage, n_rows, started, heartbeat, timings, error_code.
- annotate(progress=fn) reports stage names only.
- A heartbeat older than 5 min marks the job failed ('server restarted, please re-upload').
- More than 10 queued jobs returns 503 with Retry-After. The queue and heartbeat are per process under mod_wsgi or gunicorn, which is fine for the prototype.

Tiers and summary:
- score.py emits tier_terms LIST(STRUCT(term VARCHAR, weight DOUBLE)). README documents it.
- At job end, scored() runs once per named preset into tiers.parquet: file_row_number, tier__<p>, tier_score__<p>, tier_evidence__<p>, tier_terms__<p>.
- summary.json per preset: tier counts, region class x tier, per-condition active share, flag counts, 1 Mb bin counts and the largest gaps. The AF histogram and assay-status counts are included only when those columns exist (the global column-gating rule).

Views:
- Views join tiers.parquet by row. The card reads one row WHERE file_row_number = ?.
- On-the-fly scoring is kept only for custom presets (P3.4).
- jobs.create_from_rows(select_sql, label, kind) makes a job from pool rows or another job's rows (used by P5.2 and P6.6).
- load_weights and the manifest are lru_cached by (path, mtime).
- Connections come from snpscore.connect(), with SNPPORTAL_DUCKDB_THREADS (2) and SNPPORTAL_DUCKDB_MEMORY (2GB).

**Data.** public-available-now: data/demo/public_50k.vcf; the 1.6M-site 12-fish VCF for a dev load check

**Acceptance.** Django tests, with WORKERS=0:
- upload -> job -> results works.
- create_from_rows -> results works.
- With scored() mocked, switching preset on the results page never calls it.
- The card query is filtered by file_row_number (asserted on the SQL).
- A job whose heartbeat is backdated 6 min shows the failed state.
- jobs.submit with a stub executor returns 503 for the 11th queued job.

With SNPSCORE_DEV=1, the 1.6M-site VCF finishes in the background with no request timeout. The warm results-page time for public_50k is reported.

### P1.4 Release pinning, weights snapshot, provenance headers and methods text

**now** · effort M · must · lenses: breeder, geneticist, functional, engineer

**Spec.** Known-chromosome fix:
- annotate.py:77 builds its known chromosomes from read_parquet('{release}/*.parquet'). Replace this with manifest chrom_sizes, falling back to the interval layers.
- The pool lives under release/pool/, so annotate never scans pool, alias, transcript or other release files.

The manifest gains:
- chrom_sizes, from the genome .fai, or from the layers' maximum end when the .fai lacks a chromosome (as in the fixture).
- Per layer: sha256 per file, a citation, and synthetic: true/false.
- A release-level 'provisional' list: active states, presets, weights, assay thresholds and design defaults.
- snpscore and DuckDB versions.

Weights snapshot:
- Each job copies weights.yaml and manifest.json into its folder, and open_result reads those copies.
- Editing the release in place therefore never changes an existing job.
- A banner offers to re-annotate when their sha256 differs from the current release.

Recorded in job.json and in result.parquet KV_METADATA:
- release version, manifest sha256 and weights sha256
- snpscore and DuckDB versions
- created_utc
- input sha256 (a hash, never content)
- preset and synthetic_input

snpscore/export.py:
- provenance(job, filters) returns '#' lines: release, hashes, assembly, preset or custom conditions, filters, 'tier rules PROVISIONAL', a SYNTHETIC line when relevant, the UTC time and the equivalent snpscore CLI command. Every TSV and every SVG caption starts with these; ?plain=1 drops them.
- methods_text(manifest, weights) returns a paste-ready paragraph plus references (AQUA-FAANG, Ensembl 116, Compara 65-fish GERP, nf-rasqual).

score.py skips any layer with synthetic: true.

**Data.** public-available-now: manifest.json, weights.yaml, genome .fai

**Acceptance.** Every TSV export begins with '#' lines that include both sha256 values and 'PROVISIONAL'; ?plain=1 gives a bare TSV.

Editing weights.yaml in the release after a job is created leaves that job's tiers unchanged and shows the re-annotate banner.

Adding an extra parquet with chromosome 'NC_059442.1' to the release folder doesn't change annotate's known-chromosome check.

A layer flagged synthetic: true changes no tier_score.

manifest.chrom_sizes lists the fixture chromosomes for the test release, and 29 entries for release/dev (SNPSCORE_DEV=1).

### P1.5 Design system (minimal): palette, partials, stylesheet, accessibility

**now** · effort S · must · lenses: ux

**Spec.** Palette:
- snpportal/palette.py is the single source of colours.
- It emits CSS custom properties for HTML, and literal hex values for SVG. SVGs never use var(--...), so downloaded SVG and PNG files keep their colours.
- The ChromHMM palette is one dict, so G can swap in AQUA-FAANG's itemRgb colours.

Partials:
- base_portal.html extends salmobase/base.html. It adds a sub-nav (Search | Score SNPs | Locus browser | Data & methods | Help) and a badge 'Release <v> · Ssal_v3.1'.
- _page_header.html: breadcrumb, H1, a meta line and actions.
- _figure.html: a card with a title, an (i) popover, SVG/PNG/TSV downloads and a provenance caption.
- _badges.html: tier, PROVISIONAL, SYNTHETIC and flags.
- _footer.html.

Static files:
- static/snpportal/portal.css (about 200 lines): tokens, system font stack, tabular-nums, compact density, sticky headers, focus rings, print CSS.
- static/snpportal/portal.js (under 100 lines): SVG->PNG at 2x, copy-to-clipboard, drag-to-zoom on the locus SVG, j/k row keys.

Accessibility and clean-up:
- Every SVG has role=img, <title> and <desc>. Tooltips use SVG <title>.
- Inline styles in the current templates are removed.
- The help page has a colour key.
- No colour-blind simulation test.

**Data.** none (design); state grouping mirrors the provisional weights.yaml active/weak lists

**Acceptance.** - All portal pages extend base_portal.html.
- A grep test finds no hard-coded colours in templates.
- One pytest checks that tier badge text contrast is at least 4.5:1.
- Every figure card offers SVG, PNG and TSV.
- A downloaded SVG contains no 'var(--'.

### P1.6a Offline test kit: synthetic bigWig writer, range server, golden hash, test markers

**now** · effort S · must · lenses: engineer, functional

**Spec.** tests/bbi_writer.py: a test-only stdlib bigWig writer, about 100 lines:
- header
- one chromosome-tree leaf
- one R-tree leaf
- zlib bedGraph blocks
- one zoom level
No bigBed writer until the ChromHMM .bb lanes (P4.3c).

tests/range_server.py: a threaded http.server with:
- Range/206 support
- a request counter
- two fault modes: ignore Range (answers 200) and slow

Golden test: the sha256 of the sorted annotate output on the fixture, so refactors (P1.1, P1.4, P8.1) prove identical results. It is updated deliberately when a column is added.

pytest markers:
- 'live' (SNPSCORE_LIVE=1, network)
- 'dev' (SNPSCORE_DEV=1, needs release/dev)
Every acceptance check that needs salmobase or release/dev uses them.

**Data.** synthetic test tracks written to tmp at test time (no binaries committed)

**Acceptance.** - bbi reads back exactly the values written, at raw and zoom level.
- range_server counts requests and serves both fault modes.
- The golden hash passes.
- pytest and manage.py test pass with networking disabled.

### P1.6b Synthetic GWAS generator (make_synthetic.py gwas): Wave D

later · effort S · must · lenses: geneticist, engineer

**Spec.** This adds a 'gwas' subcommand to the prep/make_synthetic.py skeleton that P6.6 creates (seeded, deterministic, --seed 42).

Fixture scale: loci are planted only inside the existing fixture regions:
- (a) vgll3 Met54Thr 25:28996360 (CDS), p about 1e-30.
- (b) a public site inside a Liver/Gonad Active_enhancer peak in chr26 14-16 Mb (nae1), p about 1e-9.
- (c) an active element in chr21 32-34 Mb, p about 1e-12.
- (d) a decoy in chr1 110-111 Mb (LORe) whose causal SNP is intergenic tier 4, p about 1e-10.

Dev scale adds six6 9:23837450 and about 200K genome-wide public sites.

Simulation:
- Null z ~ N(0, sqrt(1.05)).
- LD is mimicked by distance decay: z_j = z_c * exp(-|d|/L) * u_j + N(0,1), with L between 20 and 80 kb.

The truth file records causal ids, z_c, L and the empirical null lambda.

Output styles:
- fastGWA-style headers
- PLINK2 .glm-style headers
- a p-only file containing the string p '1e-400'

**Data.** synthetic-for-now over public 12-fish sites

**Acceptance.** - The same seed gives identical sha256 values.
- Every file has SYNTHETIC in its name and in its first-line header.
- The truth file has the empirical lambda that the P7.1 test compares against.

### P1.7 Extend the fixture to all known loci

later · effort S · should · lenses: engineer, geneticist

**Spec.** Add chr9 23-25 Mb (six6) and chr26 18.5-19.5 Mb (bco1l) to prep/make_fixture.sh, covering all layers, the VCF and the alias rows. Add real genome sequence for those windows through prep/make_fixture_genome.py. This lets the benchmark, the catalogue card and a six6 GWAS locus run offline.

**Data.** public-available-now

**Acceptance.** The fixture benchmark annotates all 6 known loci with non-empty layers, and tests/fixture stays a small, reviewable size.

## M2 Trustworthy upload

_First-time users trust the results and can start from the files they actually have. VCF, SNP lists, PLINK and chip manifests are accepted. Wrong chromosome names, assembly or strand are caught and explained. Every dropped row is accounted for. Data handling matches the stated privacy policy._

### P2.1 Chromosome aliases, validation report and assembly/strand check

**now** · effort M · must · lenses: breeder, ux, engineer, functional

**Spec.** Aliases:
- snpscore build writes alias.parquet (alias, chrom) from salmobase alias_filtered.txt: Ensembl name, RefSeq NC_/NW_, GenBank and ssaNN; 1,011 rows.
- It adds generated chrN/ChrN/SsaN/ssaN variants for 1-29.
- fetch downloads the file, and make_fixture.sh writes the fixture chromosomes' rows to tests/fixture/alias_filtered.txt.
- read_snps maps chrom through it in one join.

validation.json:
- rows read and SNPs kept
- non-numeric pos
- unknown chromosomes, with the top names and counts
- duplicates merged
- indels and multi-allelic sites
- alias rewrites
- detected input format (P2.6)
- ref_check distribution: ok, swapped, strand_flip, mismatch, not_checked

Reference check:
- Uses the local genome in data/raw for whole lists.
- With a remote genome, it samples at most 200 SNPs.
- A chromosome missing from the .fai is not_checked, never mismatch.

Rejects and the results page:
- rejects.tsv lists dropped rows with a reason column. It is downloadable and expires with the job.
- The results page gets an 'Upload QC' panel. A red warning shows when (mismatch + strand_flip) / checked > 10%: 'these look like ICSASG_v2 coordinates or the other strand'. It links to the liftover FAQ (P5.4).
- The zero-matching-chromosomes error names the closest alias problem.

**Data.** public-available-now: salmobase alias_filtered.txt, Ssal_v3.1 genome .fai/.gzi (local copy in data/raw)

**Acceptance.** - The same SNPs named '25', 'ssa25', 'chr25' and by RefSeq accession give identical annotation, using the fixture alias rows.
- The old 'ssa21' expected-failure test is replaced by one that passes with an alias notice.
- Fixture VCF sites inside chr25 28.95-29.05 Mb, shifted by +1,000 bp, trigger the assembly warning; unshifted sites don't.
- SNPs on chr1, chr21 and chr26, which are absent from the fixture genome, are reported as not_checked.
- rejects.tsv lists every dropped row with its reason.

### P2.2 Upload page redesign with examples, paste box and safe limits

**now** · effort S · must · lenses: ux, engineer, breeder

**Spec.** Page /snp/score/ contains:
- A drag-and-drop zone: a styled native input plus a few lines of JS.
- An accepted-formats table:
  - VCF: only the first 8 columns are read, and genotypes are never stored.
  - SNP TSV/CSV with header aliases.
  - PLINK .bim/.map.
  - Illumina and Axiom manifests (P2.6).
- A paste textarea for up to 10,000 'chrom pos [ref alt]' lines.
- A preset selector.
- 'Try an example' buttons that copy files from release/<v>/demo/:
  - known loci (published)
  - 50K public 12-fish sites (public)
  - the SYNTHETIC demo chip, added in Wave C with P6.6
  The GWAS example button comes with P7.1.
- A short plain-language privacy statement matching P2.3, with a link to 'Run it locally' (P5.4).

Limits:
- SNPPORTAL_MAX_UPLOAD_MB (300) is checked on CONTENT_LENGTH before request.FILES is touched; Django parses the multipart body on first access.
- FILE_UPLOAD_TEMP_DIR is set to the results dir, so spooled uploads never stay in the system temp dir.
- SNPPORTAL_MAX_SNPS (3M) is enforced with LIMIT max+1 in read_snps. This also bounds gzip bombs.
- Error messages state both the cause and the fix.

**Data.** public-available-now (known loci, public sites); synthetic-for-now (demo chip, labelled)

**Acceptance.** - Each example button runs end to end and lands on its results.
- A 10-line paste works.
- A request with an oversized CONTENT_LENGTH is rejected before the body is parsed.
- A file over the row cap gives a clear message.
- Neither case leaves files in the results dir or the system temp dir.

### P2.3 Privacy and data-lifecycle hardening

**now** · effort S · must · lenses: engineer, breeder, geneticist

**Spec.** Lifecycle:
- Cleanup runs from the results view and from manage.py snpportal_cleanup (for cron).
- Unlink tolerates files already removed, so concurrent cleanups no longer return 500.
- Whole job folders are removed by job.json age.
- POST /results/<key>/delete/ backs a 'Delete my results now' button.
- The page header shows when the results expire.
- Exports stream from DuckDB to a temp file in the job folder that is deleted on close.
- The results dir is mode 0700 and its files 0600.

Headers and links:
- Results, card, figure and download responses send Cache-Control: no-store, private.
- Referrer-Policy: same-origin.
- Outbound links (Ensembl, UCSC, JBrowse) carry rel=noreferrer.

Logging and scripts:
- sensitive_post_parameters on the upload view.
- An exception-reporter filter strips FILES and DuckDB message text.
- Log lines carry only an event name, job_ref = sha256(key)[:8], counts and timings.
- htmx is loaded from jsdelivr with an SRI hash and crossorigin.

**Data.** none

**Acceptance.** - After a download, the job folder holds no leftover export files.
- 'Delete now' removes the folder. The URL then shows an 'expired or deleted' page with a re-upload button.
- A Django test checks the no-store and Referrer-Policy headers, and that card links carry rel=noreferrer.
- Two cleanups run at once raise no error.

### P2.4 Optional in-browser genotype stripping before upload

later · effort S · should · lenses: breeder, geneticist

**Spec.** Vanilla JS (FileReader plus DecompressionStream for .vcf.gz) strips the file before upload:
- For VCF, it keeps only the first 8 columns.
- For TSV, it keeps only chrom, pos, ref and alt.
Genotypes and private columns never leave the company. A positions-only mode lets the user join the annotation back locally.

**Data.** none

**Acceptance.** A 1M-line VCF.gz is reduced in the browser, and a test of the request body shows the server receives only site columns.

### P2.5 ICSASG_v2 -> Ssal_v3.1 offline position table

later · effort L · should · lenses: breeder

**Spec.** prep/lift_icsasg_v2.py (exact 60 bp flank match on either strand) becomes an offline prep job that builds a genome-wide v2 -> v3.1 table for public variant sites. It ships as a release file, and the portal offers it when the P2.1 check suggests v2, joining in DuckDB.

There is no on-the-fly portal mode. The script calls NCBI efetch and Ensembl REST, which are outside the runtime allowlist.

Until the table exists, the P5.4 FAQ explains how to run the script locally.

**Data.** public-available-now: NCBI ICSASG_v2 sequences, Ssal_v3.1 genome

**Acceptance.** The six known-loci SNPs in v2 coordinates lift to the positions in benchmark/known_loci.tsv. Unliftable rows are listed with a reason.

### P2.6 Chip manifests, PLINK files and header aliases

**now** · effort S · should · lenses: breeder, ux, engineer

**Spec.** snpscore/formats.py detect(path, header_lines) chooses a reader. Supported inputs:
- VCF.
- TSV/CSV with header aliases:
  - CHR/Chromosome/chr -> chrom
  - BP/Position/POS/MapInfo/Physical Position -> pos
  - SNP/Name/Marker/rsid/Probe Set ID -> id
  - REF/A2/Allele A -> ref and ALT/A1/Allele B -> alt; the ref/alt mapping is checked against the genome by P2.1.
- PLINK .bim (6 columns) and .map (4 columns), by extension.
- Illumina manifest CSV with [Heading]/[Assay]/[Controls] sections. Only the [Assay] lines are read: Name, Chr, MapInfo and SNP '[A/G]'.
- Axiom annotation CSV, skipping '#%' comment lines: 'Probe Set ID', 'Chromosome', 'Physical Position', 'Allele A', 'Allele B'.

The alias dict is shared with P7.1, and validation.json records the detected format.

Manifest positions are usually ICSASG_v2, so the P2.1 assembly warning and the liftover FAQ apply.

Tests build tiny SYNTHETIC manifests in tmp from fixture positions. They use generic layouts only, and no real manifest is committed.

**Data.** synthetic-for-now (test-time manifests from fixture positions); user uploads

**Acceptance.** - Each format, generated in tmp, gives the same chrom, pos, id, ref and alt for the same fixture sites.
- An unknown layout gives a message listing the accepted headers.
- RESERVED columns are never prefixed with in_.

## M3 Results overview and table

_After upload, a breeder sees in five seconds how many usable functional SNPs the list has, where they are, which tissues they are active in compared with a public background, and how many are assay-risky. The table then supports fast triage._

### P3.1 Public background pool and background summary

**now** · effort S · must · lenses: ux, functional, geneticist

**Spec.** New command 'snpscore pool --release <dir> [--vcf <public sites>]':
- Annotates the public 12-fish VCF sites with sequence=False. There is no assay QC for the pool, which keeps it to about 2 min for 1.6M sites at current speed.
- Writes release/pool/pool.parquet, including public AF (P6.1) and the tier per named preset.
- Writes release/pool/background.json: region-class shares, per-condition active-state shares and tier shares per preset.

The pool is used as:
- the background for dashboard markers
- the public-variant lane in the locus browser
- the variant-page lookup
- the candidate source for gene pages and gene/interval lists (P5.2)
- the filler source for chip gaps (P6.6)

The portal works without a pool.

**Data.** public-available-now: 12-fish nf-rasqual VCF (INFO AF imputed on 504 fish)

**Acceptance.** - The fixture release builds a small pool in the test setup.
- background.json shares sum to 1 per category.
- Pages render without a pool.
- With SNPSCORE_DEV=1, the release/dev pool (about 1.6M rows) builds in 10 min or less (timing reported).

### P3.2 Overview dashboard (server-rendered SVG, linked to the table)

**now** · effort M · must · lenses: ux, breeder, functional

**Spec.** The Overview tab is the default results view. Each panel is one DuckDB GROUP BY that follows the current filters, with ghosted unfiltered totals behind. A panel renders only when its columns exist.

Panels:
1. Ideogram: chromosomes to scale from manifest chrom_sizes, 1 Mb bins on a sequential palette, and tier 1-2 ticks. Clicking a bin sets ?chrom=&start=&end= (a new region filter) and opens the table.
2. Tier x region class stacked bars, with a tick for the background share.
3. A 21-cell condition heatmap:
   - rows Brain/Gonad/Liver/Muscle; columns Imm F, Imm M, Mat F, Mat M
   - an embryo row of 5 stages
   - each cell shows the share of SNPs in an active state, with the fold over background printed
   - preset cells are outlined
4. Flags: blacklist, LORe, A/T-C/G, flank variants, and assay status once P6.2 exists. Each has a 'hide' link.
5. AF histogram (public or user AF).
6. The largest inter-SNP gaps.

KPI tiles: n SNPs, % tier 1-2 for the preset, % with MAF >= 0.05, and % assay pass once P6.2 exists. The assay denominator excludes not_checked.

All renderers live in snpportal/figures.py as pure functions (plain data in, SVG string out). Labels go through html.escape, and the module has no Django imports.

**Data.** public-available-now: annotated result, background.json, chrom_sizes

**Acceptance.** - For the fixture job, every panel whose columns exist renders.
- Clicking a chr25 bin filters the table to that Mb, and the count matches a direct query.
- Each panel downloads as standalone SVG with a provenance caption, as PNG and as TSV.
- Every SVG parses as XML.
- With no assay columns, no assay KPI or panel appears and nothing errors.
- The warm render time for public_50k is reported under SNPSCORE_DEV=1.

### P3.3 Results table that scans quickly

**now** · effort M · must · lenses: ux, breeder

**Spec.** Layout:
- Grouped super-headers: Variant | Priority | Location | Regulation | Assay.
- Friendly labels, with tooltips from the manifest descriptions.

Formatting:
- thousands separators
- strand-aware gene distance ('12.3 kb upstream of X' or 'in gene')
- GERP to 1 decimal place
- booleans as icon+text badges

A per-row inline SVG chromatin barcode: 21 cells, with gaps between tissues and the preset conditions underlined.

Interaction:
- A whole-row hx-get opens the card, and the selected row is highlighted.
- j/k move between rows.
- Sticky header.
- Filter chips with x-to-remove and 'Clear all'.

New whitelisted filters, each shown only when its column exists:
- chromosome/region
- gene name, including ortholog symbols once P5.10 exists
- active in <condition>
- min GERP
- min MAF
- assay status
- known locus only
- not near chip (P6.6)

Page size 25/50/100/500. Count line: 'Showing 1-50 of 1,234 (filtered from 54,000)'.

Empty state: one SQL query counts what each active filter removes on its own, and a button drops the most restrictive one. All state stays in the URL.

**Data.** user upload + release layers

**Acceptance.** - The existing Django test is updated and passes.
- Every new filter is in the URL whitelist, with a test that it changes the count on the fixture job.
- Parameters outside the whitelist are ignored.
- A barcode renders for every row.
- With 0 matches, the page names the most restrictive filter.

### P3.4 Custom condition presets and preset comparison matrix

later · effort S · should · lenses: breeder, ux, geneticist

**Spec.** Custom presets:
- snpscore.scored() accepts an explicit condition list as well as a preset name.
- ?conditions=Brain_Mature_Male,Gonad_Mature_Male re-tiers on the fly. It is labelled 'custom' in the UI, exports and provenance.
- A 21-checkbox picker uses the heatmap grid.

Preset x tier count matrix:
- one query over tiers.parquet
- clicking a cell applies that preset and tier filter

No presets are added to weights.yaml; that is G's decision.

**Data.** public-available-now

**Acceptance.** A custom two-condition selection never gives better tiers than 'all' for the same SNPs. The export header lists the custom conditions. A matrix cell lands on the filtered table.

### P3.5 One-page report (print to PDF)

later · effort S · should · lenses: breeder

**Spec.** /results/<key>/report/ uses a print stylesheet. It contains:
- KPI tiles
- the ideogram
- tier x region bars
- the condition heatmap
- a top-20 candidates table
- the panel summary, when a panel is selected
- the provenance block
- the methods paragraph
- a disclaimer that the rules are provisional

The browser's Save as PDF makes the PDF, so no PDF library is needed.

**Data.** derived from the result and release metadata

**Acceptance.** Every number matches the overview for the same URL parameters (Django test). Fitting on 2 A4 pages is checked by hand from the TRACKER manual-QA list.

### P3.6 Tissue-pattern UpSet plot

later · effort M · could · lenses: ux

**Spec.** An SVG UpSet plot of the top 15 tissue intersections where SNPs are active. Clicking an intersection filters the table.

**Data.** user upload + release; the active definition is provisional

**Acceptance.** Intersection counts sum to the number of SNPs active in at least one tissue.

## M4 Locus browser and evidence card with salmobase tracks

_Show the evidence instead of describing it. A publication-quality, server-rendered locus view puts gene models, 21-condition chromatin states, constraint, the regulatory build, public variants and the user's SNPs on one axis, with live AQUA-FAANG ATAC signal from salmobase. A one-page evidence card per SNP explains its tier._

### P4.1 Track registry (tracks.yaml) from the AQUA-FAANG trackhubs

**now** · effort S · must · lenses: functional, ux, engineer

**Spec.** 'snpscore tracks' (also run by build) parses the BodyMap and DevMap trackDb.txt into release/tracks.yaml. snpscore fetch downloads the trackDb files from the AQUA-FAANG trackhub. BodyMap has 60 ATAC, 274 ChIP (including Input) and 168 stranded RNA bigWigs.

Each entry has:
- id
- assay: ATAC, H3K27ac, H3K4me3, H3K4me1, H3K27me3, CTCF, RNA+ or RNA-
- tissue, sex, maturity and stage
- condition, e.g. Gill_Immature_Female
- chromatin_condition: the matching chromatin_<condition> column name. It is null for Gill, which has ATAC and ChIP but no ChromHMM.
- kind (bigwig), replicate URLs and source

ChromHMM .bb files are listed for P4.3c but not drawn yet.

Default track sets are the preset conditions' ATAC tracks. They are provisional and can be edited in tracks.yaml.

Only allowlisted https URLs are accepted. URLs come only from tracks.yaml, never from request parameters, which closes the SSRF route.

**Data.** public-available-now: salmobase AQUA-FAANG trackhub (hub.txt, BodyMap/DevMap trackDb.txt)

**Acceptance.** - A trimmed trackDb fixture parses in pytest.
- With SNPSCORE_DEV=1, release/dev lists 60 BodyMap ATAC bigWigs as 20 conditions x 3 replicates, with Gill's chromatin_condition null.
- A non-allowlisted URL is rejected.

### P4.2 Gene-model features layer and gene descriptions

**now** · effort S · must · lenses: geneticist, functional, ux

**Spec.** New release file transcripts.parquet. Columns: chrom, start, end, transcript_id, gene_id, gene_name, strand, part (exon/CDS/five_prime_UTR/three_prime_UTR), phase, and canonical (from the Ensembl_canonical tag).

It uses a new layer type 'features':
- overlaps are allowed
- annotate skips it
- only the viewers and the later VEP-lite (P4.5) read it

The gene layer also keeps the GFF3 'description' attribute as gene_description, which is empty for many genes, including the maturation vgll3. The README release contract is updated.

**Data.** public-available-now: Ensembl 116 GFF3 (fixture has 157 canonical tags)

**Acceptance.** - In the fixture, vgll3 ENSSSAG00000053708 (+ strand, 25:28995075-28999268) has canonical transcript ENSSSAT00000230965, with a CDS block covering 25:28996360.
- build's overlap check skips features layers.
- Annotate output is unchanged apart from the new gene_description column; the golden hash is updated once, deliberately.

### P4.3a Server-rendered SVG locus browser: local annotation lanes (no network)

**now** · effort M · must · lenses: ux, functional, geneticist, breeder

**Spec.** Page /snp/locus/?r=<chrom:start-end>[&result=<key>][&preset=]:
- The region input accepts coordinates, kb/Mb units and aliases; gene names work once the P5.1 resolver lands.
- The fragment /snp/locus/svg/ is swapped by htmx with hx-push-url.
- The SVG has viewBox width 1200 and a 170 px label gutter.

Lanes, top to bottom:
- Chromosome ideogram with a viewport box.
- Ruler with 1/2/5 x 10^k ticks.
- The user's SNPs as tier-coloured lollipops (stem height = tier_score). Clicking one opens its card by row.
- Canonical gene models from transcripts.parquet: thick CDS, thin UTR, intron lines with strand chevrons. At most 8 rows, then '+N more'; labels are hidden when crowded.
- 21 chromatin-state rows from the local chromatin layer, grouped by tissue with embryo stages last. The legend notes 'states inside AQUA-FAANG robust peaks only'.
- Ensembl regbuild glyphs.
- GERP elements.
- Public variants from the pool, as ticks whose height is the public AF.
- Blacklist and LORe as hatched translucent bands behind all lanes.

Toolbar: zoom in x3, zoom out x3/x10, pan 50%, centre on SNP, and SVG/PNG downloads. portal.js handles the keys and drag-to-zoom.

Links:
- Ensembl.
- UCSC GenArk hub GCF_905237065.1. It uses RefSeq names, so the chromosome is mapped through alias.parquet; the link is marked 'to verify'.
- salmobase JBrowse, with the URL format marked 'to verify'.
- All with rel=noreferrer.

Lanes are capped at 2 Mb ('zoom in'). Full genome browsing stays in salmobase's jbrowse_react.

**Data.** public-available-now: release layers, transcripts.parquet, pool

**Acceptance.** On the fixture release, with no network, /snp/locus/?r=25:28,980,000-29,010,000 renders:
- the gene model for ENSSSAG00000053708
- 21 chromatin rows
- regbuild, GERP and public variants
- the bands

Also:
- Zoom and pan update the URL.
- 'ssa25:28.98-29.01Mb' resolves to the same view.
- The downloaded SVG is standalone, with a provenance caption, and parses as XML.
- A window over 2 Mb shows 'zoom in'.

### P4.3b Live AQUA-FAANG ATAC signal lanes from salmobase

**now** · effort M · must · lenses: ux, functional, geneticist, breeder, engineer

**Spec.** Signal rows:
- ATAC rows come from tracks.yaml through P1.2 bins_many.
- At most 8 signal rows per view. The default is the preset's conditions; for 'all' it is one row per tissue (provisional). The picker swaps rows.
- Replicate R1 is shown by default. A 'replicates' toggle shows the mean of R1-R3 with a min-max band, allowed only when 8 or fewer conditions are shown.
- The y-scale is shared per assay, with the max printed and a per-track autoscale toggle.

Fetching:
- A fixed tile grid: bp-per-bin ladder 10/50/200/1000/5000, 200 bins per tile, with the rung chosen for about 600 bins per view.
- Zoom summaries are read where available (P1.2).
- A 4 s deadline. A track that misses it renders as a hatched 'signal unavailable' row. Signal is never faked.

Tile cache:
- The Django cache is configured as FileBasedCache under SNPPORTAL_CACHE_DIR, or LocMemCache with MAX_ENTRIES >= 5000 (the default is 300).
- Keys are (release, track, chrom, rung, tile).
- Tiles hold public data only. User SNPs are drawn at render time and never appear in cache keys.

Signal is capped at 500 kb ('zoom in for signal'). An offcanvas track picker groups tissue > condition, with a 'use preset' option.

Deferred to P4.3c: the 21 ChromHMM .bb lanes, and the ChIP and RNA rows.

**Data.** public-available-now: AQUA-FAANG ATAC bigWigs (Range + CORS)

**Acceptance.** Offline, with a test tracks.yaml pointing at synthetic bigWigs served by range_server:
- The view renders the expected number of signal paths.
- A slow-mode track renders the hatched row while the others draw.
- Re-rendering the same view makes 0 range requests.
- No cache key contains a user position (asserted).

With SNPSCORE_LIVE=1: the maturation preset at 25:28.98-29.01 Mb renders 8 real Brain/Gonad ATAC rows, and cold and warm timings are reported.

### P4.3c Per-condition ChromHMM lanes (genome-wide segmentation) and ChIP/RNA rows

later · effort M · should · lenses: functional, ux

**Spec.** Draw the 21 per-condition ChromHMM .bb segmentations from salmobase, with the robust-peak outline. Add optional H3K27ac, H3K4me3 and CTCF rows, and RNA +/- rows. Needs a bigBed reader path in bbi.py and a test bigBed writer (with autoSql) in tests/bbi_writer.py. Rows count against the 8-row signal cap.

**Data.** public-available-now: chromatin_states/AtlanticSalmon/{BodyMap,DevMap}/*.bb, trackhub ChIP/RNA bigWigs

**Acceptance.** The vgll3 window shows quiescent segments outside robust peaks. Offline tests read a synthetic bigBed.

### P4.4a Evidence card core and permanent variant page

**now** · effort M · must · lenses: ux, breeder, geneticist, functional

**Spec.** A shared evidence(row) -> dict feeds the card, the variant page and the later API.

Section contract: each section renders only when its columns exist. Later items add sections without touching the core: P6.2 assay, P5.3 known locus, P5.10 orthologs, P4.5 coding and P4.6 molQTL.

Core sections:
1. Header: id, chrom:pos in monospace with a copy button, ref>alt, tier badge with score, and an inline preset switch.
2. 'Why this tier': a horizontal stacked bar from tier_terms, with tier cut-offs as lines and a PROVISIONAL tag linking to methods.
3. A 2-D chromatin grid:
   - tissue rows x Imm F/Imm M/Mat F/Mat M, plus an embryo row
   - cells coloured by state with a 2-3 letter abbreviation and contrast-checked text
   - preset cells outlined; blacklisted cells hatched 'n/a'
   - a legend of the states present
4. A mini locus view (+/-2 kb), lazy-loaded with hx-trigger=revealed from /results/<key>/snp/<row>/locus.svg. Addressing by row keeps coordinates out of URLs and logs. It shows ATAC for the preset tissues and links to the full browser.
5. Gene context: name/description, id, biotype, strand, 'x kb upstream of TSS' or 'in gene', and per-tissue expression bars from the existing expression layer.
6. Links: Ensembl, UCSC, JBrowse, gene page, permalink.
7. Population scope note: AF and AQUA-FAANG data come from European farmed Atlantic salmon.

Variant page /snp/variant/<chrom>-<pos>[-<ref>-<alt>]/:
- Uses the pool row when there is one.
- Otherwise it annotates the position on the fly in a temp dir, through connect().

A print stylesheet is included.

**Data.** public-available-now: release layers, expression layer, pool

**Acceptance.** - The vgll3_Met54Thr card on the fixture job shows a contribution bar summing to tier_score, the grid with preset outlines, the mini locus (synthetic tracks offline) and expression bars.
- /snp/variant/25-28996360-C-T/ renders without an upload.
- For a job with no assay columns, the card renders without an assay section.
- The mini-locus URL contains no coordinates.
- The one-page A4 print is a TRACKER manual-QA item.

### P4.5 Coding consequence (VEP-lite) from the canonical CDS and the genome

later · effort M · should · lenses: breeder, geneticist

**Spec.** Applies to CDS (or splice_region overlapping CDS) SNPs with single-base alleles. snpscore/coding.py:
- Walks the canonical CDS blocks from transcripts.parquet, by strand and phase.
- Fetches the codon and translates it with the standard table.
- Outputs consequence (synonymous/missense/stop_gained/stop_lost/start_lost), codon_change, aa_change, protein_pos and transcript_id.

It is display only, and adds a card section. weights.yaml gets a commented, provisional missense/synonymous split for G. Validation against Ensembl VEP output is a later prep step.

**Data.** public-available-now: Ensembl 116 GFF3, Ssal_v3.1 genome (fixture has real sequence at chr25 28.95-29.05 Mb)

**Acceptance.** vgll3_Met54Thr on ENSSSAT00000230965 gives missense, codon ACG/ATG and aa_change 'T54M'. If the canonical transcript numbers the residue differently, the offset is recorded as a named constant with its reason, and the test asserts the offset value.

Synthetic-sequence unit tests cover synonymous, stop_gained and minus-strand cases. Tiers are unchanged.

### P4.6 molQTL evidence contract (minimal, synthetic until nf-rasqual tables arrive)

later · effort S · could · lenses: functional, geneticist

**Spec.** Schema:
- molqtl.parquet, a 'point' layer: molqtl, molqtl_tissues, molqtl_kinds, molqtl_best_q, molqtl_n.
- molqtl_detail.parquet: one row per SNP x tissue x kind, with feature_id, beta, se, q, is_lead and synthetic.

The build reader, a make_synthetic.py 'molqtl' subcommand, and a card forest plot with a SYNTHETIC watermark.

The manifest marks it synthetic: true and weights.yaml has molqtl: 0, so it never affects tiers. Locus and table views come after real data arrives.

**Data.** synthetic-for-now; needs-G: real nf-rasqual caQTL/eQTL tables (Brain/Gill/Liver/Muscle)

**Acceptance.** The forest plot always carries the watermark. tier_score is identical with and without the layer. A differently seeded table needs no code change.

### P4.7 Condition x assay signal matrix at the SNP

later · effort M · should · lenses: functional

**Spec.** Mean signal over +/-150 bp per bigWig:
- rows: ChromHMM, ATAC, H3K27ac, H3K4me1, H3K4me3, H3K27me3, CTCF
- columns: 5 tissues x 4 conditions, plus 5 stages

Values are z-normalised with each header's totalSummary. Conditions that weren't assayed are hatched. This becomes cheap after P4.9.

**Data.** public-available-now: AQUA-FAANG bigWigs

**Acceptance.** Unassayed cells are distinguishable from zero signal, and the warm render time is reported.

### P4.8 Genome-wide ChromHMM state layer (not only inside robust peaks)

later · effort M · should · lenses: functional

**Spec.** Build a non-overlapping union of the 21 per-condition segmentations into an interval layer, giving chromhmm_<condition> per SNP. Show 'Quiescent (assayed)' separately from 'not assayed'. segmentation_counts: false in weights.yaml until G decides.

**Data.** public-available-now: chromatin_states .bed/.bb; needs-G for tier use

**Acceptance.** The known-loci set gets non-empty states in all 21 conditions on release/dev.

### P4.9 Build-time per-peak signal layer

later · effort M · should · lenses: engineer, functional

**Spec.** For each unified peak and condition, compute mean ATAC from local bigWigs into signal.parquet. annotate then adds signal_atac_<condition>. Display only until G decides.

**Data.** public-available-now (about 15-25 GB of bigWigs to fetch on the build machine)

**Acceptance.** Per-peak means match bbi.bins(n=1) within float tolerance on the fixture regions.

### P4.10 Per-base GERP RS lane and value

later · effort S · could · lenses: functional

**Spec.** Read the Ensembl 116 65-fish GERP conservation bigWig at the SNP and as a locus lane. Display only.

**Data.** public-available-now: ftp.ensembl.org GERP bigWig

**Acceptance.** The lane renders for the vgll3 window, and the card shows the RS at the SNP.

### P4.11 Allele-specific accessibility in AQUA-FAANG fish

later · effort L · could · lenses: functional

**Spec.** A stdlib BAM reader (BAI plus BGZF ranges) counts ref and alt ATAC reads in heterozygous BodyMap fish. Reports a binomial p, with warnings for mapping bias and low depth.

**Data.** public-available-now: trackhub BAM/BAI, 12-fish VCF

**Acceptance.** Counts match samtools mpileup on one test locus.

### P4.12 Rainbow trout functional conservation

later · effort L · could · lenses: functional

**Spec.** An offline halLiftover of robust peaks to the trout genome, joined to trout ChromHMM, gives a trout_conservation layer.

**Data.** public-available-now, but needs offline HAL tooling

**Acceptance.** The card shows 'trout: aligned; active in ...' for the fixture peaks.

### P4.13 Gill ATAC peak display layer (sea lice, AGD)

later · effort S · should · lenses: breeder, functional

**Spec.** Merge the replicate Gill ATAC narrowPeaks from the trackhub into a non-overlapping interval layer, gill_atac, with conditions. It shows in the table, card and locus browser. Tier use stays G's decision, so the weight is 0.

**Data.** public-available-now: trackhub Gill narrowPeak files; needs-G for tier use

**Acceptance.** Fixture SNPs inside Gill peaks get gill_atac true, and tier_score is unchanged.

## M5 Explore without an upload

_Make the portal a reference people check every day ('what is going on at vgll3 in gonad?') through search, gene pages, variant pages, ortholog names, a known-loci catalogue, transparent data, methods, help and run-locally pages, and a guided demo tour._

### P5.1 Landing page with one search box and resolver

**now** · effort S · must · lenses: ux, breeder, geneticist, functional

**Spec.** /snp/ becomes the landing page. The upload moves to /snp/score/ and keeps the URL name 'upload'.

The landing page has:
- an H1 and one line on what the portal is for
- a large search input
- example chips: vgll3, six6, 25:28.95-29.05 Mb, 25:28996360
- entry cards: Score a SNP list, Explore a locus, Known loci, Take the vgll3 tour
- a stats strip from the manifest

search.py resolver, in order:
1. Positions and regions by regex, with chr/ssa/RefSeq names through alias.parquet and kb/Mb units.
2. DuckDB on the gene layer: exact gene_id, then name ignoring case, then prefix. Ortholog symbols and descriptions are searched once P5.10 exists.
3. Catalogue locus names.

One hit redirects; several hits show a disambiguation table. Autocomplete uses hx-get suggest/ with 'keyup changed delay:200ms' and returns the top 10. No match shows suggestions.

**Data.** public-available-now: gene layer, alias.parquet, catalogue

**Acceptance.** - 'vgll3' disambiguates between Ensembl's chr21 'vgll3' and the catalogue's chr25 maturation vgll3 (ENSSSAG00000053708).
- 'ssa25:28,990,000-29,000,000' opens the locus browser on chr25.
- '25:28996360' opens the variant page.
- suggest/ returns at most 10 rows from a single query; timing is reported under SNPSCORE_DEV.

### P5.2 Gene page, and gene or interval lists to candidate jobs

**now** · effort M · must · lenses: ux, functional, breeder

**Spec.** Page /snp/gene/<gene_id>/:
- Header: display name (Ensembl name, catalogue alias or ortholog), id, description, biotype, location, strand, and Ensembl/salmobase links.
- Expression bars per tissue.
- An embedded locus browser for the gene +/-50 kb.
- Heatmap 'Regulatory elements near this gene':
  - rows are robust peaks in the window, labelled by distance to the TSS
  - columns are the 21 conditions
  - side bars show GERP overlap, regbuild type and the number of public variants
- Candidate SNPs from the pool in the window, re-tiered for the chosen preset, with public AF.
- TSV download.
- 'Score these' calls jobs.create_from_rows.
- An ohnolog placeholder until P5.8.

'From genes or intervals' tab on /snp/score/:
- Paste gene ids or names, or chrom:start-end intervals, with an optional flank.
- The matching pool rows become a job, which then reaches the overview, panel and exports.

**Data.** public-available-now: release layers, pool, expression layer

**Acceptance.** - /snp/gene/ENSSSAG00000053708/ on the fixture renders expression bars, a 21-column element heatmap, and a candidate list that includes 25:28996360.
- 'Score these' lands on a results page.
- Pasting 'ENSSSAG00000053708' and '26:14.5-15Mb' creates one job whose row count equals the pool rows in those windows.

### P5.3 Known-loci catalogue with effect alleles

**now** · effort S · should · lenses: breeder, geneticist

**Spec.** Catalogue file:
- Build copies benchmark/known_loci.tsv to release/catalog/known_loci.tsv.
- It gains structured columns effect_allele and effect_direction, filled only where the paper states an allele unambiguously. vgll3 Met54Thr: T = early maturation. vgll3 Asn323Lys: C = early maturation. The bco1l paper alleles (T/G) are on the other strand and are marked 'to verify'. The other rows stay as text.
- Extra rows of type 'qtl_interval' (chrom, start, end, trait, DOI) are allowed and are PROVISIONAL until G vets them.

Annotate adds:
- known_locus: exact position, or within 50 kb
- known_locus_dist
- known_effect_allele, harmonised to the user's ref/alt, with a note when the alleles are swapped or strand-flipped

The results get a badge and a filter. The card gets a callout section (trait, effect allele, DOI links), and the effect allele goes into exports. The landing page lists the catalogue with one-click locus, gene and candidate queries.

**Data.** public-available-now: 6 published SNPs; needs-G: QTL intervals

**Acceptance.** - Uploading known_loci.tsv badges all 6 rows.
- The vgll3_Met54Thr card shows the callout with DOIs and effect allele T.
- An upload with ref and alt swapped still reports T as the effect allele, now flagged as the user's ref allele.
- Interval rows render with a PROVISIONAL badge.

### P5.4 Data, methods, glossary, help and 'Run it locally' pages generated from the release

**now** · effort S · must · lenses: ux, geneticist, functional, breeder

**Spec.** Data page (about/data/):
- A manifest table: layer, description, source, version/date, sha256, rows, synthetic flag, citation, licence and a per-layer download link.
- A track table from tracks.yaml: assay, tissue, sex, maturity/stage, replicates, and n fish where the metadata give it.
- A population scope note: European farmed fish. North American salmon differ in karyotype and allele frequencies.

Methods page (about/methods/):
- Coordinate conventions.
- weights.yaml as readable tables: evidence -> weight, cut-offs, presets -> conditions, and later the assay/design blocks.
- A warning: 'Provisional prototype rules, pending decision by G'.
- The methods_text paragraph.
- A benchmark dot plot (server SVG) with Wilson CIs, captioned 'n = 6, smoke test only'.

Glossary: each ChromHMM state with swatch, abbreviation and a one-line definition (wording needs G). Column headers and badges link to its anchors.

Help page:
- quick start
- FAQ: aliases; ICSASG_v2 and how to lift with prep/lift_icsasg_v2.py offline; chip manifests; 'blacklisted means can't tell'; LORe cross-hybridisation; A/T-C/G
- colour key, how to cite, contact

Run it locally page, for confidential lists:
- The release download with its sha256. snpscore build writes release.zip and release.zip.sha256.
- pip install instructions.
- The exact snpscore commands for the current settings, from provenance().

**Data.** public-available-now: manifest.json, weights.yaml, tracks.yaml, benchmark.tsv; state definitions needs-G

**Acceptance.** - Every manifest layer appears on the data page.
- Editing weights.yaml in a test release changes the methods tables.
- Each glossary anchor resolves from the table headers.
- The run-locally command, run on the fixture, reproduces the job's ?plain=1 TSV.

### P5.5 Element pages and element tissue specificity

later · effort M · should · lenses: functional

**Spec.** Element CPM per tissue x condition, from the nf-rasqual ATAC consensus featureCounts, with tau and replicate CV. Page /snp/element/<chromatin_id>/ shows the state grid, CPM dots, tracks, SNPs and candidate genes.

**Data.** public-available-now: nf-rasqual ATAC consensus featureCounts

**Acceptance.** tau lies in [0,1], and the page lists the uploaded and pool SNPs inside the element.

### P5.6 Candidate target genes beyond the nearest gene

later · effort M · should · lenses: functional

**Spec.** element_gene_links.parquet: genes within +/-250 kb (provisional), with:
- ATAC-RNA correlation across matched samples
- distance
- a promoter link
- a CTCF-boundary flag
Hypothesis-generating only, with no weight.

**Data.** public-available-now: nf-rasqual ATAC and RNA count matrices

**Acceptance.** The card lists the top 3 genes with r and distance.

### P5.7 Gene expression per tissue x condition with tau

later · effort M · should · lenses: functional

**Spec.** TPM from the salmon count matrices, averaged per tissue x condition, with tau. Gonad, HeadKidney and DistalIntestine come from RNA bigWig coverage, labelled 'coverage, not TPM'.

**Data.** public-available-now

**Acceptance.** The gene page shows a tissue x condition dot plot, and tau lies in [0,1].

### P5.8 Ss4R ohnolog context

later · effort S · should · lenses: functional

**Spec.** Columns from SalmonTroutOrthologs.tsv: ohnolog id and chromosome, rediploidisation class and trout orthologs. The gene page shows mirrored expression bars for both copies and links to the ohnolog's page.

**Data.** public-available-now: AQUA-FAANG salmon-trout orthologs (check that the Ens106 ids still hold in Ens116)

**Acceptance.** The chr25 vgll3 page links to its chr21 ohnolog.

### P5.9 TF motif disruption (ref vs alt)

later · effort M · should · lenses: functional

**Spec.** Score JASPAR2022 PWMs on both strands for ref and alt in SNP +/-30 bp, with provisional thresholds. Rank by AQUA-FAANG motif activity in the active conditions.

**Data.** public-available-now: AQUA-FAANG TFBS motifs, genome

**Acceptance.** A planted synthetic motif-disrupting allele is reported.

### P5.10 Ortholog names for unnamed salmon genes

**now** · effort S · should · lenses: breeder, geneticist, ux

**Spec.** Fetch:
- Human and zebrafish ortholog symbols (one-to-one and one-to-many) for the Ensembl 116 salmon genes.
- Source: an Ensembl BioMart TSV query, or the Compara homologies TSV filtered while streaming, whichever is available for release 116.
- Stored as data/raw/gene_orthologs.tsv; the fixture gets the rows for its genes.

Build adds a 'gene'-type layer: gene_ortholog_human and gene_ortholog_zebrafish.

Display name rule: the Ensembl name, else the catalogue alias, else 'unnamed (human VGLL3)'. It is used in search, the table, the card and the gene page.

**Data.** public-available-now: Ensembl 116 Compara homologies

**Acceptance.** - Fixture ENSSSAG00000053708 shows its human ortholog symbol, as checked against the fetched table (expected VGLL3).
- Searching 'VGLL3' finds both salmon copies.
- Genes without orthologs keep their id.

### P5.11 Guided 'vgll3 and maturation' tour

**now** · effort S · should · lenses: ux, breeder, geneticist

**Spec.** /snp/tour/ is a 6-step walkthrough with a sticky 'Step n of 6 · Next' bar:
1. search 'vgll3' and disambiguate
2. the gene page for ENSSSAG00000053708
3. the locus browser with maturation-preset ATAC
4. the vgll3 Met54Thr evidence card
5. the overview and table of an example job (known loci plus public sites near vgll3, created on first visit with create_from_rows)
6. the panel designer and its exports

Short plain text explains what each view shows and what is provisional.

**Data.** public-available-now (published loci, public sites)

**Acceptance.** A Django test follows all 6 step links and gets 200 for each. The tour works offline, with signal rows hatched.

### P5.12 rsID support

later · effort S · could · lenses: geneticist, breeder

**Spec.** Search and upload by rs ID through a Ssal_v3.1 rsID table, from EVA if one exists for this assembly.

**Data.** needs verification: EVA Ssal_v3.1 rsID release

**Acceptance.** Searching rs863785818 resolves to 26:19138923.

## M6 Breeding toolkit: assayable markers, panels, chip comparison and exports

_Turn ranked SNPs into an order-ready panel. Polymorphic, assayable markers are chosen under spacing, per-gene, per-element and must-include constraints, gaps in an existing chip are found, and the result is exported in vendor and genomic-prediction formats with full provenance._

### P6.1 Public allele frequency 'point' layer and peak ids (Wave A)

**now** · effort S · must · lenses: breeder, geneticist

**Spec.** New layer type 'point':
- An exact chrom/pos join, allele-aware when the input has ref/alt; AF is flipped when the alleles are swapped.
- public_af reads the 12-fish VCF INFO fields AF (imputed on 504 fish) and DR2.
- Outputs: public_af (found), public_af_af, public_af_maf, public_af_dr2.
- A user maf/af column is preferred and labelled 'your MAF'.

Interval layers may set id: true to emit <layer>_id = chrom:start-end. It is set for chromatin, so chromatin_id identifies the AQUA-FAANG peak, which the panel's per-element cap needs.

The README documents the 'point' type and ids.

**Data.** public-available-now: 12-fish VCF INFO AF/DR2 (fixture VCF keeps INFO)

**Acceptance.** - 25:28996360 gets public_af_af equal to its VCF INFO AF (0.67).
- Swapped alleles give 1-AF.
- Non-public positions are false/NULL.
- SNPs inside peaks get chromatin_id.

### P6.2 Assay designability QC from the Ssal_v3.1 genome

**now** · effort M · must · lenses: breeder, ux, functional

**Spec.** snpscore/assay.py extends the sequence checks. Outputs:
- assay_flank: a 71-mer with [REF/ALT]. Neighbouring public variants are written as lowercase IUPAC codes, with alleles from one DuckDB range join on public_af.parquet within +/-35 bp.
- assay_gc and assay_repeat (soft-masked share).
- assay_homopolymer: the longest run touching the probe.
- assay_n: Ns in the flank.
- ref_check, which already exists.
- assay_status (pass/warn/fail/not_checked) and assay_reasons.

not_checked applies when the chromosome is missing from the .fai, or when the genome is remote and the list has more than 2,000 SNPs.

Rules come from a weights.yaml 'assay:' block, marked PROVISIONAL and to be confirmed with the genotyping lab or vendor:
- flank 35
- gc [0.30, 0.70]
- max_repeat 0.5
- max_homopolymer 6
- max_flank_variants 0 (warn)
- warn_flags [lore, blacklist, strand_ambiguous]
- fail on ref mismatch, not_snp or N in the flank

SNPs are processed in genome order. The pool is not assay-checked.

The card assay section, the table's Assay group and the dashboard KPI/panel appear through column gating.

**Data.** public-available-now: Ssal_v3.1 bgzipped genome (local in data/raw), public AF alleles

**Acceptance.** - vgll3_Met54Thr gets a 71-mer that matches the fixture genome, with [C/T] at position 36 and any public neighbour within 35 bp shown as IUPAC.
- chr25 SNPs outside 28.95-29.05 Mb fail with 'N in flank'.
- chr1/21/26 SNPs are not_checked and leave the '% assay pass' denominator.
- Changing a threshold in weights.yaml changes the status counts.
- Synthetic-sequence tests cover homopolymer, GC-extreme and lowercase-repeat cases.
- The 50K local timing is reported under SNPSCORE_DEV.

### P6.3 Panel designer (backbone + functional fill under constraints)

**now** · effort M · must · lenses: breeder, geneticist, ux

**Spec.** snpscore/panel.py design(con, params) returns the selection, with panel_reason (must_include / backbone / functional:<preset>) and panel_rank.

Inputs:
- target N and backbone fraction
- min spacing
- max per gene and max per AQUA-FAANG element (chromatin_id)
- must-include ids
- exclusions: assay fail, blacklist, A/T-C/G, flank variants > k, MAF < x, near chip (P6.6)
- presets, with slots split between them
- an optional per-chromosome minimum

The distance metric is a pluggable function: bp now, cM once a genetic-map layer exists (P6.9).

Algorithm:
1. One DuckDB query computes design_score, a provisional weighted sum of normalised tier_score, assay and MAF terms (weights in a weights.yaml 'design:' block).
2. Must-include markers go first.
3. Backbone: the best candidate per genome-length-proportional bin.
4. Fill the remaining slots by design_score, checking spacing with bisect over the selected positions per chromosome.
Ties are always broken by file_row_number.

Parameters live in the URL. The selection is saved as panels/<params-hash>.parquet in the job folder.

UI: a Panel tab with:
- a summary card: N per chromosome, tier, region class and reason; median and max gap; assay pass rate
- a per-chromosome SVG coverage strip, with gaps over X Mb highlighted
- the selected table (?panel=<hash>)

**Data.** public-available-now: the annotated upload, optionally plus pool candidates

**Acceptance.** On the fixture job, and on public_50k under SNPSCORE_DEV:
- All must-include ids are selected.
- No two markers are closer than the spacing.
- No gene or element exceeds its cap.
- The panel has exactly N markers, or fewer with the binding constraint named.
- Every row has panel_reason.
- Opening the same URL twice gives an identical parquet sha256.

### P6.4 Vendor submission exports (Illumina-style, Axiom-style, KASP) and the zip bundle

**now** · effort M · must · lenses: breeder, ux

**Spec.** snpscore/export.py writers. Each honours the current filters or panel and starts with the provenance header.

1. Illumina design input:
   - columns: Locus_Name, Target_Type=SNP, Sequence (60 bp + [REF/ALT] + 60 bp), Chromosome, Coordinate, Genome_Build_Version=Ssal_v3.1, Source, Source_Version, Sequence_Orientation, Plus_Minus
   - TOP/BOT by Illumina's published rule: A/C and A/G are TOP, T/C and T/G are BOT; A/T and C/G are resolved by walking outwards through the flanks
2. Axiom-style: ID, chrom, pos, and 35 bp[ref/alt]35 bp with known neighbours as IUPAC codes. A/T and C/G are flagged as needing two probes.
3. KASP/Agena: name plus at least 50 bp flanks in [A/G] notation.

not_checked and fail rows are excluded or flagged, by a parameter.

Column headers are kept in one dict. Every file and the UI say 'layout to confirm against the vendor's current template'. File names carry the release and preset.

Also offered: TSV, BED, Parquet, and a zip bundle containing the data, manifest.json, the weights.yaml snapshot, methods.txt and the figure SVGs.

**Data.** public-available-now: genome flanks (P6.2), public AF alleles for IUPAC

**Acceptance.** - TOP/BOT unit tests: A/G -> TOP, T/C -> BOT, and A/T and C/G resolved by the flank walk on synthetic sequences.
- The vgll3 Illumina sequence matches the fixture genome.
- Every export starts with provenance lines.
- The zip opens and lists the expected files.

### P6.5 Genomic-prediction priors bundle (BayesRC, GFBLUP/MultiBLUP, LDAK, annot)

later · effort S · must · lenses: geneticist

**Spec.** A zip from any results page, built with stdlib zipfile, with categories chosen by checkboxes and computed in one DuckDB query. Contents:
- bayesrc_classes.txt: one class per SNP in input order, from a provisional weights.yaml 'priors:' hierarchy
- sets/<category>.txt
- ldak_partitions/
- annot.tsv: CHR, BP, SNP, 0/1 category columns, tier_score and per-condition active flags
- README.txt
IDs come from the id column, or chrom:pos:ref:alt when it is missing.

**Data.** public-available-now

**Acceptance.** For the fixture VCF, bayesrc_classes.txt has 1,456 lines in input order. README counts match the table, and annot.tsv columns are 0/1 apart from tier_score.

### P6.6 Compare with an existing chip (overlap, gaps, new functional coverage)

**now** · effort S · should · lenses: breeder

**Spec.** Chip input:
- A second input on the results page: 'Reference chip (coordinates only)', accepting any P2.6 format.
- Stored as chip.parquet in the job folder; it expires with the job.

One ASOF join gives on_chip and dist_to_chip. novel_functional = tier 1-2 with no chip marker within W (default 10 kb, provisional).

Outputs:
- a KPI row: shared, novel functional, chip markers
- chip ticks on the P3.2 ideogram
- a table of chip gaps over 1 Mb, each with the best candidate from the upload or the pool
- a 'not near chip' filter and panel exclusion

Creates the prep/make_synthetic.py skeleton: seed, SYNTHETIC naming and header line. It has a 'chip' subcommand that writes release/<v>/demo/chip_demo_SYNTHETIC.tsv: every 30th public site, plus deliberate gaps over 1 Mb on three chromosomes. This file is offered as an example button.

**Data.** synthetic-for-now: demo chip from public sites (labelled); user chips are uploads only

**Acceptance.** - With the synthetic demo chip, shared + novel + other counts add up to the total.
- The planted gaps over 1 Mb are listed, each with a filler.
- The 'not near chip' filter and the panel exclusion change counts as expected.
- Every view of a demo-chip job shows the SYNTHETIC badge.

### P6.7 Saved, versioned panels with diff (opt-in retention)

later · effort M · could · lenses: breeder

**Spec.** Save a panel under a private capability URL with opt-in 30-day retention. A diff view shows two panels' added and removed markers with reasons. This would be the first Django model, so only once G agrees.

**Data.** user panels (private, time-limited)

**Acceptance.** The diff lists every change with its reason.

### P6.8 Ohnolog cross-hybridisation risk for probes

later · effort L · could · lenses: breeder

**Spec.** Per SNP: % identity of the 35 bp flank to its best Ss4R ohnolog match, from an exact or 1-mismatch scan of the paired ohnolog block (+/-50 kb). Adds a provisional 'paralog' warn rule.

**Data.** public-available-now: LORe tables, ortholog quartets, genome

**Acceptance.** In LORe region 1-18, probes show higher identity than non-LORe controls.

### P6.9 Genetic map (cM) layer and cM-based spacing

later · effort M · should · lenses: breeder, geneticist

**Spec.** Sex-specific cM positions from public salmon linkage maps, lifted to Ssal_v3.1 and interpolated per SNP. Male crossovers cluster near the telomeres, so bp spacing is a poor proxy. The cM positions feed P6.3's distance function and the P7.2 loci windows as an option.

**Data.** needs-G/data: choice of public linkage map(s) and a v2 -> v3.1 lift

**Acceptance.** Panel spacing in cM respects the minimum, and the interpolated cM values are monotonic per chromosome.

### P6.10 Multi-population allele frequencies

later · effort M · could · lenses: breeder, geneticist

**Spec.** A second AF layer for other populations or lineages, such as North American salmon, which differ in karyotype. AF is shown side by side, and the panel MAF filter can choose the population.

**Data.** needs-G: population VCFs or AF tables

**Acceptance.** The card shows AF per population, and the MAF filter follows the chosen population.

## M7 GWAS summary statistics and functional fine-mapping (next push, Wave D)

_Turn a GWAS peak into a functional short list. Upload sumstats and get a Manhattan plot, a calibration check, defined loci, LocusZoom-style regional plots over salmobase tracks, and ABF fine-mapping that compares uniform and annotation-informed priors. Results are deleted after 24 h. Everything built now (formats, jobs, locus browser, card, figures) is reused._

### P7.1 Sumstats upload mode with format detection and harmonisation

later · effort M · must · lenses: geneticist, ux, functional

**Spec.** Detection: formats.py aliases for GEMMA, GCTA-fastGWA, PLINK2 .glm, regenie and BOLT map to the RESERVED canonical names.

One DuckDB SELECT derives:
- z = beta/se, when beta and se are present.
- neglog10p from the p string. Mantissa and exponent are parsed separately, so p = 1e-400 doesn't underflow DOUBLE to 0 and p-only files work. Otherwise from LOG10P, or from z (log10 erfc through statistics.NormalDist, with the asymptotic formula for |z| > 30).
- For p-only rows, z is recovered from p for lambda.

The job records input_kind = 'gwas' and shows a validation card:
- rows and drops by reason
- share of rows with beta/se
- lambda_GC = median(z^2)/0.4549

Unplaced scaffolds are dropped and counted. The GWAS SYNTHETIC example button is added to /snp/score/.

**Data.** synthetic-for-now (P1.6b); real GWAS are user uploads only

**Acceptance.** - The fastGWA and PLINK2 variants are both detected.
- lambda_GC is within 0.01 of the truth file's empirical lambda.
- The string '1e-400' in a p-only file gives neglog10p = 400.
- The example job shows the SYNTHETIC badge on every page.

### P7.2 Manhattan plot, tier-stratified QQ plot and loci table

later · effort M · must · lenses: geneticist, ux

**Spec.** An 'Association' tab, with all figures as server SVG.

Manhattan:
- Chromosomes in alternating greys.
- Points with p > 0.01 are thinned to the max per 50 kb bin, keeping the SVG under 1 MB.
- Tier 1-2 SNPs are overplotted in tier colours.
- User-set threshold lines (defaults 5e-8, Bonferroni and 1e-5), labelled as conventions.
- Clicking a peak opens P7.3.

QQ:
- One line per tier stratum, switchable to region class or active-in-preset.
- Each line is thinned to about 2,000 quantiles, with a 95% band and lambda_GC per stratum.

Loci: greedy distance clumping. Defaults are 5e-8 and a 1 Mb window, provisional because farmed lines have long-range LD; a cM option comes with P6.9. Columns:
- locus, lead, p, beta
- n SNPs and n significant
- tier 1/2 counts within 2 log10 units of the lead
- best functional candidate and nearest genes
- LORe
- credible-set sizes (P7.4)
The table downloads as TSV or BED.

**Data.** synthetic-for-now

**Acceptance.** - Fixture scale: the four planted loci (chr25 vgll3, chr26 nae1 element, chr21 element, chr1 decoy) come out as separate loci, and the SVG is under 1 MB.
- Dev scale (SNPSCORE_DEV=1) adds the chr9 six6 locus.
- The QQ lambda matches P7.1.

### P7.3 LocusZoom-style regional association plot on the locus browser

later · effort S · must · lenses: geneticist, functional, ux

**Spec.** When the locus browser has ?result=<gwas job>, the top lane is -log10 p against position:
- points coloured by tier
- a diamond for the lead, triangles for CDS/splice, an outline for credible-set members
- a significance line
- a <title> tooltip on each point, which also opens its card
The same gene, chromatin, ATAC, regbuild and GERP lanes sit below on a shared x-axis. The page states that no LD is used.

**Data.** synthetic-for-now (sumstats) + public-available-now (tracks)

**Acceptance.** For the synthetic vgll3 locus, the plot shows the planted causal SNP with its credible-set outline, above the ATAC lanes (synthetic tracks offline, real tracks live). The SVG downloads standalone.

### P7.4 Wakefield ABF fine-mapping with uniform vs functional priors

later · effort M · must · lenses: geneticist

**Spec.** Per locus, assuming a single causal variant:
- V = se^2. W = prior_sd^2: default 0.04 on the standardised scale, from a provisional 'finemap:' block, adjustable.
- Effect scale: beta in phenotype units is divided by a user-entered trait SD. When only z, N and AF are given, V ~ 1/(2N maf(1-maf)) and beta = z sqrt(V).
- log ABF = 0.5 ln(V/(V+W)) + 0.5 z^2 W/(V+W).
- Priors: uniform, or functional pi_i proportional to exp(lambda * tier_score_i), with lambda provisional (default 0.5).
- Each locus shows its max/min prior ratio; it can reach about 90x.
- PIPs come from a log-sum-exp window query. The 95% credible set is taken in descending PIP order.

Outputs:
- PIP_uniform, PIP_functional and credible-set membership per SNP
- credible-set sizes before and after, per locus
- a slope chart SVG and a TSV

A banner states the single-causal assumption, that no LD is used, and that results are sensitive to W and lambda.

**Data.** synthetic-for-now

**Acceptance.** These checks cover mechanics only. The causal SNPs were planted in tier 1-2, so recovering them proves nothing about the method.
- PIPs sum to 1 per locus.
- Credible sets reach 0.95.
- The functional prior shrinks the credible sets at loci (a)-(c) and keeps the decoy (d) tier-4 causal in its set.
- A z/N/AF-only file gives the same PIPs as the beta/se file on standardised data.

### P7.5 Enrichment vs matched background and 21-condition relevance heatmap

later · effort M · should · lenses: geneticist, functional

**Spec.** Mantel-Haenszel OR with 95% CI, stratified by gene-distance bin x MAF bin x local density, per category and condition. Empirical p from circular-shift permutations. Shown as a forest plot and a 21-cell log-OR heatmap. It suggests presets but never changes them.

**Data.** synthetic-for-now + public background

**Acceptance.** The planted enrichment is recovered with a CI that excludes 1.

### P7.6 Public LD reference from the 504-fish phased panel

later · effort L · should · lenses: geneticist

**Spec.** Haplotype bits per biallelic SNP stored as a DuckDB BLOB, read with a stdlib BGZF reader. r^2 to the lead via bit_count. Used for LocusZoom colour bins, LD clumping and the credible-set table.

**Data.** public-available-now later: 504-fish phased VCF (929 MB); needs-G permission to host

**Acceptance.** r^2 matches a direct computation on a synthetic panel.

### P7.7 Functional proxy finder for array lead SNPs

later · effort M · should · lenses: geneticist, breeder

**Spec.** Public variants not in the upload, with r^2 >= t to a lead and tier <= 2, ranked by r^2 x tier_score and shown with assay flags.

**Data.** needs P7.6

**Acceptance.** A planted untyped causal SNP is recovered.

### P7.8 Colocalisation with caQTL/eQTL and between two traits

later · effort L · should · lenses: geneticist, functional

**Spec.** coloc ABF H0-H4 per locus x molQTL feature, with provisional priors. A PP.H4 heatmap and a mirror plot.

**Data.** needs-G: nf-rasqual result tables

**Acceptance.** Synthetic shared loci get PP.H4 > 0.8.

### P7.9 Heritability enrichment helper

later · effort S · could · lenses: geneticist

**Spec.** Upload per-category h2 and get enrichment = (h2_c/h2)/(n_c/n) with a delta-method SE.

**Data.** synthetic-for-now example

**Acceptance.** Reproduces the hand-computed example.

## M8 Scale, API and going-online readiness

_What remains between a working prototype and a shared salmobase service: annotate speed, scripted access, offline parity, observability, release integrity, fair-use limits and the reader extras deferred from P1.2. Scheduled after G says go, except P8.1, which can join Wave E._

### P8.1 Speed up annotate (nearest gene by ASOF joins, narrow table)

later · effort M · should · lenses: engineer

**Spec.** Nearest gene: replace the +/-1 Mb range join (76 s of 127 s at 1.6M SNPs) with an upstream ASOF on end, a downstream ASOF on start and a gene-body interval layer.

Count layer: replace the correlated EXISTS with an ASOF equality join.

Run every layer on a narrow (idx, chrom, pos, ref, alt) table and join the input columns once at the end.

Not blocking: the pool skips assay QC and builds in about 2 min today.

**Data.** public-available-now

**Acceptance.** The golden hash is identical, and 1.6M SNPs take under 60 s (reported, dev).

### P8.2 Versioned JSON API v1

later · effort M · should · lenses: breeder, engineer, geneticist

**Spec.** Endpoints under /snp/api/v1/:
- release
- jobs (POST, up to 10K rows; returns 202)
- jobs/<key>
- jobs/<key>/snps (the same filter whitelist)
- jobs/<key>/snps/<row> (the evidence dict)
- export
- DELETE

Plain JsonResponse. csrf_exempt applies only to API POST/DELETE, with an Origin check. Coordinates go only in request bodies. A docs page gives curl, Python and R examples.

**Data.** public-available-now

**Acceptance.** A scripted upload -> poll -> Parquet download matches the UI export, ignoring the header.

### P8.3 Offline CLI parity for confidential data

later · effort M · should · lenses: geneticist, breeder

**Spec.** CLI wrappers: snpscore panel, export --format illumina|axiom|kasp|priors, loci, finemap, and plot --region (needs figures.py moved into snpscore). The numbers match the portal.

**Data.** public-available-now

**Acceptance.** CLI and portal outputs match on the fixture and the synthetic GWAS.

### P8.4 Observability without content and a health endpoint

later · effort S · should · lenses: engineer

**Spec.** Allowlisted structured log events and Server-Timing headers.

/snp/health reports:
- release status
- results dir writable and free space
- queue depth
- track-host reachability and TLS, cached for 5 min

Counters for range reads, cache hits and timeouts.

**Data.** none

**Acceptance.** No log line contains a coordinate (tested with a canary SNP).

### P8.5 Release integrity: verify, diff and Django system checks

later · effort S · should · lenses: engineer

**Spec.** - 'snpscore verify' re-hashes release files.
- 'snpscore diff' feeds the changelog.
- A django.core.checks check validates the release, the results dir and the DuckDB version.

**Data.** public-available-now

**Acceptance.** A corrupted parquet fails 'manage.py check' with a clear message.

### P8.6 Fair-use limits and queue fairness

later · effort S · could · lenses: engineer

**Spec.** Per-client counters, keyed by a salted IP hash: 1 running and 2 queued jobs, plus a daily row budget. Caps on page size, locus window, tracks per view and exports.

**Data.** none

**Acceptance.** A third concurrent job from one client gets 429 with Retry-After.

### P8.7 Genome-wide annotated public catalogue and per-category downloads

later · effort M · could · lenses: geneticist

**Spec.** The pool published as a catalogue with a tier per preset, plus coverage.tsv per category. A downloads page with per-category BED/TXT per preset.

**Data.** public-available-now (504-fish sites when available)

**Acceptance.** Coverage shares match a direct count on the fixture.

### P8.8 Remote reader extras deferred from P1.2

later · effort S · should · lenses: engineer

**Spec.** - ETag recording and If-Range, dropping caches when a file changes.
- An on-disk header cache in SNPSCORE_CACHE_DIR (header, zoom headers and chromosome tree, keyed by url and ETag).
- Merging adjacent blocks with gaps under 8 KB.
- SNPSCORE_DATAFILES_ROOT, which maps https://salmobase.org/datafiles/... to local paths on the salmobase host.
- Range-server fault modes for ETag change and redirect.

**Data.** public-available-now

**Acceptance.** An ETag change drops the cache in the range-server test. With DATAFILES_ROOT set, reads go to local files and make 0 HTTP requests.

## Architecture notes

BUILD SCOPE AND ORDER
This push is Waves A-C: 29 build_now items (13 M, 16 S, no L). The draft had about 33 (16 M, 1 L). The reduction comes from:
- splitting P4.3 and P4.4
- trimming P1.2, P1.3, P1.5 and P1.6
- folding the gene/interval candidate lists into P5.2, and the run-locally page into P5.4
- moving GWAS (Wave D) and polish (Wave E) to the next push

Each wave stops cleanly with a working, demonstrable portal. If A-C pass acceptance with time left, continue with Wave D in order; it starts without rework.

- Wave A, foundations (in order): P1.6a, P1.1, P1.4, P6.1, P2.1, P2.6, P1.5, P1.3, P2.3.
- Wave B, the demo slice with salmobase tracks: P4.2, P4.1, P1.2, P3.1, P4.3a, P4.3b, P3.2, P3.3, P5.3, P4.4a, P5.1, P5.4, P2.2.
- Wave C, the breeder toolkit: P5.10, P5.2, P6.2, P6.3, P6.4, P6.6, P5.11 (the tour comes last, because it walks through everything).
- Wave D, the next push (GWAS): P1.6b, P7.1 (with the GWAS example button), P7.2, P7.3, P7.4.
- Wave E, polish: P3.4, P3.5, P4.5, P6.5, P4.6, P1.7, P8.1.

Dependency rules that keep the waves clean:
1. Column gating. Every dashboard panel, KPI, table filter, card section and export column renders only when its column exists in the result, the pattern views.py already uses with `if column in types`. Later layers (assay, known locus, orthologs, coding, molQTL, GWAS) add themselves without changing earlier views.
2. The locus browser accepts coordinates and aliases first. Gene names come from the P5.1 resolver, AF tick heights from P6.1 and the GWAS lane from P7.3, each appearing once its data exists.
3. Ownership:
   - tier_terms belongs to P1.3.
   - The RESERVED column list belongs to P1.1.
   - chromatin_id belongs to P6.1.
   - jobs.create_from_rows belongs to P1.3.
   - The make_synthetic.py skeleton belongs to P6.6 (chip). P1.6b adds gwas and P4.6 adds molqtl.

MODULE BOUNDARIES
salmo-snpscore owns data, rules and analytics, with no Django.
- Existing modules:
  - annotate.py:
    - read_snps uses formats.detect, sanitising, aliases, validation stats and the LIMIT cap.
    - Layer types are interval (optional id), nearest, count, gene, and the new point and features types.
    - It has a progress callback.
    - Known chromosomes come from manifest chrom_sizes.
  - score.py: emits tier_terms and skips synthetic layers.
  - bbi.py: one read per tree node, keep-alive, a persistent executor, an LRU, zoom-level reads, bins_many with a deadline.
  - fasta.py: reuses Source.
  - build.py: alias, transcripts (features), public_af (point), chrom_sizes, per-file sha256, and the synthetic/citation/provisional manifest fields; it also copies the catalogue and demo inputs and writes release.zip.
- New modules:
  - __init__.connect() (the sandbox)
  - formats.py (input detection and header aliases, shared with gwas)
  - tracks.py (trackDb -> tracks.yaml)
  - pool.py
  - assay.py
  - panel.py
  - export.py (provenance, methods_text, vendor writers, bundle)
  - Later: coding.py and gwas.py.
- CLI: adds pool and tracks.

salmo-snpportal owns HTTP, jobs, templates and figures.
- views.py: pages and fragments.
- jobs.py: job folders, the executor (WORKERS=0 for synchronous runs), job.json, cleanup, summary.json, create_from_rows.
- search.py: the resolver.
- figures.py: pure functions from plain data to SVG strings (ideogram, stacked bars, condition heatmap, barcode, chromatin grid, tier-contribution bar, locus, coverage strip, benchmark dot plot). Labels go through html.escape. They embed literal hex from palette.py and have no Django imports, so they can move into snpscore later.
- palette.py: the single source of colours.
- management/commands/snpportal_cleanup.py.
- Templates:
  - base_portal.html extends salmobase/base.html.
  - Partials: _page_header, _figure, _badges, _footer.
  - Pages: landing, score (upload | from genes or intervals), job progress, results (tabs Overview | Table | Panel; Association arrives in Wave D), card, variant, locus, gene, tour, about_data, methods, help, run_locally.
- Static: portal.css and portal.js.

Constraints:
- Python 3.8, Django 4.2, DuckDB 1.2.2.
- duckdb, pyyaml and the stdlib only.
- htmx from jsdelivr with SRI. No chart libraries and no JS build.
- No Django models; state lives in job folders.
- The SVG viewer complements salmobase's jbrowse_react through deep links.
- Cache: in the sandbox settings, FileBasedCache under SNPPORTAL_CACHE_DIR (or LocMemCache with MAX_ENTRIES >= 5000). It holds public signal tiles only.

URL MAP under /snp/:
- '' (landing); score/; search/ and search/suggest/; tour/
- locus/ and locus/svg/; gene/<id>/; variant/<chrom>-<pos>[-ref-alt]/
- about/data/, about/methods/, help/, run-locally/
- results/<key>/ with ?tab=, ?panel=, ?chip=
- results/<key>/status/
- results/<key>/snp/<row>/ and results/<key>/snp/<row>/locus.svg
- results/<key>/figure/<name>.svg
- results/<key>/download/?format=tsv|parquet|bed|illumina|axiom|kasp|bundle (plus &plain=1)
- results/<key>/chip/ (POST)
- results/<key>/delete/ (POST)
All view state stays in whitelisted URL parameters. User coordinates never appear in URLs of card or figure fragments.

DATA CONTRACTS
README 'Release format' and TRACKER are updated with each item.

Release additions:
- alias.parquet (alias, chrom)
- transcripts.parquet (type features; never annotated)
- public_af.parquet (type point: chrom, start, end, ref, alt, af, dr2)
- pool/pool.parquet and pool/background.json. Annotate never globs the release folder.
- tracks.yaml: version, hosts, tracks[{id, assay, tissue, sex, maturity, stage, condition, chromatin_condition (nullable; Gill is null), kind, urls[], source}], defaults
- catalog/known_loci.tsv, with effect_allele and effect_direction columns and optional qtl_interval rows
- demo/: known loci, public_50k, chip_demo_SYNTHETIC
- gene_orthologs, as a gene-type layer
- release.zip and release.zip.sha256
- manifest: chrom_sizes; per layer sha256, synthetic and citation; the provisional list; snpscore and DuckDB versions

New annotate columns:
- in_<slug>, for passthrough user columns
- chromatin_id
- public_af, public_af_af, public_af_maf, public_af_dr2
- gene_description, gene_ortholog_human, gene_ortholog_zebrafish
- known_locus, known_locus_dist, known_effect_allele
- assay_flank, assay_gc, assay_repeat, assay_homopolymer, assay_n, assay_status, assay_reasons (alongside the existing genome_base, ref_check, flank_gc, flank_repeat)
- tier_terms LIST(STRUCT(term, weight))
- on_chip, dist_to_chip, novel_functional (chip comparison, per job)

weights.yaml gains these blocks, each with a PROVISIONAL comment and listed in manifest.provisional:
- assay
- design (component weights, min_maf, backbone_fraction, min_spacing, max_per_gene, max_per_element)
- Wave D adds finemap. Wave E adds priors and molqtl: 0.

Job folder results/<uuid>/ (mode 0700, files 0600) holds:
- job.json
- result.parquet (with KV metadata) and tiers.parquet
- summary.json, validation.json and rejects.tsv
- weights.yaml and manifest.json (the snapshot)
- chip.parquet, when a chip was given
- panels/<hash>.parquet

job.json fields: state, stage, n_rows, heartbeat, timings, error_code, input_kind (snps|gwas|from_rows), input_format, synthetic_input, release, manifest_sha256, weights_sha256, snpscore_version, duckdb_version, created_utc, input_sha256, preset.

REMOTE TRACK DATA (measured 2026-10-06)
- salmobase serves Range requests with CORS for the bigWigs, the ChromHMM .bb/.bed files and the bgzipped genome.
- BodyMap trackDb lists 60 ATAC, 274 ChIP and 168 RNA bigWigs.
- The current reader needs 32 requests and 6-10 s to open one bigWig. It reads two requests per tree node, walking 3,361 sequences node by node. P1.2 reads one request per node and the whole chromosome tree in one read, for 3 requests or fewer to open a file and read one window.
- In the Python 3.8 venv (OpenSSL 1.1.1d), TLS fails with CERTIFICATE_VERIFY_FAILED. Set SNPSCORE_CA_FILE to a current CA bundle, including in .claude/launch.json for dev. Never disable verification.
- Views show at most 8 signal rows: R1 by default, replicate bands only on request.
- Tiles sit on a fixed public grid and never carry user positions.
- When the network is down, rows are hatched 'signal unavailable'. Signal is never synthesised in the UI.
- The 12-fish VCF INFO already carries AF (imputed on 504 fish) and DR2.
- UCSC uses the GenArk hub GCF_905237065.1 with RefSeq names, mapped through alias.parquet. The UCSC and JBrowse link formats are marked 'to verify'.

VISUAL STYLE
- Calm, compact, gnomAD/Ensembl-like on Bootstrap 5.1.3.
- Typography: system font stack; tabular-nums at 0.875rem in data views; monospace for coordinates and sequences.
- Neutral grey ramp plus a salmobase-blue accent. White cards with hairline borders. No hero images.
- Every figure card has an (i) definition, SVG/PNG/TSV downloads and a provenance caption.

Palettes are defined once in palette.py, and SVGs embed the literal hex values.
- Tiers, sequential with the number always printed:
  - 1 #08519C (white text)
  - 2 #3182BD (white text)
  - 3 #C6DBEF
  - 4 #F0F0F0 (with border)
- ChromHMM, each state with an abbreviation in every cell and legend:
  - Active_TSS #B2182B 'TSS'
  - Flanking up/down #F4A582 'Fl'
  - Active_enhancer #E66101 'Enh'
  - Primed_enhancer #FEE08B 'Pri'
  - Poised_enhancer_1/2 #92C5DE 'Poi'
  - Accessible_chromatin #2166AC 'Acc'
  - Bivalent #762A83 'Biv'
  - Repressed_polycomb #878787 'Pc'
  - ZNF_genes_and_repeats #BABABA 'ZNF'
  - Quiescent #F0F0F0 'Q'
  - Unknown_1 #DDDDDD '?'
  - no peak: white with a #ccc border
  - blacklisted: hatched 'BL'
  This is one dict, so G can swap in AQUA-FAANG itemRgb.
- Tissues, Okabe-Ito: Brain #0072B2, Gill #56B4E9, Gonad #CC79A7, Liver #D55E00, Muscle #009E73, Embryo #E69F00.
- Status: warn #B26B00 on #FFF4E0; fail #B2182B; not_checked in grey. Always icon plus text, never colour alone.
- Badges: PROVISIONAL outlined dark; SYNTHETIC striped purple #6A3D9A, plus a non-removable SVG watermark on figures built from synthetic data.

Accessibility: role=img with <title> and <desc> on every SVG; AA contrast, with one tier-badge test; visible focus; scope on table headers; print CSS for the card and report.

TESTING
- The offline suite runs on the fixture plus test-time synthetic files. With networking disabled, it covers:
  - the sanitiser and sandbox
  - aliases and formats
  - the point layer
  - synthetic bigWig read-back and range-server request counts and fault modes
  - assay rules, TOP/BOT and panel constraints
  - Django end to end: upload -> job -> overview, table, card, locus, gene, search, panel, exports, tour
  - every figure parsed as XML
- Gates are deterministic proxies, never wall-clock times:
  - request counts
  - scored() not called when the preset changes
  - row-filtered card SQL
  - identical panel hashes
  - the golden annotate hash
- Timings are reported only, under pytest markers: live (SNPSCORE_LIVE=1, salmobase) and dev (SNPSCORE_DEV=1, release/dev).
- Print layout (card on one A4 page, report on two) goes on a TRACKER manual-QA list.

RECORDS
- Add a 'Portal roadmap v2' section to salmo-snpscore TRACKER.md with these ids as checkboxes, plus the manual-QA list.
- Record every provisional choice in CLAUDE.md under 'Provisional': assay thresholds, design weights, default track sets, the chip window W and the 50 kb catalogue radius.
- Update the README release contract with each new file and column.

## Synthetic data

Labelling rules for every synthetic file:
- The file name contains SYNTHETIC.
- Text files start with '# SYNTHETIC test data generated by <script> (seed N): not real results'.
- Any release layer built from synthetic data has synthetic: true in the manifest and never adds to tier_score.
- The portal shows a striped SYNTHETIC badge, a page banner, an export header line and a non-removable SVG watermark wherever synthetic data contributes.

Storage:
- Full-size outputs go to data/synthetic/ and are never committed.
- Fixture-scale outputs are generated at test time into tmp, or committed under tests/fixture/synthetic/ only when small.
- Portal example inputs are copied into release/<v>/demo/.
- No breeder data is used or imitated beyond generic, public file formats.

Built in this push:
1. Test tracks (P1.6a, written at test time by tests/bbi_writer.py):
   - Files: synthetic_ATAC_<condition>_R1-3.bw over chr25 28.95-29.05 Mb.
   - Content: Gaussian peaks at the fixture robust peaks plus noise, with one zoom level.
   - A test tracks.yaml points at them, served by tests/range_server.py with Range, a request counter and the ignore-range and slow modes.
   - Used by the locus, card, gene and tour tests offline.
   - No bigBed until P4.3c.
2. Upload probes (P1.1, P2.1, P2.2, generated in tests):
   - headers with quotes and reserved names
   - alias-named chromosomes
   - fixture VCF sites in the chr25 real-sequence window shifted +1,000 bp (assembly warning)
   - swapped and strand-flipped alleles, and duplicates
   - a small gzip bomb for the row cap
   - an oversized CONTENT_LENGTH request
3. Chip and PLINK formats (P2.6, generated in tests):
   - tiny SYNTHETIC Illumina-manifest, Axiom-annotation, PLINK .bim/.map and header-alias CSV files
   - all built from fixture public positions, in generic layouts only; no real manifest content
4. Assay and TOP/BOT sequences (P6.2, P6.4):
   - short synthetic sequences written as BGZF with the existing bgzf_block helper in tmp
   - planted homopolymers, GC extremes, lowercase repeats, Ns, and A/T and C/G cases for the flank walk
5. chip_demo_SYNTHETIC.tsv (P6.6, prep/make_synthetic.py chip, seed 42):
   - every 30th public site, plus deliberate gaps over 1 Mb on three chromosomes
   - fixture scale: every 30th fixture VCF site plus one planted gap
   - copied to release/<v>/demo/ as the example button for chip comparison

Next push:
6. gwas_maturation_SYNTHETIC.tsv (P1.6b, make_synthetic.py gwas):
   - Columns: chrom, pos, id, ref, alt, beta, se, p, af, n (n = 1,500).
   - Variants: fastGWA headers, PLINK2 .glm headers, and a p-only file with the string '1e-400'.
   - Null z ~ N(0, sqrt(1.05)).
   - Fixture-scale loci, inside existing fixture regions:
     - (a) vgll3 Met54Thr 25:28996360, p about 1e-30
     - (b) a public site in a Liver/Gonad Active_enhancer peak in chr26 14-16 Mb, p about 1e-9
     - (c) an active element in chr21 32-34 Mb, p about 1e-12
     - (d) a chr1 110-111 Mb LORe decoy with an intergenic tier-4 causal, p about 1e-10
   - Dev scale adds six6 9:23837450 and about 200K genome-wide public sites.
   - LD is mimicked by distance decay: z_j = z_c * exp(-|d|/L) * u_j + N(0,1), with L between 20 and 80 kb.
   - gwas_maturation_SYNTHETIC_truth.tsv records the causal ids, z_c, L and the empirical null lambda. Tests compare against these values, not against nominal ones.
7. molqtl_SYNTHETIC.tsv (P4.6, Wave E, make_synthetic.py molqtl):
   - about 300 public sites inside robust peaks in the fixture regions
   - Brain/Gill/Liver/Muscle x kind ca/e
   - beta ~ N(0, 0.5), se ~ U(0.08, 0.2), BH q, is_lead per feature, synthetic = true on every row
   - some leads shared with GWAS loci (a) and (b), for later colocalisation tests

Real public demo inputs, labelled as published or public and not synthetic:
- benchmark/known_loci.tsv: 6 published SNPs with DOIs, plus the new effect_allele columns.
- data/demo/public_50k.vcf: public 12-fish sites.

Later steps replace item 6 with users' own GWAS (never kept beyond 24 h) and item 7 with G's nf-rasqual tables (a data swap with the same columns), and add the 504-fish VCF for AF and LD.

## Open questions for G

As asked on 2026-10-06. The current list, with options and recommendations, is [DECISIONS.md](DECISIONS.md); the
answers are in ../AGENTS.md "Decided". Answered or overtaken since: the nf-rasqual tables were found (R4), the genetic
map is Brekke 2023 (R5), unnamed genes get ortholog labels (P5.10), both colour schemes exist (R8; the default is
DECISIONS #18), and local installs keep results until deleted (G, 2026-11-03).

- Active states: are Active_TSS and Active_enhancer the right 'active' set? How should primed, poised, bivalent, flanking and accessible chromatin count? Should states outside robust ATAC peaks (genome-wide ChromHMM segmentation) count towards tiers at all?
- Trait presets: which conditions should each trait use (maturation, growth/fillet, disease resistance, development)? Should the embryo stages feed any trait? Which new traits are needed first (e.g. sea lice, AGD, smoltification)?
- Gill: Gill has ATAC and ChIP but no ChromHMM. Should Gill ATAC peaks (planned as a display-only layer, P4.13) feed the disease-resistance preset or a new sea lice/AGD preset, and with what weight?
- Tier weights and cut-offs: should missense outrank synonymous CDS? Should molQTL evidence get a weight once real tables exist (it is 0 for now)?
- Where are the nf-rasqual caQTL/eQTL result tables (Brain, Gill, Liver, Muscle), and in what format? Until then the molQTL contract stays synthetic and display-only.
- Population scope and lineage: AF and AQUA-FAANG come from European farmed fish. How should the 504-fish population be described (strain, origin, year)? Do partners work with North American salmon (different karyotype and AF), and is a multi-population AF layer needed? May we derive and host public AF and a packed-haplotype LD reference from the 504-fish phased VCF?
- Genetic map: which public linkage map(s) should provide sex-specific cM positions, and should panel spacing and GWAS loci windows use cM rather than bp?
- Default track sets for the locus browser: ATAC only, or also H3K27ac/H3K4me3? R1 only or the replicate mean by default? Which conditions should the 'all' preset show within the 8-row cap? Which DevMap tracks matter?
- ChromHMM colours: keep the portal's palette with abbreviations, or match AQUA-FAANG's own itemRgb colours for consistency with the papers and JBrowse? (Either is a one-file change.)
- Assay QC thresholds (GC range, repeat fraction, homopolymer length, flank-variant tolerance, LORe/blacklist handling): can the CIGENE genotyping lab confirm them? Who will supply the current Axiom and Illumina submission templates and confirm the TOP/BOT and sequence-orientation layout?
- Panel design defaults (backbone fraction, minimum spacing, max per gene and per element, MAF floor, design-score weights) and the chip-comparison window W (10 kb): are these yours or the breeding partners' to set?
- Gene naming: for genes unnamed in Ensembl 116 (including the maturation vgll3), is the label 'unnamed (human VGLL3)' from Compara orthologs acceptable? Or should we prefer NCBI RefSeq names or a curated alias list?
- Known-loci catalogue: which published QTL intervals and lead SNPs should be added beyond vgll3, six6 and bco1l (e.g. IPN on chr26 near nae1/cdh1, sea lice, growth)? Who vets them? Please confirm the effect alleles, especially the bco1l strand.
- Fine-mapping defaults (next push): prior effect SD 0.2 on the standardised scale (W=0.04), a functional prior of exp(0.5 x tier_score) (up to about 90x prior ratio), a 1 Mb clumping window and 5e-8. Acceptable as labelled defaults? Should users always supply a trait SD when betas are in phenotype units?
- Confidentiality: breeders' SNP lists are themselves IP. Is the 24 h retention with 'delete now' and the privacy statement acceptable? Is distributing the release zip with 'run it locally' instructions acceptable for confidential lists? Do you want opt-in saved panels (30 days), which would bring the first Django model?
- Should we build the genome-wide ICSASG_v2 -> Ssal_v3.1 position table (P2.5) for legacy chip manifests and published GWAS, and do partners need it soon?
- Branding and citation: the portal name, how to cite it, a contact address, and the salmobase JBrowse deep-link URL format for 'open in JBrowse'.

## Push 2: research-driven corrections and additions

From the research sweep in [RESEARCH.md](RESEARCH.md) (section numbers there). Items R1-R3 correct work built in push 1.

- **R1** Public AF from the 504-fish panel (not the 12-fish INFO AF); relabel the population; keep frequencies only (effort S, must)
- **R2** Vendor export corrections: sidecar provenance, numeric build, uppercase IUPAC, TOP/BOT 'cannot determine', locus names, chr 0, flank lengths, panel bin/spacing warnings; TOP/BOT oracle test (effort S, must)
- **R3** Known-loci catalogue 6 -> 36 verified rows across 8 traits; published-associations lane and card callout; bco1l A (+) = red (effort S, must)
- **R4** Real molQTL lead-SNP layer from the public nf-RASQUAL tables (brain, gonad, liver, muscle ATAC + 5 RNA; weight 0; licence to confirm) (effort M, should)
- **R5** Genetic map layer (Brekke 2023, native Ssal_v3.1, male/female cM) and cM spacing in the panel designer (effort S, should)
- **R6** rsID search and ICSASG_v2 -> Ssal_v3.1 for known variants via the EVA release 9 rs bridge (effort S, should)
- **R7** Alias table: accept .2 GenBank versions (chr 9, 11, 18, 26); warn on HG993277.1 (effort S, should)
- **R8** AQUA-FAANG itemRgb palette option, citation block, ENA/FAANG metadata on the Data page; SalmoBase gene deep links; NCBI LOC search (effort S, should)
- **R9** P4.5 note: vgll3 Met54Thr is T46M on ENSSSAT00000230965 (offset 8 to the published numbering) (effort S, could)

## Push 3: industry users (G, 2026-11-04)

From two industry users' requests (data security and storage, user accounts, several or custom genomes, genome
comparison, DeepFARM and a CADD-like score; chip design as in commercial software) and the review of 2026-11-04
(TRACKER.md step 8). G agreed the plan and its order on 2026-11-04: phase 1, then the chip items I7-I12, the scores
(I15-I16) when G's data is ready, the genomes later. One box per item in TRACKER.md step 9.

Assumptions (G, 2026-11-04):
- One user per install, who shares results as files (exports, the bundle, I7's project export). No accounts and no
  shared company server (on hold).
- The chip user is aquaculture genotyping in Norway, so Thermo Fisher Axiom (Affymetrix) comes first; Illumina and
  KASP second. To confirm with a partner (DECISIONS #27).
- Genome comparison is on hold until G has asked the users what they need (DECISIONS #28).

### Phase 1: ready to hand to companies

#### I1 Self-contained pages: Bootstrap and htmx shipped with the package

phase 1 · effort S · must

**Spec.** Copy Bootstrap 5.1.3 (CSS and bundle JS; MIT) and htmx 2.0.11 (0BSD) into
`snpportal/static/snpportal/vendor/` with their licence texts. The stand-in `snpsite/templates/salmobase/base.html`,
`base_portal.html` and `base_embed.html` load them with `{% static %}`; salmobase's own base template keeps its
Bootstrap. Then the README's and Help's 'what leaves your computer' are complete as written.

**Acceptance.** No template names cdn.jsdelivr.net. With the network off, `manage.py screenshots` reports htmx and
Bootstrap loaded on the Score page, and a job's progress panel refreshes until its results show.

#### I2 Data-handling sheet

phase 1 · effort S · must

**Spec.** One section in the README and in Help's privacy part (local wording), written for a company's IT review:
- what is stored (the job folder's files, the Design panel, the projects of I7);
- where (the data folder `salmo-snp info` names) and for how long (until deleted);
- every network request and why (signal tiles for viewed regions; the genome only with `--no-genome`);
- how to delete everything;
- that the files are protected by the user's account and disk encryption (FileVault, BitLocker, LUKS), as any
  working file;
- that sharing means sending exported files.
The wording is G's to approve (DECISIONS #20).

**Acceptance.** Every network call in the code (urlopen, the remote readers) is listed; a reviewer can answer "can our
SNPs leave this computer?" from the sheet alone.

#### I3 The public background pool in every install

phase 1 · effort S · must

**Spec.** `snpscore pool` takes its sites from the release itself (`public_af`: the 12 AQUA-FAANG fish's sites, as the
12-fish VCF gives today, or the 504-fish panel: DECISIONS #15), so it needs nothing from data/raw.
`salmo-snp download` builds it after checking the files (and `serve` when it is missing), and so does nrec.sh. A
weight change rebuilds it, as now.

**Acceptance.** After a fresh `salmo-snp download`, the Overview draws its thin public bars, ticks and the × fold, with
the same shares as a pool built from the 12-fish VCF.

#### I4 Versions users can name

phase 1 · effort S · must

**Spec.** G tags v0.1.0 (release.yml builds the wheels); the README and Run locally install `@v0.1.0`. Each tag's
GitHub Release carries `constraints.txt`, the exact versions its CI passed with, for installs that must reproduce a
result (`pip install -c constraints.txt ...`). `salmo-snp info` and every export name the installed salmo-snp and
snpscore versions. The three names are registered on PyPI (DECISIONS #25).

**Acceptance.** An install from the README with the constraints file has CI's versions; `salmo-snp info` prints them.

#### I5 The install on macOS and Windows

phase 1 · effort S-M · must

**Spec.** tools/user_install_test.sh finds a Windows venv's `Scripts\`; CI runs it on macOS and Windows on a schedule
and on tags (a private repository's macOS minutes count 10x: DECISIONS #26), Linux on every pull request. Then fix
what breaks (paths inside SQL literals, file modes, signals).

**Acceptance.** The three systems pass on a tag.

#### I6 The tier rules confirmed

phase 1 · G · must

**Spec.** G answers DECISIONS #1-#5 (active and weak states, presets, weights and cut-offs, synonymous SNPs) with the
eQTL benchmark (#4a-#4c); the answers go into weights.yaml and AGENTS.md "Decided", and the PROVISIONAL labels go from
what is decided. Then the genome-wide release v0.1 (TRACKER step 4).

**Acceptance.** Methods, the report and the downloads call provisional only what is still open.

### Phase 2: chip design (Axiom first)

#### I7 Saved design projects

phase 2 · effort M · must (P6.7, without its server retention)

**Spec.** A project is a named folder in the data folder (`projects/<name>/`): its candidate lists (job keys), chips,
populations (I9), notes and panel versions. A version holds the SNPs, the parameters, each SNP's reason and a hash, and
never changes. A diff page shows two versions' added and removed markers with their reasons. The project is the unit
to share: export as a zip, import on another computer. Today's one-per-browser Design panel becomes the project's
working panel. No database: JSON and Parquet files, as job folders.

**Acceptance.** After closing the browser and restarting serve, the project and every version are back; the diff of
two versions lists every change with its reason; export then import elsewhere gives the same panel hash.

#### I8 Panel presets and target sizes

phase 2 · effort M · must

**Spec.** Presets that set the designer's parameters for a purpose: genomic selection (even spacing in cM, a MAF
floor, mostly backbone), parentage and traceability (a few hundred unlinked, high-MAF SNPs), a trait panel (known loci
and tier 1-2 SNPs near them), and mixtures (a share per purpose). Target sizes follow the vendor's formats (Axiom
custom array sizes and plate formats, KASP plates; to confirm with the vendor). Every number in a preset is
PROVISIONAL, in weights.yaml `design.presets`, for G to set.

**Acceptance.** Each preset designs a fixture panel that meets its own constraints; the panel and its report name
the preset and its parameters.

#### I9 The user's own population

phase 2 · effort M · must

**Spec.** Upload allele frequencies (chrom, pos, ref, alt, af, n) or genotypes (VCF, PLINK) for one or more of the
user's populations. Genotypes are read as they stream and only per-SNP counts are kept (as snpdata's `count_gt`):
MAF, call rate and HWE p per SNP and population, in the project. The designer's MAF filter and informativeness use
the population picked, and the Table and card show it next to the public panel's. Local installs only: a server never
offers it.

**Acceptance.** On a synthetic genotype file, MAF, call rate and HWE match a direct count; no genotype reaches the
disk (tested); the designer's MAF filter uses the picked population.

#### I10 Probe uniqueness

phase 2 · effort M-L · must (P6.8, and TRACKER step 3's assay part 2b)

**Spec.** For each candidate's flanks (35 bp for Axiom; 50-60 bp for KASP and Illumina): its best match in the Ss4R
duplicate region (the paired block +/-50 kb, from synteny.parquet; P6.8's scan) and, if a seed index of the genome fits
in a release (to measure first), how many places in the genome it matches with up to 2 mismatches. Pure Python and
DuckDB; an external aligner only with G's OK. Adds a 'paralog' warn reason (its threshold is G's).

**Acceptance.** Probes in LORe regions show higher identity to their duplicate than non-LORe controls; the vgll3 test
vector (RESEARCH section 5) is checked by hand.

#### I11 Compare and upgrade chips

phase 2 · effort M · must (extends P6.6)

**Spec.** Several chips at once (Axiom annotation CSVs and Illumina manifests, read as today): a matrix of overlap
(exact and within the window), density per Mb and per cM, gaps, functional content (tier 1-2, coding, known loci) and
MAF (public, or the project's population). 'Upgrade a chip' starts from one chip and makes a new project version: it
keeps the markers that work, drops failing ones (call rate and HWE from I9's genotypes, or a QC table the user gives),
then fills gaps and adds functional markers up to a target size.

**Acceptance.** On synthetic chips, the matrix matches direct joins; an upgrade keeps every passing marker it was told
to keep and meets its target size.

#### I12 A design report per panel

phase 2 · effort S-M · should

**Spec.** One printable report per panel version, like the results report: its purpose (preset and parameters),
markers per chromosome, spacing in bp and cM, MAF (public and own population), the assay check, functional content,
uniqueness warnings, the chip it upgrades and what changed, and provenance (release, weights, versions).

**Acceptance.** Two A4 pages for a 384-marker panel; every number matches the project's files.

#### I13 Vendor round trip, Axiom first

phase 2 · effort M · should

**Spec.** With a real Axiom submission template and a design-results file from a partner or the CIGENE lab (Thermo's
columns are not public: RESEARCH section 5): export to that template exactly, import the results into the project (per
SNP: designable or not, the vendor's score and probe choice), re-rank, drop what can't be made, and export the order.
Then Illumina DesignStudio scores and KASP.

**Acceptance.** A partner's real files round-trip: every SNP of the results file matches, and the export opens in the
vendor's tool unedited (the partner checks).

#### I14 Later chip items

phase 2, later · effort L · could

- LD-aware thinning and tagging, from the project's genotypes (I9) or a public LD reference (P7.6, DECISIONS #19).
- Amplicon and GT-seq panels: flanks for primer design (Primer3 input) and multiplex constraints.
- Agena MassARRAY (not researched yet).

### Phase 3: variant scores

#### I15 One format for per-variant scores

phase 3 · effort S-M · must

**Spec.** A `point` layer of precomputed scores (chrom, pos, ref, alt, `score`, `percentile` over the scored set),
with `model`, `version` and `scored_set` in layers.yaml and the manifest. annotate adds `<layer>_score`,
`<layer>_percentile` and `<layer>_scored`: false means outside the scored set, shown as 'not scored', never 0. Shown as
a Table column, in the card and as a locus-browser lane, with a benchmark row and a weights.yaml term (weight 0 until
G sets it). The fixture gets a SYNTHETIC score file.

**Acceptance.** The synthetic layer reaches every place above; tiers are unchanged at weight 0.

#### I16 DeepFARM and a CADD-like score

phase 3 · G's data · must when ready

**Spec.** G retrains DeepFARM with the extra data and makes a CADD-like score; each comes as an I15 file with a method
note, licence and citation. snpdata builds them into the next release; G sets their weights from the benchmark.

**Acceptance.** Both in a release and benchmarked against the known loci and the eQTL leads.

### Phase 4: genomes (later)

#### I17 Several releases side by side

phase 4 · effort M · should

**Spec.** One install holds several releases, possibly on different assemblies (the manifest's `assembly`). The
portal shows which one is in use and lets the user switch it; a job keeps reading its own release (it records it
already); upload pages say which assembly they expect; nothing mixes releases.

**Acceptance.** With two releases installed, jobs from each show their own release's data.

#### I18 Placement by probe sequence

phase 4 · effort M · should

**Spec.** A manifest's probe or flank sequences place its SNPs on Ssal_v3.1 whatever assembly the positions came from:
matched against the flanks of known variant sites (the 504-fish panel, EVA) kept in the release as a lookup, or exactly
against the genome near the given position. This fixes ICSASG_v2 chips beyond the rs-ID bridge.

**Acceptance.** An ICSASG_v2 Axiom manifest places at least as many SNPs as the rs bridge, and none where the flank
differs from the genome.

#### I19 Coordinate conversion between assemblies

phase 4 · effort M-L · could (P2.5)

**Spec.** ICSASG_v2 to Ssal_v3.1 for any position (a chain from an alignment made outside the tool, or I18's flank
method), then the new assembly and Ssal_v3.1 both ways once it is in use.

**Acceptance.** Positions with an EVA rs ID convert to the rs ID's other position.

#### I20 A release on the new Atlantic salmon assembly

phase 4 · G's data · could

**Spec.** After G has re-run AQUA-FAANG and the other analyses on the new assembly: a layers.yaml per assembly, the
alias table and chromosome names, `snpdata build`, then I17. Mostly outside the tool.

**Acceptance.** Both releases install side by side (I17) and score the same public SNPs at their own positions.
