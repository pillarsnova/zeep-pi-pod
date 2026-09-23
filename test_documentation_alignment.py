"""Regression checks for the ZEEP documentation authority map."""

from __future__ import annotations

import json
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
    ROOT / "documentation",
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
        files.extend(
            path
            for path in root.rglob("*.md")
            if "archive" not in path.parts
            and not any(part.startswith(".") for part in path.relative_to(root).parts)
        )
    return sorted(set(files))


class DocumentationAlignmentTests(unittest.TestCase):
    def test_smart_senses_is_the_umbrella_not_a_firmware_or_api_rename(self):
        guide = (ROOT / "docs/onboarding/smart-senses.md").read_text(
            encoding="utf-8"
        )
        for reference in (
            "Smart Ear เป็นโมดูลเสียง",
            "/api/v1/adaptive/sessions/{session_id}",
            "/api/v1/admin/acoustics/timeline",
            "zeep-pod-acoustic-design.html",
            "ไม่ได้แก้หน้าเว็บไซต์ต้นทาง",
        ):
            self.assertIn(reference, guide)
        for name in ("README.md", "docs/README.md", "docs/onboarding/README.md"):
            self.assertIn("smart-senses.md", (ROOT / name).read_text())

    def test_onboarding_is_the_primary_human_entry_point(self) -> None:
        root_readme = (ROOT / "README.md").read_text(encoding="utf-8")
        docs_index = (ROOT / "docs" / "README.md").read_text(encoding="utf-8")

        self.assertIn("docs/onboarding/README.md", root_readme)
        self.assertIn("onboarding/README.md", docs_index)

    def test_current_domain_documents_are_indexed(self) -> None:
        index = (ROOT / "docs" / "README.md").read_text(encoding="utf-8")
        for document in (ROOT / "docs").glob("*.md"):
            if document.name == "README.md":
                continue
            with self.subTest(document=document.name):
                self.assertIn(f"({document.name})", index)

    def test_core_guide_tables_have_consistent_columns(self) -> None:
        documents = (
            "onboarding/README.md",
            "README.md",
            "zeep-interface-map-and-ui-standard-v1.md",
            "zeep-session-result-presentation-v1.md",
            "zeep-api-schema-reference-v1.md",
        )
        for name in documents:
            fenced = False
            columns = 0
            content = (ROOT / "docs" / name).read_text(encoding="utf-8")
            for number, line in enumerate(content.splitlines(), 1):
                if line.startswith("```"):
                    fenced = not fenced
                    columns = 0
                    continue
                if fenced:
                    continue
                if not line.startswith("|"):
                    columns = 0
                    continue
                count = len(re.split(r"(?<!\\)\|", line)) - 2
                if not columns:
                    columns = count
                with self.subTest(document=name, line=number):
                    self.assertEqual(columns, count)

    def test_current_status_tracks_runtime_versions(self) -> None:
        from presentation.language import PRODUCT_LANGUAGE_VERSION
        from sleep_system_policy import (
            RECOVERY_SCORE_FORMULA_VERSION,
            RESTORE_RECOMMENDATION_VERSION,
            SESSION_REPORT_VERSION,
            SLEEP_ESTIMATOR_VERSION,
            SLEEP_EVIDENCE_VERSION,
            SLEEP_SCORE_FORMULA_VERSION,
            ZEEP_SLEEP_BASELINE_VERSION,
        )

        content = (ROOT / "docs" / "current-status.md").read_text(encoding="utf-8")
        for version in (
            PRODUCT_LANGUAGE_VERSION,
            RECOVERY_SCORE_FORMULA_VERSION,
            RESTORE_RECOMMENDATION_VERSION,
            SESSION_REPORT_VERSION,
            SLEEP_ESTIMATOR_VERSION,
            SLEEP_EVIDENCE_VERSION,
            SLEEP_SCORE_FORMULA_VERSION,
            ZEEP_SLEEP_BASELINE_VERSION,
        ):
            with self.subTest(version=version):
                self.assertIn(version, content)

    def test_refactored_boundaries_remain_in_the_architecture_map(self) -> None:
        content = (ROOT / "docs/pi5-software-architecture.md").read_text()
        for source in (
            "acoustics/timeline_series.py",
            "acoustics/timeline_view.py",
            "adaptive/learning_quality.py",
            "adaptive/learning_context.py",
            "adaptive/learning_recommendations.py",
            "sessions/sleep_n3_evidence.py",
            "sessions/sleep_n3_policy.py",
            "identity/baseline_context.py",
            "api/handbook_routes.py",
        ):
            with self.subTest(source=source):
                self.assertTrue((ROOT / source).is_file())
                self.assertIn(Path(source).name, content)

    def test_baseline_display_name_matches_the_source_version(self) -> None:
        from sleep_system_policy import ZEEP_SLEEP_BASELINE_VERSION

        version = re.search(r"-v(\d+\.\d+)-", ZEEP_SLEEP_BASELINE_VERSION).group(1)
        for source in ("docs/README.md", "docs/zeep-sleep-system-current.md"):
            with self.subTest(source=source):
                content = (ROOT / source).read_text(encoding="utf-8")
                self.assertIn(f"Sleep-State Baseline v{version}", content)

    def test_handbook_build_is_in_stack_and_operations_guides(self) -> None:
        stack = (ROOT / "docs/onboarding/technology-stack-and-tools.md").read_text()
        self.assertIn("markdown-it-py", stack)
        self.assertIn("Dev/Build", stack)
        for source in ("README.md", "docs/pi5-operations-runbook.md"):
            content = (ROOT / source).read_text()
            self.assertIn("python -m documentation build", content)
            self.assertIn("python -m documentation check", content)

    def test_schema_examples_match_models_and_advice_policy(self) -> None:
        from presentation.language import PRODUCT_LANGUAGE_VERSION
        from sessions.post_rest_advice import build_post_rest_advice
        from sessions.usage_response_models import UsageSessionSummaryResponse

        document = ROOT / "docs" / "zeep-api-schema-reference-v1.md"
        content = document.read_text(encoding="utf-8")
        modes = set()
        for block in re.findall(r"```json\n(.*?)\n```", content, re.DOTALL):
            example = json.loads(block)
            data = example.get("data", {})
            restore = data.get("restore_summary", {})
            if "recommendation" not in restore:
                continue
            UsageSessionSummaryResponse.model_validate(example)
            mode = data["mode"]["key"]
            modes.add(mode)
            with self.subTest(mode=mode):
                self.assertEqual(
                    data["versions"]["product_language"], PRODUCT_LANGUAGE_VERSION
                )
                self.assertEqual(
                    restore["recommendation"],
                    build_post_rest_advice(
                        mode,
                        data["score"]["value"],
                        restore["drivers"],
                        baseline=restore.get("personal_baseline"),
                        subjective=restore.get("subjective_outcome"),
                    ),
                )
        self.assertEqual(modes, {"sleep", "nap_recovery", "unknown"})

    def test_recommendation_fields_are_all_documented(self) -> None:
        from sessions.advice_response_models import RestoreRecommendation

        content = (ROOT / "docs" / "zeep-api-schema-reference-v1.md").read_text(
            encoding="utf-8"
        )
        section = content.split("### 8.5 Recommendation,", 1)[1].split(
            "`confidence` มี", 1
        )[0]
        for field in RestoreRecommendation.model_fields:
            with self.subTest(field=field):
                self.assertIn(f"| `{field}` |", section)

    def test_obsolete_firmware_status_is_not_current_guidance(self) -> None:
        retired_claims = (
            "P0.5 Admin level-only/capability contract อยู่ใน runtime",
            "FIRMWARE CANDIDATE NOT INSTALLED",
            "Production firmware ยังไม่ส่ง spectral",
            "ไม่มีแผน Flash จากชุดนี้",
        )
        for document in current_markdown_files():
            if "reviews" in document.parts or "audits" in document.parts:
                continue
            content = document.read_text(encoding="utf-8")
            for claim in retired_claims:
                with self.subTest(document=document, claim=claim):
                    self.assertNotIn(claim, content)

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
