"""The local install's data path: snpdata publish lays out the fixture release and its raw files as they go online,
salmo-snp download fetches the release and the genome from that folder (a web server, or a disk) and checks every file,
and serve finds them. A damaged release is refused with a reason."""
import functools
import http.server
import json
import threading

import pytest

from snpdata import build, publish
from snpportal import serve
from snpscore.release import check

from conftest import DATA


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    """The published data folder: releases/<version>/, releases/latest.json and raw/ (with the genome)."""
    tmp = tmp_path_factory.mktemp("pub")
    release = build(DATA / "layers.yaml", DATA / "tests" / "fixture", tmp / "2026-01-01")
    publish(release, tmp / "site", DATA / "layers.yaml", DATA / "tests" / "fixture")
    return tmp / "site"


@pytest.fixture(scope="module")
def url(site):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(site))
    handler.log_message = lambda *a: None
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def test_publish_layout(site):
    assert json.loads((site / "releases" / "latest.json").read_text()) == {"version": "2026-01-01"}
    assert (site / "releases" / "2026-01-01" / "SHA256SUMS").exists() and (site / "raw" / "SHA256SUMS").exists()
    assert (site / "raw" / "Salmo_salar.Ssal_v3.1.dna_sm.toplevel.fa.gz.gzi").exists()


@pytest.mark.parametrize("where", ["url", "folder"])
def test_download(site, url, where, tmp_path, monkeypatch):
    monkeypatch.setattr(serve, "HOME", tmp_path)
    got = serve.download("latest", url if where == "url" else site)
    assert got == tmp_path / "releases" / "2026-01-01" and serve.pick_release() == got and not check(got)
    names = [line.split("  ", 1)[1] for line in (site / "releases" / "2026-01-01" / "SHA256SUMS").read_text().splitlines()]
    assert all((got / n).read_bytes() == (site / "releases" / "2026-01-01" / n).read_bytes() for n in names)
    assert serve.local_genome(got) == tmp_path / "genome" / "Salmo_salar.Ssal_v3.1.dna_sm.toplevel.fa.gz"


def test_an_update_fetches_only_what_changed(site, tmp_path, monkeypatch, capsys):
    """Most layers are the same file in the next release, byte for byte: download copies those from the release
    installed here and fetches the rest. A file here that no longer has its checksum is fetched like a new one."""
    import shutil

    from snpdata.build import write_sums
    monkeypatch.setattr(serve, "HOME", tmp_path / "home")
    first = serve.download("2026-01-01", site, genome=False)
    new = shutil.copytree(site / "releases" / "2026-01-01", tmp_path / "site" / "releases" / "2026-01-02")
    (new / "manifest.json").write_text((new / "manifest.json").read_text().replace('"version": "2026-01-01"', '"version": "2026-01-02"'))
    write_sums(new)
    (first / "gerp.parquet").write_bytes(b"damaged since it was installed")
    fetched, copy = [], serve.copy
    monkeypatch.setattr(serve, "copy", lambda source, name, target: (fetched.append((str(source), name)), copy(source, name, target))[1])
    capsys.readouterr()
    got = serve.download("2026-01-02", tmp_path / "site", genome=False)
    assert sorted(name for source, name in fetched if source.startswith(str(tmp_path / "site"))) == ["gerp.parquet", "manifest.json"]
    assert not check(got) and "files are unchanged since a release installed here" in capsys.readouterr().out


def test_damaged_files_are_refused(site, tmp_path, monkeypatch):
    monkeypatch.setattr(serve, "HOME", tmp_path)
    folder = serve.download("2026-01-01", site, genome=False)
    published = site / "releases" / "2026-01-01" / "manifest.json"
    original = published.read_text()
    try:
        published.write_text("{}")  # the published copy changes: the download refuses it
        (folder / "manifest.json").unlink()
        with pytest.raises(SystemExit, match="does not match its sha256"):
            serve.download("2026-01-01", site, genome=False)
    finally:
        published.write_text(original)


def test_check_names_the_problem(site, tmp_path):
    import shutil
    release = shutil.copytree(site / "releases" / "2026-01-01", tmp_path / "r")
    m = json.loads((release / "manifest.json").read_text())
    del m["layers"][0]["columns"]  # as a hand-edited manifest once lacked it
    (release / "manifest.json").write_text(json.dumps(m))
    assert check(release) == [f"layer {m['layers'][0]['name']}: manifest.json lacks columns"]


def test_own_rules_outlive_an_update(tmp_path, monkeypatch, capsys):
    """S7: `salmo-snp rules --copy` puts the tier rules in the data folder, which an update of the package leaves
    alone; every salmo-snp command then uses them (SNPSCORE_WEIGHTS), and a mistake in them is named by its key."""
    from snpscore import score
    monkeypatch.setattr(serve, "HOME", tmp_path)
    monkeypatch.setenv("SNPSCORE_WEIGHTS", "")  # recorded, so the value main() sets is undone after the test
    serve.main(["rules"])
    assert "shipped with snpscore" in capsys.readouterr().out
    serve.main(["rules", "--copy"])
    own = tmp_path / "weights.yaml"
    assert own.read_text() == score.WEIGHTS.read_text()
    monkeypatch.setenv("SNPSCORE_WEIGHTS", "")  # as a new start of salmo-snp
    serve.main(["info"])
    assert f"tier rules    {own} (your own;" in capsys.readouterr().out
    assert score.rules_file() == own
    own.write_text(own.read_text().replace("  utr: 1", "  utr: -1"))
    with pytest.raises(SystemExit, match="'utr' is -1"):
        serve.main(["rules"])
    with pytest.raises(SystemExit, match="is there already"):
        serve.main(["rules", "--copy"])


def test_the_newest_salmon_release_without_this_versions(tmp_path, monkeypatch):
    """Without the release this version names, `serve` takes the newest Atlantic salmon release by its build date:
    names alone sort the species together (rainbow_trout-... after atlantic_salmon-..., trout-... after 2026-...)."""
    for name, created, species in (("2026-11-25", "2026-11-25", None), ("trout-2026-11-25", "2026-11-25", "rainbow_trout"),
                                   ("atlantic_salmon-Ssal_v3.1-2026-11-26", "2026-11-26", None),
                                   ("rainbow_trout-USDA_OmykA_1.1-2026-11-27", "2026-11-27", "rainbow_trout")):
        (tmp_path / "releases" / name).mkdir(parents=True)
        (tmp_path / "releases" / name / "manifest.json").write_text(json.dumps(
            {"version": name, "created": created, **({"species": {"key": species}} if species else {})}))
    monkeypatch.setattr(serve, "HOME", tmp_path)
    monkeypatch.setattr(serve, "RELEASE", "atlantic_salmon-Ssal_v3.1-2099-01-01")
    assert serve.pick_release().name == "atlantic_salmon-Ssal_v3.1-2026-11-26"
