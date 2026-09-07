#!/usr/bin/env python3
"""Static dev server for the Moten control-plane prototype.

`index.html` is the Moten app. `System` is the original Investment Tracker
file, kept so it is not shown as a 374-line deletion. `/` and `/index.html`
serve Moten; `/System` serves the original tracker.
"""

import http.server
import os
import socketserver

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOTEN_FILE = os.path.join(ROOT, "index.html")
SYSTEM_FILE = os.path.join(ROOT, "System")
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8000"))


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def app_file_for_path(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            return MOTEN_FILE
        if path == "/System":
            return SYSTEM_FILE
        return None

    def do_HEAD(self):
        app_file = self.app_file_for_path()
        if app_file:
            self.serve_app(app_file, body=False)
            return
        super().do_HEAD()

    def do_GET(self):
        app_file = self.app_file_for_path()
        if app_file:
            self.serve_app(app_file)
            return
        super().do_GET()

    def serve_app(self, app_file, body=True):
        try:
            with open(app_file, "rb") as f:
                payload = f.read()
        except OSError:
            self.send_error(404, f"{os.path.basename(app_file)} not found")
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if body:
            self.wfile.write(payload)


def main():
    with socketserver.ThreadingTCPServer((HOST, PORT), Handler) as httpd:
        httpd.allow_reuse_address = True
        print(f"Moten control-plane server running at http://{HOST}:{PORT}/")
        httpd.serve_forever()


if __name__ == "__main__":
    main()
