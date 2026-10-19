#!/usr/bin/env bash
# Cut the small test regions out of data/raw into tests/fixture. Run from the repo root after `snpscore fetch`.
# Regions: chr21 32-34 Mb (Ensembl "vgll3", the ohnolog of the chr25 maturation gene), chr25 28.5-29.5 Mb (vgll3, akap11),
#          chr26 14-16 Mb (nae1, IPN QTL), chr1 110-111 Mb (LORe region 1-18), chr9 23-25 Mb (six6),
#          chr26 18.5-19.5 Mb (bco1l): the vgll3, six6, bco1l and IPN loci of benchmark/known_loci.tsv.
# SNPs come from the public 12-fish nf-rasqual VCF (every 3rd SNP, genotypes dropped).
# Also cut: the 504-fish panel sites (frequencies only, as `snpscore fetch` keeps them), the nf-RASQUAL lead SNPs with
# BF < 1, the Brekke genetic map (plus the marker either side of each region) and EVA rs IDs (every 40th in the regions
# plus the catalogue's, with their ICSASG_v2 lines).
# tests/fixture/snps.tsv is hand-written: positions with known answers, checked in tests/.
set -euo pipefail
RAW=data/raw
OUT=tests/fixture
VCF=12_samples_genotype_filtered_on_504.vcf.gz
mkdir -p "$OUT"
HIT='function hit(c, s, e) { return (c=="21" && s<34e6 && e>32e6) || (c=="25" && s<29.5e6 && e>28.5e6) ||
                                    (c=="26" && s<16e6 && e>14e6) || (c=="1" && s<111e6 && e>110e6) ||
                                    (c=="9" && s<25e6 && e>23e6) || (c=="26" && s<19.5e6 && e>18.5e6) }'
bed() { awk -F'\t' "$HIT hit(\$1, \$2, \$3)" "$RAW/$1" > "$OUT/$1"; }
gff() { gzip -dc "$RAW/$1" | awk -F'\t' "$HIT !/^#/ && hit(\$1, \$4 - 1, \$5)" | gzip > "$OUT/$1"; }

bed AtlanticSalmon_unified_peaks.bed
bed AtlanticSalmon_blacklist.bed
bed gerp_constrained_elements.salmo_salar.bed
awk -F'\t' "$HIT NR == 1 || hit(\$1, \$2, \$3)" "$RAW/Ssal_late_rediploidized_regions.tsv" > "$OUT/Ssal_late_rediploidized_regions.tsv"
gff Salmo_salar.Ssal_v3.1.116.chr.gff3.gz
gff Salmo_salar.Ssal_v3.1.regulatory_features.v116.gff3.gz
gzip -dc "$RAW/$VCF" | awk -F'\t' -v OFS='\t' "$HIT !/^#/ && hit(\$1, \$2 - 1, \$2) { print \$1,\$2,\$3,\$4,\$5,\$6,\$7,\$8 }" \
  | gzip > "$OUT/$VCF"
gzip -dc "$RAW/$VCF" | awk -F'\t' -v OFS='\t' "$HIT /^#CHROM/ || (hit(\$1, \$2 - 1, \$2) && NR % 3 == 0) { print \$1,\$2,\$3,\$4,\$5,\$6,\$7,\$8 }" \
  > "$OUT/snps.vcf"
SITES=ALL_chrome_phased_filtered_HWE_1e6_biSNPs_MAF_0.01.sites.vcf.gz  # ID (chrom_pos_ref_alt) blanked to keep it small
gzip -dc "$RAW/$SITES" | awk -F'\t' -v OFS='\t' "$HIT /^#/ { print; next } hit(\$1, \$2 - 1, \$2) { \$3 = \".\"; print }" \
  | gzip -9 > "$OUT/$SITES"
