from app.modules.feedback.service import summarize_feedback_payloads


def test_feedback_summary_waits_for_five_explicit_signals() -> None:
    summary = summarize_feedback_payloads(
        [
            {"decision": "good_match", "reason": "good_fit"},
            {"decision": "not_match", "reason": "weak_fit"},
            {"decision": "needs_edit", "reason": "too_generic"},
            {"decision": "good", "reason": "good_fit"},
        ]
    )

    assert summary["total"] == 4
    assert summary["remaining"] == 1
    assert summary["ready_for_calibration"] is False
    assert summary["top_reasons"][0] == ("good_fit", 2)


def test_feedback_summary_only_proposes_calibration_after_threshold() -> None:
    summary = summarize_feedback_payloads(
        [{"decision": "good", "reason": "good_personalization"}] * 5
    )

    assert summary["total"] == 5
    assert summary["remaining"] == 0
    assert summary["ready_for_calibration"] is True
