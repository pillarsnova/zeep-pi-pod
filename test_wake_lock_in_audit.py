import unittest

from zeep_pod.sessions.wake_lock_audit import find_suspected_wake_lock_ins


ESTIMATOR = "regression-estimator"


def stage_event(
    session_id: str,
    event_id: int,
    second: int,
    state: str,
    *,
    onset: bool,
    bed_status: str = "On bed",
    movement: float = 0.01,
    mean_hr: float = 65.0,
    awake_hr: float = 75.0,
) -> dict:
    return {
        "id": event_id,
        "session_id": session_id,
        "t": second,
        "payload": {
            "state": state,
            "sample_interval_s": 30,
            "estimator_version": ESTIMATOR,
            "metrics": {
                "sleep_onset_established": onset,
                "bed_status": bed_status,
                "movement_ratio": movement,
                "mean_hr": mean_hr,
                "awake_hr_reference": awake_hr,
            },
        },
    }


def wake_lock_fixture(session_id: str, wake_epochs: int) -> list[dict]:
    rows = [stage_event(session_id, 1, 0, "n2", onset=True)]
    rows.extend(
        stage_event(
            session_id,
            index + 2,
            (index + 1) * 30,
            "wake",
            onset=False,
        )
        for index in range(wake_epochs)
    )
    return rows


class WakeLockAuditTests(unittest.TestCase):
    def test_three_coded_regression_signatures_are_detected(self) -> None:
        rows = []
        rows.extend(wake_lock_fixture("coded-case-1", 49))
        rows.extend(wake_lock_fixture("coded-case-2", 33))
        rows.extend(wake_lock_fixture("coded-case-3", 122))

        findings = find_suspected_wake_lock_ins(
            rows,
            estimator_version=ESTIMATOR,
        )

        self.assertEqual(len(findings), 3)
        self.assertEqual(
            sorted(item["duration_s"] for item in findings),
            [990.0, 1470.0, 3660.0],
        )
        self.assertTrue(all(item["automatic_relabel"] is False for item in findings))
        self.assertTrue(all(item["onset_lost_ratio"] == 1.0 for item in findings))
        self.assertNotIn("coded-case", str(findings))

    def test_real_wake_with_motion_is_retained_and_not_flagged(self) -> None:
        rows = [stage_event("real-wake", 1, 0, "n2", onset=True)]
        rows.extend(
            stage_event(
                "real-wake",
                index + 2,
                (index + 1) * 30,
                "wake",
                onset=True,
                bed_status="Moving",
                movement=0.65,
                mean_hr=82.0,
                awake_hr=75.0,
            )
            for index in range(40)
        )

        findings = find_suspected_wake_lock_ins(
            rows,
            estimator_version=ESTIMATOR,
        )

        self.assertEqual(findings, [])

    def test_quiet_wake_is_not_relabelled_when_onset_context_is_valid(self) -> None:
        rows = [stage_event("quiet-wake", 1, 0, "n2", onset=True)]
        rows.extend(
            stage_event(
                "quiet-wake",
                index + 2,
                (index + 1) * 30,
                "wake",
                onset=True,
            )
            for index in range(30)
        )

        findings = find_suspected_wake_lock_ins(
            rows,
            estimator_version=ESTIMATOR,
        )

        self.assertEqual(findings, [])

    def test_latest_event_wins_for_a_replayed_epoch(self) -> None:
        rows = wake_lock_fixture("deduplicated", 20)
        rows.append(
            stage_event(
                "deduplicated",
                999,
                300,
                "n2",
                onset=True,
            )
        )

        findings = find_suspected_wake_lock_ins(
            rows,
            estimator_version=ESTIMATOR,
        )

        self.assertEqual(findings, [])


if __name__ == "__main__":
    unittest.main()
