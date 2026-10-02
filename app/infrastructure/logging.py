"""Structured logging that intentionally excludes message bodies and secrets."""

import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

from app.config import Settings

_SENSITIVE_VALUE = re.compile(
    r"(?i)\b(password|passwd|token|api[_-]?key|secret|authorization)\b\s*[:=]\s*([^\s,;]+)"
)
_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)


def redact(value: object) -> str:
    """Mask common credentials and email addresses in an arbitrary log value."""

    text = str(value)
    text = _SENSITIVE_VALUE.sub(lambda match: f"{match.group(1)}=[REDACTED]", text)
    return _EMAIL.sub("[EMAIL_REDACTED]", text)


class SafeJsonFormatter(logging.Formatter):
    """Small JSON formatter with an explicit allowlist of fields."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "module": record.name,
            "event": redact(record.getMessage()),
        }
        for field in ("request_id", "entity_id", "duration_ms", "safe_error_code"):
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = redact(value)
        if record.exc_info:
            exception_type = record.exc_info[0]
            if exception_type is not None:
                payload["exception_type"] = exception_type.__name__
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_logging(settings: Settings) -> None:
    """Configure the root logger once for API and CLI processes."""

    handler = logging.StreamHandler()
    handler.setFormatter(SafeJsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(settings.log_level.upper())
