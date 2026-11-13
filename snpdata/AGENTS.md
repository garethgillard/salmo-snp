# snpdata: notes

Collects the public sources listed in layers.yaml and builds a release: one Parquet file per layer, alias and rs ID
tables, the known-loci catalogue (catalog/known_loci.tsv), the portal's examples, tracks.yaml and manifest.json.
Read ../AGENTS.md first (plan, rules, biology decisions); README.md's "Release format" is the contract with snpscore
and the portal.

- A release holds data only, never the tier rules (they are snpscore's weights.yaml), so it is built once and then
  served as static files. A new release gets a new version folder; a published one never changes.
- Layers use BED coordinates; interval layers must not overlap. Paths in layers.yaml are relative to --data.
- `fetch` streams the public VCFs and keeps sites and frequencies only: genotypes are never written.
- data/ and release/ are never committed. Never edit files in data/raw by hand.
- The motif layer uses snpscore's motif scoring, so a release records the snpscore version it was built with.
- After changing layers, re-cut the test fixture: `bash prep/make_fixture.sh`.
- One registry per species: `layers.yaml` (Atlantic salmon) and `rainbow_trout/layers.yaml` (USDA_OmykA_1.1; its
  tracks.yaml beside it, its fixture tests/fixture_trout from `python prep/make_fixture_trout.py`). A release's
  version says the species (trout-<date>); README "Rainbow trout". build.py has no species in it: what differs is
  in layers.yaml (`species`, `chromosome_names`, a layer's `species`, `pool`).
- `fetch` and `build` need data/raw (~1.5 GB) and, in a cloud session, the hosts listed in ../AGENTS.md "Cloud
  sessions"; the published release (../tools/get_data.sh) is enough for everything else.

```bash
python -m pytest -q
snpdata fetch && snpdata build --out release/dev
snpdata tracks                                # regenerate tracks.yaml from the AQUA-FAANG trackhub
bash prep/make_fixture.sh                     # re-cut tests/fixture from data/raw
```
