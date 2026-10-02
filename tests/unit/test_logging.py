import json
import logging

from app.infrastructure.logging import SafeJsonFormatter, redact


def test_redact_masks_credentials_and_email() -> None:
    value = redact("password=hunter2 contact=synthetic.person@example.test token:abc123")

    assert "hunter2" not in value
    assert "synthetic.person@example.test" not in value
    assert "abc123" not in value
    assert value.count("[REDACTED]") == 2
    assert "[EMAIL_REDACTED]" in value


def test_json_formatter_uses_allowlisted_fields() -> None:
    record = logging.LogRecord(
        name="app.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="safe_event",
        args=(),
        exc_info=None,
    )
    record.request_id = "synthetic-request"
    record.untrusted_payload = "must-not-appear"

    payload = json.loads(SafeJsonFormatter().format(record))

    assert payload["event"] == "safe_event"
    assert payload["request_id"] == "synthetic-request"
    assert "untrusted_payload" not in payload
    assert "must-not-appear" not in payload.values()
