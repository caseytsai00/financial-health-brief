"""Minimal local HTTP fixture server for exercising generate_brief.py's
fetch path without hitting real Google Sheets.

Standard-library only, matching the rest of this skill's scripts.
"""

from __future__ import annotations

import http.server
import threading
import urllib.parse


class _NoReverseDnsHTTPServer(http.server.HTTPServer):
    """Skips the reverse-DNS lookup HTTPServer.server_bind() normally does
    via socket.getfqdn() -- on a machine with no reachable DNS that lookup
    can block for tens of seconds per server, even for 127.0.0.1."""

    def server_bind(self) -> None:
        import socketserver

        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = host
        self.server_port = port


class FixtureServer:
    """Serves canned CSV (or other) bodies on 127.0.0.1.

    Routes are keyed by the sheet's "/d/<id>" base path (what you'd pass as
    --transactions-url etc.) -- export_csv_url() turns that into
    "<base>/export?format=csv[&gid=...]", and this server strips the
    "/export" suffix and query string before matching, so the route key
    stays exactly the URL you handed to generate_brief.

    When a route's URL has no gid, generate_brief also fetches
    "<base>/htmlview" to discover one (see discover_default_gid()). This
    server answers any such request for a registered route with a fixed
    fake gid ("0") -- real content doesn't matter here, only that the
    request resolves against this same fixture host instead of real
    Google Sheets.

    Usage:
        with FixtureServer({"/t/d/TXN1": ("text/csv", b"a,b\\n1,2\\n")}) as server:
            url = server.url("/t/d/TXN1")
            ...
    """

    def __init__(self, routes: dict[str, tuple[str, bytes]]):
        self._routes = routes
        handler = _make_handler(routes)
        self._httpd = _NoReverseDnsHTTPServer(("127.0.0.1", 0), handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    @property
    def port(self) -> int:
        return self._httpd.server_port

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def __enter__(self) -> "FixtureServer":
        self._thread.start()
        return self

    def __exit__(self, *exc_info) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=5)


def _make_handler(routes: dict[str, tuple[str, bytes]]):
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 (stdlib method name)
            raw_path = urllib.parse.urlsplit(self.path).path
            if raw_path.endswith("/htmlview"):
                base_path = raw_path[: -len("/htmlview")]
                if base_path in routes:
                    self._respond("text/html", b'initialSheet: ("0" == gid)')
                else:
                    self.send_response(404)
                    self.end_headers()
                return

            path = raw_path
            if path.endswith("/export"):
                path = path[: -len("/export")]
            route = routes.get(path)
            if route is None:
                self.send_response(404)
                self.end_headers()
                return
            content_type, body = route
            self._respond(content_type, body)

        def _respond(self, content_type: str, body: bytes) -> None:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args) -> None:  # noqa: A002
            pass  # keep test output quiet

    return Handler
