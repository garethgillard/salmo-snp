# salmo-snpscore

Builds the annotation tables behind the salmobase SNP portal, and annotates any Atlantic salmon SNP list against them.
Layers so far: AQUA-FAANG chromatin states (21 conditions), blacklist, late-rediploidized (LORe) regions, nearest gene.

## Quick start

```bash
pip install -e .
snpscore fetch                                   # download public inputs into data/raw (~140 MB)
snpscore build --out release/v0.1                # standardise every layer in layers.yaml
snpscore annotate my_snps.vcf.gz --release release/v0.1 -o my_snps_annotated.tsv
pytest -q                                        # tests run on the small regions in tests/fixture
```

Input SNPs: a VCF, or a TSV/CSV with a header containing `chrom` and `pos` (other columns are kept).
Coordinates must be Ssal_v3.1 with chromosomes named `1`–`29`.

## Release format (the contract with the portal)

A release is one folder, named by its version:

```
release/v0.1/
  manifest.json      version, assembly, date, and per layer: type, description, url, source md5, rows, columns
  <layer>.parquet    one file per layer in layers.yaml
```

Every `<layer>.parquet` has `chrom`, `start`, `end` in BED coordinates (0-based start, end exclusive),
sorted by chrom and start, followed by the layer's value columns.

`snpscore annotate` writes one row per input SNP, in input order (TSV, or Parquet/CSV by file extension), with the input columns plus:

| Layer type | Added columns |
| --- | --- |
| `interval` | `<layer>` (true if the SNP is inside an interval), `<layer>_<column>` for each value column |
| `nearest` | `<layer>_<column>` for the nearest feature within `max_distance`, and `<layer>_distance` (0 = inside) |

A SNP at 1-based `pos` is inside an interval when `start < pos <= end`. Interval layers must not overlap; `build` checks this.

## Adding a layer

1. Add an entry to `layers.yaml` (name, type, format, file, url). If the input needs heavy processing (VEP, model scores), put the script that makes it in `prep/` and leave out `url`.
2. If the file format is new, add one reader function to `READERS` in `src/snpscore/build.py`.
3. Add a slice of it to `tests/fixture` (see `prep/make_fixture.sh`) and a check in `tests/`.

Progress and next steps: [TRACKER.md](TRACKER.md).
