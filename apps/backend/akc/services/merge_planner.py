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
# 补充分支的下界必须与 _RELATED_WITH_ENTITY_THRESHOLD 对齐：
# 否则会出现"判定说同一知识点、但没有任何分支接得住，最后又落到 create"的自相矛盾。
_SUPPLEMENT_THRESHOLD = 0.25

# 这两类不进入主知识库的自动合并链路。
_NON_DURABLE_TYPES = {"opinion", "question"}

# 「属于同一知识点」的判定依据（与 prompts.SAME_KNOWLEDGE_CRITERIA 同一口径）。
#
# 四条，缺一不可：
#   1. 同一主题域：domain 不同一律不算同一知识点；
#   2. 核心命题同一：标题/摘要相似度 >= 0.72（0.45~0.72 为"相关但未定"）；
#   3. 核心实体有交集：完全无共同实体且相似度勉强达标的，不算同一知识点；
#   4. 证据可并存：不同消息/会话的同类内容视为补充证据，合并而非新建。
# 例外：opinion/question 不参与合并；与 verified 冲突只能 review。
_SAME_DOMAIN_REQUIRED = True
_ENTITY_OVERLAP_REQUIRED = False  # 仅作加权：有交加分，无交不单独否决（避免漏合并）

# 共享核心实体达到此比例，即认为两条内容在讨论同一对象
_ENTITY_OVERLAP_SAME = 0.34
# 有实体支撑时，标题相似度可放宽到这个阈值（仍需 >= _SUPPLEMENT_THRESHOLD 才会落到"补充"分支）
_RELATED_WITH_ENTITY_THRESHOLD = 0.25

# 主题域一致时的加权系数（让同域的候选在 select_best_match 里胜出）
_DOMAIN_MATCH_BOOST = 1.15
_DOMAIN_MISMATCH_PENALTY = 0.75


def _domain_of(item: dict[str, Any]) -> str:
    """取主题域；缺失时返回空串（视为"未标注"，不参与域的否决判定）。"""
    value = item.get("domain") or item.get("knowledge_domain")
    return str(value or "").strip()


def _entities_of(item: dict[str, Any]) -> set[str]:
    raw = item.get("entities") or item.get("topics") or []
    if isinstance(raw, str):
        raw = [raw]
    return {str(e).strip().lower() for e in raw if str(e).strip()}


def entity_overlap(left: dict[str, Any], right: dict[str, Any]) -> float:
    """核心实体交集比例（Jaccard）；双方都没有实体时返回 0（无从判断，不否决）。"""
    a = _entities_of(left)
    b = _entities_of(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def same_knowledge_verdict(
    candidate: dict[str, Any], existing: dict[str, Any], similarity: float
) -> tuple[bool, str]:
    """判定「是否属于同一知识点」，返回 ``(是否同一, 依据说明)``。

    这是判定依据的**唯一代码入口**：``plan_merge`` 与单测都走这里，
    避免规则在两处各写一套而漂移。
    """
    cand_domain = _domain_of(candidate)
    exist_domain = _domain_of(existing)
    if _SAME_DOMAIN_REQUIRED and cand_domain and exist_domain and cand_domain != exist_domain:
        return False, f"主题域不同（候选 {cand_domain} / 已有 {exist_domain}），不算同一知识点"

    overlap = entity_overlap(candidate, existing)

    # 先给"实体支撑"放行：同一域 + 共享核心实体（如都围绕「南澳岛」）时，
    # 标题措辞不同不应被判成两条知识。中文标题的字符 n-gram 相似度对
    # 换序/增减修饰词非常敏感（"南澳岛入岛预约" vs "南澳岛国庆入岛预约要求"
    # 只有 0.29），只看它会大量漏合并——这正是"同主题被拆成多条"的根因之一。
    if (
        overlap >= _ENTITY_OVERLAP_SAME
        and similarity >= _RELATED_WITH_ENTITY_THRESHOLD
    ):
        return True, (
            f"同一主题域且共享核心实体（交集 {overlap:.2f}），认定为同一知识点"
            f"（标题相似度 {similarity:.2f}，实体支撑）"
        )

    if _ENTITY_OVERLAP_REQUIRED and overlap == 0.0 and similarity < _SEMANTIC_SAME_THRESHOLD:
        return False, f"核心实体无交集（相似度 {similarity:.2f} 未达同一阈值）"

    if similarity < _RELATED_THRESHOLD:
        return False, f"核心命题相似度 {similarity:.2f} 低于相关阈值 {_RELATED_THRESHOLD}"

    if similarity >= _SEMANTIC_SAME_THRESHOLD:
        return True, (
            f"同一主题域、核心命题相同（{similarity:.2f} >= {_SEMANTIC_SAME_THRESHOLD}）"
            f"、实体交集 {overlap:.2f}"
        )
    return True, (
        f"同一主题域且语义相关（{similarity:.2f}），视为同一知识点的补充证据"
        f"、实体交集 {overlap:.2f}"
    )


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

    # 2) 不属于同一知识点 → 新建（判定依据见 same_knowledge_verdict）
    is_same, why = same_knowledge_verdict(candidate, existing, similarity)
    if not is_same:
        return MergeDecision(
            action="create",
            reason=f"不判定为同一知识点：{why}",
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


def raw_similarity(candidate: dict[str, Any], item: dict[str, Any]) -> float:
    """候选与某条已有知识的**原始相似度**（不含域/实体加权）。

    单独抽出来，是为了让「排序用的加权分」与「判定用的真实分」分清楚：
    加权分只决定谁排第一，真正过阈值的必须是原始分，否则会出现
    "select_best_match 说 0.5、plan_merge 算出 0.45 于是新建" 的自相矛盾。
    """
    score = text_similarity(str(candidate.get("title") or ""), str(item.get("title") or ""))
    return max(
        score,
        0.5
        * (
            score
            + text_similarity(
                str(candidate.get("summary") or ""),
                str(item.get("summary") or item.get("markdown") or ""),
            )
        ),
    )


def select_best_match(
    candidate: dict[str, Any], candidates: list[dict[str, Any]]
) -> tuple[dict[str, Any] | None, float]:
    """在已有知识候选中挑出最相似的一条，返回 ``(候选, 原始相似度)``。

    排序时按判定依据加权：同主题域加分、异域减分、实体有交集加分。
    但返回值是**原始相似度**，交给 ``plan_merge`` 按真实阈值判定。
    """
    best: dict[str, Any] | None = None
    best_raw = 0.0
    best_weighted = 0.0
    cand_domain = _domain_of(candidate)

    for item in candidates:
        raw = raw_similarity(candidate, item)
        weighted = raw

        item_domain = _domain_of(item)
        if cand_domain and item_domain:
            weighted *= (
                _DOMAIN_MATCH_BOOST if item_domain == cand_domain else _DOMAIN_MISMATCH_PENALTY
            )

        overlap = entity_overlap(candidate, item)
        if overlap > 0:
            weighted *= 1.0 + 0.15 * overlap

        if weighted > best_weighted:
            best, best_raw, best_weighted = item, raw, weighted
    return best, best_raw
