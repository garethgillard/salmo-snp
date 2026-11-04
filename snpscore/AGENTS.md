# snpscore: notes

Scores a SNP list against a release built by ../snpdata: `snpscore annotate` writes one row per SNP with each layer's
evidence and a tier. Read ../AGENTS.md first (plan, rules, biology decisions); README.md describes the input formats,
the annotate output, tiers, the pool, GWAS fine-mapping and the benchmark.

- The tier rules live in `src/snpscore/weights.yaml` (shipped with the package; `snpscore.WEIGHTS`). Every value in
  it is G's to decide; the PROVISIONAL ones say so.
- Output columns: `<layer>` (bool hit, or a number for count layers) and `<layer>_<column>`; then `strand_ambiguous`,
  `tier`, `tier_score`, `tier_evidence`.
- Interval layers must not overlap (annotate uses an ASOF join).
- Prefer one DuckDB SQL query over Python loops.
- Nothing here imports snpdata or snpportal; only the tests build their fixture release with snpdata.
- When the annotate output changes on purpose, update the golden hash in tests/test_snpscore.py (its comment says how).

Without a release/dev (it needs snpdata/data/raw, as on G's Mac), use the downloaded release: `bash
../tools/get_data.sh`, then `--release ~/.local/share/salmo-snp/releases/<version>` (`salmo-snp info` says where).

```bash
python -m pytest -q
snpscore annotate ../snpdata/tests/fixture/snps.vcf --release ../snpdata/release/dev -o /tmp/out.tsv
snpscore pool --release ../snpdata/release/dev --background ../snpdata/data/raw/12_samples_genotype_filtered_on_504.vcf.gz
snpscore benchmark --release ../snpdata/release/dev -o ../snpdata/release/dev/benchmark.tsv
```
