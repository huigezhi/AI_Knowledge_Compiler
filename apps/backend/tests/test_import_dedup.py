"""导入幂等与去重（E2E-03）。"""

from __future__ import annotations

from sqlalchemy.orm import Session

from akc.config import Settings
from akc.repositories import conversation as conv_repo
from akc.repositories import message as msg_repo
from akc.services.import_service import import_conversation


def _payload(title: str = "SQL 优化", body: str = "first answer") -> dict:
    return {
        "id": "conv_1",
        "provider": "deepseek",
        "provider_conversation_id": "ext-1",
        "title": title,
        "messages": [
            {"id": "m1", "role": "user", "sequence": 0, "content": [{"type": "text", "text": "question"}]},
            {
                "id": "m2",
                "role": "assistant",
                "sequence": 1,
                "content": [{"type": "text", "text": body}],
            },
        ],
        "content_hash": "sha256:" + "0" * 64,
    }


def test_second_import_creates_no_duplicates(session: Session, settings: Settings) -> None:
    first = import_conversation(session, _payload(), settings=settings)
    assert first["created"] is True
    assert first["created_messages"] == 2

    second = import_conversation(session, _payload(), settings=settings)
    assert second["created"] is False
    assert second["created_messages"] == 0
    assert second["updated_messages"] == 0

    rows = msg_repo.list_messages(session, first["conversation_id"])
    assert len(rows) == 2


def test_changed_content_updates_in_place(session: Session, settings: Settings) -> None:
    first = import_conversation(session, _payload(), settings=settings)
    second = import_conversation(session, _payload(body="revised answer"), settings=settings)
    assert second["created"] is False
    assert second["updated_messages"] == 1
    rows = msg_repo.list_messages(session, first["conversation_id"])
    assert len(rows) == 2
    assert "revised answer" in rows[1].content_json[0]["text"]


def test_import_enqueues_compile_job_when_requested(session: Session, settings: Settings) -> None:
    result = import_conversation(
        session, _payload(), settings=settings, options={"compile": True}
    )
    assert result["job_id"] is not None


def test_raw_markdown_written_to_vault(session: Session, settings: Settings, vault) -> None:  # noqa: ANN001
    result = import_conversation(
        session, _payload(), settings=settings, options={"write_raw_to_obsidian": True}
    )
    assert result["obsidian_path"] is not None
    path = __import__("pathlib").Path(result["obsidian_path"])
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---")
    assert "type: raw_chat" in text
    assert "provider: deepseek" in text
    assert "## User" in text and "## Assistant" in text


def test_vault_failure_does_not_lose_raw_data(session: Session, settings: Settings) -> None:
    settings.vault_path = None
    result = import_conversation(
        session, _payload(), settings=settings, options={"write_raw_to_obsidian": True}
    )
    assert result["conversation_id"]
    assert any("obsidian" in warning for warning in result["warnings"])
    conv = conv_repo.get(session, result["conversation_id"])
    assert conv is not None
    assert len(msg_repo.list_messages(session, conv.id)) == 2


# ---------------------------------------------------------------- 编译开关
def test_explicit_compile_false_overrides_server_auto_compile(
    session: Session, settings: Settings
) -> None:
    """服务端开了 AKC_AUTO_COMPILE 时，客户端显式 compile=False 必须能关掉编译。

    否则扩展里的「是否开启 AI 编译」开关形同虚设：服务端照样入队。
    """
    from akc.repositories import job as job_repo

    settings.auto_compile = True
    import_conversation(session, _payload(body="a"), options={"compile": False}, settings=settings)
    jobs = [j for j in job_repo.list_jobs(session, limit=100) if j.job_type == "COMPILE_CONVERSATION"]
    assert len(jobs) == 0, "显式 compile=False 却仍然入队了编译任务"


def test_explicit_compile_true_enqueues_even_when_server_disabled(
    session: Session, settings: Settings
) -> None:
    from akc.repositories import job as job_repo

    settings.auto_compile = False
    import_conversation(session, _payload(body="b"), options={"compile": True}, settings=settings)
    jobs = [j for j in job_repo.list_jobs(session, limit=100) if j.job_type == "COMPILE_CONVERSATION"]
    assert len(jobs) == 1


def test_omitted_compile_falls_back_to_server_auto_compile(
    session: Session, settings: Settings
) -> None:
    """不表态时沿用服务端配置（兼容脚本等不传该字段的调用方）。"""
    from akc.repositories import job as job_repo

    settings.auto_compile = True
    import_conversation(session, _payload(body="c"), options={}, settings=settings)
    jobs = [j for j in job_repo.list_jobs(session, limit=100) if j.job_type == "COMPILE_CONVERSATION"]
    assert len(jobs) == 1


# ---------------------------------------------------------------- 编译开关
def test_explicit_compile_false_overrides_server_auto_compile(
    session: Session, settings: Settings
) -> None:
    """服务端开了 AKC_AUTO_COMPILE 时，客户端显式 compile=False 必须能关掉编译。

    否则扩展里的「是否开启 AI 编译」开关形同虚设：服务端照样入队。
    """
    from akc.repositories import job as job_repo

    settings.auto_compile = True
    import_conversation(session, _payload(body="a"), options={"compile": False}, settings=settings)
    jobs = [j for j in job_repo.list_jobs(session, limit=100) if j.job_type == "COMPILE_CONVERSATION"]
    assert len(jobs) == 0, "显式 compile=False 却仍然入队了编译任务"


def test_explicit_compile_true_enqueues_even_when_server_disabled(
    session: Session, settings: Settings
) -> None:
    from akc.repositories import job as job_repo

    settings.auto_compile = False
    import_conversation(session, _payload(body="b"), options={"compile": True}, settings=settings)
    jobs = [j for j in job_repo.list_jobs(session, limit=100) if j.job_type == "COMPILE_CONVERSATION"]
    assert len(jobs) == 1


def test_omitted_compile_falls_back_to_server_auto_compile(
    session: Session, settings: Settings
) -> None:
    """不表态时沿用服务端配置（兼容脚本等不传该字段的调用方）。"""
    from akc.repositories import job as job_repo

    settings.auto_compile = True
    import_conversation(session, _payload(body="c"), options={}, settings=settings)
    jobs = [j for j in job_repo.list_jobs(session, limit=100) if j.job_type == "COMPILE_CONVERSATION"]
    assert len(jobs) == 1
