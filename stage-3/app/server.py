"""HTTP layer: routing, request bodies and JSON responses."""
import json
import mimetypes
import os
import re
import sys
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

from .errors import ApiError, malformed_request
from .service import Service

SERVICE = Service()
STATIC_ROOT = Path(__file__).resolve().parent.parent / "static"
SCREENS = {"/": "index.html", "/signup": "signup.html", "/login": "login.html", "/lookup": "lookup.html"}
_REFERENCE_PATH = re.compile(r"/reservations/([^/]+)(/cancel)?")
_RESTAURANT_PATH = re.compile(r"/restaurants/([^/]+)")


class StaticFile:
    """A response body served as-is from the static directory."""

    def __init__(self, content, content_type):
        self.content = content
        self.content_type = content_type


def static_file(path):
    """The static file behind a URL path, or None."""
    name = SCREENS.get(path, path.lstrip("/"))
    candidate = (STATIC_ROOT / name).resolve()
    if STATIC_ROOT not in candidate.parents or not candidate.is_file():
        return None
    content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
    if content_type.startswith("text/") or content_type in ("application/javascript", "application/json"):
        content_type += "; charset=utf-8"
    return StaticFile(candidate.read_bytes(), content_type)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    timeout = 120

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_PATCH(self):
        self._handle("PATCH")

    def do_PUT(self):
        self._handle("PUT")

    def do_DELETE(self):
        self._handle("DELETE")

    def _handle(self, method):
        try:
            raw = self._read_body()
            status, payload = self._route(method, urlsplit(self.path), raw)
        except ApiError as error:
            status, payload = error.status, {"error": {"code": error.code, "message": error.message}}
        except Exception as error:  # a bug must still answer with the error body
            print(f"internal error: {error!r}", file=sys.stderr, flush=True)
            status, payload = 500, {"error": {"code": "internal_error", "message": "internal error"}}
        self._send(status, payload)

    def _read_body(self):
        if "chunked" in self.headers.get("Transfer-Encoding", "").lower():
            chunks = []
            while True:
                size = int(self.rfile.readline().split(b";")[0].strip() or b"0", 16)
                if size == 0:
                    while self.rfile.readline().strip():
                        pass
                    return b"".join(chunks)
                chunks.append(self.rfile.read(size))
                self.rfile.readline()
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise malformed_request("invalid Content-Length")
        return self.rfile.read(length) if length > 0 else b""

    def _send(self, status, payload):
        content_type = "application/json; charset=utf-8"
        if isinstance(payload, StaticFile):
            body, content_type = payload.content, payload.content_type
        else:
            body = b"" if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        if payload is not None:
            self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _route(self, method, url, raw):
        path = unquote(url.path)
        if len(path) > 1 and path.endswith("/"):
            path = path[:-1]
        auth = self.headers.get("Authorization")
        key = self.headers.get("Idempotency-Key")
        service = SERVICE
        routes = {
            ("GET", "/health"): lambda: (200, {"status": "ok"}),
            ("POST", "/_test/reset"): lambda: service.reset(raw),
            ("GET", "/_test/export"): service.export_state,
            ("POST", "/_test/import"): lambda: service.import_state(raw),
            ("POST", "/auth/signup"): lambda: service.signup(raw),
            ("POST", "/auth/login"): lambda: service.login(raw),
            ("GET", "/restaurants"): service.list_restaurants,
            ("GET", "/availability"): lambda: service.availability(_first_values(url.query)),
            ("POST", "/reservations"): lambda: service.create_reservation(auth, key, raw),
            ("GET", "/reservations"): lambda: service.list_reservations(auth),
            ("POST", "/reservation-moves"): lambda: service.moves(auth, key, raw),
        }
        if (method, path) in routes:
            return routes[(method, path)]()
        match = _RESTAURANT_PATH.fullmatch(path)
        if match and method == "GET":
            return service.get_restaurant(match.group(1))
        match = _REFERENCE_PATH.fullmatch(path)
        if match:
            reference, cancel = match.group(1), match.group(2)
            if cancel and method == "POST":
                return service.cancel(auth, reference)
            if not cancel and method == "GET":
                return service.get_reservation(auth, reference)
            if not cancel and method == "PATCH":
                return service.amend(auth, reference, raw)
        page = static_file(path) if method == "GET" else None
        if page:
            return 200, page
        if match or path in {known for _, known in routes}:
            raise ApiError(405, "method_not_allowed", "method not allowed")
        raise ApiError(404, "not_found", "no such endpoint")

    def log_message(self, format, *args):
        pass


def _first_values(query):
    return {name: values[0] for name, values in parse_qs(query, keep_blank_values=True).items()}


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 256
    allow_reuse_address = True


def main():
    port = int(os.environ.get("PORT") or 8080)
    Server(("0.0.0.0", port), Handler).serve_forever()
