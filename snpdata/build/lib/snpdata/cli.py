import argparse

from .build import build, fetch


def main():
    p = argparse.ArgumentParser(prog="snpdata", description="Collect the public sources and build a release")
    sub = p.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("fetch", help="download the public inputs listed in layers.yaml (the 504-fish VCF is streamed: "
                                     "frequencies kept, genotypes never written)")
    f.add_argument("--layers", default="layers.yaml")
    f.add_argument("--data", default="data/raw")

    b = sub.add_parser("build", help="build a release from layers.yaml")
    b.add_argument("--layers", default="layers.yaml")
    b.add_argument("--data", default="data/raw")
    b.add_argument("--out", required=True, help="release folder, e.g. release/v0.1")

    sub.add_parser("tracks", help="regenerate tracks.yaml from the AQUA-FAANG trackhubs on salmobase", add_help=False)

    args, rest = p.parse_known_args()
    if args.cmd == "tracks":
        from .trackhub import main as tracks_main
        return tracks_main(rest)
    args = p.parse_args()
    if args.cmd == "fetch":
        fetch(args.layers, args.data)
    else:
        build(args.layers, args.data, args.out)


if __name__ == "__main__":
    main()
