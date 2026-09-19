"""结构化日志 + request_id 贯穿。

规则：
* 日志为单行 JSON，便于本地排障与后续接入采集；
* 每条日志自动携带 ``request_id``（若处于请求上下文中）；
* **禁止**记录 API Key、Cookie、Authorization 头与完整外发 payload。
"""

from __future__ import annotations

import contextvars
import json
import logging
import sys
import time
import uuid
from typing import Any

_REQUEST_ID: contextvars.ContextVar[str] = contextvars.ContextVar("akc_request_id", default="-")


def get_request_id() -> str:
    return _REQUEST_ID.get()


def set_request_id(value: str | None = None) -> str:
    rid = value or uuid.uuid4().hex
    _REQUEST_ID.set(rid)
    return rid


class _JsonFormatter(logging.Formatter):
    """单行 JSON 格式化器。"""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
            "request_id": getattr(record, "request_id", get_request_id()),
        }
        for key, value in getattr(record, "extra_fields", {}).items():
            payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


class _TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return (
            f"{time.strftime('%H:%M:%S', time.localtime(record.created))} "
            f"{record.levelname:<7} [{getattr(record, 'request_id', get_request_id())}] "
            f"{record.getMessage()}"
        )


def configure_logging(level: str = "INFO", *, json_logs: bool = True) -> None:
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(_JsonFormatter() if json_logs else _TextFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
    # 第三方库噪声降级
    for noisy in ("httpx", "httpcore", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str = "akc") -> logging.Logger:
    return logging.getLogger(name)


def log_event(event: str, **fields: Any) -> None:
    """便捷的结构化事件日志。fields 中的敏感键会自动脱敏。"""
    safe = {k: ("***redacted***" if _is_sensitive(k) else v) for k, v in fields.items()}
    get_logger().info(event, extra={"extra_fields": safe})


_SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "token",
    "access_token",
    "refresh_token",
    "secret",
    "password",
}


def _is_sensitive(key: str) -> bool:
    lowered = key.lower()
    return any(token in lowered for token in _SENSITIVE_KEYS)
