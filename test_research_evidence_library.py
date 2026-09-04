import hashlib
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent
LIBRARY = ROOT / "research" / "evidence-library"


class ResearchEvidenceLibraryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.register = json.loads((LIBRARY / "source-register.json").read_text(encoding="utf-8"))
        cls.sources = cls.register["sources"]

    def test_register_has_unique_ids_and_required_categories(self):
        ids = [source["id"] for source in self.sources]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(
            {"sleep", "health-wellness", "indoor-air-voc", "who", "vendor"}
            <= {source["category"] for source in self.sources}
        )

    def test_every_source_has_a_safe_https_origin_and_review_notes(self):
        for source in self.sources:
            with self.subTest(source=source["id"]):
                self.assertTrue(source["source_url"].startswith("https://"))
                self.assertTrue(source["use_in_zeep"].strip())
                self.assertTrue(source["limitations"].strip())
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
                self.assertTrue(source["local_file"].endswith(".pdf"))

    def test_cached_downloads_are_real_pdfs_and_match_lock_when_present(self):
        for source in self.sources:
            if source["access"] != "downloadable":
                continue
            path = LIBRARY / source["local_file"]
            if not path.exists():
                continue
            with self.subTest(source=source["id"]):
                self.assertGreater(path.stat().st_size, 10_000)
                self.assertEqual(path.read_bytes()[:5], b"%PDF-")
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), source["sha256"])

    def test_pdf_validator_rejects_html_with_pdf_extension(self):
        import importlib.util

        script = LIBRARY / "update_research_library.py"
        spec = importlib.util.spec_from_file_location("evidence_library", script)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            fake = Path(directory) / "challenge.pdf"
            fake.write_text("<html>challenge</html>", encoding="utf-8")
            errors = module.validate_pdf(fake, "0" * 64)
        self.assertIn("not a PDF signature", errors)

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


if __name__ == "__main__":
    unittest.main()
