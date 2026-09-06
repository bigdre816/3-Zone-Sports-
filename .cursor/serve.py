#!/usr/bin/env python3
"""Static dev server for The-system Investment Tracker.

The app lives in a single extension-less file named `System`, so a naive static
server would serve it as a binary download. This server serves that file as
`text/html` at `/` and `/System`, and falls back to normal static serving for
any other path.
"""

import http.server
import os
import socketserver

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_FILE = os.path.join(ROOT, "System")
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8000"))


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def do_GET(self):
        if self.path.split("?")[0] in ("/", "/index.html", "/System"):
            self.serve_app()
            return
        super().do_GET()

    def serve_app(self):
        try:
            with open(APP_FILE, "rb") as f:
                body = f.read()
        except OSError:
            self.send_error(404, "System app file not found")
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    with socketserver.ThreadingTCPServer((HOST, PORT), Handler) as httpd:
        httpd.allow_reuse_address = True
        print(f"Investment Tracker dev server running at http://{HOST}:{PORT}/")
        httpd.serve_forever()


if __name__ == "__main__":
    main()
