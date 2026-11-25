"""A sequence model's prediction for one SNP, on demand (G, 2026-11-25: a button on the SNP card): the released
ChromBPNet models of salmo-chrombpnet, run where the portal runs, as the models' own scorer runs them.

Needs numpy and onnxruntime, which the base install does not have (INSTALL below); both are imported only when a
prediction is asked for. A model's files are fetched once from where models.yaml says they are published, each
checked against the release's SHA256SUMS. The SNP itself goes nowhere.

The rules are the model release's (its scorer/chrombpnet_predict.py, which follows variant-scorer): a window of the
model's input length centred on the SNP, once with each allele and each also on the other strand; counts =
exp(log counts), the two strands averaged, and the profile logits likewise (the other strand's reversed); effect =
log2(alt counts / ref counts); jsd = the Jensen-Shannon distance of the two predicted profiles; the more accessible
allele's quantile among the model's predictions over its own training peaks; the percentile of |effect| and of jsd
among the model's 100,000 random public SNPs. The fold model used is the one that held the SNP's chromosome out of
training. self_test() compares this module with the release's own test SNPs."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import threading
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from snpscore import bbi

MODELS = Path(__file__).with_name("models.yaml")
PACKAGES = ("numpy", "onnxruntime")
INSTALL = "pip install numpy onnxruntime"  # or the extra: pip install "salmo-snp[chrombpnet]"
BASES = "ACGT"
COMPLEMENT = str.maketrans(BASES, BASES[::-1])
_LOCK = threading.Lock()  # one download or prediction at a time in a process: each takes a core for a second or two
WAIT = 30  # seconds a prediction waits for the ones before it, then says the model is busy


class Unavailable(Exception):
    """This install cannot run the model now (packages or model files are missing): the message says which."""


class NotScored(Exception):
    """The model has no prediction for this variant: the message says why."""


def models(assembly):
    """The models published for an assembly, as models.yaml lists them ([] for an assembly without any)."""
    return list((yaml.safe_load(MODELS.read_text(encoding="utf-8")) or {}).get(assembly) or [])


def missing_packages():
    """The packages a prediction needs that this install lacks ([] when it can predict)."""
    return [p for p in PACKAGES if importlib.util.find_spec(p) is None]


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url, target):
    request = urllib.request.Request(url, headers={"User-Agent": "salmo-snp"})
    with urllib.request.urlopen(request, timeout=60) as r, open(target, "wb") as out:
        while chunk := r.read(1 << 20):
            out.write(chunk)


def fetch(model, folder, name):
    """The model's file `name` (as in its release: scorer/fold_2.onnx) under `folder`, fetched on first use from the
    model's `url` and checked against the release's SHA256SUMS. On the server that publishes the model
    (SNPSCORE_SALMOBASE: snpscore.bbi.local) it is the published file itself, where it is."""
    served = bbi.local(model["url"].rstrip("/") + "/" + name)
    if "://" not in served:
        return Path(served)
    folder = Path(folder)
    target = folder / name
    if target.exists():
        return target
    base = model["url"].rstrip("/") + "/"
    if not base.startswith("https://"):
        raise Unavailable(f"The model's address is not https: {base}")
    try:
        folder.mkdir(parents=True, exist_ok=True)
        sums = folder / "SHA256SUMS"
        if not sums.exists():
            download(base + "SHA256SUMS", sums.with_name("SHA256SUMS.part"))
            sums.with_name("SHA256SUMS.part").rename(sums)
        want = {line.split()[1].removeprefix("./"): line.split()[0] for line in sums.read_text().splitlines() if len(line.split()) == 2}
        if name not in want:
            raise Unavailable(f"{name} is not among the model's published files")
        target.parent.mkdir(parents=True, exist_ok=True)
        part = target.with_name(target.name + ".part")
        download(base + name, part)
        if sha256(part) != want[name]:
            part.unlink()
            raise Unavailable(f"{name} did not match the model's checksum after its download: try again")
        part.rename(target)
    except OSError as e:  # no network, no room, the address gone
        raise Unavailable(f"The model's files could not be fetched from {urlsplit(base).hostname}: {e}") from None
    return target


def one_hot(np, seqs):
    """(n, length, 4) float32, columns A, C, G, T; any other letter (N) is all zeros, as in variant-scorer."""
    table = np.zeros((256, 4), dtype=np.float32)
    for i, b in enumerate(BASES):
        table[ord(b), i] = table[ord(b.lower()), i] = 1
    return table[np.frombuffer("".join(seqs).encode("ascii"), dtype=np.uint8)].reshape(len(seqs), -1, 4)


def softmax(np, x):
    """variant-scorer's softmax of one row of logits: centred on the mean."""
    e = np.exp(x - x.mean())
    return e / e.sum()


