"""Reuse production theme assets in local, synthetic interface reviews."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def preview_page(content: str, scripts: str, *, view: str = "monitor") -> str:
    """Render only fixture content; this shell never loads the live app runtime."""
    template = (ROOT / "static/index.template.html").read_text()
    base_css = (ROOT / "static/partials/app/styles.css").read_text()
    head = re.search(r"<head>(.*?)</head>", template, re.DOTALL).group(1)
    head = head.replace("/* ZEEP_PARTIAL:app/styles.css */", base_css)
    head = head.replace("ZEEP Control", "ZEEP · ตัวอย่างหน้าจอ")
    sprite = re.search(
        r'<svg class="ui-icon-sprite".*?</svg>', template, re.DOTALL
    ).group(0)
    heading = "ประวัติการใช้งาน" if view == "sessions" else "ติดตามระบบและการพัก"
    role = "user" if view == "sessions" else "admin"
    return f"""<!doctype html><html lang="th"><head>{head}
    <style>
    .preview-nav{{display:flex;flex-wrap:wrap;gap:8px;margin:16px 0}}
    .preview-nav a{{text-decoration:none}}
    .preview-note{{color:var(--muted);font-size:13px;margin:12px 0 20px}}
    .preview-content{{display:grid;gap:20px;min-width:0}}
    </style></head><body data-view="{view}" data-role="{role}">{sprite}<main class="wrap">
    <header class="page-heading"><div><div class="page-kicker">ZEEP</div>
    <h2>{heading}</h2><p>ตัวอย่างหน้าจอสำหรับตรวจรูปแบบและการใช้งาน</p></div>
    <span class="pill warn">ข้อมูลจำลอง</span></header>
    <nav class="preview-nav" aria-label="หน้าตัวอย่าง">
    <a class="btn" href="/?view=monitor">ติดตามระบบ</a>
    <a class="btn" href="/?view=sessions&amp;mode=nap">Nap &amp; Refresh</a>
    <a class="btn" href="/?view=sessions&amp;mode=sleep">Overnight Recovery</a>
    </nav><p class="preview-note">ใช้ธีมและส่วนแสดงผลเดียวกับระบบจริง · ไม่เชื่อมต่ออุปกรณ์หรือข้อมูลผู้ใช้</p>
    <div class="preview-content">{content}</div>
    <p class="preview-note" id="previewNotice" role="status"></p>
    </main><script>{scripts}</script></body></html>"""


def static_asset(url_path: str) -> tuple[bytes, str] | None:
    """Serve stylesheet assets only; never expose source, databases or secrets."""
    path = (ROOT / url_path.lstrip("/")).resolve()
    if (
        not path.is_relative_to(ROOT / "static")
        or path.suffix != ".css"
        or not path.is_file()
    ):
        return None
    return path.read_bytes(), "text/css; charset=utf-8"
