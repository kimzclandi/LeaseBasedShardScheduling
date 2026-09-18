"""Loopback-only lab API. No external service, database or paid API needed."""

import argparse
import json
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from .core import Conflict, Missing, Store, canonical


def serve(db, port=0):
    store = Store(db)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.reply(200, {"service": "ai-data-shard-lab", "scope": "loopback lab"})

        def reply(self, status, value):
            body = canonical(value).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass  # Client may have lost an acknowledgement; commits are replayable.

        def do_POST(self):
            routes = {
                "/submit": store.submit,
                "/claim": store.claim,
                "/renew": store.renew,
                "/commit": store.commit,
                "/status": store.status,
                "/publish": store.publish,
            }
            if self.path not in routes:
                return self.reply(404, {"error": "unknown endpoint"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 16 * 1024 * 1024:
                    return self.reply(413, {"error": "body must be 1..16 MiB"})
                value = json.loads(
                    self.rfile.read(length),
                    parse_constant=lambda x: (_ for _ in ()).throw(ValueError("nonfinite JSON")),
                )
                if not isinstance(value, dict):
                    raise ValueError("body must be an object")
                result = routes[self.path](**value)
                self.reply(200, result)
            except Missing as exc:
                self.reply(404, {"error": str(exc)})
            except Conflict as exc:
                self.reply(409, {"error": str(exc)})
            except (ValueError, TypeError, KeyError) as exc:
                self.reply(400, {"error": str(exc)})
            except sqlite3.OperationalError:
                self.reply(503, {"error": "database temporarily unavailable"})

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(canonical({"url": f"http://127.0.0.1:{server.server_port}"}), flush=True)
    server.serve_forever(poll_interval=0.05)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--db", required=True)
    p.add_argument("--port", type=int, default=0)
    args = p.parse_args()
    serve(args.db, args.port)
