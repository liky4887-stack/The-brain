"""Serving API (stdlib http.server): submit and read plan jobs.

POST /jobs      {"seed": 7, "n_skus": 20, ...} -> {"id": N}
GET  /jobs/N    -> {"id": N, "status": queued|running|done|failed, "result": ...}
GET  /health    -> {"ok": true}

Same contract any future UI or customer integration consumes; the
cockpit pattern (Stage 2) already set the zero-dependency precedent.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer


def make_handler(queue):
    class Handler(BaseHTTPRequestHandler):
        def _json(self, code: int, payload: dict) -> None:
            body = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if self.path == "/health":
                self._json(200, {"ok": True})
                return
            if self.path.startswith("/jobs/"):
                try:
                    job_id = int(self.path.rsplit("/", 1)[1])
                except ValueError:
                    self._json(400, {"error": "bad job id"})
                    return
                job = queue.get(job_id)
                if job is None:
                    self._json(404, {"error": "not found"})
                else:
                    self._json(200, job)
                return
            self._json(404, {"error": "unknown path"})

        def do_POST(self) -> None:
            if self.path != "/jobs":
                self._json(404, {"error": "unknown path"})
                return
            try:
                n = int(self.headers.get("Content-Length", 0))
                spec = json.loads(self.rfile.read(n) or b"{}")
                if not isinstance(spec, dict):
                    raise ValueError
            except ValueError:
                self._json(400, {"error": "body must be a JSON object"})
                return
            from worker import validate_spec
            bad = validate_spec(spec)
            if bad:
                self._json(400, {"error": "invalid spec",
                                 "problems": bad})
                return
            from worker import unknown_keys
            warn = unknown_keys(spec)
            reply = {"id": queue.submit(spec)}
            if warn:
                reply["warnings"] = [f"unknown spec key(s) {warn} will be "
                                     "ignored (SPEC_STRICT_KEYS=1 rejects)"]
            self._json(201, reply)

        def log_message(self, *args) -> None:  # quiet in tests
            pass

    return Handler


def serve_http(queue, host: str = "127.0.0.1", port: int = 8080) -> HTTPServer:
    return HTTPServer((host, port), make_handler(queue))
