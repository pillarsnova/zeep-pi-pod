"""Guardrails for the Admin-only Smart Ear level-only shadow."""

from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime

from acoustics import (
    acoustic_contract_snapshot,
    build_acoustic_monitor_snapshot,
)


def live_snapshot(sound_dba: object = 43.2) -> dict:
    return {
        "sensor": {
            "esp32": {"firmware_version": "production-example"},
            "environment": {
                "sound_dba_est": sound_dba,
                "devices": {"sph0645": {"status": "live"}},
            },
        },
        "system": {
            "sound_transform": {"accepted_range_dba": [30, 130]},
            "sound_analysis": {
                "status": "valid",
                "sample_count": 1,
                "leq_dba": sound_dba,
                "min_dba": sound_dba,
                "max_dba": sound_dba,
                "span_db": 0,
                "window_s": 10,
                "window_end": "2026-09-17T00:00:00+00:00",
            },
        },
    }


class AcousticContractTests(unittest.TestCase):
    def test_contract_exposes_candidates_without_claiming_capability(self) -> None:
        contract = acoustic_contract_snapshot()
        encoded = json.dumps(contract, ensure_ascii=False)

        self.assertEqual(contract["mode"], "admin_shadow_level_only")
        self.assertTrue(contract["current_capability"]["sound_level"])
        self.assertFalse(contract["current_capability"]["acoustic_classification"])
        for label in ("speech_like", "snore_like", "cough_like"):
            self.assertIn(label, encoded)
        self.assertNotIn("apnea", encoded.casefold())
        self.assertEqual(
            contract["validation"]["protocol_id"],
            "ZEEP-ACOUSTIC-SHADOW-001",
        )
        self.assertFalse(any(contract["impact"].values()))
        self.assertFalse(contract["clinical_validated"])
        self.assertFalse(contract["automatic_actuation"])

    def test_scalar_level_never_manufactures_a_classification(self) -> None:
        result = build_acoustic_monitor_snapshot(
            live_snapshot(),
            generated_at=datetime(2026, 9, 17, tzinfo=UTC),
        )

        self.assertEqual(result["status"], "level_only")
        self.assertEqual(result["classification_state"], "not_evaluated")
        self.assertEqual(result["confidence_band"], "unavailable")
        self.assertEqual(result["level"]["sound_dba"], 43.2)
        self.assertFalse(result["level"]["certified_laeq"])
        self.assertEqual(result["results"]["shapes"], [])
        self.assertEqual(result["results"]["likely_sources"], [])
        self.assertEqual(result["results"]["human_sound_hypotheses"], [])
        self.assertIn("feature_telemetry_unavailable", result["reason_codes"])
        self.assertFalse(any(result["impact"].values()))

        encoded = json.dumps(result, ensure_ascii=False).casefold()
        for forbidden in ("raw_pcm", "base64", "transcript"):
            self.assertNotIn(forbidden, encoded)
        self.assertFalse(result["privacy"]["speaker_identity_processed"])

    def test_invalid_or_stale_level_fails_soft(self) -> None:
        snapshot = live_snapshot(-41.2)
        snapshot["sensor"]["environment"]["devices"]["sph0645"]["status"] = "stale"
        result = build_acoustic_monitor_snapshot(snapshot)

        self.assertEqual(result["status"], "stale")
        self.assertIsNone(result["level"]["sound_dba"])
        self.assertEqual(result["classification_state"], "not_evaluated")
        self.assertIn("sound_level_unavailable", result["reason_codes"])
        self.assertIn("microphone_not_live", result["reason_codes"])


if __name__ == "__main__":
    unittest.main()
