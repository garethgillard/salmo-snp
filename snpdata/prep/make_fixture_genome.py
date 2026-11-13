"""Write tests/fixture's genome: real sequence in small windows around the known loci and N elsewhere, so positions
match Ssal_v3.1. Each chromosome ends at its window, so SNPs further along it are outside the genome.
Bgzipped with .fai and .gzi like the real file. Run in snpdata/ after `snpdata fetch`."""
import struct
import sys
import zlib
from pathlib import Path

NAME = "Salmo_salar.Ssal_v3.1.dna_sm.toplevel.fa.gz"
WINDOWS = [("9", 23_790_000, 23_890_000),    # six6 and its two GWAS lead SNPs
           ("25", 28_950_000, 29_050_000),   # vgll3
           ("26", 19_090_000, 19_190_000)]   # bco1l
LINE = 60


def bgzf_block(data):
    """One BGZF block: a gzip member whose extra field 'BC' holds the block size."""
    deflate = zlib.compressobj(6, zlib.DEFLATED, -15)
    body = deflate.compress(data) + deflate.flush()
    header = struct.pack("<BBBBIBBHBBHH", 31, 139, 8, 4, 0, 0, 255, 6, 66, 67, 2, len(body) + 25)
    return header + body + struct.pack("<II", zlib.crc32(data) & 0xFFFFFFFF, len(data))


def main(name=NAME, windows=WINDOWS, raw="data/raw", fixture="tests/fixture"):
    sys.path.insert(0, "src")
    from snpscore.fasta import Fasta

    genome = Fasta(f"{raw}/{name}")
    text, fai = b"", []
    for chrom, start, end in windows:
        seq = "N" * start + genome.fetch(chrom, start, end)
        header = f">{chrom}\n"
        fai.append(f"{chrom}\t{len(seq)}\t{len(text) + len(header)}\t{LINE}\t{LINE + 1}\n")
        text += (header + "\n".join(seq[i:i + LINE] for i in range(0, len(seq), LINE)) + "\n").encode()
    out, gzi, compressed = Path(fixture) / name, [], 0
    with open(out, "wb") as f:
        for i in range(0, len(text), 65280):
            if i:
                gzi.append((compressed, i))
            block = bgzf_block(text[i:i + 65280])
            f.write(block)
            compressed += len(block)
        f.write(bgzf_block(b""))  # BGZF end-of-file marker
    Path(f"{out}.gzi").write_bytes(struct.pack("<Q", len(gzi)) + b"".join(struct.pack("<QQ", c, u) for c, u in gzi))
    Path(f"{out}.fai").write_text("".join(fai))
    print(f"{out}: {out.stat().st_size} bytes")


if __name__ == "__main__":
    main()