def js_distance(np, p, q):
    """scipy.spatial.distance.jensenshannon(p, q, base=2) of two profiles."""
    p, q = p / p.sum(), q / q.sum()
    m = (p + q) / 2
    with np.errstate(divide="ignore", invalid="ignore"):
        left = np.where(p > 0, p * np.log(p / m), 0.0).sum()
        right = np.where(q > 0, q * np.log(q / m), 0.0).sum()
    return float(np.sqrt(max((left + right) / np.log(2) / 2, 0)))


def onnx_runner(path, output_length, threads=1):
    """A function from one-hot sequences (n, input length, 4) to (profile logits (n, output length), log counts (n,))
    of one fold model."""
    import onnxruntime as ort
    options = ort.SessionOptions()
    options.intra_op_num_threads, options.inter_op_num_threads = int(threads), 1
    session = ort.InferenceSession(str(path), options, providers=["CPUExecutionProvider"])
    name = session.get_inputs()[0].name
    widths = [o.shape[-1] for o in session.get_outputs()]
    profile, count = widths.index(output_length), widths.index(1)

    def run(x):
        out = session.run(None, {name: x})
        return out[profile], out[count][:, 0]
    return run


def oriented(base, ref, alt):
    """(ref, alt, on the other strand) as the genome has them: one of the two alleles must be the genome's base at the
    SNP, read on its strand or on the other one."""
    if base in (ref, alt):
        return ref, alt, False
    other = ref.translate(COMPLEMENT), alt.translate(COMPLEMENT)
    if base in other:
        return *other, True
    raise NotScored(f"Neither allele ({ref}, {alt}) is the genome's base here ({base or 'none'}): another assembly's position?")


