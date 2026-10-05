"""一个对话 = 一条知识点；同主题的多个对话合并为同一条；已有内容不丢失。

对应需求：
* 一个对话最多只产出一个知识点（此前模型会把一个对话拆成好几条）；
* 多个对话讨论同一主题时，合并为同一个知识点；
* 已有知识点数据不丢失（合并只能是追加，不能覆盖）。
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from sqlalchemy.orm import Session

from akc.compiler.client import ClaudeClient, ClaudeSettings
from akc.compiler.extractor import enforce_single_item, run_extraction
from akc.config import Settings
from akc.repositories import knowledge as kn_repo
from akc.services.compile_service import compile_conversation
from akc.services.merge_planner import entity_overlap, plan_merge, same_knowledge_verdict


def _transport(payload: Any) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        text = payload if isinstance(payload, str) else json.dumps(payload)
        return httpx.Response(200, json={"content": [{"type": "text", "text": text}]})

    return httpx.MockTransport(handler)


def _client(payload: Any) -> ClaudeClient:
    return ClaudeClient(
        ClaudeSettings(api_key="k", model="configured-model"), transport=_transport(payload)
    )


def _item(title: str, summary: str, body: str = "", **extra: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "title": title,
        "type": "method",
        "domain": "休闲旅游",
        "summary": summary,
        "body_markdown": body or summary,
        "source_message_ids": ["m2"],
        "confidence": 0.8,
        "needs_verification": False,
        "entities": ["南澳岛"],
        "merge_action": "create",
    }
    base.update(extra)
    return base


# ---------------------------------------------------------------- 条数硬约束
def test_multiple_items_are_folded_into_one() -> None:
    """模型不听话输出 3 条时，必须折叠成 1 条，而不是产出 3 条知识。"""
    payload = {
        "items": [
            _item("要点一", "第一条内容。", "正文一"),
            _item("要点二", "第二条内容。", "正文二"),
            _item("要点三", "第三条内容。", "正文三"),
        ],
        "entities": [],
        "relations": [],
        "contradictions": [],
        "notes": [],
    }
    normalized = enforce_single_item(payload)
    assert len(normalized["items"]) == 1
    body = normalized["items"][0]["body_markdown"]
    # 内容不能丢：被折叠的要点仍留在正文里
    assert "正文一" in body
    assert "正文二" in body
    assert "正文三" in body


def test_single_item_passes_through_unchanged() -> None:
    payload = {"items": [_item("只有一条", "内容。")]}
    assert enforce_single_item(payload)["items"] == payload["items"]


def test_extraction_never_returns_more_than_one_item() -> None:
    """端到端：即便模型返回多条，run_extraction 的产出也只能是 1 条。"""
    payload = {
        "items": [_item(f"要点{i}", f"第{i}条内容。") for i in range(4)],
        "entities": [],
        "relations": [],
        "contradictions": [],
        "notes": [],
    }
    result = run_extraction(
        _client(payload), {"provider": "deepseek", "title": "t", "messages": []}, []
    )
    assert len(result["items"]) == 1


@pytest.mark.parametrize("count", [2, 3, 5])
def test_compile_creates_at_most_one_knowledge(count: int, session: Session, settings: Settings) -> None:
    """一个对话编译完，库里最多只多出一条知识。"""
    from akc.services.import_service import import_conversation

    imported = import_conversation(
        session,
        {
            "id": f"conv_{count}",
            "provider": "deepseek",
            "provider_conversation_id": f"ext-{count}",
            "title": "南澳岛出行",
            "messages": [
                {"id": "m1", "role": "user", "sequence": 0, "content": [{"type": "text", "text": "怎么去"}]},
                {"id": "m2", "role": "assistant", "sequence": 1, "content": [{"type": "text", "text": "要预约"}]},
            ],
            "content_hash": "sha256:" + str(count) * 64,
        },
        settings=settings,
    )
    settings.llm_enabled = True
    settings.llm_model = "configured-model"

    payload = {
        "items": [
            _item(f"要点{i}", f"第{i}条完全不同的内容。", f"正文{i}", source_message_ids=["m2"])
            for i in range(count)
        ],
        "entities": [],
        "relations": [],
        "contradictions": [],
        "notes": [],
    }
    import akc.services.compile_service as compile_service

    original = compile_service._claude_client
    compile_service._claude_client = lambda _s: _client(payload)  # type: ignore[assignment]
    try:
        result = compile_conversation(session, imported["conversation_id"], settings=settings)
    finally:
        compile_service._claude_client = original  # type: ignore[assignment]

    assert len(result["knowledge_ids"]) == 1


# ---------------------------------------------------------------- 同主题合并
def test_two_conversations_same_topic_merge_into_one_knowledge(
    session: Session, settings: Settings
) -> None:
    """两个对话聊同一主题：第二个必须并入第一条，且不覆盖第一条的内容。"""
    from akc.services.import_service import import_conversation

    existing = kn_repo.create(
        session,
        knowledge_id="k_existing",
        slug="nanaodao-yuyue",
        title="南澳岛入岛需要预约",
        knowledge_type="fact",
        domain="休闲旅游",
        summary="南澳岛入岛实行预约制。",
        markdown="## 原始结论\n\n南澳岛入岛需要提前预约。",
        status="candidate",
        entities=["南澳岛"],
        topics=["南澳岛"],
    )
    session.flush()

    imported = import_conversation(
        session,
        {
            "id": "conv_2",
            "provider": "deepseek",
            "provider_conversation_id": "ext-2",
            "title": "南澳岛国庆出行",
            "messages": [
                {"id": "m1", "role": "user", "sequence": 0, "content": [{"type": "text", "text": "国庆去南澳岛"}]},
                {"id": "m2", "role": "assistant", "sequence": 1, "content": [{"type": "text", "text": "国庆入岛要预约，且限流"}]},
            ],
            "content_hash": "sha256:" + "9" * 64,
        },
        settings=settings,
    )
    settings.llm_enabled = True
    settings.llm_model = "configured-model"

    payload = {
        "items": [
            _item(
                "南澳岛国庆入岛预约要求",
                "国庆期间入岛需预约并限流。",
                "## 国庆安排\n\n国庆入岛需预约，且有限流措施。",
                source_message_ids=["m2"],
            )
        ],
        "entities": [],
        "relations": [],
        "contradictions": [],
        "notes": [],
    }
    import akc.services.compile_service as compile_service

    original = compile_service._claude_client
    compile_service._claude_client = lambda _s: _client(payload)  # type: ignore[assignment]
    try:
        result = compile_conversation(session, imported["conversation_id"], settings=settings)
    finally:
        compile_service._claude_client = original  # type: ignore[assignment]

    # 没有新建第二条知识
    assert result["created"] == 0
    assert result["knowledge_ids"] == ["k_existing"]

    # 已有内容必须还在（这是"数据不丢失"的核心断言）
    updated = kn_repo.get(session, "k_existing")
    assert updated is not None
    assert "南澳岛入岛需要提前预约" in (updated.markdown or ""), "已有正文被覆盖了"
    # 新对话带来的补充也要进来
    assert "国庆" in (updated.markdown or "")


def test_different_domain_is_not_merged() -> None:
    """不同主题域：即便标题相似也不合并（避免把旅游和编程揉成一条）。"""
    decision = plan_merge(
        {"title": "预约机制", "type": "fact", "summary": "入岛要预约。", "domain": "休闲旅游"},
        {
            "id": "k1",
            "title": "预约机制",
            "knowledge_type": "fact",
            "status": "candidate",
            "summary": "接口要预约。",
            "domain": "编程技术",
        },
    )
    assert decision.action == "create"
    assert "主题域不同" in decision.reason


def test_same_domain_and_shared_entity_is_same_knowledge() -> None:
    """同域 + 共享核心实体：标题措辞不同也应判为同一知识点。"""
    cand = {
        "title": "南澳岛国庆入岛预约要求",
        "type": "fact",
        "summary": "国庆期间入岛需预约。",
        "domain": "休闲旅游",
        "entities": ["南澳岛", "预约"],
    }
    exist = {
        "id": "k1",
        "title": "南澳岛入岛需要预约",
        "knowledge_type": "fact",
        "status": "candidate",
        "summary": "南澳岛入岛实行预约制。",
        "domain": "休闲旅游",
        "entities": ["南澳岛", "预约"],
    }
    assert entity_overlap(cand, exist) > 0
    verdict, reason = same_knowledge_verdict(cand, exist, 0.29)
    assert verdict is True, f"应当判为同一知识点，实际：{reason}"


def test_unrelated_knowledge_is_not_merged() -> None:
    verdict, _reason = same_knowledge_verdict(
        {"title": "番茄炒蛋", "summary": "先炒蛋。", "domain": "生活健康", "entities": ["鸡蛋"]},
        {
            "id": "k1",
            "title": "南澳岛预约",
            "summary": "入岛要预约。",
            "domain": "休闲旅游",
            "entities": ["南澳岛"],
        },
        0.1,
    )
    assert verdict is False
