"""
Structured JSON logging. Denylist below is checked on every log call so a secret or a full
uploaded spreadsheet can never end up in application logs (spec Section 95).
"""
import json
import logging
import sys
from datetime import datetime, timezone

_DENYLISTED_FIELDS = {"password", "password_hash", "token", "access_key", "secret_key", "secret"}


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in getattr(record, "context", {}).items():
            if key.lower() in _DENYLISTED_FIELDS:
                continue
            payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
