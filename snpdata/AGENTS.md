# snpdata: notes

Collects the public sources listed in layers.yaml and builds a release: one Parquet file per layer, alias and rs ID
tables, the known-loci catalogue (catalog/known_loci.tsv), the portal's examples, tracks.yaml and manifest.json.
Read ../AGENTS.md first (plan, rules, biology decisions); README.md's "Release format" is the contract with snpscore
and the portal.

- A release holds data only, never the tier rules (they are snpscore's weights.yaml), so it is built once and then
  served as static files. A new release gets a new version folder; a published one never changes.
- Layers use BED coordinates; interval layers must not overlap. Paths in layers.yaml are relative to --data.
- `fetch` streams the public VCFs and keeps sites and frequencies only: genotypes are never written. It keeps a
  file that is there, except a salmobase file whose size or date on the server has changed since it was fetched
  (`.fetched.json` in the data folder): that one is downloaded again (G, 2026-11-25).
- `build --reuse <release>` copies a layer only when its settings and input checksums are the same and the release
  was built by the same code (the manifest's `code`: checksums of build.py and of snpscore's motif.py and fasta.py).
  So after a change to a reader every layer is computed again; never weaken that to save a build's minutes. Layers
  are written in a full row order (`ORDER BY ALL`): the same input gives the same bytes.
- data/ and release/ are never committed. Never edit files in data/raw by hand.
- The motif layer uses snpscore's motif scoring, so a release records the snpscore version it was built with.
- After changing layers, re-cut the test fixture: `bash prep/make_fixture.sh`.
- A per-variant score layer (README "A per-variant score") is a file from another project and one registry entry.
  The first is `chrombpnet_gill`, from the salmo-chrombpnet work on Orion (../docs/ORION.md has the request and the
  address). The fixture's file holds real predictions for its 697 SNPs in the model's peaks, made with the model's
  own scorer (numpy and onnxruntime in a scratch environment, never in this project's dependencies).
- One registry per species: `layers.yaml` (Atlantic salmon) and `rainbow_trout/layers.yaml` (USDA_OmykA_1.1; its
  tracks.yaml beside it, its fixture tests/fixture/rainbow_trout from `python prep/make_fixture_trout.py`). A release's
  version says the species and the assembly (`snpdata name`: rainbow_trout-USDA_OmykA_1.1-<date>; G, 2026-11-26;
  trout-<date> before); README "Rainbow trout". Code reads the species from the manifest, never from a name. build.py has no species in it: what differs is
  in layers.yaml (`species`, `chromosome_names`, a layer's `species`, `pool`).
- `fetch` and `build` need data/raw (~1.5 GB) and, in a cloud session, the hosts listed in ../AGENTS.md "Cloud
  sessions"; the published release (../tools/get_data.sh) is enough for everything else.

```bash
python -m pytest -q
snpdata fetch && snpdata build --out release/dev
snpdata tracks                                # regenerate tracks.yaml from the AQUA-FAANG trackhub
bash prep/make_fixture.sh                     # re-cut tests/fixture from data/raw
```
