"""Keep the deployed single-file UI synchronized with Control partials."""

from pathlib import Path
import re
import unittest

import ui_composer


class UiComposerTests(unittest.TestCase):
    def test_generated_index_matches_template_and_partials(self):
        self.assertEqual(
            ui_composer.INDEX.read_text(encoding="utf-8"),
            ui_composer.render(),
        )

    def test_each_control_section_has_one_partial_and_one_runtime_instance(self):
        runtime = ui_composer.INDEX.read_text(encoding="utf-8")
        template = ui_composer.TEMPLATE.read_text(encoding="utf-8")
        for class_token, filename in ui_composer.PARTIALS.items():
            with self.subTest(section=class_token):
                self.assertTrue((ui_composer.PARTIAL_DIR / filename).is_file())
                matches = re.findall(
                    rf'<section\b[^>]*class="[^"]*\b{re.escape(class_token)}\b[^"]*"',
                    runtime,
                )
                self.assertEqual(len(matches), 1)
                self.assertEqual(
                    template.count(ui_composer.MARKER.format(name=filename)), 1
                )


if __name__ == "__main__":
    unittest.main()
