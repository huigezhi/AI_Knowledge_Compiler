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
