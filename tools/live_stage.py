"""Zero-dependency live-reload HTTP + SSE visual stage server for real-time browser preview."""
from __future__ import annotations

import argparse
import functools
import http.server
import os
import socketserver
import sys
import time
from pathlib import Path

RELOAD_SNIPPET = (
    b"<script>(() => {"
    b"const s = new EventSource('/__live_events');"
    b"s.onmessage = (e) => { if (e.data === 'reload') location.reload(); };"
    b"})();</script>"
)


def _snapshot_mtime(root: Path) -> float:
    latest = 0.0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d != "__pycache__" and d != ".venv"]
        for fn in filenames:
            if fn.endswith((".html", ".js", ".css", ".json", ".glb", ".png", ".svg")):
                try:
                    mt = (Path(dirpath) / fn).stat().st_mtime
                    if mt > latest:
                        latest = mt
                except OSError:
                    pass
    return latest


class _LiveHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path.split("?")[0] == "/__live_events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            root = Path(self.directory)
            last = _snapshot_mtime(root)
            try:
                while True:
                    time.sleep(0.25)
                    cur = _snapshot_mtime(root)
                    if cur > last + 1e-4:
                        last = cur
                        self.wfile.write(b"data: reload\n\n")
                        self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                return

        if self.path in ("/", "/index.html") or self.path.split("?")[0].endswith(".html"):
            rel = "index.html" if self.path == "/" else self.path.split("?")[0].lstrip("/")
            target = Path(self.directory) / rel
            if target.is_file():
                body = target.read_bytes()
                if b"/__live_events" not in body:
                    idx = body.lower().rfind(b"</body>")
                    body = (body[:idx] + RELOAD_SNIPPET + body[idx:]) if idx != -1 else (body + RELOAD_SNIPPET)
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return
        super().do_GET()

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return


class _ThreadingHTTP(socketserver.ThreadingMixIn, http.server.HTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def main() -> int:
    ap = argparse.ArgumentParser(description="Live-reload visual preview HTTP server")
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    root = args.root.resolve()
    handler = functools.partial(_LiveHandler, directory=str(root))
    srv = _ThreadingHTTP(("127.0.0.1", args.port), handler)
    print(f"[live_stage] serving {root} at http://127.0.0.1:{args.port} (auto-reload on edit)", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
