import base64
from datetime import datetime, timezone
import struct
import unittest

from audit_sleep_history_shadow import (
    operational_status_row,
    replay_session,
)
from promote_sleep_history import public_promotion_summary
from sleep_history_policy import (
    promotion_ready,
    quality_tier,
    replay_integrity_blockers,
    replay_review_warnings,
    split_issue_codes,
)
from sleep_system_policy import AGE_SLEEP_BASELINES


class SleepHistoryPolicyTests(unittest.TestCase):
    @staticmethod
    def packets_for_minute(*, missing_waveform_bucket=None):
        payload = base64.b64encode(struct.pack("<25h", *([1] * 25))).decode()
        packets = []
        for bucket_index in range(6):
            for packet_index in range(8):
                timestamp = bucket_index * 10 + packet_index + 0.1
                packets.append({
                    "timestamp": datetime.fromtimestamp(
                        timestamp, timezone.utc,
                    ).isoformat(),
                    "status_code": 0,
                    "heart_rate": 60.0,
                    "respiration_rate": 15.0,
                    "bcg_base64": (
                        "" if bucket_index == missing_waveform_bucket
                        else payload
                    ),
                })
        return packets

    def test_operational_status_is_not_a_sleep_stage(self):
        row = operational_status_row(
            {
                "t": 30.0,
                "packet_count": 0,
                "paired_packets": 0,
                "paired_vital_coverage": 0.0,
            },
            state="no_data",
            data_status="sensor_gap",
            reason="missing",
            segment=0,
        )

        self.assertEqual(row["label"], "NO DATA · หลักฐานไม่ครบ")
        self.assertFalse(row["sleep_stage"])
        self.assertTrue(row["excluded_from_score"])

    def test_promotion_cli_summary_excludes_session_health_details(self):
        result = {
            "applied": True,
            "selected_sessions": 2,
            "selected_ids": ["private-session"],
            "derived_events": 10,
            "report_rescore": {"sessions": [{"email": "private@test"}]},
            "reviewed_report_parity": [{"session_id": "private-session"}],
            "baselines_rebuilt": 1,
            "sessions_integrity_check": "ok",
            "raw_timeline_sha256_before": "same-timeline",
            "raw_timeline_sha256_after": "same-timeline",
            "raw_bcg_sha256_before": "same-bcg",
            "raw_bcg_sha256_after": "same-bcg",
        }

        summary = public_promotion_summary(result)

        self.assertNotIn("selected_ids", summary)
        self.assertNotIn("report_rescore", summary)
        self.assertEqual(summary["reviewed_report_parity_count"], 1)
        self.assertTrue(summary["raw_timeline_hash_unchanged"])
        self.assertTrue(summary["raw_bcg_hash_unchanged"])

    def test_replay_exposes_every_empty_epoch_as_no_data(self):
        replay = replay_session(
            [],
            0.0,
            90.0,
            baseline=AGE_SLEEP_BASELINES["30-44"],
            rem_variability_weight=1.0,
        )

        self.assertEqual(replay["evaluation_epoch_count"], 3)
        self.assertEqual(replay["confirmed_count"], 0)
        self.assertEqual(replay["operational_status_counts"], {"no_data": 3})

    def test_current_epoch_requires_bed_hr_rr_and_raw_bcg(self):
        replay = replay_session(
            self.packets_for_minute(missing_waveform_bucket=4),
            0.0,
            60.0,
            baseline=AGE_SLEEP_BASELINES["30-44"],
            rem_variability_weight=1.0,
        )

        self.assertEqual(replay["evaluation_epoch_count"], 2)
        self.assertEqual(replay["status_rows"][-1]["state"], "no_data")
        self.assertEqual(
            replay["status_rows"][-1]["data_status"],
            "incomplete_current_epoch_evidence",
        )
        self.assertFalse(any(
            row["t"] == 60.0 for row in replay["evidence_rows"]
        ))

    def test_quality_tier_is_descriptive_not_a_promotion_gate(self):
        tier = quality_tier(
            timeline_paired_hr_rr=0.76,
            raw_paired_hr_rr=0.75,
            raw_acquisition=0.82,
            raw_maximum_gap_s=120.0,
            context_reset_gap_s=60.0,
        )
        item = {
            "quality_tier": tier,
            "review_warnings": ["wellness_score_not_releasable"],
            "promotion_blockers": [],
            "evidence_rows": [{"candidate": "wake"}],
            "state_rows": [{"state": "wake"}],
        }

        self.assertEqual(tier, "below_B")
        self.assertTrue(promotion_ready(item))

    def test_review_warning_does_not_block_valid_epochs(self):
        warnings, blockers = split_issue_codes([
            "overnight_N3_zero",
            "ping_pong_within_60s",
        ])

        self.assertEqual(
            warnings,
            ["overnight_N3_zero", "ping_pong_within_60s"],
        )
        self.assertEqual(blockers, [])

    def test_transition_invariant_is_a_hard_blocker(self):
        replay = {
            "evidence_count": 10,
            "confirmed_count": 8,
            "forbidden_transition_count": 1,
            "confirmed_transition_without_current_gate_count": 0,
        }

        blockers = replay_integrity_blockers(replay, raw_packet_count=120)

        self.assertEqual(blockers, ["forbidden_transition"])

    def test_missing_replay_rows_warn_but_raw_loss_blocks(self):
        blockers = replay_integrity_blockers(
            {
                "evidence_count": 0,
                "confirmed_count": 0,
                "forbidden_transition_count": 0,
                "confirmed_transition_without_current_gate_count": 0,
            },
            raw_packet_count=0,
        )

        self.assertEqual(
            blockers,
            ["missing_raw_bcg_packets"],
        )
        self.assertEqual(
            replay_review_warnings({
                "evidence_count": 0,
                "confirmed_count": 0,
            }),
            ["no_valid_epoch_evidence", "no_confirmed_sleep_state"],
        )

    def test_status_only_result_is_promotable(self):
        item = {
            "promotion_blockers": [],
            "evidence_rows": [],
            "state_rows": [],
            "status_rows": [{"state": "off_bed"}],
        }

        self.assertTrue(promotion_ready(item))

    def test_unknown_issue_fails_closed(self):
        warnings, blockers = split_issue_codes(["future_unreviewed_rule"])

        self.assertEqual(warnings, [])
        self.assertEqual(blockers, ["unclassified_issue:future_unreviewed_rule"])


if __name__ == "__main__":
    unittest.main()
