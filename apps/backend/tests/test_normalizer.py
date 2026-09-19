"""归一化与 Schema 校验。"""

from __future__ import annotations

import pytest

from akc.errors import ValidationFailedError
from akc.services.hasher import hash_message
from akc.services.normalizer import conversation_plain_text, digest_text, normalize_conversation


def _conversation(**overrides: object) -> dict:
    base = {
        "id": "conv_1",
        "provider": "DeepSeek",
        "provider_conversation_id": "ext-1",
        "title": "SQL 优化",
        "messages": [
            {"id": "m1", "role": "user", "sequence": 0, "content": [{"type": "text", "text": "hi"}]},
            {
                "id": "m2",
                "role": "assistant",
                "sequence": 1,
                "content": [{"type": "code", "language": "sql", "text": "SELECT 1"}],
            },
        ],
        "content_hash": "sha256:" + "0" * 64,
    }
    base.update(overrides)  # type: ignore[arg-type]
    return base


def test_normalizes_provider_and_fills_defaults() -> None:
    conv = normalize_conversation(_conversation())
    assert conv["provider"] == "deepseek"
    assert conv["schema_version"] == "1.0.0"
    assert [m["sequence"] for m in conv["messages"]] == [0, 1]
    assert all(m["content_hash"].startswith("sha256:") for m in conv["messages"])


def test_rejects_missing_required_field() -> None:
    payload = _conversation()
    del payload["provider_conversation_id"]
    with pytest.raises(ValidationFailedError):
        normalize_conversation(payload)


def test_rejects_bad_content_hash_format() -> None:
    payload = _conversation(content_hash="nope")
    with pytest.raises(ValidationFailedError):
        normalize_conversation(payload)


def test_content_hash_is_recomputed_server_side() -> None:
    conv = normalize_conversation(_conversation())
    assert conv["content_hash"] != "sha256:" + "0" * 64
    assert conv["content_hash"].startswith("sha256:")


def test_unknown_role_falls_back() -> None:
    conv = normalize_conversation(
        _conversation(
            messages=[
                {"id": "m1", "role": "moderator", "sequence": 0, "content": [{"type": "text", "text": "x"}]}
            ]
        )
    )
    assert conv["messages"][0]["role"] == "unknown"


def test_same_dom_different_order_yields_same_schema() -> None:
    """需求 §16.1：同一平台不同顺序/结构应收敛为相同 Schema。"""
    a = normalize_conversation(
        _conversation(
            messages=[
                {"id": "b", "role": "assistant", "sequence": 1, "content": [{"type": "text", "text": "B"}]},
                {"id": "a", "role": "user", "sequence": 0, "content": [{"type": "text", "text": "A"}]},
            ]
        )
    )
    b = normalize_conversation(
        _conversation(
            messages=[
                {"id": "a", "role": "user", "sequence": 0, "content": [{"type": "text", "text": "A"}]},
                {"id": "b", "role": "assistant", "sequence": 1, "content": [{"type": "text", "text": "B"}]},
            ]
        )
    )
    assert a["content_hash"] == b["content_hash"]


def test_message_hash_matches_service_implementation() -> None:
    conv = normalize_conversation(_conversation())
    msg = conv["messages"][0]
    assert msg["content_hash"] == hash_message(
        conv["id"], msg["role"], msg["sequence"], msg["content"]
    )


def test_plain_text_and_digest() -> None:
    conv = normalize_conversation(_conversation())
    text = conversation_plain_text(conv)
    assert "[user] hi" in text and "SELECT 1" in text
    assert len(digest_text(text, limit=10)) <= 10
