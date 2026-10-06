"""Test-only threaded HTTP/1.1 server (keep-alive) for the files in one folder, with Range support and a request log.
Fault modes by path prefix: /no-range/<file> ignores Range and answers 200 with the whole file; /slow/<file> waits
`delay` seconds before answering.

    with RangeServer(folder) as server:
        url = server.url + "track.bw"      # or server.url + "slow/track.bw"
        ...
        server.requests                     # [(path, start, end)], end None for a whole-file GET
        server.connections                  # connections accepted (tests may reset it)
        server.open                         # connections open now
"""
from __future__ import annotations

import http.server
import re
import threading
import time
from pathlib import Path


class RangeServer:
    def __init__(self, root, delay=3.0):
        self.root, self.delay = Path(root), delay
        self.requests, self.connections, self.open = [], 0, 0
        server = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def setup(self):
                super().setup()
                server.connections += 1
                server.open += 1

            def finish(self):
                try:
                    super().finish()
                finally:
                    server.open -= 1

            def do_GET(self):
                mode, _, name = self.path.lstrip("/").rpartition("/")
                path = server.root / name
                m = re.fullmatch(r"bytes=(\d+)-(\d+)", self.headers.get("Range", ""))
                server.requests.append((self.path, int(m.group(1)) if m else None, int(m.group(2)) if m else None))
                if mode == "slow":
                    time.sleep(server.delay)
                if not path.is_file() or mode not in ("", "slow", "no-range"):
                    return self.answer(404, b"")
                data = path.read_bytes()
                if not m or mode == "no-range":
                    return self.answer(200, data)
                start, end = int(m.group(1)), min(int(m.group(2)), len(data) - 1)
                if start >= len(data):
                    return self.answer(416, b"", {"Content-Range": f"bytes */{len(data)}"})
                self.answer(206, data[start:end + 1], {"Content-Range": f"bytes {start}-{end}/{len(data)}"})

            def answer(self, status, body, headers=()):
                self.send_response(status)
                for k, v in dict(headers, **{"Content-Length": str(len(body)), "Accept-Ranges": "bytes"}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.httpd.handle_error = lambda request, address: None  # clients that give up (deadline tests) are expected
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
