import hashlib
import importlib.util
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parent
LIBRARY = ROOT / "research" / "evidence-library"


def load_tool():
    script = LIBRARY / "update_research_library.py"
    spec = importlib.util.spec_from_file_location("evidence_library", script)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ResearchEvidenceLibraryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.register = json.loads((LIBRARY / "source-register.json").read_text(encoding="utf-8"))
        cls.sources = cls.register["sources"]
        cls.tool = load_tool()

    def test_register_has_unique_ids_and_required_categories(self):
        ids = [source["id"] for source in self.sources]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(
            {"sleep", "health-wellness", "indoor-air-voc", "who", "vendor"}
            <= {source["category"] for source in self.sources}
        )

    def test_every_source_has_a_safe_https_origin_and_review_notes(self):
        self.assertTrue(self.register["authority"]["authoritative"])
        for source in self.sources:
            with self.subTest(source=source["id"]):
                self.assertTrue(source["source_url"].startswith("https://"))
                self.assertTrue(source["use_in_zeep"].strip())
                self.assertTrue(source["limitations"].strip())
                self.assertEqual(source["provenance"]["checked_on"], "2026-09-05")
                self.assertTrue(source["provenance"]["checked_by_role"].strip())
                self.assertTrue(source["provenance"]["method"].strip())
                local_file = source.get("local_file")
                if local_file:
                    path = Path(local_file)
                    self.assertFalse(path.is_absolute())
                    self.assertNotIn("..", path.parts)

    def test_downloadable_records_are_hash_locked(self):
        for source in self.sources:
            with self.subTest(source=source["id"]):
                if source["access"] != "downloadable":
                    self.assertIsNone(source["download_url"])
                    self.assertIsNone(source["local_file"])
                    self.assertIsNone(source["sha256"])
                    continue
                self.assertTrue(source["download_url"].startswith("https://"))
                self.assertRegex(source["sha256"], r"^[0-9a-f]{64}$")
                media_type = source.get("media_type", "application/pdf")
                suffix = ".xml" if media_type in {"application/xml", "text/xml"} else ".pdf"
                self.assertTrue(source["local_file"].endswith(suffix))

    def test_cached_downloads_are_real_pdfs_and_match_lock_when_present(self):
        for source in self.sources:
            if source["access"] != "downloadable":
                continue
            path = LIBRARY / source["local_file"]
            if not path.exists():
                continue
            with self.subTest(source=source["id"]):
                self.assertFalse(
                    self.tool.validate_artifact(
                        path,
                        source["sha256"],
                        source.get("media_type", "application/pdf"),
                    )
                )
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), source["sha256"])

    def test_pdf_validator_rejects_html_with_pdf_extension(self):
        with tempfile.TemporaryDirectory() as directory:
            fake = Path(directory) / "challenge.pdf"
            fake.write_text("<html>challenge</html>", encoding="utf-8")
            errors = self.tool.validate_pdf(fake, "0" * 64)
        self.assertIn("not a PDF signature", errors)

    def test_json_schema_validates_both_authoritative_registers(self):
        try:
            import jsonschema
        except ModuleNotFoundError:
            self.skipTest("jsonschema is installed in evidence-library CI")
        for stem in ("source-register", "protocol-register"):
            instance = json.loads((LIBRARY / f"{stem}.json").read_text(encoding="utf-8"))
            schema = json.loads((LIBRARY / f"{stem}.schema.json").read_text(encoding="utf-8"))
            jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(instance)

    def test_markdown_view_matches_authoritative_json_ids_and_urls(self):
        markdown = (LIBRARY / "SOURCE_REGISTER.md").read_text(encoding="utf-8")
        self.assertEqual(self.tool.validate_markdown_consistency(self.register, markdown), [])

    def test_two_mode_score_evidence_is_registered_and_explicit(self):
        source_ids = {source["id"] for source in self.sources}
        self.assertTrue({"SLP-007", "SLP-008", "SLP-009", "SLP-010", "SLP-011"} <= source_ids)
        for source_id in ("SLP-007", "SLP-008", "SLP-009"):
            source = next(item for item in self.sources if item["id"] == source_id)
            self.assertEqual(source["access"], "downloadable")
            self.assertTrue(source["local_file"].startswith("papers/sleep/"))

        guide = (LIBRARY / "TWO_MODE_SCORE_EVIDENCE.md").read_text(encoding="utf-8")
        self.assertIn("Overnight Recovery** | คืนนี้นอนเป็นอย่างไร | **Sleep Score", guide)
        self.assertIn("Nap & Refresh** | การพักครั้งนี้", guide)
        self.assertIn("**Recovery Score**", guide)
        self.assertIn("ไม่ควรนำตัวเลขของสองรูปแบบมาเทียบตรง ๆ", guide)
        for evidence_group in (
            "SLP-001", "SLP-002–004", "SLP-005–006", "SLP-007",
            "SLP-008", "SLP-009", "SLP-010–011",
        ):
            self.assertIn(evidence_group, guide)

    def test_shared_path_resolver_blocks_escape_for_all_commands(self):
        for unsafe in ("../outside.pdf", "/tmp/outside.pdf", "papers/../../outside.pdf"):
            with self.subTest(path=unsafe):
                with self.assertRaises(ValueError):
                    self.tool.resolve_library_path(unsafe)
        unsafe_source = {
            "id": "TST-001",
            "title": "Unsafe test record",
            "access": "downloadable",
            "download_url": "https://example.org/evidence.pdf",
            "local_file": "../outside.pdf",
            "sha256": "0" * 64,
        }
        with self.assertRaises(ValueError):
            self.tool.download_one(unsafe_source, force=True)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(self.tool.command_verify({"sources": [unsafe_source]}, set()), 1)
            self.assertEqual(self.tool.command_status({"sources": [unsafe_source]}, set()), 1)

    def test_https_policy_rejects_source_and_redirect_downgrade(self):
        with self.assertRaises(ValueError):
            self.tool.ensure_https_url("file:///tmp/evidence.pdf", field="source_url")
        with self.assertRaises(ValueError):
            self.tool.HTTPSOnlyRedirectHandler().redirect_request(
                None, None, 302, "Found", {}, "http://example.org/evidence.pdf"
            )

    def test_checksum_mismatch_is_quarantined_once_without_retry(self):
        class FakeResponse(io.BytesIO):
            def geturl(self):
                return "https://example.org/evidence.pdf"

        payload = b"%PDF-1.7\n" + (b"review-required\n" * 1_000)
        source = {
            "id": "TST-001",
            "download_url": "https://example.org/evidence.pdf",
            "local_file": "papers/test/evidence.pdf",
            "sha256": "0" * 64,
            "media_type": "application/pdf",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with mock.patch.object(self.tool, "LIBRARY_ROOT", root), mock.patch.object(
                self.tool, "open_https", return_value=FakeResponse(payload)
            ) as opener:
                with self.assertRaises(self.tool.IntegrityError):
                    self.tool.download_one(source, force=True)
            rejected = root / "papers/test/evidence.pdf.rejected"
            self.assertEqual(rejected.read_bytes(), payload)
            self.assertFalse((root / "papers/test/evidence.pdf.part").exists())
            opener.assert_called_once()

    def test_registered_voc_protocol_requires_pending_g1_and_g3_signoff(self):
        register = json.loads((LIBRARY / "protocol-register.json").read_text(encoding="utf-8"))
        self.assertTrue(register["authority"]["authoritative"])
        protocol = next(item for item in register["protocols"] if item["id"] == "ZEEP-VOC-CTRL-001")
        self.assertEqual(protocol["status"], "pending-approval")
        self.assertEqual(set(protocol["required_gates"]), {"G1", "G3"})
        self.assertEqual({gate["id"] for gate in protocol["gates"]}, {"G1", "G3"})
        for gate in protocol["gates"]:
            self.assertEqual(gate["status"], "pending")
            self.assertIsNone(gate["signed_by"])
            self.assertIsNone(gate["signed_at"])
        plan = (LIBRARY / protocol["document"]).read_text(encoding="utf-8")
        for expected in (protocol["id"], protocol["owner_role"], "G1", "G3", "Pending"):
            self.assertIn(expected, plan)

    def test_voc_control_plan_is_primary_and_source_agnostic(self):
        readme = (LIBRARY / "README.md").read_text(encoding="utf-8")
        plan = (LIBRARY / "VOC_CONTROL_VALIDATION.md").read_text(encoding="utf-8")
        case_note = (LIBRARY / "SMOKING_VOC_CASE.md").read_text(encoding="utf-8")
        self.assertIn("VOC_CONTROL_VALIDATION.md", readme)
        self.assertIn("ไม่ใช่การตรวจหาผู้สูบบุหรี่", plan)
        for metric in (
            "percent_time_in_target",
            "valid_coverage_percent",
            "auc_above_baseline",
            "clearance_time_min",
            "SRAW_VOC",
        ):
            self.assertIn(metric, plan)
        self.assertIn("VOC_CONTROL_VALIDATION.md", case_note)
        self.assertIn("AIR-006", {source["id"] for source in self.sources})
        self.assertNotIn("epa.gov/sites/default/files", case_note)
        self.assertNotIn("epa.gov/sites/default/files", plan)


if __name__ == "__main__":
    unittest.main()
