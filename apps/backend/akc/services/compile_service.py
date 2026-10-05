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
from akc.compiler.extractor import enforce_single_item, run_extraction
from akc.compiler.prompts import EXTRACTOR_PROMPT_VERSION
from akc.config import COMPILER_VERSION, Settings
from akc.errors import AppError, ClaudeRequestError, LLMDisabledError
from akc.logging_setup import log_event
from akc.repositories import (
    audit,
    conversation as conv_repo,
    knowledge as kn_repo,
    sync_run as run_repo,
)
from akc.repositories import message as msg_repo
from akc.services.merge_planner import _RELATED_THRESHOLD, plan_merge, select_best_match, text_similarity
from akc.services.search import related_knowledge_for_conversation

_REVIEW_CONFIDENCE_THRESHOLD = 0.6


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:20]}"


def _claude_client(settings: Settings) -> ClaudeClient:
    if not settings.llm_enabled:
        # 采集原始对话不需要 LLM；只有「编译成知识」才需要。
        raise LLMDisabledError("llm compiler is disabled (set AKC_LLM_ENABLED=true to enable)")
    return ClaudeClient(
        ClaudeSettings(
            api_key=settings.llm_api_key or "",
            model=settings.llm_model or "",
            base_url=settings.llm_base_url,
            timeout_seconds=settings.llm_timeout_seconds,
            max_context_tokens=settings.llm_max_context_tokens,
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
    #
    # 以前这里是二选一：命中「会话正文关键词」就用它，否则才退到「会话标题」。
    # 结果是检索面很窄——同主题的旧知识只要没被其中一路命中，就进不了候选池，
    # 于是每次都新建一条，"多个对话讨论同一主题应合并" 自然做不到。
    # 现在三路检索**合并去重**：正文关键词 + 会话标题 + 最近更新的知识。
    pool = _build_candidate_pool(session, conversation, conversation_id)

    # --- Extractor --------------------------------------------------------
    client = _claude_client(settings)
    run = run_repo.create_compile_run(
        session,
        run_id=_new_id("crun"),
        conversation_id=conversation_id,
        model=settings.llm_model or "",
        prompt_version=EXTRACTOR_PROMPT_VERSION,
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
            max_chars=settings.llm_max_context_tokens * 4,
        )
    except Exception as exc:  # noqa: BLE001 - 统一记录后向上抛，由 job 层决定重试
        run_repo.finish_compile_run(session, run, status="failed", error=str(exc)[:500])
        session.commit()
        raise
    finally:
        client.close()

    # --- Dedup / Merge / Write --------------------------------------------
    # 兜底：即使调用方绕过 extractor（测试/直接构造），一个对话也只产出一条知识点。
    output = enforce_single_item(output)
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

        title = str(item.get("title") or "")
        best, score = select_best_match(item, pool)
        if best is None or score < _RELATED_THRESHOLD:
            # 候选池按会话标题检索，覆盖面有限；再用**候选标题本身**搜一次全库。
            # 否则"同主题的新会话"永远找不到早前的知识，只会不停建重复条目——
            # 这正是"相似知识点要合并到一起"的关键一步。
            seen_ids = {str(p.get("id") or "") for p in pool}
            extra_pool = [
                {**kn_repo.to_dict(cand), "source_message_ids": []}
                for cand in kn_repo.search_fts(session, title, limit=5)
                if str(cand.id) not in seen_ids
                and cand.status in ("verified", "candidate", "review", "merged")
            ]
            if extra_pool:
                alt, alt_score = select_best_match(item, extra_pool)
                if alt is not None and alt_score > score:
                    best, score = alt, alt_score

        decision = (
            plan_merge(
                item,
                best,
                require_review_for_conflicts=settings.require_review_for_conflicts,
            )
            if best is not None
            else None
        )

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
                domain=str(item.get("domain") or "其他"),
                summary=str(item.get("summary") or ""),
                markdown=str(item.get("body_markdown") or item.get("summary") or ""),
                confidence=confidence,
                needs_verification=needs_review,
                topics=list(item.get("entities") or []),
                entities=list(item.get("entities") or []),
                status=status,
                prompt_version=EXTRACTOR_PROMPT_VERSION,
                model=settings.llm_model,
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
            # 关键：**先追加，绝不覆盖**。
            # 以前这里直接 update_content(markdown=候选正文)，把已有知识整个替换掉；
            # 而对 verified 目标更是只改状态、完全不落内容——新会话的正文就此丢失。
            # 在"一个对话 = 一条知识点"的规则下，同主题的后续会话必然走进这个分支，
            # 于是"已有知识点不丢失"被破坏。统一走 _fold_into_target：
            # 只在候选确实带来新信息时以「## 补充」追加。
            _fold_into_target(session, target, item, heading="补充")
            if target.status == "verified" and settings.require_review_for_conflicts:
                # 追加本身是安全的（不覆盖），但仍把已确认的知识标回待审核，
                # 让人工确认这次补充——既做到合并，又不绕过"verified 需人工把关"。
                target.status = "review"
                stats["review"] += 1
                decisions.append(
                    {"title": title, "action": "review", "reason": decision.reason}
                )
            else:
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
            # 合并不再只是"把来源挂上去"：把候选里**确实新增的信息**折叠进已有笔记，
            # 真正做到"相似知识点合并成一条"。语义几乎重复（相似度 >= 0.75）时不追加，
            # 避免同一句话在正文里堆两遍。
            _fold_into_target(session, target, item)
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
                domain=str(item.get("domain") or "其他"),
                summary=str(item.get("summary") or ""),
                markdown=str(item.get("body_markdown") or ""),
                confidence=confidence,
                needs_verification=True,
                entities=list(item.get("entities") or []),
                status="review",
                prompt_version=EXTRACTOR_PROMPT_VERSION,
                model=settings.llm_model,
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
            "model": settings.llm_model,
            "prompt_version": EXTRACTOR_PROMPT_VERSION,
        },
    )
    audit.record(
        session,
        log_id=_new_id("audit"),
        event_type="conversation.compiled",
        entity_type="conversation",
        entity_id=conversation_id,
        detail={"stats": stats, "model": settings.llm_model},
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


# 参与合并判定的状态：已删除的不参与（避免把新内容合并进一条已被丢弃的知识）
_MERGEABLE_STATUSES = ("verified", "candidate", "review", "merged")


def _build_candidate_pool(
    session: Session, conversation: dict[str, Any], conversation_id: str
) -> list[dict[str, Any]]:
    """合并三路检索，得到「可能与本次对话同主题」的已有知识候选池。

    1. 会话正文关键词（FTS）——覆盖面最广，能命中没出现在标题里的主题；
    2. 会话标题（FTS）——标题往往就是主题，权重高；
    3. 最近更新的知识——兜底，让"刚聊过的主题"始终在候选里。
    """
    from akc.services.search import related_knowledge_for_conversation

    pool: dict[str, dict[str, Any]] = {}

    def add(entity: Any) -> None:
        if entity is None or entity.status not in _MERGEABLE_STATUSES:
            return
        if entity.id in pool:
            return
        pool[entity.id] = kn_repo.to_dict(entity)

    for item in _load_pool(
        session, related_knowledge_for_conversation(session, conversation_id, limit=15)
    ):
        add(item)

    title = str(conversation.get("title") or "").strip()
    if title:
        for entity in kn_repo.search_fts(session, title, limit=15):
            add(entity)

    # 兜底：最近更新的知识始终参与匹配，保证"刚聊过的话题"不会漏掉
    recent, _total = kn_repo.list_knowledge(session, limit=30, offset=0)
    for entity in recent:
        add(entity)

    return list(pool.values())


def _fold_into_target(
    session: Session, target: Any, item: dict[str, Any], *, heading: str = "补充"
) -> bool:
    """把候选里**新增的信息**追加进已有知识，返回是否真的追加了。

    只在候选与已有正文不重复（相似度 < 0.75）时才追加，避免同一句话堆两遍；
    **永不覆盖**已有内容（覆盖会导致历史沉淀丢失，无法恢复）。
    """
    cand_body = str(item.get("body_markdown") or "").strip() or str(item.get("summary") or "").strip()
    if not cand_body:
        return False
    existing_body = target.markdown or target.summary or ""
    if text_similarity(cand_body, existing_body) >= 0.75:
        return False
    folded = f"{(target.markdown or '').rstrip()}\n\n## {heading}\n\n{cand_body}"
    kn_repo.update_content(session, target, markdown=folded)
    return True


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
