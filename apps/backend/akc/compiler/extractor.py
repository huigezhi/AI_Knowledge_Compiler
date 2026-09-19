"""Extractor：调用 Claude 抽取结构化知识，并强制通过 JSON Schema 校验。"""

from __future__ import annotations

from typing import Any

from akc.compiler.client import ClaudeClient
from akc.compiler.prompts import (
    EXTRACTOR_PROMPT_VERSION,
    KNOWLEDGE_DOMAINS,
    SYSTEM_PROMPT,
    build_extractor_prompt,
    build_merge_planner_prompt,
)
from akc.compiler.validator import validate_compiler_output
from akc.errors import ClaudeOutputInvalidError
from akc.logging_setup import get_logger

_MERGE_ACTIONS = {"create", "update", "merge", "ignore", "review"}


# 输出预算梯次：先给足，被截断就逐档收紧，而不是直接判死。
# 汇聚式抽取后通常 1 条就够；梯次里第 3 档是"整场对话压成 1 条"的兜底。
_EXTRACTION_BUDGETS: tuple[tuple[int, int], ...] = ((3, 600), (2, 400), (1, 300))


def run_extraction(
    client: ClaudeClient,
    conversation: dict[str, Any],
    related_knowledge: list[dict[str, Any]],
    *,
    max_chars: int = 50_000,
) -> dict[str, Any]:
    """返回 ``CompilerOutput``（已通过 Schema 校验）。

    Schema 校验失败抛 ``ClaudeOutputInvalidError``——**不可自动重试**，因为重试通常
    仍不合规且会放大成本；调用方应把 job 标记为失败并交由人工处理。

    唯一例外是**输出被截断**（``stop_reason=max_tokens``）：那不是模型不合规，
    而是要写的东西太多。此时收紧输出预算重试，最多 ``_EXTRACTION_BUDGETS`` 档。
    """
    last_error: ClaudeOutputInvalidError | None = None
    for attempt, (max_items, max_body_chars) in enumerate(_EXTRACTION_BUDGETS):
        prompt = build_extractor_prompt(
            conversation,
            related_knowledge,
            max_chars=max_chars,
            max_items=max_items,
            max_body_chars=max_body_chars,
        )
        try:
            raw = client.complete_json(SYSTEM_PROMPT, prompt)
        except ClaudeOutputInvalidError as exc:
            if not (exc.details or {}).get("truncated"):
                raise
            last_error = exc
            get_logger().warning(
                "extraction_truncated_retry",
                extra={
                    "extra_fields": {
                        "attempt": attempt + 1,
                        "next_max_items": max_items,
                    }
                },
            )
            continue

        normalized = _coerce(raw)
        # 抢救回来的结果里一条都没剩下时，值得用更小的预算再试一次
        if not normalized["items"] and attempt + 1 < len(_EXTRACTION_BUDGETS):
            last_error = ClaudeOutputInvalidError(
                "compiler output truncated before any complete item",
                details={"truncated": True},
            )
            continue
        try:
            validate_compiler_output(normalized)
        except Exception as exc:  # noqa: BLE001 - 统一转换为不可重试错误
            raise ClaudeOutputInvalidError(
                "compiler output failed schema validation",
                details={"reason": str(exc)},
            ) from exc
        normalized["prompt_version"] = EXTRACTOR_PROMPT_VERSION
        normalized["model"] = client.model
        return normalized

    raise last_error or ClaudeOutputInvalidError("compiler output could not be produced")


def run_merge_planning(
    client: ClaudeClient, existing: dict[str, Any], candidate: dict[str, Any]
) -> dict[str, Any]:
    """让高能力模型判断冲突场景下的合并动作。"""
    prompt = build_merge_planner_prompt(existing, candidate)
    # 2048 太容易被截断成半个 JSON（截断后必然解析失败，白花钱还拿不到结果）
    raw = client.complete_json(SYSTEM_PROMPT, prompt, max_tokens=8192)
    action = str(raw.get("action", "review")).lower()
    if action not in _MERGE_ACTIONS:
        action = "review"
    return {
        "action": action,
        "reason": str(raw.get("reason", "")),
        "proposed_markdown_patch": str(raw.get("proposed_markdown_patch", "")),
        "conflicts": raw.get("conflicts") or [],
    }


