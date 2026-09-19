"""编译流水线：JSON Schema 校验 + 假 Claude 传输层端到端。"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from sqlalchemy.orm import Session

from akc.compiler.client import ClaudeClient, ClaudeSettings
from akc.compiler.extractor import run_extraction
from akc.compiler.validator import validate_compiler_output
from akc.errors import (
    ClaudeOutputInvalidError,
    ClaudeRequestError,
    ErrorCode,
    LLMDisabledError,
)
from akc.config import Settings
from akc.services.compile_service import compile_conversation


def _transport(payload: Any, status: int = 200) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        body = (
            {"content": [{"type": "text", "text": payload if isinstance(payload, str) else json.dumps(payload)}]}
            if status == 200
            else {"error": {"message": "failed"}}
        )
        return httpx.Response(status, json=body)

    return httpx.MockTransport(handler)


def _output() -> dict[str, Any]:
    return {
        "items": [
            {
                "title": "SQL 查询性能优化方法",
                "type": "method",
                "summary": "先看执行计划，再改写 SQL。",
                "body_markdown": "## 方法\n1. 看执行计划",
                "source_message_ids": ["m2"],
                "confidence": 0.85,
                "needs_verification": False,
                "entities": ["SQL Server"],
                "merge_action": "create",
            }
        ],
        "entities": [{"name": "SQL Server", "type": "technology", "canonical_name": "SQL Server"}],
        "relations": [],
        "contradictions": [],
        "notes": ["ok"],
    }


def test_valid_output_passes_schema() -> None:
    validate_compiler_output(_output())


def test_invalid_output_fails_schema() -> None:
    bad = {"items": [{"title": "x"}]}  # 缺 type/summary/source_message_ids
    with pytest.raises(Exception):
        validate_compiler_output(bad)


def test_client_parses_fenced_json() -> None:
    client = ClaudeClient(
        ClaudeSettings(api_key="k", model="configured-model"),
        transport=_transport("```json\n" + json.dumps(_output()) + "\n```"),
    )
    data = client.complete_json("sys", "user")
    assert data["items"][0]["title"].startswith("SQL")


def test_client_raises_on_non_json() -> None:
    client = ClaudeClient(
        ClaudeSettings(api_key="k", model="configured-model"), transport=_transport("I cannot help")
    )
    with pytest.raises(ClaudeOutputInvalidError):
        client.complete_json("sys", "user")


def test_client_retries_on_5xx() -> None:
    client = ClaudeClient(
        ClaudeSettings(api_key="k", model="configured-model"), transport=_transport(None, status=500)
    )
    with pytest.raises(ClaudeRequestError) as exc:
        client.complete_json("sys", "user")
    assert exc.value.retryable is True


def test_client_does_not_retry_on_401() -> None:
    client = ClaudeClient(
        ClaudeSettings(api_key="bad", model="configured-model"), transport=_transport(None, status=401)
    )
    with pytest.raises(ClaudeRequestError) as exc:
        client.complete_json("sys", "user")
    assert exc.value.retryable is False


def test_extraction_drops_items_without_valid_sources() -> None:
    payload = _output()
    payload["items"].append(
        {
            "title": "无来源的观点",
            "type": "fact",
            "summary": "没有任何出处。",
            "source_message_ids": [],
            "confidence": 0.4,
        }
    )
    client = ClaudeClient(
        ClaudeSettings(api_key="k", model="configured-model"), transport=_transport(payload)
    )
    result = run_extraction(client, {"provider": "deepseek", "title": "t", "messages": []}, [])
    assert len(result["items"]) == 1


def test_full_compile_pipeline(session: Session, settings: Settings) -> None:
    """端到端：导入 → 编译（假 Claude）→ 知识入库并带来源。"""
    from akc.services.import_service import import_conversation
    from akc.repositories import knowledge as kn_repo

    imported = import_conversation(
        session,
        {
            "id": "conv_1",
            "provider": "deepseek",
            "provider_conversation_id": "ext-1",
            "title": "SQL 优化",
            "messages": [
                {"id": "m1", "role": "user", "sequence": 0, "content": [{"type": "text", "text": "怎么优化"}]},
                {"id": "m2", "role": "assistant", "sequence": 1, "content": [{"type": "text", "text": "看执行计划"}]},
            ],
            "content_hash": "sha256:" + "0" * 64,
        },
        settings=settings,
    )

    settings.llm_enabled = True
    settings.llm_api_key = "test-key"
    settings.llm_model = "configured-model"

    import akc.services.compile_service as compile_service

    original = compile_service._claude_client
    compile_service._claude_client = lambda _settings: ClaudeClient(  # type: ignore[assignment]
        ClaudeSettings(api_key="k", model="configured-model"), transport=_transport(_output())
    )
    try:
        result = compile_conversation(session, imported["conversation_id"], settings=settings)
    finally:
        compile_service._claude_client = original  # type: ignore[assignment]

    assert result["created"] + result["review"] == 1
    knowledge_id = result["knowledge_ids"][0]
    sources = kn_repo.sources_for(session, knowledge_id)
    assert len(sources) >= 1
    assert sources[0].conversation_id == imported["conversation_id"]


def test_compile_requires_enabled_compiler(session: Session, settings: Settings) -> None:
    """未启用编译器时，编译任务必须失败且标记为不可重试（Raw 数据不受影响）。"""
    from akc.services.import_service import import_conversation

    imported = import_conversation(
        session,
        {
            "id": "conv_1",
            "provider": "deepseek",
            "provider_conversation_id": "ext-1",
            "title": "SQL 优化",
            "messages": [
                {"id": "m1", "role": "user", "sequence": 0, "content": [{"type": "text", "text": "hi"}]}
            ],
            "content_hash": "sha256:" + "0" * 64,
        },
        settings=settings,
    )
    settings.llm_enabled = False
    with pytest.raises(LLMDisabledError) as exc:
        compile_conversation(session, imported["conversation_id"], settings=settings)
    assert exc.value.retryable is False
    # 单独的错误码：让前端能区分「没配 LLM」与「调用失败」
    assert exc.value.code == ErrorCode.LLM_DISABLED
