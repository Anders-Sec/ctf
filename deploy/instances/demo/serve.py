"""A five-line target for the spec 009 demo.

Serves the per-instance answer the launcher injected, so a player who reaches
their own instance can read the flag and submit it. Real challenges replace this
with something that has to be exploited to reveal the same env value.
"""

import http.server
import os

ANSWER = os.environ.get("INSTANCE_ANSWER", "flag{demo_unset}")


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        body = f"Welcome, adventurer. The flag is {ANSWER}\n".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: object) -> None:
        pass  # quiet; the platform logs at the ingress


if __name__ == "__main__":
    http.server.HTTPServer(("0.0.0.0", 8080), Handler).serve_forever()  # noqa: S104
