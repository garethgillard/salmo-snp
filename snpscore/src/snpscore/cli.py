import argparse

from .annotate import annotate
from .build import build, fetch


def main():
    p = argparse.ArgumentParser(prog="snpscore")
    sub = p.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("fetch", help="download the public inputs listed in layers.yaml")
    f.add_argument("--layers", default="layers.yaml")
    f.add_argument("--data", default="data/raw")

    b = sub.add_parser("build", help="build a release from layers.yaml")
    b.add_argument("--layers", default="layers.yaml")
    b.add_argument("--data", default="data/raw")
    b.add_argument("--out", required=True, help="release folder, e.g. release/v0.1")

    a = sub.add_parser("annotate", help="annotate a SNP list (VCF, or TSV/CSV with chrom,pos)")
    a.add_argument("snps")
    a.add_argument("--release", required=True)
    a.add_argument("-o", "--out", default="annotated.tsv")

    args = p.parse_args()
    if args.cmd == "fetch":
        fetch(args.layers, args.data)
    elif args.cmd == "build":
        build(args.layers, args.data, args.out)
    else:
        annotate(args.snps, args.release, args.out)
