"""Predictions on demand (lib/predict.py): the registry, the files' checksums and the model's rules. The rules are
tested with a stand-in for the fold model (they need numpy, which the base install lacks: skipped there), and against
the releases' own test SNPs when SNPPORTAL_MODEL_TEST names a folder for the models' files (a folder per model in it)
and SNPPORTAL_MODEL_GENOME the genome (not in CI: the files are 25 MB a fold)."""
import hashlib
import json
import math
import os
import random

import pytest

from snpportal.lib import predict

TOY = {"name": "toy", "label": "Toy", "version": "v0", "url": "https://example.org/toy/", "what": "a toy signal",
       "direction": ["more", "less"]}
LENGTH, OUT, SIZE = 114, 20, 2000  # the toy model's input and output windows, and its chromosomes' length
RNG = random.Random(7)
GENOME = "".join(RNG.choice("ACGT") for _ in range(SIZE))


def sequence(chrom, start, end):
    return GENOME[start:end]


def test_registry():
    found = {m["name"]: m for m in predict.models("Ssal_v3.1")}
    assert list(found) == ["chrombpnet_gill", "chrombpnet_liver"]  # the liver model too (G, 2026-11-26)
    for m in found.values():
        assert m["url"].startswith("https://salmobase.org/") and m["direction"] == ["more accessible", "less accessible"]
    assert predict.models("USDA_OmykA_1.1") == []  # no model for rainbow trout yet: its cards have no button


def test_fetch_checks_the_files(tmp_path, monkeypatch):
    """A model's file is fetched once and kept only when it matches the release's SHA256SUMS."""
    files = {"scorer/a.bin": b"good", "scorer/b.bin": b"changed on the way"}
    sums = f"{hashlib.sha256(b'good').hexdigest()}  ./scorer/a.bin\n{hashlib.sha256(b'as published').hexdigest()}  ./scorer/b.bin\n"
    asked = []

    def download(url, target):
        asked.append(url)
        name = url.removeprefix(TOY["url"])
        target.write_bytes(sums.encode() if name == "SHA256SUMS" else files[name])
    monkeypatch.setattr(predict, "download", download)
    assert predict.fetch(TOY, tmp_path, "scorer/a.bin").read_bytes() == b"good"
    assert predict.fetch(TOY, tmp_path, "scorer/a.bin").exists() and asked.count(TOY["url"] + "scorer/a.bin") == 1
    with pytest.raises(predict.Unavailable, match="did not match the model's checksum"):
        predict.fetch(TOY, tmp_path, "scorer/b.bin")
    assert not (tmp_path / "scorer" / "b.bin").exists() and not list(tmp_path.rglob("*.part"))
    with pytest.raises(predict.Unavailable, match="not among the model's published files"):
        predict.fetch(TOY, tmp_path, "scorer/c.bin")

    def offline(url, target):
        raise OSError("no route to host")
    monkeypatch.setattr(predict, "download", offline)
    with pytest.raises(predict.Unavailable, match="could not be fetched from example.org"):
        predict.fetch(TOY, tmp_path / "elsewhere", "scorer/a.bin")


def test_without_the_packages(monkeypatch):
    monkeypatch.setattr(predict, "missing_packages", lambda: ["onnxruntime"])
    with pytest.raises(predict.Unavailable, match="lacks onnxruntime.*pip install numpy onnxruntime"):
        predict.predict(TOY, "nowhere", sequence, "1", 500, "A", "C")
    with pytest.raises(predict.NotScored, match="single-base"):  # said first: no packages are needed to know it
        predict.predict(TOY, "nowhere", sequence, "1", 500, "A", "AC")


def toy_model(tmp_path):
    """A folder with the toy model's manifest and reference files, and its stand-in fold model: the counts follow the
    number of A and T in the window (the same on both strands), the profile the A's of the output window."""
    np = pytest.importorskip("numpy")
    folder = tmp_path / "toy"
    (folder / "scorer").mkdir(parents=True)
    manifest = {"model": "Toy", "version": "v0", "assembly": "toy", "input_length": LENGTH, "output_length": OUT,
                "chrom_sizes": {"1": SIZE, "2": SIZE}, "folds": {"0": {"test": ["2"], "onnx": "scorer/fold_0.onnx"},
                                                               "1": {"test": ["1"], "onnx": "scorer/fold_1.onnx"}},
                "peak_counts": {"file": "scorer/peak_counts.npz"}, "background": {"file": "scorer/background.npz"}}
    (folder / "scorer" / "manifest.json").write_text(json.dumps(manifest))
    np.savez(folder / "scorer" / "peak_counts.npz", fold_0=np.arange(1.0, 101.0), fold_1=np.arange(1.0, 101.0))
    np.savez(folder / "scorer" / "background.npz", abs_logfc=np.linspace(0, 0.1, 1000), jsd=np.linspace(0, 0.5, 1000))

    def run(x):
        a = (LENGTH - OUT) // 2
        return x[:, a:a + OUT, 0] * 2.0, np.log(1 + x[:, :, 0].sum(axis=1) + x[:, :, 3].sum(axis=1))
    return folder, run


