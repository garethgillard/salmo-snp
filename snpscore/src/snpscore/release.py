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


def verify(folder):
    """check(), then every file of SHA256SUMS re-hashed (a corrupted or edited file is named): [problem, ...]."""
    import hashlib
    folder = Path(folder)
    problems = check(folder)
    sums = folder / "SHA256SUMS"
    if not sums.exists():
        return problems + ["no SHA256SUMS: the files can't be checked (built by an older snpdata?)"]
    for line in sums.read_text().splitlines():
        if not line.strip():
            continue
        want, name = line.split(None, 1)
        name = name.strip().lstrip("*")
        path = folder / name
        if not path.is_file():
            problems.append(f"{name} is missing")
            continue
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""):
                h.update(block)
        if h.hexdigest() != want:
            problems.append(f"{name} differs from SHA256SUMS: damaged or edited; download or rebuild the release")
    return problems


TABLES = ("alias", "rsid", "synteny", "bgee", "flank_keys", "catalog")  # manifest entries besides layers


def diff(old, new):
    """What changed from release `old` to release `new` (folders), as lines for a changelog: version and assembly,
    layers added, removed or changed (rows, columns, sha256), and the other tables (rows, sha256)."""
    a, b = (json.loads((Path(x) / "manifest.json").read_text()) for x in (old, new))
    out = [f"release {a.get('version')} -> {b.get('version')}"]
    if a.get("assembly") != b.get("assembly"):
        out.append(f"assembly {a.get('assembly')} -> {b.get('assembly')}")
    la, lb = ({x["name"]: x for x in m.get("layers", [])} for m in (a, b))
    out += [f"layer added: {n} ({lb[n].get('rows', '?'):,} rows)" for n in lb if n not in la]
    out += [f"layer removed: {n}" for n in la if n not in lb]
    for n in (n for n in lb if n in la):
        x, y, what = la[n], lb[n], []
        if x.get("rows") != y.get("rows"):
            what.append(f"rows {x.get('rows'):,} -> {y.get('rows'):,}" if isinstance(x.get("rows"), int) and
                        isinstance(y.get("rows"), int) else "rows changed")
        cols = set(y.get("columns") or []) - set(x.get("columns") or []), set(x.get("columns") or []) - set(y.get("columns") or [])
        what += [f"columns added: {', '.join(sorted(cols[0]))}"] if cols[0] else []
        what += [f"columns removed: {', '.join(sorted(cols[1]))}"] if cols[1] else []
        if not what and x.get("sha256") != y.get("sha256"):
            what.append("same rows, other content")
        if what:
            out.append(f"layer {n}: " + "; ".join(what))
    for t in TABLES + tuple(sorted(set(b.get("liftover") or {}) | set(a.get("liftover") or {}), key=str)):
        x = (a.get("liftover") or {}).get(t) if t not in TABLES else a.get(t)
        y = (b.get("liftover") or {}).get(t) if t not in TABLES else b.get(t)
        name = t if t in TABLES else f"liftover {t}"
        if x is None and y is not None:
            out.append(f"{name}: added ({y.get('rows', y.get('blocks', '?'))} rows)")
        elif y is None and x is not None:
            out.append(f"{name}: removed")
        elif x and y and x.get("sha256") != y.get("sha256"):
            out.append(f"{name}: changed ({x.get('rows', x.get('blocks'))} -> {y.get('rows', y.get('blocks'))} rows)")
    return out + (["no other changes"] if len(out) == 1 else [])
