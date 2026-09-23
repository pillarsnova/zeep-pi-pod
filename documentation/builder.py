"""Compile approved project documents into one offline, reproducible reader."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from documentation.rendering import REPOSITORY, contained_file, render_document

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "docs/portal/index.html"
KINDS = {
    "guide": "คู่มือระบบ",
    "contract": "ข้อกำหนด",
    "shadow": "ทดสอบ / Shadow",
    "plan": "แผนพัฒนา",
    "evidence": "หลักฐานอ้างอิง",
    "audit": "ผลตรวจตามวันที่",
}


def load_catalog(root: Path = ROOT) -> dict:
    catalog = json.loads((root / "documentation/catalog.json").read_text())
    ids, paths = set(), set()
    for group in catalog["groups"]:
        for doc_id, relative, _title, _summary, kind in group["documents"]:
            if doc_id in ids or relative in paths or kind not in KINDS:
                raise ValueError(f"Duplicate or invalid catalog entry: {doc_id}")
            if not relative.endswith(".md"):
                raise ValueError("Only allowlisted Markdown documents can be bundled")
            contained_file(root, relative)
            ids.add(doc_id)
            paths.add(relative)
    return catalog


def compile_data(root: Path = ROOT) -> dict:
    catalog = load_catalog(root)
    document_ids = {
        contained_file(root, entry[1]): entry[0]
        for group in catalog["groups"]
        for entry in group["documents"]
    }
    documents, groups, digest = [], [], hashlib.sha256()
    digest.update(json.dumps(catalog, sort_keys=True, ensure_ascii=False).encode())
    for group in catalog["groups"]:
        groups.append(
            {key: value for key, value in group.items() if key != "documents"}
        )
        for doc_id, relative, title, summary, kind in group["documents"]:
            source = contained_file(root, relative)
            content = source.read_text(encoding="utf-8")
            digest.update(relative.encode() + b"\0" + content.encode())
            documents.append(
                {
                    "id": doc_id,
                    "path": relative,
                    "title": title,
                    "summary": summary,
                    "kind": kind,
                    "kindLabel": KINDS[kind],
                    "group": group["id"],
                    "source": REPOSITORY + relative,
                    "checksum": hashlib.sha256(content.encode()).hexdigest(),
                    **render_document(content, source, root, document_ids),
                }
            )
    return {
        "edition": catalog["edition"],
        "reviewedOn": catalog["reviewed_on"],
        "digest": digest.hexdigest(),
        "groups": groups,
        "documents": documents,
    }


def build_html(root: Path = ROOT) -> str:
    assets = root / "documentation/assets"
    page = (assets / "index.template.html").read_text(encoding="utf-8")
    data = json.dumps(compile_data(root), ensure_ascii=False, separators=(",", ":"))
    # JSON is data, never executable HTML, even when a source contains </script>.
    data = (
        data.replace("<", "\\u003c")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )
    replacements = {
        "@@STYLE@@": (assets / "handbook.css").read_text(encoding="utf-8"),
        "@@DATA@@": data,
        "@@SCRIPT@@": (assets / "handbook.js").read_text(encoding="utf-8"),
    }
    return re.sub(
        r"@@(?:STYLE|DATA|SCRIPT)@@", lambda match: replacements[match[0]], page
    )


def write_bundle() -> Path:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(build_html(), encoding="utf-8")
    return OUTPUT
