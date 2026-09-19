"""Claude 编译流水线（需求文档 §8.1 / §9）。

阶段：Preprocessor → Chunker → Candidate Retriever → Extractor → Dedup →
Contradiction → Merge Planner → Knowledge Writer → Review Queue。

强制原则落地：
* Claude 输出必须过 JSON Schema；
* 每条知识必须有可解析且**确实存在**的 ``source_message_ids``；
* Verified 内容不会被低置信度 Candidate 静默覆盖（冲突 → ``review``）。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from akc.compiler.client import ClaudeClient, ClaudeSettings
from akc.compiler.extractor import run_extraction
from akc.config import COMPILER_VERSION, Settings
from akc.errors import AppError, ClaudeRequestError
from akc.logging_setup import log_event
from akc.repositories import (
    audit,
    conversation as conv_repo,
    knowledge as kn_repo,
    sync_run as run_repo,
)
from akc.repositories import message as msg_repo
from akc.services.merge_planner import plan_merge, select_best_match
from akc.services.search import related_knowledge_for_conversation

_REVIEW_CONFIDENCE_THRESHOLD = 0.6


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:20]}"


def _claude_client(settings: Settings) -> ClaudeClient:
    if not settings.claude_enabled:
        raise ClaudeRequestError(
            "claude compiler is disabled; enable it in settings first",
            retryable=False,
        )
    return ClaudeClient(
        ClaudeSettings(
            api_key=settings.claude_api_key or "",
            model=settings.claude_model or "",
            base_url=settings.claude_base_url,
            timeout_seconds=settings.claude_timeout_seconds,
            max_context_tokens=settings.claude_max_context_tokens,
        )
    )


def compile_conversation(
    session: Session,
    conversation_id: str,
    *,
    settings: Settings,
    job_id: str | None = None,
) -> dict[str, Any]:
    """编译一个会话。返回统计结果。失败时抛出带 ``retryable`` 语义的错误。"""
    conv_row = conv_repo.get(session, conversation_id)
    if conv_row is None:
        raise AppError("conversation not found", code=AppError.code.__class__("NOT_FOUND"))  # type: ignore[attr-defined]

    conversation = conv_repo.to_dict(conv_row, with_messages=True)
    messages = conversation.get("messages") or []
    if not messages:
        return {
            "conversation_id": conversation_id,
            "items": 0,
            "created": 0,
            "updated": 0,
            "merged": 0,
            "ignored": 0,
            "review": 0,
            "knowledge_ids": [],
            "notes": ["conversation has no messages"],
        }

    # --- Candidate Retrieval（FTS5）---------------------------------------
    related = related_knowledge_for_conversation(session, conversation_id)
    existing_pool = [
        {**item, "source_message_ids": []}
        for item in kn_repo.search_fts(session, conversation.get("title") or "", limit=10)
        if item.status in ("verified", "candidate", "review", "merged")
    ] or []
    pool: list[dict[str, Any]] = [
        kn_repo.to_dict(item) for item in _load_pool(session, related)
    ] or existing_pool

    # --- Extractor --------------------------------------------------------
    client = _claude_client(settings)
    run = run_repo.create_compile_run(
        session,
        run_id=_new_id("crun"),
        conversation_id=conversation_id,
        model=settings.claude_model or "",
        prompt_version="extractor-v1",
        compiler_version=COMPILER_VERSION,
        adapter_version=conv_row.adapter_version,
        job_id=job_id,
        input_digest=str(conversation.get("content_hash") or "")[:64],
    )
    try:
        output = run_extraction(
            client,
            conversation,
            pool,
            max_chars=settings.claude_max_context_tokens * 4,
        )
    except Exception as exc:  # noqa: BLE001 - 统一记录后向上抛，由 job 层决定重试
        run_repo.finish_compile_run(session, run, status="failed", error=str(exc)[:500])
        session.commit()
        raise
    finally:
        client.close()

    # --- Dedup / Merge / Write --------------------------------------------
    valid_message_ids = {str(m["id"]) for m in messages}
    stats = {"created": 0, "updated": 0, "merged": 0, "ignored": 0, "review": 0}
    knowledge_ids: list[str] = []
    decisions: list[dict[str, Any]] = []

    for item in output.get("items", []):
        source_ids = [sid for sid in item.get("source_message_ids", []) if sid in valid_message_ids]
        if not source_ids:
            # 强制原则第 5 条：无有效来源的知识不允许落库。
            stats["ignored"] += 1
            decisions.append(
                {"title": item.get("title"), "action": "ignore", "reason": "no valid source messages"}
            )
            continue

        best, score = select_best_match(item, pool)
        decision = (
            plan_merge(
                item,
                best,
                require_review_for_conflicts=settings.require_review_for_conflicts,
            )
            if best is not None
            else None
        )

        title = str(item.get("title") or "")
        confidence = float(item.get("confidence") or 0.5)
        needs_review = bool(item.get("needs_verification")) or confidence < _REVIEW_CONFIDENCE_THRESHOLD
        declared_action = str(item.get("merge_action") or "create").lower()

        if decision is None or decision.action == "create":
            status = "review" if (needs_review or declared_action == "review") else "candidate"
            entity = kn_repo.create(
                session,
                knowledge_id=_new_id("k"),
                slug=_slug_for(title),
                title=title,
                knowledge_type=str(item.get("type") or "fact"),
                summary=str(item.get("summary") or ""),
                markdown=str(item.get("body_markdown") or item.get("summary") or ""),
                confidence=confidence,
                needs_verification=needs_review,
                topics=list(item.get("entities") or []),
                entities=list(item.get("entities") or []),
                status=status,
                prompt_version="extractor-v1",
                model=settings.claude_model,
            )
            kn_repo.link_sources(
                session,
                knowledge_id=entity.id,
                message_ids=source_ids,
                conversation_id=conversation_id,
            )
            knowledge_ids.append(entity.id)
            stats["review" if status == "review" else "created"] += 1
            decisions.append({"title": title, "action": status, "reason": "new knowledge candidate"})
            pool.append(_pool_entry(entity, source_ids))

        elif decision.action == "update":
            target = kn_repo.get(session, decision.existing_knowledge_id or "")
            if target is None:
                continue
            if target.status == "verified" and settings.require_review_for_conflicts:
                target.status = "review"
                stats["review"] += 1
                decisions.append(
                    {"title": title, "action": "review", "reason": decision.reason}
                )
            else:
                kn_repo.update_content(
                    session,
                    target,
                    markdown=str(item.get("body_markdown") or ""),
                    summary=str(item.get("summary") or ""),
                )
                stats["updated"] += 1
                decisions.append({"title": title, "action": "update", "reason": decision.reason})
            kn_repo.link_sources(
                session,
                knowledge_id=target.id,
                message_ids=source_ids,
                conversation_id=conversation_id,
            )
            knowledge_ids.append(target.id)

        elif decision.action == "merge":
            target = kn_repo.get(session, decision.existing_knowledge_id or "")
            if target is None:
                continue
            kn_repo.link_sources(
                session,
                knowledge_id=target.id,
                message_ids=source_ids,
                conversation_id=conversation_id,
            )
            stats["merged"] += 1
            knowledge_ids.append(target.id)
            decisions.append({"title": title, "action": "merge", "reason": decision.reason})

        elif decision.action == "review":
            target = kn_repo.get(session, decision.existing_knowledge_id or "")
            entity = kn_repo.create(
                session,
                knowledge_id=_new_id("k"),
                slug=_slug_for(title),
                title=title,
                knowledge_type=str(item.get("type") or "fact"),
                summary=str(item.get("summary") or ""),
                markdown=str(item.get("body_markdown") or ""),
                confidence=confidence,
                needs_verification=True,
                entities=list(item.get("entities") or []),
                status="review",
                prompt_version="extractor-v1",
                model=settings.claude_model,
            )
            kn_repo.link_sources(
                session,
                knowledge_id=entity.id,
                message_ids=source_ids,
                conversation_id=conversation_id,
            )
            if target is not None:
                kn_repo.link_knowledge(
                    session,
                    knowledge_id=entity.id,
                    related_knowledge_id=target.id,
                    link_type="conflicts_with",
                    confidence=confidence,
                )
            stats["review"] += 1
            knowledge_ids.append(entity.id)
            decisions.append(
                {"title": title, "action": "review", "reason": decision.reason,
                 "conflicts": decision.conflicts}
            )

        else:  # ignore
            stats["ignored"] += 1
            decisions.append({"title": title, "action": "ignore", "reason": decision.reason})

    # --- 实体/关系落库（最小可用） ----------------------------------------
    _persist_entities(session, output.get("entities") or [])

    conv_repo.mark_compiled(session, conversation_id, datetime.now(timezone.utc))
    run_repo.finish_compile_run(
        session,
        run,
        status="succeeded",
        result={
            "stats": stats,
            "decisions": decisions,
            "model": settings.claude_model,
            "prompt_version": "extractor-v1",
        },
    )
    audit.record(
        session,
        log_id=_new_id("audit"),
        event_type="conversation.compiled",
        entity_type="conversation",
        entity_id=conversation_id,
        detail={"stats": stats, "model": settings.claude_model},
    )
    session.commit()
    log_event("conversation_compiled", conversation_id=conversation_id, **stats)

    return {
        "conversation_id": conversation_id,
        "items": len(output.get("items", [])),
        "knowledge_ids": knowledge_ids,
        "decisions": decisions,
        "notes": list(output.get("notes") or []),
        **stats,
    }


def _load_pool(session: Session, related: list[dict[str, Any]]) -> list[Any]:
    rows = []
    for item in related:
        entity = kn_repo.get(session, str(item.get("id")))
        if entity is not None:
            rows.append(entity)
    return rows


def _pool_entry(entity: Any, source_ids: list[str]) -> dict[str, Any]:
    return {
        "id": entity.id,
        "title": entity.title,
        "summary": entity.summary,
        "markdown": entity.markdown,
        "knowledge_type": entity.knowledge_type,
        "status": entity.status,
        "source_message_ids": list(source_ids),
    }


def _slug_for(title: str) -> str:
    from akc.services.obsidian import slugify

    return slugify(title)


def _persist_entities(session: Session, entities: list[dict[str, Any]]) -> None:
    from akc.db.models import Entity

    for item in entities:
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        entity_id = f"ent_{abs(hash(name)) % (10**12):012d}"
        existing = session.get(Entity, entity_id)
        if existing is not None:
            continue
        session.add(
            Entity(
                id=entity_id,
                name=name,
                type=str(item.get("type") or "unknown"),
                canonical_name=str(item.get("canonical_name") or name),
            )
        )
    session.flush()


def compile_handler(
    session: Session, payload: dict[str, Any], settings: Settings, job_id: str
) -> dict[str, Any]:
    """COMPILE_CONVERSATION 任务的处理器。"""
    conversation_id = str(payload.get("conversation_id") or "")
    if not conversation_id:
        raise AppError("payload.conversation_id is required", code=_NOT_FOUND_NOT_USED)
    return compile_conversation(session, conversation_id, settings=settings, job_id=job_id)


# 占位：仅用于上面 handler 的显式错误码引用（保持错误码枚举单一来源）
from akc.errors import ErrorCode as _ErrorCode  # noqa: E402

_NOT_FOUND_NOT_USED = _ErrorCode.BAD_REQUEST
