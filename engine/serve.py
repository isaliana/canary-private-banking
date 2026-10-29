"""
Serve the workbench locally, with translation at the keyboard.

    .venv/bin/python engine/serve.py            # http://127.0.0.1:8000/app/
    .venv/bin/python engine/serve.py --port 8765

Opening app/index.html from file:// still works for everything else. The one
thing a file:// page cannot do is call a model while the RM types, because
that needs an API key and a key has no business in a browser. This holds the
key on the RM's own machine and exposes a single endpoint the composer calls.

Only app/ and assets/ are served — the repository root holds .anthropic_key
when the RM puts one there, and the data/ directory is not the browser's
business either. The server listens on 127.0.0.1 only, and the translation
endpoint refuses any request a page on another site could make: it demands a
JSON body and a custom header (so a cross-site form post or a no-preflight
fetch is turned away by the browser) and checks the Host header against DNS
rebinding.

Standard library only. Translation itself needs Python 3.10+ and the anthropic
SDK, installed in the project's virtual environment (see the README); without
them the workbench is still served and the composer says why it cannot
translate.
"""
import argparse
import json
import os
import posixpath
import sys
import urllib.parse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import translate                             # noqa: E402

ROOT = os.path.dirname(HERE)
SERVED = ("/app/", "/assets/")
MAX_BODY = 64 * 1024


class Bundle:
    """findings.json, re-read whenever build.py rewrites it."""

    def __init__(self):
        self._mtime, self._data = None, None

    def get(self):
        mtime = os.path.getmtime(translate.BUNDLE) if os.path.exists(translate.BUNDLE) else None
        if mtime != self._mtime:
            self._data, self._mtime = translate.load_bundle(), mtime
        return self._data


BUNDLE = Bundle()


class Handler(SimpleHTTPRequestHandler):
    server_version = "Canary"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    # ── static ────────────────────────────────────────────────────────────
    def do_GET(self):
        raw = urllib.parse.unquote(self.path.split("?", 1)[0])
        if raw in ("/", "/app"):
            self.send_response(302)
            self.send_header("Location", "/app/")
            self.end_headers()
            return
        if raw == "/api/health":
            ready, why = translate.availability()
            return self._json(200, {"translate": ready, "reason": why,
                                    "model": translate.MODEL})
        # normalised the same way the parent class will resolve it, so a
        # /app/../data/... cannot pass this check and then land somewhere else
        path = posixpath.normpath(raw)
        inside = path == "/app" or path.startswith(SERVED)
        hidden = any(part.startswith(".") for part in path.split("/"))
        if not inside or hidden:
            return self.send_error(404)
        return super().do_GET()

    def do_HEAD(self):
        # the parent's HEAD would skip the checks above
        return self.send_error(405)

    def end_headers(self):
        # the bundle changes on every build; never serve a stale one
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    # ── the one endpoint ──────────────────────────────────────────────────
    def do_POST(self):
        if self.path != "/api/translate":
            return self._json(404, {"error": "not found"})
        host = (self.headers.get("Host") or "").split(":")[0]
        if host not in ("127.0.0.1", "localhost"):
            return self._json(403, {"error": "wrong host"})
        if (self.headers.get("Content-Type") or "").split(";")[0].strip() != "application/json" \
                or self.headers.get("X-Canary") != "1":
            return self._json(403, {"error": "not from the workbench"})
        length = int(self.headers.get("Content-Length") or 0)
        if not 0 < length <= MAX_BODY:
            return self._json(413, {"error": "the note is too large to send"})
        try:
            req = json.loads(self.rfile.read(length).decode("utf-8"))
            profile, _ = translate.profile_for(BUNDLE.get(), str(req["finding_id"]))
            ready, why = translate.availability()
            if not ready:
                raise translate.TranslateError("translation is off: " + why, 503)
            out = translate.translate(str(req["text"]), str(req["from"]), str(req["to"]),
                                      profile)
        except translate.TranslateError as e:
            return self._json(e.status, {"error": str(e)})
        except (KeyError, ValueError, TypeError):
            return self._json(400, {"error": "the request was malformed"})
        except Exception as e:                                # noqa: BLE001
            # an API or network failure: say so plainly, keep the key out of it
            self.log_error("translate failed: %s", type(e).__name__)
            return self._json(502, {"error": "the translation service did not answer "
                                             "(%s) — try again" % type(e).__name__})
        return self._json(200, out)

    def _json(self, status, body):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        sys.stderr.write("  %s\n" % (fmt % args))


def main():
    ap = argparse.ArgumentParser(description="Serve the workbench on this machine.")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()

    ready, why = translate.availability()
    httpd = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print("  Canary on http://127.0.0.1:%d/app/" % args.port, flush=True)
    print("  translation: %s" % ("on (%s)" % translate.MODEL if ready else "off — " + why),
          flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    main()
