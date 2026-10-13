"""JSON log formatter. The library never configures logging; the application attaches this.

handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())
logging.getLogger("apiframework").addHandler(handler)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

# Fields the library passes via ``extra=``. Only these are copied onto the JSON record.
EXTRA_FIELDS = (
    "api",
    "method",
    "url_template",
    "status",
    "latency_ms",
    "attempts",
    "error",
    "attempt",
    "delay_s",
    "reason",
    "waited_s",
    "exhausted",
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in EXTRA_FIELDS:
            if hasattr(record, field):
                payload[field] = getattr(record, field)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)
