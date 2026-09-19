"""Merge Planner —— 决定新知识候选与已有知识之间的关系（需求文档 §9.4）。

规则表：
* 语义相同 + 证据相同 → ``ignore``
* 语义相同 + 证据不同 → ``merge``
* 已有更完整 + 新内容为补充 → ``update``
* 与已有（尤其 verified）冲突 → ``review``（**绝不静默覆盖**）
* 新内容仅为 opinion / question → ``ignore``（不入主知识库）

本模块是纯函数，不依赖 HTTP / 数据库，便于单测覆盖全部分支。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

_SEMANTIC_SAME_THRESHOLD = 0.72
_RELATED_THRESHOLD = 0.45
_SUPPLEMENT_THRESHOLD = 0.30

# 这两类不进入主知识库的自动合并链路。
_NON_DURABLE_TYPES = {"opinion", "question"}


@dataclass(frozen=True)
class MergeDecision:
    action: str  # create | update | merge | ignore | review
    reason: str
    existing_knowledge_id: str | None = None
    similarity: float = 0.0
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    proposed_markdown_patch: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "reason": self.reason,
            "existing_knowledge_id": self.existing_knowledge_id,
            "similarity": round(self.similarity, 3),
            "conflicts": self.conflicts,
            "proposed_markdown_patch": self.proposed_markdown_patch,
        }


def text_similarity(left: str, right: str) -> float:
    """中英文通用的相似度：字符 bigram 的 Jaccard 系数。"""
    a = _bigrams(left)
    b = _bigrams(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _bigrams(text: str) -> set[str]:
    normalized = "".join(ch for ch in text.lower() if not ch.isspace())
    if len(normalized) < 2:
        return {normalized} if normalized else set()
    return {normalized[i : i + 2] for i in range(len(normalized) - 1)}


def _evidence(candidate: dict[str, Any]) -> set[str]:
    return {str(s) for s in (candidate.get("source_message_ids") or [])}


def plan_merge(
    candidate: dict[str, Any],
    existing: dict[str, Any],
    *,
    require_review_for_conflicts: bool = True,
) -> MergeDecision:
    """比较候选知识与单条已有知识，给出合并决策。"""
    cand_title = str(candidate.get("title") or "")
    cand_summary = str(candidate.get("summary") or "")
    existing_title = str(existing.get("title") or "")
    existing_summary = str(existing.get("summary") or existing.get("markdown") or "")

    similarity = max(
        text_similarity(cand_title, existing_title),
        0.5 * (text_similarity(cand_title, existing_title) + text_similarity(cand_summary, existing_summary)),
    )
    cand_type = str(candidate.get("type") or "fact")
    existing_type = str(existing.get("knowledge_type") or "fact")
    existing_status = str(existing.get("status") or "candidate")
    existing_id = str(existing.get("id") or "")

    # 1) 不耐久类型：观点与临时问题不参与自动合并
    if cand_type in _NON_DURABLE_TYPES:
        return MergeDecision(
            action="ignore",
            reason=f"候选类型为 {cand_type}，属于观点或临时问题，不进入主知识库自动合并链路",
            existing_knowledge_id=existing_id,
            similarity=similarity,
        )

    # 2) 语义不同 → 新建
    if similarity < _RELATED_THRESHOLD:
        return MergeDecision(
            action="create",
            reason="与已有知识语义差异较大，作为新知识创建",
            existing_knowledge_id=existing_id,
            similarity=similarity,
        )

    shared_evidence = _evidence(candidate) & {
        str(s) for s in (existing.get("source_message_ids") or [])
    }

    # 3) 类型冲突 → review（尤其已有知识已 verified）
    if cand_type != existing_type and similarity >= _RELATED_THRESHOLD:
        return MergeDecision(
            action="review",
            reason=f"语义相关但知识类型不同（已有 {existing_type} / 候选 {cand_type}），需人工判断",
            existing_knowledge_id=existing_id,
            similarity=similarity,
            conflicts=[
                {
                    "field": "knowledge_type",
                    "existing": existing_type,
                    "new": cand_type,
                    "severity": "medium" if existing_status != "verified" else "high",
                }
            ],
        )

    # 4) 语义高度相同
    if similarity >= _SEMANTIC_SAME_THRESHOLD:
        if shared_evidence:
            return MergeDecision(
                action="ignore",
                reason="语义相同且证据相同，已存在于知识库中",
                existing_knowledge_id=existing_id,
                similarity=similarity,
            )
        # verified 内容不允许被静默合并修改：内容实质不同（而不仅仅是新增来源）时转人工。
        content_similarity = text_similarity(cand_summary, existing_summary)
        if (
            existing_status == "verified"
            and require_review_for_conflicts
            and content_similarity < _SEMANTIC_SAME_THRESHOLD
        ):
            return MergeDecision(
                action="review",
                reason="核心命题相同但正文存在实质差异，verified 知识需人工确认后才能合并",
                existing_knowledge_id=existing_id,
                similarity=similarity,
                conflicts=[
                    {
                        "field": "body",
                        "existing": existing_summary[:400],
                        "new": cand_summary[:400],
                        "severity": "high",
                    }
                ],
            )
        return MergeDecision(
            action="merge",
            reason="语义相同但来自不同证据，合并来源并保留主知识",
            existing_knowledge_id=existing_id,
            similarity=similarity,
        )

    # 5) 语义相关但不完全相同：已有更完整 → update，否则 review
    if _SUPPLEMENT_THRESHOLD <= similarity < _SEMANTIC_SAME_THRESHOLD:
        if existing_status == "verified" and require_review_for_conflicts:
            return MergeDecision(
                action="review",
                reason="已有知识为 verified，不允许被候选内容静默更新",
                existing_knowledge_id=existing_id,
                similarity=similarity,
                conflicts=[
                    {
                        "field": "body",
                        "existing": existing_summary[:400],
                        "new": cand_summary[:400],
                        "severity": "medium",
                    }
                ],
            )
        return MergeDecision(
            action="update",
            reason="候选内容为已有知识提供补充细节",
            existing_knowledge_id=existing_id,
            similarity=similarity,
            proposed_markdown_patch=str(candidate.get("body_markdown") or cand_summary),
        )

    return MergeDecision(
        action="create",
        reason="未达到任何合并阈值，作为新知识创建",
        existing_knowledge_id=existing_id,
        similarity=similarity,
    )


def select_best_match(
    candidate: dict[str, Any], candidates: list[dict[str, Any]]
) -> tuple[dict[str, Any] | None, float]:
    """在已有知识候选中挑出最相似的一条。"""
    best: dict[str, Any] | None = None
    best_score = 0.0
    for item in candidates:
        score = text_similarity(
            str(candidate.get("title") or ""), str(item.get("title") or "")
        )
        score = max(
            score,
            0.5 * (score + text_similarity(
                str(candidate.get("summary") or ""),
                str(item.get("summary") or item.get("markdown") or ""),
            )),
        )
        if score > best_score:
            best, best_score = item, score
    return best, best_score