def predict(model, folder, sequence, chrom, pos, ref, alt, threads=1, runners=None):
    """The model's prediction for one SNP: a dict of what was scored (chrom, pos, ref, alt as on the genome's strand,
    `other_strand` when the input's alleles were read on the other one), the fold model, ref_counts and alt_counts
    (predicted Tn5 cuts in the output window around the SNP), effect (log2 alt/ref), score (|effect|), percentile,
    jsd, jsd_percentile, active_allele_quantile, and ref_profile and alt_profile (predicted cuts per base over the
    output window, the SNP at its middle). `sequence(chrom, start, end)` gives the genome's bases (BED coordinates);
    `folder` holds the model's files (fetch); `runners` ({fold: run}) keeps fold models between calls, and tests give
    their own. Raises Unavailable (packages or files) or NotScored (this variant)."""
    ref, alt = str(ref or "").upper(), str(alt or "").upper()
    if len(ref) != 1 or len(alt) != 1 or ref not in BASES or alt not in BASES or ref == alt:
        raise NotScored("Only single-base changes (A, C, G, T) are predicted")
    absent = missing_packages() if runners is None else [p for p in missing_packages() if p == "numpy"]
    if absent:
        raise Unavailable(f"This install lacks {' and '.join(absent)}, which the model needs: {INSTALL}")
    import numpy as np
    if not _LOCK.acquire(timeout=WAIT):
        raise Unavailable("The model is busy with other predictions: try again in a moment")
    try:
        m = json.loads(fetch(model, folder, "scorer/manifest.json").read_text())
        length, out_length = int(m["input_length"]), int(m["output_length"])
        flank, sizes = length // 2, m["chrom_sizes"]
        chrom = str(chrom)
        if chrom not in sizes:
            raise NotScored(f"The model covers chromosomes {next(iter(sizes))}-{list(sizes)[-1]} of {m.get('assembly', 'its assembly')}")
        if not (pos - flank > 0 and pos + flank <= int(sizes[chrom])):
            raise NotScored(f"Too close to the chromosome's end: the model's {length:,}-bp window does not fit")
        window = sequence(chrom, pos - 1 - flank, pos - 1 + flank).upper()
        if len(window) != length:
            raise Unavailable("The genome sequence around the SNP could not be read")
        ref, alt, other = oriented(window[flank], ref, alt)
        fold = next(int(k) for k, f in m["folds"].items() if chrom in f["test"])
        run = (runners or {}).get(fold)
        if run is None:
            run = onnx_runner(fetch(model, folder, m["folds"][str(fold)]["onnx"]), out_length, threads)
            if runners is not None:
                runners[fold] = run
        both = one_hot(np, [window[:flank] + ref + window[flank + 1:], window[:flank] + alt + window[flank + 1:]])
        logits, logcounts = run(np.ascontiguousarray(np.concatenate([both, both[:, ::-1, ::-1]])))
        counts = np.exp(logcounts.astype(np.float32)).astype(np.float64)
        ref_counts, alt_counts = (counts[0] + counts[2]) / 2, (counts[1] + counts[3]) / 2
        ref_logits = ((logits[0] + logits[2, ::-1]) / 2).astype(np.float64)
        alt_logits = ((logits[1] + logits[3, ::-1]) / 2).astype(np.float64)
        effect = float(np.log2(alt_counts / ref_counts))
        ref_profile, alt_profile = softmax(np, ref_logits), softmax(np, alt_logits)
        jsd = js_distance(np, alt_profile, ref_profile)
        with np.load(fetch(model, folder, m["peak_counts"]["file"])) as z:
            peaks = np.sort(z[f"fold_{fold}"].astype(np.float64))
        with np.load(fetch(model, folder, m["background"]["file"])) as z:
            background = {k: np.sort(z[k].astype(np.float64)) for k in ("abs_logfc", "jsd")}
    finally:
        _LOCK.release()
    quantile = lambda c: max(float(np.searchsorted(peaks, c, side="left")) / len(peaks), 1 / len(peaks))
    share = lambda key, v: float(np.searchsorted(background[key], v, side="left")) / len(background[key])
    return {"model": m["model"], "version": m["version"], "fold": fold, "chrom": chrom, "pos": int(pos), "ref": ref, "alt": alt,
            "other_strand": other, "ref_counts": float(ref_counts), "alt_counts": float(alt_counts), "effect": effect,
            "score": abs(effect), "percentile": share("abs_logfc", abs(effect)), "jsd": jsd, "jsd_percentile": share("jsd", jsd),
            "active_allele_quantile": max(quantile(ref_counts), quantile(alt_counts)),
            "ref_profile": [round(float(v), 5) for v in ref_profile * ref_counts],
            "alt_profile": [round(float(v), 5) for v in alt_profile * alt_counts]}


def self_test(model, folder, sequence, limit=None, threads=1):
    """This module against the model release's own test SNPs (scorer/test_variants.tsv: variant-scorer's scores of 200
    SNPs): (SNPs compared, the largest difference of effect, jsd and active-allele quantile). The release's own scorer
    accepts 0.001."""
    lines = fetch(model, folder, "scorer/test_variants.tsv").read_text().splitlines()
    head, runners, worst, n = lines[0].split("\t"), {}, [0.0, 0.0, 0.0], 0
    for line in lines[1:][:limit]:
        r = dict(zip(head, line.split("\t")))
        got = predict(model, folder, sequence, r["chrom"], int(r["pos"]), r["ref"], r["alt"], threads, runners)
        pairs = (("effect", "logfc"), ("jsd", "jsd"), ("active_allele_quantile", "active_allele_quantile"))
        worst = [max(w, abs(got[a] - float(r[b]))) for w, (a, b) in zip(worst, pairs)]
        n += 1
    return n, *worst
