"""Versioned Smart Ear capability and validation contracts."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

CONTRACT_VERSION = "zeep-acoustic-shadow-v0.2"
LIVE_SCHEMA = "zeep.acoustic.shadow.live"
LIVE_SCHEMA_VERSION = "0.1"
VALIDATION_PROTOCOL_ID = "ZEEP-ACOUSTIC-SHADOW-001"


_CANDIDATE_LABEL_GROUPS: tuple[dict[str, Any], ...] = (
    {
        "key": "signal_shape",
        "display_name": "รูปแบบสัญญาณ",
        "labels": (
            {
                "key": "quiet_steady",
                "display_name": "เงียบและคงที่",
                "proof_status": "planned",
            },
            {
                "key": "steady",
                "display_name": "เสียงต่อเนื่อง",
                "proof_status": "planned",
            },
            {
                "key": "tonal",
                "display_name": "เสียงโทนเด่น",
                "proof_status": "planned",
            },
            {
                "key": "impulsive",
                "display_name": "เสียงกระชาก",
                "proof_status": "planned",
            },
            {
                "key": "intermittent",
                "display_name": "เสียงเป็นช่วง",
                "proof_status": "planned",
            },
            {
                "key": "modulated",
                "display_name": "เสียงขึ้นลงเป็นจังหวะ",
                "proof_status": "planned",
            },
        ),
    },
    {
        "key": "equipment_or_context",
        "display_name": "แหล่งเสียงที่เป็นไปได้",
        "labels": (
            {
                "key": "airflow_like",
                "display_name": "คล้ายเสียงลม",
                "proof_status": "planned",
            },
            {
                "key": "compressor_transition_like",
                "display_name": "คล้ายคอมเพรสเซอร์เปลี่ยนสถานะ",
                "proof_status": "planned",
            },
            {
                "key": "ventilation_or_purifier_like",
                "display_name": "คล้ายระบบระบายหรือกรองอากาศ",
                "proof_status": "planned",
            },
            {
                "key": "zeep_audio_likely",
                "display_name": "น่าจะมาจากเสียงที่ ZEEP เล่น",
                "proof_status": "planned",
            },
            {
                "key": "door_or_mechanical_like",
                "display_name": "คล้ายประตูหรือกลไก",
                "proof_status": "planned",
            },
            {
                "key": "movement_or_bedding_like",
                "display_name": "คล้ายการขยับหรือเครื่องนอน",
                "proof_status": "planned",
            },
            {
                "key": "other_or_unresolved",
                "display_name": "แหล่งอื่นหรือยังแยกไม่ได้",
                "proof_status": "planned",
            },
        ),
    },
    {
        "key": "purpose_gated_human_sound",
        "display_name": "เสียงจากมนุษย์ · ต้องมี Consent",
        "labels": (
            {
                "key": "speech_like",
                "display_name": "คล้ายเสียงพูด · ไม่ถอดคำ",
                "proof_status": "planned",
                "consent_required": True,
                "medical_claim": False,
            },
            {
                "key": "snore_like",
                "display_name": "คล้ายรูปแบบเสียงกรน · ไม่ใช่การวินิจฉัย",
                "proof_status": "planned",
                "consent_required": True,
                "medical_claim": False,
            },
            {
                "key": "cough_like",
                "display_name": "คล้ายเสียงไอ · ไม่ใช่การประเมินโรค",
                "proof_status": "planned",
                "consent_required": True,
                "medical_claim": False,
            },
            {
                "key": "breathing_pattern_like",
                "display_name": "คล้ายรูปแบบการหายใจ · เพื่อวิจัยเท่านั้น",
                "proof_status": "planned",
                "consent_required": True,
                "medical_claim": False,
            },
        ),
    },
)

_REQUIRED_FEATURES = (
    "feature_coverage",
    "clip_ratio",
    "crest_factor",
    "transient_count",
    "spectral_bands",
    "spectral_centroid",
    "spectral_flatness",
    "periodicity",
    "modulation_index",
)

_VALIDATION_PHASES: tuple[dict[str, Any], ...] = (
    {
        "phase": "P0",
        "title": "ยืนยัน Firmware และเส้นทาง dBA",
        "status": "in_progress",
        "exit_gate": "ระบุ source/version/checksum และพิสูจน์ direct sound_dba",
    },
    {
        "phase": "P1",
        "title": "เพิ่ม DSP Feature ที่มี Version",
        "status": "planned",
        "exit_gate": "ผ่าน golden vectors, coverage, clipping และ fail-soft tests",
    },
    {
        "phase": "P2",
        "title": "เก็บ Controlled Dataset",
        "status": "planned",
        "exit_gate": "อนุมัติ protocol, consent, label audit และ test split",
    },
    {
        "phase": "P3",
        "title": "Shadow Classifier",
        "status": "planned",
        "exit_gate": "รายงาน precision/recall/F1, false alerts และ unknown rate ราย class",
    },
    {
        "phase": "P4",
        "title": "Admin Pilot Monitor",
        "status": "planned",
        "exit_gate": "ผ่าน Privacy, Product, Safety และ restart/gap regression",
    },
    {
        "phase": "P5",
        "title": "Session Aggregate สำหรับ Admin",
        "status": "planned",
        "exit_gate": "ยืนยันว่าไม่เปลี่ยน Sleep State, Score หรือ Control",
    },
    {
        "phase": "P6",
        "title": "ข้อความสรุปสำหรับผู้ใช้",
        "status": "planned",
        "exit_gate": "เปิดเฉพาะ label/copy ที่ผ่านหลักฐานและ Positive Allowlist",
    },
)


def acoustic_contract_snapshot() -> dict[str, Any]:
    """Return the immutable Admin contract as a detached JSON-safe mapping."""
    contract = {
        "contract_version": CONTRACT_VERSION,
        "live_schema": LIVE_SCHEMA,
        "live_schema_version": LIVE_SCHEMA_VERSION,
        "phase": "P0.6",
        "mode": "admin_shadow_level_only",
        "current_capability": {
            "sound_level": True,
            "packet_energy_aggregation": True,
            "session_level_timeline": True,
            "level_pattern_events": True,
            "dsp_feature_telemetry": False,
            "acoustic_classification": False,
        },
        "classification_states": (
            "not_evaluated",
            "insufficient_input",
            "unknown",
            "mixed",
            "provisional",
            "confirmed",
        ),
        "confidence_bands": ("unavailable", "low", "medium", "high"),
        "candidate_label_groups": _CANDIDATE_LABEL_GROUPS,
        "required_features": _REQUIRED_FEATURES,
        "validation": {
            "protocol_id": VALIDATION_PROTOCOL_ID,
            "required_gates": ("G1", "G3"),
            "phases": _VALIDATION_PHASES,
            "release_rule": (
                "Candidate labels remain Admin-only planned capabilities until "
                "their class-specific evidence and required gates are approved."
            ),
        },
        "privacy": {
            "raw_audio_transmitted": False,
            "raw_audio_retained": False,
            "speech_content_processed": False,
            "speaker_identity_processed": False,
        },
        "impact": {
            "sleep_state": False,
            "sleep_score": False,
            "recovery_score": False,
            "control": False,
        },
        "clinical_validated": False,
        "automatic_actuation": False,
    }
    return deepcopy(contract)
