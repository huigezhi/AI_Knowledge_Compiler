"""配置校验、错误体系与日志脱敏。"""

from __future__ import annotations

import pytest

from akc.errors import (
    AppError,
    ErrorCode,
    NotFoundError,
    ValidationFailedError,
    error_payload,
)
from akc.logging_setup import _is_sensitive


def test_settings_rejects_bad_log_level(monkeypatch: pytest.MonkeyPatch) -> None:
    from akc.config import Settings

    monkeypatch.setenv("AKC_LOG_LEVEL", "VERBOSE")
    with pytest.raises(Exception):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_settings_requires_key_and_model_when_enabled() -> None:
    from akc.config import Settings

    with pytest.raises(Exception):
        Settings(claude_enabled=True, claude_api_key=None, claude_model=None, _env_file=None)  # type: ignore[call-arg]


def test_settings_rejects_non_loopback_in_production() -> None:
    from akc.config import Settings

    with pytest.raises(Exception):
        Settings(env="production", host="0.0.0.0", _env_file=None)  # type: ignore[call-arg]


def test_settings_parses_csv_backoff() -> None:
    from akc.config import Settings

    settings = Settings(job_backoff_seconds="2,5,15", _env_file=None)  # type: ignore[call-arg]
    assert settings.job_backoff_seconds == [2, 5, 15]


def test_auth_token_persisted(tmp_path) -> None:  # noqa: ANN001
    from akc.config import Settings

    settings = Settings(data_dir=tmp_path, _env_file=None)  # type: ignore[call-arg]
    token = settings.ensure_auth_token()
    assert token
    assert (tmp_path / "auth_token").exists()
    assert settings.ensure_auth_token() == token


def test_error_payload_shape() -> None:
    payload = AppError("boom", code=ErrorCode.CONFLICT, retryable=True).to_payload("rid-1")
    assert payload == {
        "error": {
            "code": "CONFLICT",
            "message": "boom",
            "retryable": True,
            "details": {},
        },
        "request_id": "rid-1",
    }


def test_specific_errors_default_status() -> None:
    assert NotFoundError("x").http_status == 404
    assert ValidationFailedError("x").http_status == 422


def test_error_payload_helper_uses_request_id() -> None:
    payload = error_payload(ErrorCode.INTERNAL, "m", retryable=False)
    assert payload["error"]["code"] == "INTERNAL"
    assert "request_id" in payload


def test_sensitive_keys_are_redacted() -> None:
    assert _is_sensitive("AKC_CLAUDE_API_KEY")
    assert _is_sensitive("authorization")
    assert not _is_sensitive("conversation_id")


def test_migrations_are_reversible() -> None:
    from akc.db import get_engine
    from akc.db.migrate import applied_versions, available_versions, downgrade, upgrade

    engine = get_engine()
    assert set(available_versions()) >= {"001", "002"}
    assert applied_versions(engine) == ["001", "002"]

    rolled = downgrade(engine, "0")
    assert set(rolled) == {"001", "002"}
    assert applied_versions(engine) == []

    upgrade(engine)
    assert applied_versions(engine) == ["001", "002"]
