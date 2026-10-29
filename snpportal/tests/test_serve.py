"""salmo-snp download: a published release (here the fixture release on a local web server) is fetched file by file
and checked against its SHA256SUMS; a file that doesn't match is refused, and files already there are kept."""
import functools
import http.server
import threading

import pytest

from snpdata import build
from snpportal import serve

from conftest import DATA


@pytest.fixture(scope="module")
def published(tmp_path_factory):
    """The fixture release under http://127.0.0.1:<port>/2026-01-01/."""
    root = tmp_path_factory.mktemp("web")
    build(DATA / "layers.yaml", DATA / "tests" / "fixture", root / "2026-01-01")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    handler.log_message = lambda *a: None
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield root / "2026-01-01", f"http://127.0.0.1:{server.server_port}/2026-01-01"
    server.shutdown()


def test_download(published, tmp_path, monkeypatch):
    folder, url = published
    monkeypatch.setattr(serve, "HOME", tmp_path)
    got = serve.download(url)
    assert got == tmp_path / "releases" / "2026-01-01" and serve.newest_release() == got
    names = [line.split("  ", 1)[1] for line in (folder / "SHA256SUMS").read_text().splitlines()]
    assert all((got / n).read_bytes() == (folder / n).read_bytes() for n in names)
    (folder / "manifest.json").write_text("{}")  # the server's copy changes: the download refuses it
    (got / "manifest.json").unlink()
    with pytest.raises(SystemExit, match="does not match its sha256"):
        serve.download(url)
    assert not (got / "manifest.json").exists()
