"""Refresh report explanations on read, without rewriting stored results."""

from collections.abc import Mapping
from typing import Any

from sessions.result_contract import build_result_contract


def refresh_report_copy(session: Mapping[str, Any]) -> dict[str, Any]:
    """Use the same current explanation as the public usage API.

    Only Restore Summary is replaced in the response. Scores, findings,
    timelines and the persisted report remain unchanged.
    """
    report = session.get("session_report")
    if not isinstance(report, Mapping):
        return {}
    result = build_result_contract(session)
    return {**report, "restore_summary": result["restore_summary"]}
