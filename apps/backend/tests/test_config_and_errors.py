"""配置校验、错误体系与日志脱敏。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

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

    # 显式清空令牌，验证「未配置时生成并持久化」这条路径（测试环境注入了固定令牌）
    settings = Settings(data_dir=tmp_path, auth_token=None, _env_file=None)  # type: ignore[call-arg]
    token = settings.ensure_auth_token()
    assert token
    assert (tmp_path / "auth_token").exists()
    assert settings.ensure_auth_token() == token


def test_empty_env_values_are_unset(tmp_path) -> None:  # noqa: ANN001
    """`.env` 里写 `AKC_VAULT_PATH=` 必须等同「未配置」。

    回归：pydantic 会把空串解析成 Path('.')（真值），导致「未配置 Vault」的校验
    被绕过、同步把文件写进当前工作目录。
    """
    from akc.config import Settings

    settings = Settings(
        data_dir=tmp_path,
        vault_path="",
        claude_model="",
        claude_api_key="",
        _env_file=None,  # type: ignore[call-arg]
    )
    assert settings.vault_path is None
    assert settings.claude_model is None
    assert settings.claude_api_key is None


def test_deepseek_provider_preset() -> None:
    """provider=deepseek 时自动使用其 Anthropic 兼容端点（不需要手填 base_url）。"""
    from akc.config import Settings

    settings = Settings(
        llm_enabled=True,
        llm_provider="deepseek",
        llm_model="some-deepseek-model",
        llm_api_key="sk-test",
        _env_file=None,  # type: ignore[call-arg]
    )
    assert settings.llm_base_url == "https://api.deepseek.com/anthropic"
    # 旧字段被镜像，旧代码/旧脚本继续可用
    assert settings.claude_base_url == settings.llm_base_url
    assert settings.claude_model == "some-deepseek-model"


def test_claude_env_names_still_work() -> None:
    """旧配置名 AKC_CLAUDE_* 必须继续生效（向后兼容，不能因为改名把用户配置废掉）。"""
    from akc.config import Settings

    settings = Settings(
        claude_enabled=True,
        claude_model="legacy-model",
        claude_api_key="legacy-key",
        claude_base_url="https://api.anthropic.com",
        _env_file=None,  # type: ignore[call-arg]
    )
    assert settings.llm_enabled is True
    assert settings.llm_model == "legacy-model"
    assert settings.llm_api_key == "legacy-key"
    assert settings.llm_base_url == "https://api.anthropic.com"


def test_custom_provider_requires_base_url_when_enabled() -> None:
    """custom provider 没有预设端点：未启用时回落官方地址，启用时必须显式给 base_url。"""
    from akc.config import Settings

    # 未启用：回落，不至于一启动就崩
    disabled = Settings(llm_provider="custom", _env_file=None)  # type: ignore[call-arg]
    assert disabled.llm_base_url == "https://api.anthropic.com"

    # 启用但没给地址：直接报错，否则请求会静默打到 Anthropic
    with pytest.raises(ValidationError):
        Settings(
            llm_enabled=True,
            llm_provider="custom",
            llm_model="qwen",
            llm_api_key="k",
            _env_file=None,  # type: ignore[call-arg]
        )

    # 给了地址：正常
    ok = Settings(
        llm_enabled=True,
        llm_provider="custom",
        llm_base_url="http://localhost:11434/",
        llm_model="qwen",
        llm_api_key="k",
        _env_file=None,  # type: ignore[call-arg]
    )
    assert ok.llm_base_url == "http://localhost:11434"  # 结尾斜杠被去掉


def test_llm_provider_is_normalized_and_validated() -> None:
    """拼错 provider 必须报错，而不是静默回落到 Anthropic 默认地址。

    没有这层校验时，`DeepSeek`（大小写）或 `deep-seek` 都查不到预设，
    请求会悄悄发到 api.anthropic.com —— 表现为「配了 DeepSeek 却一直 401」。
    """
    from akc.config import Settings

    upper = Settings(
        llm_enabled=True,
        llm_provider="DeepSeek",
        llm_model="m",
        llm_api_key="k",
        _env_file=None,  # type: ignore[call-arg]
    )
    assert upper.llm_provider == "deepseek"
    assert upper.llm_base_url == "https://api.deepseek.com/anthropic"

    with pytest.raises(ValidationError):
        Settings(llm_provider="deep-seek", _env_file=None)  # type: ignore[call-arg]


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
