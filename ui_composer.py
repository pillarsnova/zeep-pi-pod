#!/usr/bin/env python3
"""Build the runtime UI from reviewable HTML, CSS, and JavaScript partials.

The Pi still serves one static ``index.html``: no browser-side fetch, ordering
race or new runtime dependency is introduced.  Developers edit
``static/index.template.html`` plus files under ``static/partials`` and run
``python ui_composer.py build``. CI uses ``check`` to reject a stale bundle.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
INDEX = STATIC / "index.html"
TEMPLATE = STATIC / "index.template.html"
PARTIAL_DIR = STATIC / "partials" / "control"

PARTIALS = {
    "door-zone": "door.html",
    "air-zone": "air.html",
    "bed-zone": "bed.html",
    "light-zone": "light.html",
    "audio-zone": "audio.html",
    "aroma-zone": "aroma.html",
}
MARKER = "<!-- ZEEP_PARTIAL:control/{name} -->"
INLINE_MARKER = "/* ZEEP_PARTIAL:{name} */"
STYLE_PARTIAL = "app/styles.css"
SCRIPT_PARTIALS = (
    ("app/scripts/00-product-copy-alerts.js", "const names = "),
    ("app/scripts/01-runtime-safety.js", "const pulseOutputs = "),
    (
        "app/scripts/02-device-controls.js",
        "/* ---- track metadata:",
    ),
    ("app/scripts/03-dashboard.js", "function compactMetric("),
    ("app/scripts/04-unified-controls.js", "function unifiedAirconPowerToggle("),
    ("app/scripts/05-hardware-actions.js", "/* ---- Red ambient:"),
    ("app/scripts/06-client-api.js", "/* Optional auth:"),
    ("app/scripts/07-debug-brainwave.js", "let brainwaveCatalog=null;"),
    ("app/scripts/08-sensors-monitor.js", "function fmt(v,d=1)"),
    (
        "app/scripts/09-auth-login.js",
        "/* ---------- per-person session:",
    ),
    (
        "app/scripts/10-session-end-report.js",
        "/* ---- จบ Session:",
    ),
    ("app/scripts/11-history-list.js", "function fmtDateTh("),
    ("app/scripts/12-history-report.js", "const REPORT_STAGE_META="),
    ("app/scripts/13-runtime-websocket.js", "/* ---------- audio visualizer:"),
)
INLINE_PARTIALS = (STYLE_PARTIAL,) + tuple(name for name, _ in SCRIPT_PARTIALS)


def _section_span(text: str, class_token: str) -> tuple[int, int]:
    start_match = re.search(
        rf'<section\b[^>]*class="[^"]*\b{re.escape(class_token)}\b[^"]*"[^>]*>',
        text,
    )
    if start_match is None:
        raise ValueError(f"Control section not found: {class_token}")
    token = re.compile(r"<section\b|</section>")
    depth = 0
    for match in token.finditer(text, start_match.start()):
        if match.group(0).startswith("<section"):
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                return start_match.start(), match.end()
    raise ValueError(f"Unclosed Control section: {class_token}")


def extract(force: bool = False) -> None:
    if TEMPLATE.exists() and not force:
        raise FileExistsError("Template already exists; use build or pass --force")
    text = INDEX.read_text(encoding="utf-8")
    PARTIAL_DIR.mkdir(parents=True, exist_ok=True)
    found: list[tuple[int, int, str, str]] = []
    for class_token, filename in PARTIALS.items():
        start, end = _section_span(text, class_token)
        partial = text[start:end]
        (PARTIAL_DIR / filename).write_text(partial + "\n", encoding="utf-8")
        found.append((start, end, filename, partial))
    for start, end, filename, partial in sorted(found, reverse=True):
        indent = re.search(r"(^|\n)([ \t]*)<section", partial)
        prefix = indent.group(2) if indent else ""
        text = text[:start] + prefix + MARKER.format(name=filename) + text[end:]
    TEMPLATE.write_text(text, encoding="utf-8")
    split_inline()
    build()


def _inline_marker(name: str) -> str:
    return INLINE_MARKER.format(name=name)


def _write_partial(name: str, content: str) -> None:
    path = STATIC / "partials" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _extract_style(text: str) -> str:
    opening = "  <style>\n"
    start = text.index(opening) + len(opening)
    end = text.index("  </style>", start)
    _write_partial(STYLE_PARTIAL, text[start:end])
    return text[:start] + _inline_marker(STYLE_PARTIAL) + "\n" + text[end:]


def _extract_scripts(text: str) -> str:
    opening = "<script>\n"
    start = text.index(opening) + len(opening)
    end = text.index("</script>", start)
    body = text[start:end]
    positions = [body.index(token) for _, token in SCRIPT_PARTIALS]
    if positions[0] != 0 or positions != sorted(positions):
        raise ValueError("Inline script boundaries are missing or out of order")
    for index, (name, _) in enumerate(SCRIPT_PARTIALS):
        stop = positions[index + 1] if index + 1 < len(positions) else len(body)
        _write_partial(name, body[positions[index] : stop])
    markers = "".join(f"{_inline_marker(name)}\n" for name, _ in SCRIPT_PARTIALS)
    return text[:start] + markers + text[end:]


def split_inline() -> None:
    """Move embedded CSS/JS into ordered build-time fragments once."""
    text = TEMPLATE.read_text(encoding="utf-8")
    if any(_inline_marker(name) in text for name in INLINE_PARTIALS):
        raise FileExistsError("Inline partial markers already exist")
    TEMPLATE.write_text(_extract_scripts(_extract_style(text)), encoding="utf-8")


def _validate_inline_layout(text: str) -> None:
    """Protect CSS cascade and classic-script dependency order."""
    positions: list[int] = []
    for name in INLINE_PARTIALS:
        marker = _inline_marker(name)
        if text.count(marker) != 1:
            raise ValueError(f"Expected one marker for {name}")
        positions.append(text.index(marker))
    if positions != sorted(positions):
        raise ValueError("Inline partial markers are out of manifest order")

    style_start = text.index("<style>")
    style_end = text.index("</style>", style_start)
    if not style_start < positions[0] < style_end:
        raise ValueError("Base style marker must remain inside the inline style")

    script_start = text.index("<script>\n")
    script_end = text.index("</script>", script_start)
    if not all(script_start < position < script_end for position in positions[1:]):
        raise ValueError("JavaScript markers must remain inside the classic script")


def render() -> str:
    text = TEMPLATE.read_text(encoding="utf-8")
    _validate_inline_layout(text)
    for filename in PARTIALS.values():
        marker = MARKER.format(name=filename)
        if text.count(marker) != 1:
            raise ValueError(f"Expected one marker for {filename}")
        partial = (PARTIAL_DIR / filename).read_text(encoding="utf-8").rstrip("\n")
        text = text.replace(marker, partial)
    for name in INLINE_PARTIALS:
        marker = _inline_marker(name)
        partial = (STATIC / "partials" / name).read_text(encoding="utf-8")
        if not partial.endswith("\n"):
            raise ValueError(f"Inline partial must end with a newline: {name}")
        text = text.replace(marker + "\n", partial)
    if "ZEEP_PARTIAL:" in text:
        raise ValueError("Unknown partial marker remains in generated index")
    return text


def build() -> None:
    temporary = INDEX.with_name(f".{INDEX.name}.tmp")
    try:
        temporary.write_text(render(), encoding="utf-8")
        temporary.replace(INDEX)
    finally:
        temporary.unlink(missing_ok=True)


def check() -> None:
    generated = render()
    current = INDEX.read_text(encoding="utf-8")
    if generated != current:
        raise SystemExit("static/index.html is stale; run: python ui_composer.py build")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=("extract", "split-inline", "build", "check"),
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if args.command == "extract":
        extract(args.force)
    elif args.command == "split-inline":
        split_inline()
    elif args.command == "build":
        build()
    else:
        check()


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(2) from exc
