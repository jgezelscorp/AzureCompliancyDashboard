"""Structured JSON logging with secret and token redaction."""

import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

REDACTED = "[REDACTED]"

_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}(?:\.[A-Za-z0-9_-]*)?"),
    re.compile(
        r"(?i)(password|passwd|token|pwd|secret|client_secret|access_token|refresh_token|id_token"
        r"|assertion|sig|sas|api[_-]?key|authorization)(\"?\s*[:=]\s*\"?)[^\s\"'&,;]+"
    ),
    re.compile(r"(?i)(postgres(?:ql)?(?:\+\w+)?://[^:/@\s]+:)[^@\s]+(@)"),
)

_SENSITIVE_KEYS = re.compile(
    r"(?i)password|secret|token|authorization|api[_-]?key|credential|assertion|cookie"
)


def redact(text: str) -> str:
    text = _PATTERNS[0].sub(f"Bearer {REDACTED}", text)
    text = _PATTERNS[1].sub(REDACTED, text)
    text = _PATTERNS[2].sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}", text)
    return _PATTERNS[3].sub(lambda m: f"{m.group(1)}{REDACTED}{m.group(2)}", text)


def redact_value(key: str, value: Any) -> Any:
    if _SENSITIVE_KEYS.search(key):
        return REDACTED
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {str(k): redact_value(str(k), v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [redact_value(key, v) for v in value]
    return value


_STANDARD = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD and not key.startswith("_"):
                payload[key] = redact_value(key, value)
        if record.exc_info:
            payload["exception"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
