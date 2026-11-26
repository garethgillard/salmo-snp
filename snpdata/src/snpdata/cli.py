import argparse

from .build import build, fetch, publish


def main():
    p = argparse.ArgumentParser(prog="snpdata", description="Collect the public sources and build a release")
    sub = p.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("fetch", help="download the public inputs listed in layers.yaml (the 504-fish VCF is streamed: "
                                     "frequencies kept, genotypes never written)")
    f.add_argument("--layers", default="layers.yaml")
    f.add_argument("--data", default="data/raw")
    f.add_argument("--mirror", help="fetch the published input files instead (a URL or folder holding raw/, from publish --raw)")

    b = sub.add_parser("build", help="build a release from layers.yaml")
    b.add_argument("--layers", default="layers.yaml")
    b.add_argument("--data", default="data/raw")
    b.add_argument("--out", required=True, help="release folder, named by `snpdata name`, e.g. release/atlantic_salmon-Ssal_v3.1-2026-11-26")
    b.add_argument("--reuse", help="an earlier release folder: layers with the same settings and inputs are copied from it")
    b.add_argument("--memory", help="DuckDB's memory limit, e.g. 32GB (default: 80%% of the machine's; set it in a SLURM job)")
    b.add_argument("--threads", type=int, help="DuckDB's threads (default: every core of the machine)")
    b.add_argument("--temp", help="a folder DuckDB may spill to when the memory limit is reached")

    u = sub.add_parser("publish", help="lay out a release (and with --raw the input files) as the folder that goes online")
    u.add_argument("release", help="release folder, e.g. release/2026-11-03")
    u.add_argument("--to", required=True, help="the site folder to upload (releases/<version>/, releases/latest.json, raw/)")
    u.add_argument("--raw", action="store_true", help="also mirror data/raw: the inputs layers.yaml names")
    u.add_argument("--layers", default="layers.yaml")
    u.add_argument("--data", default="data/raw")

    sub.add_parser("tracks", help="regenerate tracks.yaml from the AQUA-FAANG trackhubs on salmobase", add_help=False)

    n = sub.add_parser("name", help="a release's name: <species>-<assembly>-<date>, e.g. atlantic_salmon-Ssal_v3.1-2026-11-26")
    n.add_argument("--layers", default="layers.yaml")
    n.add_argument("--date", help="the build's day, YYYY-MM-DD (without it: the part before the date)")

    args, rest = p.parse_known_args()
    if args.cmd == "tracks":
        from .trackhub import main as tracks_main
        return tracks_main(rest)
    args = p.parse_args()
    if args.cmd == "name":
        from .build import release_name
        print(release_name(args.layers, args.date))
        return
    if args.cmd == "fetch":
        fetch(args.layers, args.data, args.mirror)
    elif args.cmd == "publish":
        print(publish(args.release, args.to, *((args.layers, args.data) if args.raw else ())))
    else:
        build(args.layers, args.data, args.out, args.reuse, args.memory, args.threads, args.temp)


if __name__ == "__main__":
    main()
