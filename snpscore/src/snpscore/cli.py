import argparse
import json
import sys
from pathlib import Path

from .annotate import annotate, rsid
from .benchmark import benchmark
from .build import build, fetch
from .formats import InputError


def main():
    p = argparse.ArgumentParser(prog="snpscore")
    sub = p.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("fetch", help="download the public inputs listed in layers.yaml (the 504-fish VCF is streamed: "
                                     "frequencies kept, genotypes never written)")
    f.add_argument("--layers", default="layers.yaml")
    f.add_argument("--data", default="data/raw")

    b = sub.add_parser("build", help="build a release from layers.yaml (and weights.yaml next to it)")
    b.add_argument("--layers", default="layers.yaml")
    b.add_argument("--data", default="data/raw")
    b.add_argument("--out", required=True, help="release folder, e.g. release/v0.1")

    a = sub.add_parser("annotate", help="annotate a SNP list (VCF, TSV/CSV with chrom,pos, PLINK .bim/.map, chip manifest)")
    a.add_argument("snps")
    a.add_argument("--release", required=True)
    a.add_argument("--trait", default="all", help="trait preset from the release's weights.yaml (default: all)")
    a.add_argument("-o", "--out", default="annotated.tsv",
                   help="TSV, .csv or .parquet; <stem>.validation.json and <stem>.rejects.tsv go next to it")
    a.add_argument("--threads", type=int, default=4)
    a.add_argument("--memory", default="4GB", help="DuckDB memory limit")
    a.add_argument("--max-snps", type=int, help="refuse files with more SNPs than this")

    m = sub.add_parser("benchmark", help="positives vs matched controls per layer, region class and tier")
    m.add_argument("--release", required=True)
    m.add_argument("--positives", default="benchmark/known_loci.tsv")
    m.add_argument("--background", default="data/raw/12_samples_genotype_filtered_on_504.vcf.gz",
                   help="SNPs to draw matched controls from")
    m.add_argument("--controls", type=int, default=10, help="controls per positive")
    m.add_argument("--trait", default="all")
    m.add_argument("-o", "--out", help="also write the table as TSV")

    r = sub.add_parser("rsid", help="where rs IDs are on Ssal_v3.1 and ICSASG_v2 (EVA release 9), as JSON lines")
    r.add_argument("rs", nargs="+")
    r.add_argument("--release", required=True)

    sub.add_parser("tracks", help="regenerate tracks.yaml from the AQUA-FAANG trackhubs on salmobase", add_help=False)
    sub.add_parser("gwas", help="GWAS summary statistics: harmonise, annotate, clump loci and fine-map (snpscore gwas -h)",
                   add_help=False)

    o = sub.add_parser("pool", help="annotate the public sites into <release>/pool (pool.parquet, background.json)")
    o.add_argument("--release", required=True)
    o.add_argument("--background", default="data/raw/12_samples_genotype_filtered_on_504.vcf.gz", help="public sites (VCF)")
    o.add_argument("--assay", action="store_true",
                   help="also run the sequence and assay checks (1.6M sites: about 80 s with --memory 8GB; 4GB is too little)")
    o.add_argument("--threads", type=int, default=4)
    o.add_argument("--memory", default="4GB", help="DuckDB memory limit")

    n = sub.add_parser("panel", help="design a genotyping panel (backbone + functional fill) from annotated SNPs; "
                                     "options left out come from the release's weights.yaml 'design' block")
    n.add_argument("annotated", help="snpscore annotate output (.parquet or TSV), or a pool.parquet")
    n.add_argument("--release", required=True)
    n.add_argument("--preset", default="all", help="trait preset whose tiers rank the SNPs (recomputed when the input "
                                                  "was annotated with another --trait)")
    n.add_argument("--n", type=int, dest="n_target", help="number of SNPs")
    n.add_argument("--min-spacing", type=int, dest="min_spacing_bp", help="bp between selected SNPs")
    n.add_argument("--min-maf", type=float)
    n.add_argument("--backbone", type=float, dest="backbone_fraction", help="share of the panel spread over the genome")
    n.add_argument("--max-per-gene", type=int)
    n.add_argument("--max-per-element", type=int, help="per AQUA-FAANG peak (chromatin_id)")
    n.add_argument("--require-assay-pass", action="store_true", default=None)
    n.add_argument("--exclude", dest="exclude_flags", help="comma-separated columns, e.g. blacklist,lore,strand_ambiguous")
    n.add_argument("--must-include", help="comma-separated ids")
    n.add_argument("-o", "--out", default="panel.parquet", help="selected SNPs; <stem>.summary.json goes next to it")

    e = sub.add_parser("export", help="write annotated SNPs or a panel as tsv, parquet, bed, illumina, axiom, kasp or a "
                                      "zip bundle (vendor layouts to confirm against the vendor's current template)")
    e.add_argument("annotated", help="snpscore annotate or panel output (.parquet or TSV)")
    e.add_argument("--release", required=True)
    e.add_argument("--format", required=True, choices=["tsv", "parquet", "bed", "illumina", "axiom", "kasp", "bundle"])
    e.add_argument("--preset", default="all", help="trait preset: the tier columns, provenance header and file name")
    e.add_argument("--include-failed", action="store_true", help="keep assay fail/not_checked SNPs, flagged")
    e.add_argument("--plain", action="store_true", help="no '#' provenance lines")
    e.add_argument("-o", "--out", help="default: snpscore_<release>_<preset>[_<vendor>].<ext>")

    c = sub.add_parser("compare", help="compare annotated SNPs with a chip: shared, novel functional, chip gaps")
    c.add_argument("annotated", help="snpscore annotate output (.parquet or TSV)")
    c.add_argument("--chip", required=True, help="the chip's SNPs (manifest, PLINK, VCF or a chrom/pos table)")
    c.add_argument("--release", required=True)
    c.add_argument("--preset", default="all", help="trait preset whose tiers say which SNPs are functional")
    c.add_argument("--pool", action="store_true", help="fill gaps from <release>/pool/pool.parquet when the list has none")

    args, rest = p.parse_known_args()
    if args.cmd == "tracks":
        from .tracks import main as tracks_main
        return tracks_main(rest)
    if args.cmd == "gwas":
        from .gwas import main as gwas_main
        return gwas_main(rest)
    args = p.parse_args()
    if args.cmd == "fetch":
        fetch(args.layers, args.data)
    elif args.cmd == "build":
        build(args.layers, args.data, args.out)
    elif args.cmd == "annotate":
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
    elif args.cmd in ("pool", "panel", "export", "compare"):
        try:
            tools(args)
        except InputError as e:
            sys.exit(f"snpscore: {e}")
    else:
        rows = benchmark(args.positives, args.background, args.release, args.out, args.controls, args.trait)
        print(f"{'feature':32} {'share_pos':>9} {'share_ctrl':>10} {'enrichment':>10}   ({rows[0][1]} positives, {rows[0][2]} controls)")
        for feature, _, _, sp, sc, e in rows:
            print(f"{feature:32} {sp:9.3f} {sc:10.3f} {'' if e is None else f'{e:10.2f}'}")


