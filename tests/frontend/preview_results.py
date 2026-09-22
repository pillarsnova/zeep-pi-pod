"""Local result preview using the integrated, synthetic production UI shell."""

import sys
from http.server import ThreadingHTTPServer

from preview_adaptive import Handler as AdaptivePreviewHandler


class Handler(AdaptivePreviewHandler):
    def do_GET(self):
        if self.path == "/":
            self.send_response(302)
            self.send_header("Location", "/?view=sessions&mode=nap")
            self.end_headers()
            return
        super().do_GET()


if __name__ == "__main__":
    server = ThreadingHTTPServer(
        ("127.0.0.1", int(sys.argv[1]) if len(sys.argv) > 1 else 0), Handler
    )
    print(f"http://127.0.0.1:{server.server_port}/", flush=True)
    server.serve_forever()
