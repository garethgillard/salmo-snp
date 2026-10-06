#!/usr/bin/env bash
# Cut the small test regions out of data/raw into tests/fixture. Run from the repo root after `snpscore fetch`.
# Regions: chr21 32-34 Mb (vgll3), chr26 14-16 Mb (nae1, IPN QTL), chr1 110-111 Mb (LORe region 1-18).
# SNPs come from the public 12-fish nf-rasqual VCF (every 3rd SNP, genotypes dropped).
# tests/fixture/snps.tsv is hand-written: positions with known answers, checked in tests/.
set -euo pipefail
RAW=data/raw
OUT=tests/fixture
VCF_URL=https://salmobase.org/datafiles/datasets/nf-rasqual-data/12_samples_genotype_filtered_on_504.vcf.gz
mkdir -p "$OUT"
HIT='function hit(c, s, e) { return (c=="21" && s<34e6 && e>32e6) || (c=="26" && s<16e6 && e>14e6) || (c=="1" && s<111e6 && e>110e6) }'

awk -F'\t' "$HIT hit(\$1, \$2, \$3)" "$RAW/AtlanticSalmon_unified_peaks.bed" > "$OUT/AtlanticSalmon_unified_peaks.bed"
awk -F'\t' "$HIT hit(\$1, \$2, \$3)" "$RAW/AtlanticSalmon_blacklist.bed" > "$OUT/AtlanticSalmon_blacklist.bed"
cp "$RAW/Ssal_late_rediploidized_regions.tsv" "$OUT/"
zcat "$RAW/Salmo_salar.Ssal_v3.1.116.chr.gff3.gz" | awk -F'\t' "$HIT \$3 ~ /gene\$/ && hit(\$1, \$4 - 1, \$5)" \
  | gzip > "$OUT/Salmo_salar.Ssal_v3.1.116.chr.gff3.gz"
curl -fsS "$VCF_URL" | zcat | awk -F'\t' -v OFS='\t' "$HIT /^#CHROM/ || (hit(\$1, \$2 - 1, \$2) && NR % 3 == 0) { print \$1,\$2,\$3,\$4,\$5,\$6,\$7,\$8 }" \
  > "$OUT/snps.vcf"
wc -l "$OUT"/*
