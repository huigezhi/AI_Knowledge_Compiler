"""API 冒烟测试：关键端点连通性与错误契约（需求文档 §11 / §11.2）。"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def _conversation_payload() -> dict:
    return {
        "id": "conv_1",
        "provider": "deepseek",
        "provider_conversation_id": "ext-1",
        "title": "SQL 优化",
        "messages": [
            {"id": "m1", "role": "user", "sequence": 0, "content": [{"type": "text", "text": "怎么优化"}]},
            {"id": "m2", "role": "assistant", "sequence": 1, "content": [{"type": "text", "text": "看执行计划"}]},
        ],
        "content_hash": "sha256:" + "0" * 64,
    }


def test_health(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["schema_version"] == "1.0.0"


def test_ready(client: TestClient) -> None:
    assert client.get("/api/v1/ready").status_code == 200


def test_request_id_header(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.headers.get("X-Request-ID")


def test_providers(client: TestClient) -> None:
    body = client.get("/api/v1/providers").json()
    ids = {item["id"] for item in body["items"]}
    assert {"chatgpt", "claude", "deepseek", "doubao", "zhipu"} <= ids
    assert body["count"] == 5


def test_import_and_list(client: TestClient) -> None:
    response = client.post(
        "/api/v1/conversations/import",
        json={"conversation": _conversation_payload(), "options": {}},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["created"] is True
    assert body["created_messages"] == 2

    listed = client.get("/api/v1/conversations").json()
    assert listed["total"] == 1

    detail = client.get(f"/api/v1/conversations/{body['conversation_id']}").json()
    assert len(detail["messages"]) == 2

    exported = client.get(f"/api/v1/conversations/{body['conversation_id']}/export?fmt=json").json()
    assert exported["format"] == "json"


def test_import_rejects_invalid_payload(client: TestClient) -> None:
    payload = _conversation_payload()
    del payload["provider_conversation_id"]
    response = client.post("/api/v1/conversations/import", json={"conversation": payload})
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "SCHEMA_VALIDATION_FAILED"
    assert body["request_id"]


def test_not_found_contract(client: TestClient) -> None:
    response = client.get("/api/v1/conversations/missing")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_job_compile_enqueue(client: TestClient) -> None:
    imported = client.post(
        "/api/v1/conversations/import", json={"conversation": _conversation_payload()}
    ).json()
    job = client.post(
        "/api/v1/jobs/compile", json={"conversation_id": imported["conversation_id"]}
    ).json()
    assert job["status"] == "pending"
    assert client.get(f"/api/v1/jobs/{job['id']}").status_code == 200


def test_settings_roundtrip(client: TestClient) -> None:
    body = client.get("/api/v1/settings").json()
    assert "vault_path" in body["values"]

    updated = client.put("/api/v1/settings", json={"values": {"vault_raw_folder": "01_Raw"}})
    assert updated.status_code == 200
    assert updated.json()["updated"] == ["vault_raw_folder"]

    rejected = client.put("/api/v1/settings", json={"values": {"claude_api_key": "nope"}}).json()
    assert rejected["rejected"] == ["claude_api_key"]


def test_obsidian_sync_writes_knowledge(client: TestClient, vault: Path) -> None:
    client.put("/api/v1/settings", json={"values": {"vault_path": str(vault)}})

    imported = client.post(
        "/api/v1/conversations/import", json={"conversation": _conversation_payload()}
    ).json()

    raw = client.post(
        "/api/v1/obsidian/sync",
        json={"conversation_ids": [imported["conversation_id"]]},
    ).json()
    assert raw["written"][0]["changed"] is True
    assert Path(raw["written"][0]["path"]).exists()

    from akc.repositories import knowledge as kn_repo
    from akc.db import get_session_factory

    session = get_session_factory()()
    try:
        item = kn_repo.create(
            session,
            knowledge_id="k_smoke",
            slug="sql-method",
            title="SQL 方法",
            knowledge_type="method",
            summary="先看执行计划",
            markdown="## 方法\n1. 看执行计划",
            confidence=0.8,
        )
        kn_repo.link_sources(
            session,
            knowledge_id=item.id,
            # 使用真实入库的 message id，验证 Raw → Knowledge 的 Wiki Link 溯源
            message_ids=["m1"],
            conversation_id=imported["conversation_id"],
        )
        session.commit()
    finally:
        session.close()

    synced = client.post("/api/v1/obsidian/sync", json={"knowledge_ids": ["k_smoke"]}).json()
    assert synced["written"][0]["path"].endswith("sql-method.md")
    text = Path(synced["written"][0]["path"]).read_text(encoding="utf-8")
    assert "type: knowledge" in text
    assert "[[Deepseek - SQL 优化 -" in text


def test_obsidian_sync_requires_vault(client: TestClient) -> None:
    response = client.post("/api/v1/obsidian/sync", json={"knowledge_ids": []})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "OBSIDIAN_VAULT_NOT_CONFIGURED"


def test_knowledge_review_flow(client: TestClient) -> None:
    from akc.db import get_session_factory
    from akc.repositories import knowledge as kn_repo

    session = get_session_factory()()
    try:
        kn_repo.create(
            session, knowledge_id="k_review", slug="k-review", title="待审核", status="candidate"
        )
        session.commit()
    finally:
        session.close()

    verified = client.post("/api/v1/knowledge/k_review/review", json={"action": "verify"})
    assert verified.status_code == 200
    assert verified.json()["status"] == "verified"

    bad = client.post("/api/v1/knowledge/k_review/review", json={"action": "unknown"})
    assert bad.status_code == 400
