"""Move a published SNP from ICSASG_v2 to Ssal_v3.1 by matching its flanking sequence. Used for catalog/known_loci.tsv.
Usage: python prep/lift_icsasg_v2.py <v2 RefSeq/GenBank accession> <v2 pos> <v3.1 chrom> <window start> <window end>
e.g.   python prep/lift_icsasg_v2.py NC_027324.1 28656101 25 28500000 29500000   (vgll3 Met54Thr -> 25:28996360)
Prints every position in the v3.1 window where 60 bp either side of the SNP match exactly, on either strand.
Checked against EVA's own remapping of rs863785818 (26:19138923)."""
import re
import sys
import urllib.request

FLANK = 60


def ncbi(acc, start, end):
    url = (f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=nuccore&id={acc}"
           f"&seq_start={start}&seq_stop={end}&rettype=fasta&retmode=text")
    return "".join(urllib.request.urlopen(url).read().decode().splitlines()[1:]).upper()


def ensembl(chrom, start, end):
    url = f"https://rest.ensembl.org/sequence/region/salmo_salar/{chrom}:{start}..{end}:1?content-type=text/plain"
    return urllib.request.urlopen(url).read().decode().upper()


def revcomp(s):
    return s[::-1].translate(str.maketrans("ACGTN", "TGCAN"))


acc, pos, chrom, wstart, wend = sys.argv[1], int(sys.argv[2]), sys.argv[3], int(sys.argv[4]), int(sys.argv[5])
v2 = ncbi(acc, pos - FLANK, pos + FLANK)
left, base, right = v2[:FLANK], v2[FLANK], v2[FLANK + 1:]
window = ensembl(chrom, wstart, wend)
hits = [(wstart + m.start() + FLANK, "+", window[m.start() + FLANK])
        for m in re.finditer(f"(?={left}.{right})", window)]
hits += [(wstart + m.start() + FLANK, "-", revcomp(window[m.start() + FLANK]))
         for m in re.finditer(f"(?={revcomp(right)}.{revcomp(left)})", window)]
print(f"{acc}:{pos} (v2 base {base}) -> Ssal_v3.1 {chrom}: {hits or 'no match'}")
