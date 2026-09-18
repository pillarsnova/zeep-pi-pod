"""Local-only UI fixture preview; no Pod, authentication or personal data."""

import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "static/partials/app/scripts"


def page():
    sources = "\n".join(
        (SCRIPTS / name).read_text()
        for name in (
            "00-product-copy-alerts.js",
            "11-result-summary.js",
            "11-history-list.js",
            "12-history-report.js",
        )
    )
    fixtures = (Path(__file__).with_name("result-fixtures.json")).read_text()
    styles = "".join(
        f'<link rel="stylesheet" href="/static/{name}">'
        for name in (
            "theme-modern.css",
            "styles/sessions.css",
            "styles/result-summary.css",
        )
    )
    return f"""<!doctype html><html lang="th"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">{styles}
    <title>ZEEP · Result preview</title><style>
    *{{box-sizing:border-box}}body{{margin:0;padding:24px;background:#060f19;color:#d7eaf1;font-family:system-ui,sans-serif}}
    main{{max-width:1100px;margin:auto}}header{{display:flex;flex-wrap:wrap;align-items:center;gap:14px;margin-bottom:24px}}
    button{{padding:12px 18px;background:#153341;color:#def5fa;border:1px solid #365360;border-radius:12px;font:inherit}}
    button:focus-visible{{outline:2px solid #8bf1d7}}h1{{font-size:22px}}#sessionDetail{{width:100%}}
    @media(max-width:600px){{body{{padding:12px}}}}
    </style></head><body data-view="sessions"><main>
    <header><h1>ZEEP · ผลการพัก</h1><button onclick="show('nap')">Nap &amp; Refresh</button><button onclick="show('sleep')">Overnight</button><small>ข้อมูลจำลองเพื่อทดสอบหน้าจอ · ไม่ใช่ผลผู้ใช้จริง</small></header>
    <div id="sessionDetail"></div></main><script>
    let currentPrincipal={{role:'user'}};
    {sources}
    const fixtures={fixtures};
    function show(mode){{document.getElementById('sessionDetail').innerHTML=renderRestoreSummary(fixtures[mode],mode==='nap'?'recovery':'sleep',true);}}
    show('nap');</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            body, content_type = page().encode(), "text/html; charset=utf-8"
        elif self.path.startswith("/static/"):
            path = (ROOT / self.path.lstrip("/").split("?")[0]).resolve()
            if not path.is_relative_to(ROOT / "static") or not path.is_file():
                self.send_error(404)
                return
            body, content_type = path.read_bytes(), "text/css; charset=utf-8"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    server = ThreadingHTTPServer(
        ("127.0.0.1", int(sys.argv[1]) if len(sys.argv) > 1 else 0), Handler
    )
    print(f"http://127.0.0.1:{server.server_port}/", flush=True)
    server.serve_forever()
