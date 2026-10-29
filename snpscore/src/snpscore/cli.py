import argparse
import json
import sys
from pathlib import Path

from .annotate import annotate, rsid
from .benchmark import benchmark_sets
from .formats import InputError


def main():
    p = argparse.ArgumentParser(prog="snpscore")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("annotate", help="annotate a SNP list (VCF, TSV/CSV with chrom,pos, PLINK .bim/.map, chip manifest)")
    a.add_argument("snps")
    a.add_argument("--release", required=True)
    a.add_argument("--trait", default="all", help="trait preset from the release's weights.yaml (default: all)")
    a.add_argument("-o", "--out", default="annotated.tsv",
                   help="TSV, .csv or .parquet; <stem>.validation.json and <stem>.rejects.tsv go next to it")
    a.add_argument("--threads", type=int, default=4)
    a.add_argument("--memory", default="4GB", help="DuckDB memory limit")
    a.add_argument("--max-snps", type=int, help="refuse files with more SNPs than this")

    m = sub.add_parser("benchmark", help="positives vs controls matched on gene distance and public MAF, per layer, "
                                         "evidence term, region class, consequence and tier, with 95%% intervals")
    m.add_argument("--release", required=True)
    m.add_argument("--positives", nargs="+",
                   help="default: the release's known-loci catalogue. SNP files, or molqtl[:ca|e][:Tissue] for the release's nf-RASQUAL lead SNPs (ca = caQTL, e = eQTL)")
    m.add_argument("--by-tissue", action="store_true", help="also one set per kind and kind:tissue under each molqtl set "
                                                            "(one-tissue sets use that tissue's preset when --trait is all)")
    m.add_argument("--background", help="SNPs to draw controls from: a VCF or an annotated parquet (default: "
                                        "<release>/pool/pool.parquet, from `snpscore pool`)")
    m.add_argument("--controls", type=int, default=10, help="controls per positive")
    m.add_argument("--trait", default="all")
    m.add_argument("-o", "--out", help="also write the table as TSV (one file for all sets)")

    r = sub.add_parser("rsid", help="where rs IDs are on Ssal_v3.1 and ICSASG_v2 (EVA release 9), as JSON lines")
    r.add_argument("rs", nargs="+")
    r.add_argument("--release", required=True)

    sub.add_parser("gwas", help="GWAS summary statistics: harmonise, annotate, clump loci and fine-map (snpscore gwas -h)",
                   add_help=False)

    o = sub.add_parser("pool", help="annotate the public sites into <release>/pool (pool.parquet, background.json)")
    o.add_argument("--release", required=True)
    o.add_argument("--background", default="data/raw/12_samples_genotype_filtered_on_504.vcf.gz", help="public sites (VCF)")
    o.add_argument("--assay", action="store_true",
                   help="also run the sequence and assay checks (1.6M sites: about 80 s with --memory 8GB; 4GB is too little)")
    o.add_argument("--threads", type=int, default=4)
    o.add_argument("--memory", default="4GB", help="DuckDB memory limit")

    args, rest = p.parse_known_args()
    if args.cmd == "gwas":
        from .gwas import main as gwas_main
        return gwas_main(rest)
    args = p.parse_args()
    if args.cmd == "annotate":
        try:
            annotate(args.snps, args.release, args.out, args.trait, threads=args.threads, memory_limit=args.memory,
                     max_snps=args.max_snps)
        except InputError as e:
            sys.exit(f"snpscore: {e}")
        out = Path(args.out)
        report = json.loads((out.parent / f"{out.stem}.validation.json").read_text())
        rejected = ", ".join(f"{n} {reason}" for reason, n in report["rejected"].items()) or "none"
        print(f"{report['snps_kept']} of {report['rows_read']} rows annotated ({report['format']}); rejected: {rejected}")
        if report.get("rsid"):
            r = report["rsid"]
            print(f"rs IDs: {r['placed']} placed, {r['moved_from_icsasg_v2']} moved from ICSASG_v2 "
                  f"({r['alleles_complemented']} with complemented alleles), {r['unknown']} unknown")
        for w in report.get("alias_warnings", []):
            print(f"warning ({w['rows']} rows): {w['message']}")
        if report.get("assembly", {}).get("message"):
            print("warning: " + report["assembly"]["message"])
        if report.get("assay"):
            print("assay QC (PROVISIONAL rules): " + ", ".join(f"{n} {status}" for status, n in report["assay"].items()))
    elif args.cmd == "rsid":
        for rs in args.rs:
            print(json.dumps(rsid(args.release, rs) or {"rs": rs, "found": False}))
    elif args.cmd == "pool":
        try:
            pool(args)
        except InputError as e:
            sys.exit(f"snpscore: {e}")
    else:
        if not args.background and not (Path(args.release) / "pool" / "pool.parquet").exists():
            sys.exit("snpscore: no controls: run `snpscore pool` for this release first, or give --background")
        positives = args.positives or [str(Path(args.release) / "catalog" / "known_loci.tsv")]
        try:
            sets = benchmark_sets(positives, args.background, args.release, args.out, args.controls, args.trait,
                                  by_tissue=args.by_tissue)
        except InputError as e:
            sys.exit(f"snpscore: {e}")
        print_benchmark(sets)


def print_benchmark(sets):
    """One set: its table with 95% intervals; several: enrichment per feature (rows) and set (columns)."""
    num = lambda v, f: "" if v is None else format(v, f)  # noqa: E731
    if len(sets) == 1:
        (name, (trait, rows)), = sets.items()
        n = f"{rows[0][1]} positives, {rows[0][2]} controls" if rows else "no positives"
        print(f"{name} ({n}; trait {trait})")
        print(f"{'feature':44} {'share_pos':>9} {'share_ctrl':>10} {'enrichment':>10}  95% interval")
        for r in rows:
            print(f"{r[0]:44} {num(r[3], '9.3f'):>9} {num(r[4], '10.3f'):>10} {num(r[5], '10.2f'):>10}  "
                  f"{num(r[12], '.2f')}-{num(r[13], '.2f')}")
        return
    names = [n.replace("molqtl:", "") for n in sets]
    print("enrichment over matched controls (n positives in brackets)")
    print(f"{'feature':44}" + "".join(f" {n[:10]:>10}" for n in names))
    print(f"{'':44}" + "".join(f" {'(' + str(rows[0][1] if rows else 0) + ')':>10}" for _, rows in sets.values()))
    table = {name: {r[0]: r[5] for r in rows} for name, (_, rows) in sets.items()}
    for feature in dict.fromkeys(f for t in table.values() for f in t):
        print(f"{feature:44}" + "".join(f" {num(t.get(feature), '10.2f'):>10}" for t in table.values()))


def pool(args):
    """Annotate the public sites into <release>/pool: a cache of the current weights' tiers, rebuilt after a change."""
    import time

    from .pool import build_pool

    t0 = time.time()
    out = build_pool(Path(args.release), args.background, args.assay, args.threads, args.memory)
    print(f"{out / 'pool.parquet'}: {json.loads((out / 'background.json').read_text())['n_sites']} sites "
          f"in {time.time() - t0:.0f} s")
