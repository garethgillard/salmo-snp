# salmo-snp: notes for people and their AI assistants

Functional SNP scoring for Atlantic salmon (Ssal_v3.1): public annotation data, a scoring engine and a web portal.
Owner: Gareth Gillard (G). The repository is private (invite only); licence: PolyForm Noncommercial 1.0.0 (LICENSE).
Each folder has its own CLAUDE.md with the details; read snpscore/CLAUDE.md before any data or scoring change.

## Layout
- `snpscore/`: builds the release (`snpscore fetch`, `snpscore build`) and scores SNP lists against it (`snpscore annotate`).
  Its CLAUDE.md holds the biology decisions (Decided / Provisional / Open); TRACKER.md says what's next.
- `snpportal/`: the Django web portal; reads a release and calls snpscore. `deploy/nrec.sh` runs the public demo.
- `snpdata/` (planned): the release build moves here out of snpscore/.

## Plan (G, 2026-10-28)
1. One repository, three folders. `snpdata/` collects the public sources and builds a versioned release (Parquet tables
   and manifest) once; it is published as static files on Apache, beside salmobase in its own folder. `snpscore/` only
   scores a SNP list against a release and can change without touching the rest. `snpportal/` is the website.
2. Dependencies point one way: snpdata -> snpscore <- snpportal. The release format (snpscore/README.md "Release
   format") is the contract between them.
3. Scoring rules stay out of the release: weights.yaml lives with snpscore, and whatever depends on the weights (the
   public pool's tiers, background summaries) is a cache that snpscore or the portal builds from the release.
4. The portal runs as its own Docker container: the same image for the public site and for running locally on
   127.0.0.1, so a user's SNP list never leaves their computer. salmobase links to it with a button; it is not merged
   into salmobase's Django. The release and genome are downloaded once into a volume and checked against the manifest's
   sha256, not baked into the image.
5. Semi-offline is fine: the portal may fetch public data at given locations (genome bases, AQUA-FAANG signal), but
   users' SNPs and results are never stored online.
6. A downloadable desktop program may come later, so nothing should depend on Docker-only features.

## Rules
- Biology decisions belong to G: thresholds, weights, 'active' state definitions, condition sets. Ask, don't invent;
  answers are recorded in snpscore/CLAUDE.md and snpscore/DECISIONS.md.
- Never commit breeder data (genotypes, GWAS results, array manifests): not in fixtures, tests or docs either.
  `data/`, `release/` and results folders are never committed.
- Keep it small: few files, little code, readable over clever. No new dependencies without asking G.
- Python 3.8 compatible until the portal's Dockerfile sets the version.

## Development
Tests use the small fixture in `snpscore/tests/fixture`, so they need no downloads.

```bash
python3 -m venv .venv
cd snpportal && ../.venv/bin/pip install -e "../snpscore[test]" -r requirements.txt && cd ..
(cd snpscore && ../.venv/bin/python -m pytest -q)
(cd snpportal && SNPPORTAL_WORKERS=0 ../.venv/bin/python manage.py test snpportal)
```