SYNCHRO=synchrosmolt_parents.sites.vcf.gz  # sites and counted frequencies only (as fetch keeps them); chromosomes ssa01-ssa29
gzip -dc "$RAW/$SYNCHRO" | awk -F'\t' -v OFS='\t' "$HIT /^#/ { print; next } { c = \$1; sub(/^ssa0?/, \"\", c) }
     hit(c, \$2 - 1, \$2) { \$3 = \".\"; print }" | gzip -9 > "$OUT/$SYNCHRO"
for f in "$RAW"/nfrasqual_*.txt; do
  awk -F'\t' "$HIT FNR == 1 { print; next } { split(\$1, s, \"_\") } hit(s[1], s[2] - 1, s[2]) && \$7 < 1" "$f" > "$OUT/${f##*/}"
done
awk "$HIT NR == 1 { print; next } { h = hit(\$1, \$3 - 1, \$3) } h && !was && prev { print prev } h || was { print }
     { prev = \$0; was = h }" "$RAW/brekke2023_linkage_map.txt" > "$OUT/brekke2023_linkage_map.txt"
V31=8030_GCA_905237065.2_current_ids.vcf.gz
V2=8030_GCA_000233375.4_current_ids.vcf.gz
cut -f15 benchmark/known_loci.tsv | grep '^rs' > "$OUT/rs.tmp"
gzip -dc "$RAW/$V31" | awk -F'\t' -v OFS='\t' "$HIT NR == FNR { keep[\$1]; next } /^#CHROM/ { print; next } /^#/ { next }
     { c = \$1; sub(/^ssa0?/, \"\", c) } hit(c, \$2 - 1, \$2) && (++n % 40 == 0 || \$3 in keep) { print \$1,\$2,\$3,\$4,\$5,\".\",\".\",\".\" }" \
  "$OUT/rs.tmp" - | gzip -9 > "$OUT/$V31"
gzip -dc "$OUT/$V31" | cut -f3 | grep '^rs' > "$OUT/rs.tmp"
gzip -dc "$RAW/$V2" | awk -F'\t' -v OFS='\t' 'NR == FNR { keep[$1]; next } /^#CHROM/ { print; next } /^#/ { next }
     $3 in keep { print $1,$2,$3,$4,$5,".",".","." }' "$OUT/rs.tmp" - | gzip -9 > "$OUT/$V2"
rm "$OUT/rs.tmp"
# Expression and orthologs: only the genes in the fixture GFF3. Aliases: only the fixture chromosomes.
gzip -dc "$OUT/Salmo_salar.Ssal_v3.1.116.chr.gff3.gz" | grep -o 'gene_id=[^;]*' | cut -d= -f2 | sort -u > "$OUT/genes.tmp"
for f in rna_counts_Brain.txt rna_counts_Gill.txt rna_counts_Liver.txt rna_counts_Muscle.txt gene_orthologs.tsv; do
  awk -F'\t' 'NR == FNR { keep[$1]; next } FNR == 1 || ($1 in keep)' "$OUT/genes.tmp" "$RAW/$f" > "$OUT/$f"
done
# Ss4R table: whole salmon-trout clades of the fixture genes, so their duplicates on other chromosomes stay in.
awk -F'\t' 'NR == FNR { keep[$1]; next } $4 in keep { print $1 }' "$OUT/genes.tmp" "$RAW/SalmonTroutOrthologs.tsv" | sort -u > "$OUT/ogs.tmp"
awk -F'\t' 'NR == FNR { keep[$1]; next } FNR == 1 || ($1 in keep)' "$OUT/ogs.tmp" "$RAW/SalmonTroutOrthologs.tsv" > "$OUT/SalmonTroutOrthologs.tsv"
# Bgee 16.0 RNA-seq values: three multi-tissue studies cut to the fixture genes on chromosomes 21 and 25 (vgll3 and its
# duplicate); the other study files keep their header only.
mkdir -p "$OUT/bgee16"
gzip -dc "$OUT/Salmo_salar.Ssal_v3.1.116.chr.gff3.gz" | awk -F'\t' '$1 == "21" || $1 == "25"' | grep -o 'gene_id=[^;]*' | cut -d= -f2 | sort -u > "$OUT/genes2125.tmp"
for f in "$RAW"/bgee16/*.tsv.gz; do
  case "$f" in
    *SRP011583*|*SRP279079*|*ERP131682*) gzip -dc "$f" | awk -F'\t' 'NR == FNR { keep[$1]; next } FNR == 1 || ($4 in keep)' "$OUT/genes2125.tmp" - ;;
    *) gzip -dc "$f" | head -1 ;;
  esac | gzip -9n > "$OUT/bgee16/$(basename "$f")"
done
rm "$OUT/genes2125.tmp"
rm "$OUT/genes.tmp" "$OUT/ogs.tmp"
# Ss4R blocks touching the fixture chromosomes.
awk -F'\t' 'NR == 1 || $2 ~ /^(1|9|21|25|26)$/ || $5 ~ /^(1|9|21|25|26)$/' "$RAW/AtlanticSalmon_synteny.tsv" > "$OUT/AtlanticSalmon_synteny.tsv"
awk -F'\t' '$1 == "1" || $1 == "9" || $1 == "21" || $1 == "25" || $1 == "26"' "$RAW/alias_filtered.txt" > "$OUT/alias_filtered.txt"
.venv/bin/python prep/make_fixture_genome.py
wc -l "$OUT"/*
