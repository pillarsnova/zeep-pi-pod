"""Regression checks for the ZEEP documentation authority map."""

from __future__ import annotations

import re
import unittest
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent
CURRENT_DOC_FILES = (
    ROOT / "README.md",
    ROOT / "CONTRIBUTING.md",
    ROOT / "TESTING.md",
)
CURRENT_DOC_DIRS = (
    ROOT / "docs",
    ROOT / "firmware",
    ROOT / "research" / "evidence-library",
    ROOT / "static" / "partials" / "app",
)
RETIRED_DOCUMENTS = (
    "REMOTE-ACCESS.md",
    "onboarding/refactor-roadmap-v1.md",
    "zeep-sleep-state-baseline-v1.0.md",
)
LINK_PATTERN = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def current_markdown_files() -> list[Path]:
    """Return user-facing current docs; evidence/archive files remain provenance."""

    files = list(CURRENT_DOC_FILES)
    for root in CURRENT_DOC_DIRS:
        files.extend(path for path in root.rglob("*.md") if "archive" not in path.parts)
    return sorted(set(files))


class DocumentationAlignmentTests(unittest.TestCase):
    def test_onboarding_is_the_primary_human_entry_point(self) -> None:
        root_readme = (ROOT / "README.md").read_text(encoding="utf-8")
        docs_index = (ROOT / "docs" / "README.md").read_text(encoding="utf-8")

        self.assertIn("docs/onboarding/README.md", root_readme)
        self.assertIn("onboarding/README.md", docs_index)

    def test_retired_documents_are_absent_and_unreferenced(self) -> None:
        self.assertFalse((ROOT / "REMOTE-ACCESS.md").exists())
        self.assertFalse(
            (ROOT / "docs" / "onboarding" / "refactor-roadmap-v1.md").exists()
        )
        self.assertFalse((ROOT / "docs" / "zeep-sleep-state-baseline-v1.0.md").exists())

        for document in current_markdown_files():
            content = document.read_text(encoding="utf-8")
            for retired in RETIRED_DOCUMENTS:
                with self.subTest(document=document, retired=retired):
                    self.assertNotIn(retired, content)

    def test_relative_markdown_links_resolve(self) -> None:
        missing: list[str] = []
        for document in current_markdown_files():
            content = document.read_text(encoding="utf-8")
            for raw_target in LINK_PATTERN.findall(content):
                target = raw_target.strip().strip("<>")
                if not target or target.startswith(("#", "/")):
                    continue
                if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.IGNORECASE):
                    continue
                target = unquote(target.split("#", 1)[0].split("?", 1)[0])
                if target and not (document.parent / target).resolve().exists():
                    missing.append(f"{document.relative_to(ROOT)} -> {raw_target}")

        self.assertEqual([], missing, "Broken local links:\n" + "\n".join(missing))


if __name__ == "__main__":
    unittest.main()
