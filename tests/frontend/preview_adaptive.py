"""Local synthetic UI review. Never connects to a Pod or executes controls."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from preview_theme import preview_page, static_asset

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

# Direct script execution needs the project root for the production builders.
from adaptive.journey import (  # noqa: E402
    build_journey,
    command_events,
    normalize_samples,
)
from adaptive.outcomes import compare_commands  # noqa: E402

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
        "message": "จากการพักที่คุณระบุว่าสบาย 3 ครั้ง",
        "ranges": {
            "temperature": {"low": 22, "high": 24, "sessions": 3},
            "humidity": {"low": 45, "high": 55, "sessions": 3},
        },
    },
    "recommendation": {
        "message": "ยังไม่มีคำแนะนำเพิ่มเติม",
        "item": {
            "id": "demo-only",
            "title": "แนะนำให้ลดอุณหภูมิ",
            "reason": "อุณหภูมิ 5 นาทีล่าสุด 26 °C สูงกว่าช่วงที่คุณพักสบาย 22–24 °C",
            "confirmation_label": "ไปหน้าควบคุม",
        },
    },
}


def page(view: str = "monitor", mode: str = "nap") -> str:
    panel = (ROOT / "static/partials/app/adaptive-journey.html").read_text()
    if view == "monitor":
        overview = (ROOT / "static/partials/app/smart-senses.html").read_text()
        panel = overview + panel
    scripts = ROOT / "static/partials/app/scripts"
    result = ""
    script = (
        "const currentPrincipal={subject:'demo',account_key:'demo',role:"
        + ("'user'" if view == "sessions" else "'admin'")
        + "};const current={session:{session_id:'synthetic-demo'}};"
        "function authenticatedHeaders(){return {}}"
        "function toast(s){document.getElementById('previewNotice').textContent=s}"
        "async function post(){toast('ตัวอย่างการใช้งาน · ไม่บันทึกข้อมูลหรือสั่งอุปกรณ์');return null}"
    )
    if view == "sessions":
        result = '<div id="sessionDetail"></div>'
        script += "\n".join(
            (scripts / name).read_text()
            for name in (
                "00-product-copy-alerts.js",
                "11-result-summary.js",
                "11-history-list.js",
                "12-history-report.js",
            )
        )
        fixtures = Path(__file__).with_name("result-fixtures.json").read_text()
        presentation = "sleep" if mode == "sleep" else "recovery"
        script += f"\nconst fixtures={fixtures};"
        script += (
            "document.getElementById('sessionDetail').innerHTML="
            f"renderRestoreSummary(fixtures['{mode}'],'{presentation}',true);"
        )
    script += (scripts / "08-adaptive-journey.js").read_text()
    script += (
        "\nselectJourneySession('synthetic-demo');"
        if view == "sessions"
        else "\nrefreshJourney();"
    )
    return preview_page(result + panel, script, view=view)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self):
        url = urlsplit(self.path)
        if url.path == "/api/v1/adaptive/sessions/synthetic-demo":
            payload = data
            if parse_qs(urlsplit(self.headers.get("Referer", "")).query).get(
                "view"
            ) == ["sessions"]:
                payload = {
                    **data,
                    "recommendation": {
                        "item": None,
                        "message": "คำแนะนำปรับอุปกรณ์แสดงขณะใช้งานตู้เท่านั้น",
                    },
                }
            body = json.dumps({"data": payload}, ensure_ascii=False).encode()
            content_type = "application/json"
        elif url.path == "/":
            query = parse_qs(url.query)
            view = "sessions" if query.get("view") == ["sessions"] else "monitor"
            mode = "sleep" if query.get("mode") == ["sleep"] else "nap"
            body = page(view, mode).encode()
            content_type = "text/html; charset=utf-8"
        elif url.path.startswith("/static/") and (asset := static_asset(url.path)):
            body, content_type = asset
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
