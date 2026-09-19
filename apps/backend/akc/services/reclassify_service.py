"""知识重新分类与归并（手动触发的整理工具，需求：主题分类纠偏 + 相似合并）。

设计要点：
* **先预览、后执行**：``plan()`` 只算不落库（dry_run），用户确认后再 ``apply()``；
* 分类用**规则式关键词**判定（标题 + 摘要），不依赖 LLM：快、免费、结果可预期；
* 归并只在**同一个主题域内**做（跨域合并没有意义），且基于可撤销的
  ``review_service.merge_knowledge``（source 标记 merged + superseded_by，可 unmerge）；
* 只动指定域的数据，其他主题不受影响。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from akc.repositories import knowledge as kn_repo
from akc.services.merge_planner import text_similarity

# 主题域判定规则：按顺序命中即停（前面的优先级更高）。
# 关键词覆盖用户点名的"经济类"（CPI/PPI/M1/M2/央行……归入金融投资）。
DOMAIN_RULES: list[tuple[str, tuple[str, ...]]] = [
    (
        "金融投资",
        (
            "经济", "金融", "投资", "股票", "基金", "理财", "通胀", "通缩", "cpi", "ppi",
            "m1", "m2", "央行", "货币", "汇率", "gdp", "利率", "存款", "贷款", "证券",
            "期货", "债券", "宏观",
        ),
    ),
    (
        "编程技术",
        (
            "编程", "代码", "git", "github", "python", "javascript", "typescript",
            "java", "sql", "api", "程序", "算法", "开发", "软件", "编译", "脚本",
            "命令行", "环境变量", "node", "npm", "终端", "服务器", "部署", "docker",
            "linux", "windows", "gpu", "显卡", "驱动", "虚焊", "笔记本", "数据库",
            "模型部署", "显卡", "硬件", "报错", "排查", "安装",
        ),
    ),
    (
        "休闲旅游",
        (
            "旅游", "旅行", "景点", "行程", "出游", "攻略", "机票", "酒店", "景区",
            "门票", "自驾", "假期", "目的地", "梯田", "古镇", "海岛",
        ),
    ),
    (
        "工作职场",
        (
            "工作", "职场", "会议", "周报", "汇报", "简历", "面试", "加班", "绩效",
            "同事", "领导", "办公", "出访", "外交",
        ),
    ),
    (
        "学习成长",
        ("学习", "课程", "教程", "笔记", "读书", "考试", "培训", "方法论", "知识点"),
    ),
    (
        "生活健康",
        (
            "健康", "睡眠", "运动", "饮食", "美食", "烹饪", "食谱", "就医", "体检",
            "中秋", "节日", "习俗", "月饼",
        ),
    ),
]

# 归并阈值：标题/摘要 bigram 相似度达到该值才视为"高度相近"。
# 预览确认后再执行，且合并可撤销（unmerge），阈值不宜过松。
_MERGE_SIMILARITY_THRESHOLD = 0.55


def classify_text(title: str, summary: str) -> str | None:
    """规则式主题域判定；都不命中返回 None（保持原域）。"""
    text = f"{title} {summary}".lower()
    for domain, keywords in DOMAIN_RULES:
        if any(keyword in text for keyword in keywords):
            return domain
    return None


def _keep_and_drop(a: dict[str, Any], b: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """归并时决定保留哪条：优先 verified > candidate/review，其次更早创建。"""
    rank = {"verified": 0, "candidate": 1, "review": 2}
    rank_a = rank.get(str(a.get("status") or ""), 9)
    rank_b = rank.get(str(b.get("status") or ""), 9)
    if rank_a != rank_b:
        return (a, b) if rank_a < rank_b else (b, a)
    return (a, b) if str(a.get("created_at") or "") <= str(b.get("created_at") or "") else (b, a)


def plan(
    session: Session,
    *,
    domain: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """计算重新分类与归并计划，**不落库**。

    ``domain`` 只处理该主题域（None = 全部）；``force=False`` 时只重判
    ``其他`` 的条目 —— 已被人工/模型分好类的默认不动，避免越理越乱。
    """
    rows, _total = kn_repo.list_knowledge(
        session, domain=domain, limit=500, offset=0
    )
    items = [kn_repo.to_dict(row) for row in rows]

    # --- 1) 重新分类 -------------------------------------------------------
    reclassify: list[dict[str, Any]] = []
    for item in items:
        if not force and item.get("domain") != "其他":
            continue
        target = classify_text(str(item.get("title") or ""), str(item.get("summary") or ""))
        if target and target != item.get("domain"):
            reclassify.append(
                {"id": item["id"], "title": item["title"], "from": item.get("domain"), "to": target}
            )

    # 分类结果在内存里先生效，归并按"整理后的域"分组
    domain_of = {item["id"]: item.get("domain") for item in items}
    for change in reclassify:
        domain_of[change["id"]] = change["to"]

    # --- 2) 域内归并 -------------------------------------------------------
    by_domain: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        by_domain.setdefault(str(domain_of.get(item["id"], item.get("domain"))), []).append(item)

    merges: list[dict[str, Any]] = []
    dropped: set[str] = set()
    for group in by_domain.values():
        if len(group) < 2:
            continue
        for index, candidate in enumerate(group):
            if candidate["id"] in dropped:
                continue
            for other in group[index + 1 :]:
                if other["id"] in dropped:
                    continue
                similarity = max(
                    text_similarity(
                        str(candidate.get("title") or ""), str(other.get("title") or "")
                    ),
                    0.5
                    * (
                        text_similarity(
                            str(candidate.get("title") or ""), str(other.get("title") or "")
                        )
                        + text_similarity(
                            str(candidate.get("summary") or ""),
                            str(other.get("summary") or other.get("markdown") or ""),
                        )
                    ),
                )
                if similarity < _MERGE_SIMILARITY_THRESHOLD:
                    continue
                keep, drop = _keep_and_drop(candidate, other)
                merges.append(
                    {
                        "keep_id": keep["id"],
                        "keep_title": keep["title"],
                        "drop_id": drop["id"],
                        "drop_title": drop["title"],
                        "similarity": round(similarity, 3),
                    }
                )
                dropped.add(drop["id"])

    return {
        "reclassify": reclassify,
        "merges": merges,
        "total": len(items),
        "note": "预览：确认后才会应用；合并可随时撤销（unmerge）。",
    }


def apply(session: Session, plan_result: dict[str, Any], *, reason: str = "reclassify") -> dict[str, Any]:
    """执行计划：先改域，再归并。返回实际发生的变更数量。"""
    from akc.services import review_service

    domain_changes = 0
    for change in plan_result.get("reclassify") or []:
        item = kn_repo.get(session, str(change["id"]))
        if item is None:
            continue
        item.domain = str(change["to"])
        domain_changes += 1
    session.flush()

    merged = 0
    for pair in plan_result.get("merges") or []:
        if kn_repo.get(session, str(pair["drop_id"])) is None:
            continue  # 可能已被更早的合并吸收
        review_service.merge_knowledge(
            session, str(pair["drop_id"]), str(pair["keep_id"]), reason=reason
        )
        merged += 1

    session.commit()
    # 键名不能用 merges：预览阶段 merges 是「待合并列表」，执行阶段是「已合并数量」，
    # 同名不同类会让调用方（前端）无法静态描述，只能靠运行期猜。
    return {
        "domain_changes": domain_changes,
        "merges_applied": merged,
        "note": "已应用。合并可用 unmerge 撤销。",
    }
