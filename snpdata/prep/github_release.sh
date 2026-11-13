#!/usr/bin/env bash
# Temporary data hosting until salmobase: the published data folder (snpdata publish) as two files on a GitHub Release
# of this repository, so anyone can install locally (README "Run it on your own computer").
#   bash prep/github_release.sh release/2026-11-03        (run in snpdata/, after the build; needs gh)
#   bash prep/github_release.sh release/trout-2026-11-13  (another species: its genome comes from the manifest's path)
# salmo-snp-data-<version>.tar     site/releases/<version>/ (with SHA256SUMS) and site/releases/latest.json
# salmo-snp-genome-<assembly>.tar  site/raw/: the bgzipped genome, .fai and .gzi (checked against the manifest)
# Users: curl -LO both files from the release (README), untar both, salmo-snp download --from site.
# Not a vX.Y.Z tag, so the wheel workflow doesn't run. Delete the GitHub Release once the data is on salmobase.
set -euo pipefail
RELEASE=${1:?give the release folder, e.g. release/2026-11-03}
VERSION=$(basename "$RELEASE")
GENOME=$(python3 -c "import json; print(json.load(open('$RELEASE/manifest.json'))['genome']['path'])")  # where build read it
ASSEMBLY=$(python3 -c "import json; print(json.load(open('$RELEASE/manifest.json'))['assembly'])")
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
snpdata publish "$RELEASE" --to "$T/site" > /dev/null
mkdir -p "$T/site/raw"
for ext in "" .fai .gzi; do cp "$GENOME$ext" "$T/site/raw/"; done
python3 -c "from snpdata.build import write_sums; write_sums('$T/site/raw')"
tar -C "$T" -cf "$T/salmo-snp-data-$VERSION.tar" site/releases
tar -C "$T" -cf "$T/salmo-snp-genome-$ASSEMBLY.tar" site/raw
cat > "$T/notes.md" <<EOF
The data for a local install, until it is hosted on salmobase: release $VERSION (the snapshot \`salmo-snp download\`
needs) and the $ASSEMBLY genome. Each layer keeps its source's licence (docs/LICENSING.md).

\`\`\`bash
bash tools/get_data.sh [$VERSION]   # in a clone of the repository; or by hand:
curl -LO https://github.com/garethgillard/salmo-snp/releases/download/data-$VERSION/salmo-snp-data-$VERSION.tar
curl -LO https://github.com/garethgillard/salmo-snp/releases/download/data-$VERSION/salmo-snp-genome-$ASSEMBLY.tar
tar -xf salmo-snp-data-$VERSION.tar && tar -xf salmo-snp-genome-$ASSEMBLY.tar
salmo-snp download $VERSION --from site    # checks every file, copies them into the data folder; then: salmo-snp serve
\`\`\`
EOF
gh release view "data-$VERSION" --repo garethgillard/salmo-snp > /dev/null 2>&1 ||
  gh release create "data-$VERSION" --repo garethgillard/salmo-snp --prerelease \
    --title "Data release $VERSION (temporary hosting)" --notes-file "$T/notes.md"
for f in "$T/salmo-snp-data-$VERSION.tar" "$T/salmo-snp-genome-$ASSEMBLY.tar"; do  # big uploads can drop: retry
  for try in 1 2 3; do
    gh release upload "data-$VERSION" "$f" --repo garethgillard/salmo-snp --clobber && break
    [ "$try" = 3 ] && exit 1
    echo "upload of $(basename "$f") failed, retrying" >&2
  done
done
