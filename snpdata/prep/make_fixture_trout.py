"""Cut the rainbow trout test fixture out of data/rainbow_trout/raw into tests/fixture_trout: two small regions of
USDA_OmykA_1.1, chromosome 28 12.00-12.22 Mb (greb1l and rock1) and Y 5.95-6.05 Mb (sdY). Run in snpdata/ after
`snpdata fetch --layers rainbow_trout/layers.yaml --data data/rainbow_trout/raw`. Sites and frequencies only: the
fetched files hold no genotypes."""
import gzip
import shutil
from pathlib import Path

from make_fixture_genome import main as genome

RAW, OUT = Path("data/rainbow_trout/raw"), Path("tests/fixture_trout")
REGIONS = {"28": (12_000_000, 12_220_000), "Y": (5_950_000, 6_050_000)}
GENOME = "Oncorhynchus_mykiss.USDA_OmykA_1.1.dna_sm.toplevel.fa.gz"
GFF = "Oncorhynchus_mykiss.USDA_OmykA_1.1.116.chr.gff3.gz"


def hit(chrom, start, end):
    return chrom in REGIONS and int(start) < REGIONS[chrom][1] and int(end) > REGIONS[chrom][0]


def lines(name):
    with (gzip.open if name.endswith(".gz") else open)(RAW / name, "rt") as f:
        yield from f


def write(name, rows):
    (OUT / name).parent.mkdir(parents=True, exist_ok=True)
    with (gzip.open(OUT / name, "wt", compresslevel=9) if name.endswith(".gz") else open(OUT / name, "w")) as f:
        f.writelines(rows)


def main():
    alias = [x.split("\t") for x in lines("alias_filtered.txt")]
    refseq = {a[1]: a[0] for a in alias}
    write("alias_filtered.txt", ("\t".join(a) for a in alias if a[0] in REGIONS))
    for name in ("RainbowTrout_unified_peaks.bed", "RainbowTrout_blacklist.bed", "gerp_constrained_elements.oncorhynchus_mykiss.bed"):
        write(name, (x for x in lines(name) if hit(*x.split("\t")[:3])))
    write("Omyk_late_rediploidized_regions.tsv", (x for i, x in enumerate(lines("Omyk_late_rediploidized_regions.tsv"))
                                                  if i == 0 or x.split("\t")[0] in REGIONS))
    for name in (GFF, "Oncorhynchus_mykiss.USDA_OmykA_1.1.regulatory_features.v116.gff3.gz"):
        write(name, (x for x in lines(name) if not x.startswith("#") and hit(x.split("\t")[0], int(x.split("\t")[3]) - 1, x.split("\t")[4])))
    ncbi = "GCF_013265735.2_USDA_OmykA_1.1_genomic.gff.gz"
    write(ncbi, (x for x in lines(ncbi) if not x.startswith("#") and x.split("\t")[0] in refseq
                 and hit(refseq[x.split("\t")[0]], int(x.split("\t")[3]) - 1, x.split("\t")[4])))
    genes = {x.split("gene_id=")[1].split(";")[0] for x in lines("../../../" + str(OUT / GFF)) if "gene_id=" in x}
    write("gene_orthologs.tsv", (x for i, x in enumerate(lines("gene_orthologs.tsv")) if i == 0 or x.split("\t")[0] in genes))
    clades = {x.split("\t")[0] for x in lines("SalmonTroutOrthologs.tsv") if x.split("\t")[3] in genes}
    write("SalmonTroutOrthologs.tsv", (x for i, x in enumerate(lines("SalmonTroutOrthologs.tsv")) if i == 0 or x.split("\t")[0] in clades))
    write("RainbowTrout_synteny.tsv", (x for i, x in enumerate(lines("RainbowTrout_synteny.tsv"))
                                       if i == 0 or x.split("\t")[1] in REGIONS or x.split("\t")[4] in REGIONS))
    for name in sorted(p.name for p in RAW.glob("umd_trout_*.sites.vcf.gz")):  # sites and counts, as fetch keeps them
        write(name, (x for x in lines(name) if x.startswith("#") or hit(x.split("\t")[0], int(x.split("\t")[1]) - 1, x.split("\t")[1])))
    rs = "8022_GCA_013265735.3_current_ids.vcf.gz"  # every 20th rs ID in the regions, and their Omyk_1.0 lines
    kept, n = set(), 0
    def new():
        nonlocal n
        for x in lines(rs):
            f = x.split("\t")
            if x.startswith("#CHROM"):
                yield x
            elif not x.startswith("#") and hit(f[0], int(f[1]) - 1, f[1]):
                n += 1
                if n % 20 == 0:
                    kept.add(f[2])
                    yield "\t".join(f[:5] + [".", ".", ".\n"])
    write(rs, new())
    old = "8022_GCA_002163495.1_current_ids.vcf.gz"
    write(old, (x if x.startswith("#") else "\t".join(x.split("\t")[:5] + [".", ".", ".\n"]) for x in lines(old)
                if x.startswith("#CHROM") or (not x.startswith("#") and x.split("\t")[2] in kept)))
    shutil.copy("tests/fixture/JASPAR2024_CORE_vertebrates_non-redundant_pfms_meme.txt", OUT)  # the salmon fixture's cut
    genome(GENOME, [(c, a, b) for c, (a, b) in REGIONS.items()], str(RAW), str(OUT))


if __name__ == "__main__":
    main()
