"""Is a folder a usable release? check() lists what is wrong with it (nothing: fine). salmo-snp download and serve,
snpscore annotate and snpdata publish call it, so a damaged or hand-edited release fails with a reason up front
instead of inside a scoring job."""
from __future__ import annotations

import json
from pathlib import Path

LAYER_KEYS = ("name", "file", "columns", "sha256")  # what annotate reads of each layer (snpdata README "Release format")


def check(folder):
    """[problem, ...] for the release in `folder`."""
    folder = Path(folder)
    try:
        manifest = json.loads((folder / "manifest.json").read_text())
    except FileNotFoundError:
        return [f"{folder} has no manifest.json: is it a release folder?"]
    except ValueError:
        return [f"{folder / 'manifest.json'} is not valid JSON"]
    problems = [f"manifest.json has no '{key}'" for key in ("version", "assembly", "layers") if key not in manifest]
    for layer in manifest.get("layers", []):
        missing = [key for key in LAYER_KEYS if key not in layer]
        if missing:
            problems.append(f"layer {layer.get('name', '?')}: manifest.json lacks {', '.join(missing)}")
        elif not (folder / layer["file"]).is_file():
            problems.append(f"layer {layer['name']}: {layer['file']} is missing")
    return problems