def tools(args):
    """The pool, panel, export and compare subcommands."""
    import tempfile
    import time

    from . import export, panel
    from .pool import build_pool
    from .score import load_weights

    release = Path(args.release)
    manifest = json.loads((release / "manifest.json").read_text())
    synthetic = [l["name"] for l in manifest["layers"] if l.get("synthetic")]  # never counted in recomputed tiers
    if args.cmd == "pool":
        t0 = time.time()
        out = build_pool(release, args.background, args.assay, args.threads, args.memory)
        print(f"{out / 'pool.parquet'}: {json.loads((out / 'background.json').read_text())['n_sites']} sites "
              f"in {time.time() - t0:.0f} s")
    elif args.cmd == "panel":
        split = lambda v: [x.strip() for x in v.split(",") if x.strip()] if v else None  # noqa: E731
        result = panel.design(args.annotated, args.preset, args.n_target, args.min_spacing_bp, args.min_maf,
                              args.backbone_fraction, args.max_per_gene, args.max_per_element, args.require_assay_pass,
                              split(args.exclude_flags), split(args.must_include), weights=load_weights(release),
                              chrom_sizes=manifest.get("chrom_sizes"), out=args.out, synthetic=synthetic)
        out = Path(args.out)
        summary = {"hash": result["hash"], "params": result["params"], **result["summary"]}
        out.with_name(out.stem + ".summary.json").write_text(json.dumps(summary, indent=2))
        s = result["summary"]
        print(f"{s['n_selected']} of {s['n_target']} SNPs ({', '.join(f'{n} {k}' for k, n in s['reasons'].items())}); "
              f"{s['n_candidates']} candidates; panel {result['hash']}" + (f"; short because of {s['binding']}" if s["binding"] else ""))
    elif args.cmd == "export":
        out = args.out or export.filename(args.format, manifest["version"], args.preset)
        if args.format == "bundle":
            export.bundle_zip(out, args.annotated, release, args.preset, include_failed=args.include_failed)
            print(out)
        else:
            stats = export.export(args.annotated, args.format, out, release, args.preset,
                                  include_failed=args.include_failed, plain=args.plain)
            print(f"{out}: {stats['rows']} SNPs" + "".join(f"; {n} left out ({w})" for w, n in stats["skipped"].items()))
    else:
        with tempfile.TemporaryDirectory() as tmp:
            chip = Path(tmp) / "chip.parquet"
            panel.read_chip(args.chip, release, chip)
            pool = release / "pool" / "pool.parquet"
            result = panel.compare(args.annotated, chip, args.preset, pool=pool if args.pool and pool.exists() else None,
                                   weights=load_weights(release), chrom_sizes=manifest.get("chrom_sizes"),
                                   synthetic=synthetic)
        print(json.dumps(result["summary"]))
        for g in result["gaps"]:
            f = g["filler"]
            print(f"gap {g['chrom']}:{g['start']}-{g['end']} ({g['size'] / 1e6:.2f} Mb): "
                  + (f"best SNP {f['chrom']}:{f['pos']} {f['id'] or ''} tier {f['tier']} ({f['source']})" if f else "no SNP"))
