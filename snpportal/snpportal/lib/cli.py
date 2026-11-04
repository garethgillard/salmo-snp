"""The portal's breeder tools from the command line, on snpscore annotate output and a release:
python -m snpportal.lib.cli panel|export|compare ... (run in snpportal/)."""
import argparse
import json
import sys
from pathlib import Path

from snpscore.formats import InputError
from snpscore.score import load_weights

from . import export, panel


def main():
    p = argparse.ArgumentParser(prog="python -m snpportal.lib.cli")
    sub = p.add_subparsers(dest="cmd", required=True)

    n = sub.add_parser("panel", help="design a genotyping panel (backbone + functional fill) from annotated SNPs; "
                                     "options left out come from snpscore's weights.yaml 'design' block")
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
    n.add_argument("--purpose", help="a preset of weights.yaml design.presets (genomic_selection, parentage, trait): its "
                   "parameters are the defaults for the options not given (PROVISIONAL numbers)")
    n.add_argument("-o", "--out", default="panel.parquet", help="selected SNPs; <stem>.summary.json goes next to it")

    e = sub.add_parser("export", help="write annotated SNPs or a panel as tsv, parquet, bed, illumina, axiom, kasp, a "
                                      "zip bundle (vendor layouts to confirm against the vendor's current template) or "
                                      "genomic-prediction priors (zip: BayesRC, GFBLUP/MultiBLUP, LDAK)")
    e.add_argument("annotated", help="snpscore annotate or panel output (.parquet or TSV)")
    e.add_argument("--release", required=True)
    e.add_argument("--format", required=True, choices=["tsv", "parquet", "bed", "illumina", "axiom", "kasp", "bundle", "priors"])
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

    args = p.parse_args()
    try:
        tools(args)
    except InputError as e:
        sys.exit(f"snpportal: {e}")


def tools(args):
    """The panel, export and compare subcommands."""
    import tempfile

    release = Path(args.release)
    manifest = json.loads((release / "manifest.json").read_text())
    synthetic = [l["name"] for l in manifest["layers"] if l.get("synthetic")]  # never counted in recomputed tiers
    if args.cmd == "panel":
        split = lambda v: [x.strip() for x in v.split(",") if x.strip()] if v else None  # noqa: E731
        result = panel.design(args.annotated, args.preset, args.n_target, args.min_spacing_bp, args.min_maf,
                              args.backbone_fraction, args.max_per_gene, args.max_per_element, args.require_assay_pass,
                              split(args.exclude_flags), split(args.must_include), weights=load_weights(),
                              chrom_sizes=manifest.get("chrom_sizes"), out=args.out, synthetic=synthetic, purpose=args.purpose)
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
                                   weights=load_weights(), chrom_sizes=manifest.get("chrom_sizes"),
                                   synthetic=synthetic)
        print(json.dumps(result["summary"]))
        for g in result["gaps"]:
            f = g["filler"]
            print(f"gap {g['chrom']}:{g['start']}-{g['end']} ({g['size'] / 1e6:.2f} Mb): "
                  + (f"best SNP {f['chrom']}:{f['pos']} {f['id'] or ''} tier {f['tier']} ({f['source']})" if f else "no SNP"))


if __name__ == "__main__":
    main()
