"""Local synthetic UI review. Never connects to a Pod or executes controls."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from adaptive.journey import build_journey, command_events, normalize_samples
from adaptive.outcomes import compare_commands

now = time.time()
samples = [
    {
        "timestamp": datetime.fromtimestamp(now - 900 + i * 10, UTC).isoformat(),
        "temperature": 28.0 if i < 40 else 26.0,
        "humidity": 50.0,
        "sound": 44.0 if i < 40 else 40.0,
        "lux": 0.5,
        "co2": 850.0,
        "pm2_5": 8.0,
        "voc_index": 105.0,
        "heart_rate": 64.0,
        "respiration_rate": 15.0,
        "bed_status": "on_bed",
    }
    for i in range(90)
]
events = [
    {
        "id": 1,
        "type": "aircon_command",
        "value": {"command": "set_temp"},
        "timestamp": datetime.fromtimestamp(now - 510, UTC).isoformat(),
    }
]
data = {
    "session_id": "synthetic-demo",
    "data_truncated": False,
    "journey": build_journey(samples, events),
    "outcomes": compare_commands(
        normalize_samples(samples), command_events(events), now=now
    ),
    "comfort_reference": {
        "message": "อ้างอิงช่วงที่คุณบอกว่าสบายจาก 3 ครั้งก่อน",
        "ranges": {"temperature": {"low": 22, "high": 24, "sessions": 3}},
    },
    "recommendation": {
        "message": "ยังไม่มีข้อเสนอให้ปรับอุปกรณ์",
        "item": {
            "id": "demo-only",
            "title": "ลองลดอุณหภูมิ",
            "reason": "อุณหภูมิช่วงล่าสุดสูงกว่าช่วงที่คุณเคยบอกว่าสบาย",
            "confirmation_label": "รับคำแนะนำและไปหน้าควบคุม",
        },
    },
}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self):
        if self.path.startswith("/api/"):
            body = json.dumps({"data": data}, ensure_ascii=False).encode()
            content_type = "application/json"
        elif self.path == "/":
            panel = (ROOT / "static/partials/app/adaptive-journey.html").read_text()
            script = (
                ROOT / "static/partials/app/scripts/08-adaptive-journey.js"
            ).read_text()
            body = (
                "<!doctype html><html lang='th'><meta charset='utf-8'>"
                "<meta name='viewport' content='width=device-width, initial-scale=1'>"
                "<link rel='stylesheet' href='/static/styles/adaptive-journey.css'>"
                "<style>body{margin:0;background:#071722;color:#dbeef2;font-family:system-ui,sans-serif}"
                "main{max-width:1200px;margin:auto;padding:24px}.card{padding:24px;border:1px solid #23424e;border-radius:20px}"
                "button{background:#123a48;color:#cafaff;border:1px solid #327184;border-radius:8px;padding:10px;font:inherit;cursor:pointer}"
                "@media(max-width:500px){main{padding:10px}.card{padding:16px}}</style>"
                "<body data-view='monitor'><main><p>ข้อมูลจำลองสำหรับตรวจหน้าจอ — ไม่เชื่อมต่ออุปกรณ์จริง</p>"
                + panel
                + "</main><script>const currentPrincipal={subject:'demo',account_key:'demo'};"
                "const current={session:{session_id:'synthetic-demo'}};"
                "function authenticatedHeaders(){return {}}function toast(s){alert(s)}"
                "async function post(){toast('หน้าตัวอย่างไม่บันทึกหรือสั่งอุปกรณ์');return null}"
                + script
                + "\nrefreshJourney();</script></html>"
            ).encode()
            content_type = "text/html; charset=utf-8"
        elif self.path == "/static/styles/adaptive-journey.css":
            body = (ROOT / "static/styles/adaptive-journey.css").read_bytes()
            content_type = "text/css"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Synthetic preview: http://127.0.0.1:{server.server_port}/", flush=True)
    server.serve_forever()
