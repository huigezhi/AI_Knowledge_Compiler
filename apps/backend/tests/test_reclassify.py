"""重新分类与归并（手动整理工具）：预览 -> 确认 -> 执行；合并可撤销。"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from akc.repositories import knowledge as kn_repo
from akc.services import reclassify_service

_counter = 0


def _create(session, *, title: str, summary: str, domain: str = "其他", status: str = "candidate") -> str:
    global _counter
    _counter += 1
    item = kn_repo.create(
        session,
        knowledge_id=f"k_reclass_{_counter}_{uuid.uuid4().hex[:6]}",
        slug=f"slug-reclass-{_counter}",
        title=title,
        knowledge_type="fact",
        domain=domain,
        summary=summary,
        markdown=summary,
        status=status,
    )
    session.flush()
    return item.id


def test_plan_reclassifies_other_by_keywords(session) -> None:
    """误归入「其他」的经济类 / 编程类内容应被规则正确捞回来。"""
    econ = _create(session, title="2026年7月中国CPI与PPI数据要点", summary="CPI 低位震荡，PPI 降幅收窄，央行强调流动性。")
    tech = _create(session, title="nvm-windows 与 conda 会破坏 dsh 全局命令环境", summary="切换 node 版本后 npm prefix 变化，PATH 需同步更新。")
    travel = _create(session, title="广州出发国庆出游清单", summary="按假期时长分层的目的地与交通方式。")
    session.flush()

    plan_result = reclassify_service.plan(session, domain=None, force=False)
    to_map = {c["id"]: c["to"] for c in plan_result["reclassify"]}
    assert to_map.get(econ) == "金融投资"
    assert to_map.get(tech) == "编程技术"
    assert to_map.get(travel) == "休闲旅游"


def test_plan_does_not_touch_non_other_by_default(session) -> None:
    """force=False 时不动已分类的条目（避免越理越乱）。"""
    _create(session, title="CPI 数据要点", summary="CPI 走势。", domain="编程技术")
    session.flush()

    plan_result = reclassify_service.plan(session, domain=None, force=False)
    assert plan_result["reclassify"] == []

    forced = reclassify_service.plan(session, domain=None, force=True)
    assert any(c["to"] == "金融投资" for c in forced["reclassify"])


def test_plan_merges_highly_similar_items(session) -> None:
    """高度相近的条目（同域、同义）应进入归并计划，保留更早/更权威的一条。"""
    _create(session, title="国庆出行通用操作贴士：预订与避峰", summary="提前预订酒店与车票，避开高峰时段出行。", status="verified")
    dup = _create(session, title="国庆出行通用操作贴士（预订避峰）", summary="提前预订酒店与车票，避开高峰时段出行。")

    plan_result = reclassify_service.plan(session, domain=None, force=False)
    pair = next(
        (m for m in plan_result["merges"] if dup in (m["drop_id"], m["keep_id"])),
        None,
    )
    assert pair is not None
    assert pair["drop_id"] == dup  # verified 的保留，重复的并入


def test_apply_reclassify_and_merge(session) -> None:
    keep = _create(session, title="南澳岛国庆入岛预约要求", summary="国庆期间南澳岛入岛需提前预约。", status="verified")
    _create(session, title="南澳岛国庆入岛需要预约", summary="国庆期间南澳岛入岛需提前预约。")
    _create(session, title="龙脊梯田观赏期", summary="国庆为金黄梯田最佳观赏期。", domain="其他")

    plan_result = reclassify_service.plan(session, domain=None, force=False)
    result = reclassify_service.apply(session, plan_result)

    assert result["domain_changes"] >= 1
    assert result["merges_applied"] >= 1
    session.expire_all()
    dropped = [i for i in session.query(kn_repo.Knowledge).all() if i.status == "merged"]
    assert any(i.superseded_by for i in dropped)


def test_delete_action_and_fts_exclusion(session, client: TestClient) -> None:
    kid = _create(session, title="要删除的条目", summary="内容")
    session.commit()

    response = client.post(f"/api/v1/knowledge/{kid}/review", json={"action": "delete"})
    assert response.status_code == 200
    assert response.json()["status"] == "deleted"

    # 默认列表（不含 inactive）不再出现
    listed = client.get("/api/v1/knowledge").json()
    assert all(item["id"] != kid for item in listed["items"])
    # FTS 也不再命中
    searched = client.get("/api/v1/knowledge/search", params={"q": "要删除的条目"}).json()
    assert all(item["id"] != kid for item in searched["items"])

    # 误删可恢复：deleted -> candidate
    restore = client.post(f"/api/v1/knowledge/{kid}/review", json={"action": "restore"})
    assert restore.status_code == 200
    assert restore.json()["status"] == "candidate"
