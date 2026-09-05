#!/usr/bin/env python3
"""Compare two read-only ZEEP historical replay summary manifests."""

from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
from typing import Any, Mapping


STAGES = ("wake", "n1", "n2", "n3", "rem")
MAINTENANCE_TOOL_NAME = "compare_sleep_history_replay.py"


def private_write(path: Path, text: str) -> None:
    """Write a review artifact readable only by its owner."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", closefd=False) as handle:
            handle.write(text)
    finally:
        os.close(descriptor)


def load_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("sessions"), list):
        raise ValueError(f"invalid replay summary: {path}")
    return payload


def session_index(manifest: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item["session_id"]): item
        for item in manifest.get("sessions") or []
        if isinstance(item, dict) and item.get("session_id")
    }


def stage_counts(item: Mapping[str, Any] | None) -> dict[str, int]:
    replay = (item or {}).get("replay") or {}
    counts = replay.get("counts") or {}
    return {stage: int(counts.get(stage) or 0) for stage in STAGES}


def score(item: Mapping[str, Any] | None, key: str) -> int | float | None:
    value = (item or {}).get(key)
    return value if isinstance(value, (int, float)) else None


def display(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.1f}"
    return str(value)


def stage_text(counts: Mapping[str, int]) -> str:
    populated = [
        f"{stage.upper()} {int(counts.get(stage) or 0)}"
        for stage in STAGES
        if int(counts.get(stage) or 0) > 0
    ]
    return (
        ", ".join(populated)
        if populated
        else "ไม่มี State ที่ยืนยัน"
    )


def build_comparison(
    old_manifest: Mapping[str, Any],
    new_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    old_by_id = session_index(old_manifest)
    new_by_id = session_index(new_manifest)
    common_ids = set(old_by_id) & set(new_by_id)
    new_only_ids = set(new_by_id) - set(old_by_id)
    removed_ids = set(old_by_id) - set(new_by_id)
    old_allowed = set(
        (old_manifest.get("acceptance") or {}).get(
            "wellness_derived_promotion_eligible_session_ids"
        ) or []
    )
    new_allowed = set(
        (new_manifest.get("acceptance") or {}).get(
            "wellness_derived_promotion_eligible_session_ids"
        ) or []
    )
    rows = []
    for session_id, new_item in new_by_id.items():
        old_item = old_by_id.get(session_id, {})
        old_counts = stage_counts(old_item)
        new_counts = stage_counts(new_item)
        old_shadow = score(old_item, "shadow_score")
        new_shadow = score(new_item, "shadow_score")
        rows.append({
            "session_id": session_id,
            "email": new_item.get("email"),
            "start_time": new_item.get("start_time"),
            "duration_minutes": new_item.get("duration_minutes"),
            "mode": (new_item.get("shadow_mode") or {}).get("label"),
            "score_title": (new_item.get("shadow_mode") or {}).get("score_title"),
            "quality_tier_old": (old_item.get("quality") or {}).get("tier"),
            "quality_tier_new": (new_item.get("quality") or {}).get("tier"),
            "stored_score_before": score(new_item, "old_score"),
            "previous_shadow_score": old_shadow,
            "new_shadow_score": new_shadow,
            "new_engineering_shadow_score": new_item.get(
                "shadow_engineering_score"
            ),
            "new_score_releasable": bool(
                new_item.get("shadow_score_releasable")
            ),
            "shadow_score_delta": (
                new_shadow - old_shadow
                if new_shadow is not None and old_shadow is not None else None
            ),
            "old_stage_counts": old_counts,
            "new_stage_counts": new_counts,
            "stage_counts_changed": old_counts != new_counts,
            "previously_promotion_eligible": session_id in old_allowed,
            "now_promotion_eligible": session_id in new_allowed,
            "old_review_flags": old_item.get("manual_review_flags") or [],
            "new_review_warnings": new_item.get("review_warnings") or [],
            "new_promotion_blockers": new_item.get("promotion_blockers") or [],
            "operational_status_counts": (
                new_item.get("shadow_operational_status_counts") or {}
            ),
            "confidence_percent": (
                new_item.get("shadow_confidence_percent") or {}
            ),
            "confirmed_coverage_percent": (
                (new_item.get("replay") or {}).get("confirmed_coverage_percent")
            ),
            "timeline_paired_hr_rr_percent": (
                (new_item.get("quality") or {}).get(
                    "timeline_paired_hr_rr_percent"
                )
            ),
            "raw_paired_hr_rr_percent": (
                (new_item.get("quality") or {}).get("raw_paired_hr_rr_percent")
            ),
        })
    warning_counts = Counter(
        warning
        for row in rows
        for warning in row["new_review_warnings"]
    )
    blocker_counts = Counter(
        blocker
        for row in rows
        for blocker in row["new_promotion_blockers"]
    )
    operational_status_counts = Counter()
    old_stage_totals = Counter()
    new_stage_totals = Counter()
    common_old_stage_totals = Counter()
    common_new_stage_totals = Counter()
    new_only_stage_totals = Counter()
    fit_fusion_totals = Counter()
    fit_overall_winner_counts = Counter()
    fit_eligible_winner_counts = Counter()
    for row in rows:
        operational_status_counts.update(row["operational_status_counts"])
        old_stage_totals.update(row["old_stage_counts"])
        new_stage_totals.update(row["new_stage_counts"])
        if row["session_id"] in common_ids:
            common_old_stage_totals.update(row["old_stage_counts"])
            common_new_stage_totals.update(row["new_stage_counts"])
        elif row["session_id"] in new_only_ids:
            new_only_stage_totals.update(row["new_stage_counts"])
        replay = (new_by_id.get(row["session_id"]) or {}).get("replay") or {}
        fusion = replay.get("hr_rr_fit_fusion") or {}
        fit_fusion_totals["evidence_epochs"] += int(
            fusion.get("evidence_epochs") or 0
        )
        fit_fusion_totals["changed_evidence_winner_count"] += int(
            fusion.get("changed_evidence_winner_count") or 0
        )
        fit_fusion_totals["agreed_with_confirmed_state_count"] += int(
            fusion.get("agreed_with_confirmed_state_count") or 0
        )
        fit_fusion_totals["overall_fit_winner_gate_closed_count"] += int(
            fusion.get("overall_fit_winner_gate_closed_count") or 0
        )
        fit_overall_winner_counts.update(
            fusion.get("overall_fit_winner_counts") or {}
        )
        fit_eligible_winner_counts.update(
            fusion.get("eligible_fit_winner_counts") or {}
        )
    evaluation_epochs = (
        sum(new_stage_totals.values())
        + sum(operational_status_counts.values())
    )
    confirmed_coverage_percent = (
        round(sum(new_stage_totals.values()) * 100.0 / evaluation_epochs, 1)
        if evaluation_epochs else 0.0
    )
    return {
        "scope": {
            "sessions": len(rows),
            "previous_sessions": len(old_by_id),
            "common_sessions": len(common_ids),
            "new_sessions": len(new_only_ids),
            "removed_sessions": len(removed_ids),
            "unique_emails": len({row["email"] for row in rows}),
            "raw_files_modified": False,
            "production_database_modified": False,
        },
        "policy_change": {
            "previous_promotion_eligible_sessions": len(old_allowed),
            "new_promotion_eligible_sessions": len(new_allowed),
            "newly_eligible_sessions": sorted(new_allowed - old_allowed),
            "quality_tier_is_advisory": True,
            "review_warnings_block_promotion": False,
            "promotion_accepts_state_evidence_or_operational_status_rows": True,
        },
        "result_change": {
            "sessions_with_stage_count_changes": sum(
                row["stage_counts_changed"] for row in rows
            ),
            "common_sessions_with_stage_count_changes": sum(
                row["stage_counts_changed"]
                and row["session_id"] in common_ids
                for row in rows
            ),
            "sessions_with_comparable_score_changes": sum(
                row["shadow_score_delta"] not in (None, 0) for row in rows
            ),
            "sessions_with_comparable_scores": sum(
                row["shadow_score_delta"] is not None for row in rows
            ),
            "sessions_with_newly_available_replay": sum(
                not any(row["old_stage_counts"].values())
                and any(row["new_stage_counts"].values())
                for row in rows
            ),
            "scores_releasable": sum(
                row["new_score_releasable"] for row in rows
            ),
            "scores_withheld": sum(
                not row["new_score_releasable"] for row in rows
            ),
            "review_warning_counts": dict(warning_counts),
            "promotion_blocker_counts": dict(blocker_counts),
            "operational_status_counts": dict(operational_status_counts),
            "old_stage_counts": dict(old_stage_totals),
            "new_stage_counts": dict(new_stage_totals),
            "stage_count_delta": {
                stage: new_stage_totals[stage] - old_stage_totals[stage]
                for stage in STAGES
            },
            "common_cohort_old_stage_counts": dict(
                common_old_stage_totals
            ),
            "common_cohort_new_stage_counts": dict(
                common_new_stage_totals
            ),
            "common_cohort_stage_count_delta": {
                stage: (
                    common_new_stage_totals[stage]
                    - common_old_stage_totals[stage]
                )
                for stage in STAGES
            },
            "new_session_stage_counts": dict(new_only_stage_totals),
            "hr_rr_fit_fusion": {
                **dict(fit_fusion_totals),
                "overall_fit_winner_counts": dict(
                    fit_overall_winner_counts
                ),
                "eligible_fit_winner_counts": dict(
                    fit_eligible_winner_counts
                ),
                "fit_can_bypass_state_gate": False,
                "fit_can_bypass_confirmation": False,
            },
            "evaluation_epoch_count": evaluation_epochs,
            "confirmed_stage_coverage_percent": confirmed_coverage_percent,
            "mode_counts": dict(Counter(
                row["mode"] or "unknown" for row in rows
            )),
            "quality_tier_counts": dict(Counter(
                row["quality_tier_new"] or "unknown" for row in rows
            )),
        },
        "sessions": rows,
    }


def markdown_report(comparison: Mapping[str, Any]) -> str:
    scope = comparison["scope"]
    policy = comparison["policy_change"]
    result = comparison["result_change"]
    lines = [
        "# ZEEP Historical Replay — Policy Review",
        "",
        "> Dry Run เท่านั้น · ไม่แก้ Production DB · "
        "ไม่แก้ Raw BCG/Timeline",
        "",
        "## ภาพรวม",
        "",
        f"- Session: {scope['sessions']} · "
        f"ผู้ใช้: {scope['unique_emails']} บัญชี",
        "- สิทธิ์เขียน Derived เดิม: "
        f"{policy['previous_promotion_eligible_sessions']} Session",
        "- สิทธิ์เขียน Derived ตามนโยบายใหม่: "
        f"{policy['new_promotion_eligible_sessions']} Session",
        "- Session ที่ Stage count เปลี่ยนจาก Dry Run เดิม: "
        f"{result['sessions_with_stage_count_changes']}",
        "- Session ที่คะแนน Shadow เปลี่ยน "
        "(เมื่อมีค่าทั้งสองรุ่น): "
        f"{result['sessions_with_comparable_score_changes']}",
        "- Session ที่ได้ Replay เพิ่มใหม่: "
        f"{result['sessions_with_newly_available_replay']}",
        "- คะแนนเผยแพร่ได้: "
        f"{result['scores_releasable']} · "
        "ระงับคะแนนเพราะ coverage: "
        f"{result['scores_withheld']}",
        "- Coverage ของ State ที่ยืนยันรวม: "
        f"{result['confirmed_stage_coverage_percent']}% จาก "
        f"{result['evaluation_epoch_count']} Epoch",
        "- Session ที่เทียบโมเดลได้ทั้งสองรุ่น: "
        f"{scope['common_sessions']} · Session ใหม่: "
        f"{scope['new_sessions']}",
        "",
        "## State ของ Cohort เดียวกันก่อนและหลัง",
        "",
        "| State | เดิม | ใหม่ | ผลต่าง |",
        "|---|---:|---:|---:|",
        *[
            f"| {stage.upper()} | "
            f"{result['common_cohort_old_stage_counts'].get(stage, 0)} | "
            f"{result['common_cohort_new_stage_counts'].get(stage, 0)} | "
            f"{result['common_cohort_stage_count_delta'].get(stage, 0):+d} |"
            for stage in STAGES
        ],
        "",
        "## ผลของ HR/RR Fit Fusion",
        "",
        "- Epoch ที่มีหลักฐาน: "
        f"{result['hr_rr_fit_fusion'].get('evidence_epochs', 0)}",
        "- Fit ทำให้ Evidence winner เปลี่ยน: "
        f"{result['hr_rr_fit_fusion'].get('changed_evidence_winner_count', 0)}",
        "- Fit winner ตรงกับ State ที่ยืนยันก่อนหน้า: "
        f"{result['hr_rr_fit_fusion'].get('agreed_with_confirmed_state_count', 0)}",
        "- Fit winner ถูก Gate ปิดและไม่อนุญาตให้แข่งขัน: "
        f"{result['hr_rr_fit_fusion'].get('overall_fit_winner_gate_closed_count', 0)}",
        "",
        "สถานะที่ไม่ใช่ Sleep Stage: "
        + ", ".join(
            f"{key.upper()} {value}"
            for key, value in result["operational_status_counts"].items()
        ),
        "",
        "## ค่าเดิมเทียบค่าใหม่",
        "",
        "| Email | Mode | นาที | Tier เดิม→ใหม่ | คะแนน DB→ใหม่ | "
        "Engineering | เขียน State เดิม→ใหม่ | Coverage | "
        "Confidence H/M/L | State ใหม่ |",
        "|---|---|---:|---|---:|---:|---|---:|---|---|",
    ]
    for row in comparison["sessions"]:
        old_allowed = (
            "ได้" if row["previously_promotion_eligible"] else "ไม่ได้"
        )
        new_allowed = (
            "ได้" if row["now_promotion_eligible"] else "ไม่ได้"
        )
        confidence = row["confidence_percent"]
        confidence_text = "/".join(
            display(confidence.get(level, 0))
            for level in ("high", "medium", "low")
        )
        lines.append(
            f"| {row['email']} | {row['mode']} | "
            f"{display(row['duration_minutes'])} | "
            f"{display(row['quality_tier_old'])}→"
            f"{display(row['quality_tier_new'])} | "
            f"{display(row['stored_score_before'])}→"
            f"{display(row['new_shadow_score'])} | "
            f"{display(row['new_engineering_shadow_score'])} | "
            f"{old_allowed}→{new_allowed} | "
            f"{display(row['confirmed_coverage_percent'])}% | "
            f"{confidence_text} | "
            f"{stage_text(row['new_stage_counts'])} |"
        )
    lines.extend([
        "",
        "## หลักการอนุมัติใหม่",
        "",
        "- Tier เป็นตัวชี้วัดความครบถ้วนระดับ Session "
        "สำหรับ Admin QA เท่านั้น",
        "- คำเตือนสัดส่วน/coverage/คะแนนไม่พร้อม "
        "ไม่ขวาง State ที่มีหลักฐาน",
        "- ขวางเฉพาะฐานข้อมูล/Raw เสีย, Session ยังไม่จบ "
        "หรือผลละเมิด invariant",
        "- ช่วงข้อมูลขาดไม่ถูกสร้างเป็น Sleep State "
        "และไม่ถูกนับในคะแนน",
        "- ผลยังเป็น ZEEP Wellness estimate "
        "ไม่ใช่ AASM/PSG diagnosis",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old", required=True, type=Path)
    parser.add_argument("--new", required=True, type=Path)
    parser.add_argument("--json-output", required=True, type=Path)
    parser.add_argument("--markdown-output", required=True, type=Path)
    args = parser.parse_args()

    comparison = build_comparison(
        load_manifest(args.old),
        load_manifest(args.new),
    )
    private_write(
        args.json_output,
        json.dumps(comparison, ensure_ascii=False, indent=2),
    )
    private_write(args.markdown_output, markdown_report(comparison))
    public_policy_summary = {
        key: value
        for key, value in comparison["policy_change"].items()
        if key != "newly_eligible_sessions"
    }
    print(json.dumps({
        "json_output": str(args.json_output),
        "markdown_output": str(args.markdown_output),
        **comparison["scope"],
        **public_policy_summary,
        **comparison["result_change"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
