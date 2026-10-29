#!/usr/bin/env bash
# Recreate the portal's demo inputs from data/raw. Run in snpdata/ after `snpdata fetch`, then
# `snpdata build --out release/dev` copies them into release/dev/demo/ (layers.yaml `demo`).
#   data/demo/public_50k.vcf     every 32nd site of the public 12-fish VCF (50,708 sites; first 8 columns, no genotypes)
#   data/synthetic/              SYNTHETIC demo chip and maturation GWAS (prep/make_synthetic.py chip, gwas; seed 42)
set -euo pipefail
PYTHON=${PYTHON:-python}
mkdir -p data/demo
gzip -dc data/raw/12_samples_genotype_filtered_on_504.vcf.gz \
  | awk -F'\t' -v OFS='\t' '/^##/ { next } /^#/ || ++n % 32 == 21 { print $1,$2,$3,$4,$5,$6,$7,$8 }' > data/demo/public_50k.vcf
"$PYTHON" prep/make_synthetic.py chip
"$PYTHON" prep/make_synthetic.py gwas