def test_the_rules(tmp_path):
    """Both alleles in the window, both strands, the fold that held the chromosome out; the effect is the input alt
    allele's, whichever of the two the genome has and whichever strand they were written on."""
    folder, run = toy_model(tmp_path)
    pos = next(p for p in range(900, 1100) if GENOME[p - 1] == "A")  # an A in the genome: A>C loses one A or T
    window = GENOME[pos - 1 - LENGTH // 2:pos - 1 + LENGTH // 2]
    at = window.count("A") + window.count("T")
    used = {}

    def fold_1(x):  # chromosome 1 is fold 1's test chromosome: the model that never saw it
        used["shape"] = x.shape
        return run(x)
    got = predict.predict(TOY, folder, sequence, "1", pos, "A", "C", runners={1: fold_1})
    assert used["shape"] == (4, LENGTH, 4)  # ref and alt, each on both strands
    assert (got["fold"], got["ref"], got["alt"], got["other_strand"]) == (1, "A", "C", False)
    assert math.isclose(got["ref_counts"], 1 + at, rel_tol=1e-5) and math.isclose(got["alt_counts"], at, rel_tol=1e-5)
    assert math.isclose(got["effect"], math.log2(at / (1 + at)), rel_tol=1e-4) and got["score"] == abs(got["effect"])
    assert 0 <= got["percentile"] <= 1 and 0 <= got["jsd_percentile"] <= 1 and 0 < got["active_allele_quantile"] <= 1
    assert len(got["ref_profile"]) == len(got["alt_profile"]) == OUT
    assert math.isclose(sum(got["ref_profile"]), got["ref_counts"], rel_tol=1e-3)  # the profile shares out the counts
    swapped = predict.predict(TOY, folder, sequence, "1", pos, "C", "A", runners={1: run})  # the genome's base as alt
    assert math.isclose(swapped["effect"], -got["effect"], rel_tol=1e-9) and (swapped["ref"], swapped["alt"]) == ("C", "A")
    other = predict.predict(TOY, folder, sequence, "1", pos, "T", "G", runners={1: run})  # written on the other strand
    assert other["other_strand"] and (other["ref"], other["alt"]) == ("A", "C") and math.isclose(other["effect"], got["effect"], rel_tol=1e-9)
    for args, why in ((("1", pos, "G", "C"), "Neither allele"), (("1", 20, "A", "C"), "Too close to the chromosome's end"),
                      (("9", pos, "A", "C"), "covers chromosomes 1-2 of toy"), (("1", pos, "A", "A"), "single-base")):
        with pytest.raises(predict.NotScored, match=why):
            predict.predict(TOY, folder, sequence, *args, runners={1: run})


@pytest.mark.skipif(not (os.environ.get("SNPPORTAL_MODEL_TEST") and os.environ.get("SNPPORTAL_MODEL_GENOME")),
                    reason="set SNPPORTAL_MODEL_TEST (a folder for the models' files) and SNPPORTAL_MODEL_GENOME (Ssal_v3.1 fa.gz)")
@pytest.mark.parametrize("name", ["chrombpnet_gill", "chrombpnet_liver"])
def test_the_models_themselves(name):
    """Each ChromBPNet model on 10 of its release's own test SNPs: this module's scores are variant-scorer's."""
    from pathlib import Path
    from snpscore.fasta import Fasta
    genome = Fasta(os.environ["SNPPORTAL_MODEL_GENOME"])
    model = next(m for m in predict.models("Ssal_v3.1") if m["name"] == name)
    n, *worst = predict.self_test(model, Path(os.environ["SNPPORTAL_MODEL_TEST"]) / name, lambda c, s, e: genome.fetch(c, s, e), limit=10)
    assert n == 10 and max(worst) < 1e-3
