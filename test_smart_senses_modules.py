"""Small contract tests for Smart Senses' read-only module boundaries."""

from __future__ import annotations

import ast
import copy
import unittest
from pathlib import Path

from acoustics import build_acoustic_timeline_snapshot
from acoustics.level_events import normalise_level_samples
from acoustics.timeline_series import compact_points, summarize_levels
from acoustics.timeline_view import event_summary, visible_events
from adaptive.learning_context import session_summary
from adaptive.learning_quality import data_quality, learning_blockers
from adaptive.learning_recommendations import build_candidate_recommendations

ROOT = Path(__file__).resolve().parent
MODULES = (
    "acoustics/timeline_projection.py",
    "acoustics/timeline_series.py",
    "acoustics/timeline_view.py",
    "adaptive/learning.py",
    "adaptive/learning_context.py",
    "adaptive/learning_quality.py",
    "adaptive/learning_recommendations.py",
)


class SmartSensesModuleTests(unittest.TestCase):
    def test_public_acoustic_entry_point_is_preserved(self):
        from acoustics.timeline_projection import (
            DEFAULT_DISPLAY_RANGE,
            DETECTOR_VERSION,
            MAX_VISIBLE_EVENTS,
        )
        from acoustics.timeline_projection import (
            build_acoustic_timeline_snapshot as facade,
        )

        self.assertIs(build_acoustic_timeline_snapshot, facade)
        self.assertEqual(DEFAULT_DISPLAY_RANGE, (30.0, 130.0))
        self.assertEqual(MAX_VISIBLE_EVENTS, 24)
        self.assertEqual(DETECTOR_VERSION, "zeep-level-pattern-v1.0+dsp-label-v0.1")

    def test_chart_compaction_preserves_gaps_and_energy_average(self):
        rows = normalise_level_samples(
            [{"t": 1000, "dba": 40}, {"t": 1010}, {"t": 1020, "dba": 50}],
            display_min=30,
            display_max=130,
        )
        points = compact_points(
            rows, cadence_s=10, display_range=(30, 130), max_points=240
        )
        summary = summarize_levels(
            rows, [40, 50], [], {}, cadence_s=10, display_range=(30, 130)
        )
        self.assertEqual([point["dba"] for point in points], [40, 50])
        self.assertEqual([point["gap_before"] for point in points], [False, True])
        self.assertEqual(summary["average_dba"], 47.4)
        self.assertEqual(summary["coverage_pct"], 66.7)

    def test_event_cards_are_bounded_without_losing_total_counts(self):
        events = [
            {"id": str(index), "key": "rapid_change", "start_epoch_s": index + 1}
            for index in range(60)
        ]
        visible = visible_events(events)
        summary = event_summary(events, visible)
        self.assertEqual(len(visible), 24)
        self.assertEqual(summary["total_count"], 60)
        self.assertEqual(summary["counts"]["rapid_change"], 60)
        self.assertTrue(summary["truncated"])
        visible[0]["key"] = "changed"
        self.assertTrue(all(event["key"] == "rapid_change" for event in events))

    def test_missing_vitals_do_not_hide_remaining_environment_observations(self):
        snapshot = {
            "session": {"recording": True},
            "sensor": {"environment": {"devices": {"light": {"status": "live"}}}},
        }
        quality = data_quality(snapshot, [], 30)
        self.assertTrue(quality["observation_ready"])
        self.assertFalse(quality["vital_pair_live"])
        self.assertEqual(quality["window_coverage_pct"], 0)
        self.assertEqual(
            [item["code"] for item in learning_blockers(snapshot, quality)],
            ["physiology_not_live"],
        )

    def test_advice_preserves_priority_and_never_gains_execution_authority(self):
        snapshot = {
            "smart_response": {
                "recommendations": [
                    {"domain": "first", "level": "attention", "executable": True},
                    {"domain": "second", "level": "attention", "command": "ignored"},
                    {
                        "domain": "alarm",
                        "level": "critical",
                        "command_endpoint": "/ignored",
                    },
                ]
            }
        }
        original = copy.deepcopy(snapshot)
        result = build_candidate_recommendations(snapshot, [], {}, "synthetic:1")
        self.assertEqual(
            [item["domain"] for item in result], ["alarm", "first", "second"]
        )
        self.assertEqual(snapshot, original)
        for item in result:
            self.assertFalse(item["executable"])
            self.assertTrue(item["requires_user_confirmation"])
            self.assertNotIn("command", item)
            self.assertNotIn("command_endpoint", item)

    def test_session_context_only_projects_allowed_fields(self):
        result = session_summary(
            {
                "session_id": "synthetic",
                "email": "private-marker",
                "token": "private-marker",
            },
            {},
            "sleep",
        )
        self.assertNotIn("private-marker", repr(result))
        self.assertEqual(result["session_id"], "synthetic")

    def test_facades_remain_small(self):
        for path, limit in (
            ("acoustics/timeline_projection.py", 140),
            ("adaptive/learning.py", 120),
        ):
            with self.subTest(path=path):
                self.assertLessEqual(len((ROOT / path).read_text().splitlines()), limit)

    def test_pure_modules_do_not_import_io_or_command_owners(self):
        forbidden = {
            "app",
            "api",
            "hardware",
            "database",
            "serial",
            "paho",
            "httpx",
            "requests",
        }
        for path in MODULES:
            with self.subTest(path=path):
                tree = ast.parse((ROOT / path).read_text())
                imports = []
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        imports.extend(alias.name for alias in node.names)
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        imports.append(node.module)
                self.assertFalse({name.split(".")[0] for name in imports} & forbidden)


if __name__ == "__main__":
    unittest.main()
