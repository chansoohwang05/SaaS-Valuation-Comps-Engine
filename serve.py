#!/usr/bin/env python3
"""Serve site/ locally.

The page loads one JSON file per company on demand, and browsers refuse
cross-file fetches on `file://` URLs. On GitHub Pages it is served over HTTP and
this script is unnecessary; locally it is the difference between a working page
and a blank one.
"""

from __future__ import annotations

import http.server
import socketserver
import webbrowser
from functools import partial

from forty import config

PORT = 8000


class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self) -> None:
        # Rebuilds change the JSON in place; without this the browser keeps
        # showing yesterday's numbers and the build looks broken.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt: str, *args) -> None:
        if "404" in (fmt % args):
            super().log_message(fmt, *args)


def main() -> None:
    if not (config.SITE / "index.json").exists():
        print("No build output. Run `python run.py --demo` first.")
        return
    handler = partial(Handler, directory=str(config.SITE))
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", PORT), handler) as httpd:
        url = f"http://localhost:{PORT}/"
        print(f"Serving {config.SITE} at {url}   (ctrl-c to stop)")
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001 - headless machines have no browser
            pass
        httpd.serve_forever()


if __name__ == "__main__":
    main()
