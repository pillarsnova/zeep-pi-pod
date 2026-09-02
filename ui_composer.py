#!/usr/bin/env python3
"""Build the runtime UI from reviewable Control-section partials.

The Pi still serves one static ``index.html``: no browser-side fetch, ordering
race or new runtime dependency is introduced.  Developers edit
``static/index.template.html`` plus ``static/partials/control/*.html`` and run
``python ui_composer.py build``.  CI uses ``check`` to reject a stale bundle.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys


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
    build()


def render() -> str:
    text = TEMPLATE.read_text(encoding="utf-8")
    for filename in PARTIALS.values():
        marker = MARKER.format(name=filename)
        if text.count(marker) != 1:
            raise ValueError(f"Expected one marker for {filename}")
        partial = (PARTIAL_DIR / filename).read_text(encoding="utf-8").rstrip("\n")
        text = text.replace(marker, partial)
    if "ZEEP_PARTIAL:" in text:
        raise ValueError("Unknown partial marker remains in generated index")
    return text


def build() -> None:
    INDEX.write_text(render(), encoding="utf-8")


def check() -> None:
    generated = render()
    current = INDEX.read_text(encoding="utf-8")
    if generated != current:
        raise SystemExit("static/index.html is stale; run: python ui_composer.py build")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("extract", "build", "check"))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if args.command == "extract":
        extract(args.force)
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
