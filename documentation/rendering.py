"""Safe Markdown rendering and repository-aware handbook links."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

from markdown_it import MarkdownIt

REPOSITORY = "https://github.com/pillarsnova/zeep-pi-pod/blob/develop/"


def contained_file(root: Path, relative: str) -> Path:
    """Reject absolute paths, traversal and symlinks outside the repository."""
    if Path(relative).is_absolute() or Path(relative).suffix != ".md":
        raise ValueError("A relative repository path is required")
    target = (root / relative).resolve()
    if not target.is_relative_to(root.resolve()) or not target.is_file():
        raise ValueError(f"Missing or out-of-scope documentation: {relative}")
    return target


def heading_slug(text: str) -> str:
    return re.sub(r"[^\w\-\s\u0e00-\u0e7f]", "", text.lower()).replace(" ", "-")


def document_link(
    href: str, source: Path, root: Path, document_ids: dict[Path, str]
) -> str | None:
    """Bundle internal articles; only permit explicit HTTP(S) external links."""
    parsed = urlsplit(href)
    if parsed.scheme:
        return href if parsed.scheme in {"https", "http"} else None
    if parsed.netloc or parsed.path.startswith("/"):
        return None
    target = (source.parent / unquote(parsed.path)).resolve() if parsed.path else source
    if target == root / "docs/portal/index.html":
        return "#/"
    anchor = "/" + quote(unquote(parsed.fragment), safe="") if parsed.fragment else ""
    if target in document_ids:
        return f"#/read/{document_ids[target]}{anchor}"
    if not target.is_relative_to(root) or not target.exists():
        return None
    relative = target.relative_to(root).as_posix()
    # Do not publish links to runtime stores, binaries or private configuration.
    if target.suffix not in {".py", ".md", ".json", ".html", ".cpp", ".h", ".yml"}:
        return None
    if any(part.startswith(".") for part in target.relative_to(root).parts):
        return None
    fragment = "#" + quote(unquote(parsed.fragment)) if parsed.fragment else ""
    return REPOSITORY + quote(relative) + fragment


def render_document(
    text: str, source: Path, root: Path, document_ids: dict[Path, str]
) -> dict:
    parser = MarkdownIt("commonmark", {"html": False}).enable("table")
    tokens = parser.parse(text)
    outline, search_parts, seen = [], [], {}
    for index, token in enumerate(tokens):
        if token.type == "heading_open":
            heading = tokens[index + 1].content
            slug = heading_slug(heading)
            occurrence = seen.get(slug, 0)
            seen[slug] = occurrence + 1
            anchor = f"{slug}-{occurrence}" if occurrence else slug
            token.attrSet("id", anchor)
            outline.append({"title": heading, "id": anchor, "level": int(token.tag[1])})
        if token.type in {"inline", "fence", "code_block"}:
            search_parts.append(token.content)
        for child in token.children or []:
            if child.type == "image":
                # No remote media requests, tracking pixels or local file leaks.
                child.type, child.tag = "text", ""
                child.content = f"[ภาพประกอบ: {child.content}]"
            if child.type == "link_open":
                href = document_link(
                    child.attrGet("href") or "", source, root, document_ids
                )
                child.attrs.pop("href", None)
                if href:
                    child.attrSet("href", href)
                    if href.startswith("http"):
                        child.attrSet("target", "_blank")
                        child.attrSet("rel", "noopener noreferrer")
                else:
                    child.attrSet("title", "เอกสารอ้างอิงนอกชุดนี้ — ตรวจจากต้นฉบับ")
                    child.attrSet("class", "unavailable-reference")
    return {
        "html": parser.renderer.render(tokens, parser.options, {}),
        "outline": outline,
        "text": "\n".join(search_parts),
    }
