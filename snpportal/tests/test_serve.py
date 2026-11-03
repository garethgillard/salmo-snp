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