def _coerce_domain(value: Any) -> str:
    """主题域归一：不在枚举里的值一律落「其他」，保证目录可控。"""
    text = str(value or "").strip()
    return text if text in KNOWLEDGE_DOMAINS else "其他"


def _coerce(raw: dict[str, Any]) -> dict[str, Any]:
    """把模型输出收敛到 Schema 期望的形状（只做安全的结构补全，不改语义）。"""
    items: list[dict[str, Any]] = []
    for item in raw.get("items") or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        summary = str(item.get("summary") or "").strip()
        source_ids = [str(s) for s in (item.get("source_message_ids") or []) if str(s).strip()]
        if not title or not summary or not source_ids:
            # 无来源或缺失标题的条目无法溯源，直接丢弃（违反强制原则第 5 条）。
            continue
        action = str(item.get("merge_action") or "create").lower()
        if action not in _MERGE_ACTIONS:
            action = "review"
        try:
            confidence = float(item.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
        items.append(
            {
                "title": title,
                "type": _coerce_type(item.get("type")),
                "domain": _coerce_domain(item.get("domain")),
                "summary": summary,
                "body_markdown": str(item.get("body_markdown") or summary),
                "source_message_ids": source_ids,
                "confidence": min(1.0, max(0.0, confidence)),
                "needs_verification": bool(item.get("needs_verification", True)),
                "entities": [str(e) for e in (item.get("entities") or [])],
                "candidate_existing_knowledge_ids": [
                    str(k) for k in (item.get("candidate_existing_knowledge_ids") or [])
                ],
                "merge_action": action,
            }
        )

    return {
        "items": items,
        "entities": _coerce_entities(raw.get("entities")),
        "relations": _coerce_relations(raw.get("relations")),
        "contradictions": _coerce_contradictions(raw.get("contradictions")),
        "notes": [str(n) for n in (raw.get("notes") or [])],
    }


def _coerce_type(value: Any) -> str:
    allowed = {
        "fact",
        "concept",
        "method",
        "heuristic",
        "decision",
        "question",
        "hypothesis",
        "opinion",
    }
    text = str(value or "").lower().strip()
    return text if text in allowed else "fact"


def _coerce_entities(raw: Any) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for item in raw or []:
        if isinstance(item, dict) and item.get("name") and item.get("type"):
            out.append(
                {
                    "name": str(item["name"])[:200],
                    "type": str(item["type"])[:80],
                    "canonical_name": str(item.get("canonical_name") or item["name"])[:200],
                }
            )
    return out


def _coerce_relations(raw: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in raw or []:
        if isinstance(item, dict) and item.get("source") and item.get("relation") and item.get("target"):
            try:
                confidence = float(item.get("confidence", 0.5))
            except (TypeError, ValueError):
                confidence = 0.5
            out.append(
                {
                    "source": str(item["source"])[:200],
                    "relation": str(item["relation"])[:80],
                    "target": str(item["target"])[:200],
                    "confidence": min(1.0, max(0.0, confidence)),
                }
            )
    return out


def _coerce_contradictions(raw: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        severity = str(item.get("severity") or "medium").lower()
        if severity not in {"low", "medium", "high"}:
            severity = "medium"
        out.append(
            {
                "knowledge_id": str(item.get("knowledge_id", "")) or None,
                "field": str(item.get("field", ""))[:120],
                "existing": str(item.get("existing", "")),
                "new": str(item.get("new", "")),
                "severity": severity,
                "reason": str(item.get("reason", "")),
            }
        )
    return out
