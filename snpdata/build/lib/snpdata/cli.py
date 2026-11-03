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
    b.add_argument("--out", required=True, help="release folder, e.g. release/v0.1")

    u = sub.add_parser("publish", help="lay out a release (and with --raw the input files) as the folder that goes online")
    u.add_argument("release", help="release folder, e.g. release/2026-11-03")
    u.add_argument("--to", required=True, help="the site folder to upload (releases/<version>/, releases/latest.json, raw/)")
    u.add_argument("--raw", action="store_true", help="also mirror data/raw: the inputs layers.yaml names")
    u.add_argument("--layers", default="layers.yaml")
    u.add_argument("--data", default="data/raw")

    sub.add_parser("tracks", help="regenerate tracks.yaml from the AQUA-FAANG trackhubs on salmobase", add_help=False)

    args, rest = p.parse_known_args()
    if args.cmd == "tracks":
        from .trackhub import main as tracks_main
        return tracks_main(rest)
    args = p.parse_args()
    if args.cmd == "fetch":
        fetch(args.layers, args.data, args.mirror)
    elif args.cmd == "publish":
        print(publish(args.release, args.to, *((args.layers, args.data) if args.raw else ())))
    else:
        build(args.layers, args.data, args.out)


if __name__ == "__main__":
    main()
