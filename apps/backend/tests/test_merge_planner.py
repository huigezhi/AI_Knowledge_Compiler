"""Merge Planner 全分支（需求文档 §9.4）。"""

from __future__ import annotations

from akc.services.merge_planner import MergeDecision, plan_merge, select_best_match, text_similarity


def _candidate(**overrides: object) -> dict:
    base = {
        "title": "SQL 查询性能优化方法",
        "type": "method",
        "summary": "先看执行计划，再改写 SQL，最后验证索引。",
        "body_markdown": "1. 看执行计划\n2. 改写 SQL",
        "source_message_ids": ["m2"],
        "confidence": 0.8,
    }
    base.update(overrides)  # type: ignore[arg-type]
    return base


def _existing(**overrides: object) -> dict:
    base = {
        "id": "k_001",
        "title": "SQL 查询性能优化方法",
        "knowledge_type": "method",
        "status": "candidate",
        "summary": "先看执行计划，再改写 SQL，最后验证索引。",
        "markdown": "1. 看执行计划\n2. 改写 SQL",
        "source_message_ids": ["m2"],
    }
    base.update(overrides)  # type: ignore[arg-type]
    return base


def test_same_meaning_same_evidence_ignored() -> None:
    decision = plan_merge(_candidate(), _existing())
    assert decision.action == "ignore"
    assert decision.similarity >= 0.72


def test_same_meaning_new_evidence_merges() -> None:
    decision = plan_merge(_candidate(source_message_ids=["m9"]), _existing())
    assert decision.action == "merge"
    assert decision.existing_knowledge_id == "k_001"


def test_supplementary_detail_updates() -> None:
    decision = plan_merge(
        _candidate(
            title="SQL 查询性能优化方法的补充",
            summary="除了执行计划，还可以用 CTE 拆解复杂子查询。",
            source_message_ids=["m5"],
        ),
        _existing(),
    )
    assert decision.action in {"update", "create", "merge"}
    assert isinstance(decision, MergeDecision)


def test_verified_conflict_requires_review() -> None:
    decision = plan_merge(
        _candidate(
            title="SQL 查询性能优化方法的补充",
            summary="补充了例外条件：列存索引不适用。",
            source_message_ids=["m7"],
        ),
        _existing(status="verified"),
    )
    assert decision.action == "review"
    assert decision.conflicts


def test_type_conflict_requires_review() -> None:
    decision = plan_merge(_candidate(type="fact"), _existing(knowledge_type="method"))
    assert decision.action == "review"
    assert decision.conflicts[0]["field"] == "knowledge_type"


def test_unrelated_creates() -> None:
    decision = plan_merge(
        _candidate(title="做番茄炒蛋的步骤", summary="先炒蛋再下番茄。"),
        _existing(),
    )
    assert decision.action == "create"


def test_opinion_is_ignored() -> None:
    decision = plan_merge(_candidate(type="opinion"), _existing())
    assert decision.action == "ignore"
    assert "观点" in decision.reason or "opinion" in decision.reason


def test_question_is_ignored() -> None:
    decision = plan_merge(_candidate(type="question"), _existing())
    assert decision.action == "ignore"


def test_similarity_properties() -> None:
    assert text_similarity("abc", "abc") == 1.0
    assert text_similarity("abc", "xyz") == 0.0
    assert text_similarity("", "") == 0.0


def test_select_best_match() -> None:
    pool = [
        {"title": "无关主题", "summary": ""},
        {"title": "SQL 查询性能优化方法", "summary": "先看执行计划"},
    ]
    best, score = select_best_match(_candidate(), pool)
    assert best is not None and best["title"].startswith("SQL")
    assert score > 0.5
