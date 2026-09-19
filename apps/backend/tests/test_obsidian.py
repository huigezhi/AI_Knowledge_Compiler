"""Obsidian 写入：模板、原子替换、冲突检测（需求文档 §10 / §18.3）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from akc.errors import ConflictError
from akc.services import obsidian


def _conversation() -> dict:
    return {
        "provider": "deepseek",
        "provider_conversation_id": "ext-1",
        "title": "SQL 优化",
        "content_hash": "sha256:" + "a" * 64,
        "schema_version": "1.0.0",
        "adapter_version": "0.1.0",
        "created_at": "2026-09-18T20:31:00+08:00",
        "updated_at": "2026-09-18T21:10:00+08:00",
        "messages": [
            {"sequence": 0, "role": "user", "content": [{"type": "text", "text": "怎么优化 SQL？"}]},
            {
                "sequence": 1,
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "先看执行计划。"},
                    {"type": "code", "language": "sql", "text": "EXPLAIN SELECT 1;"},
                ],
            },
        ],
    }


def test_raw_markdown_has_frontmatter_and_structure() -> None:
    md = obsidian.build_raw_markdown(_conversation())
    assert md.startswith("---")
    assert "type: raw_chat" in md
    assert "provider: deepseek" in md
    assert "content_hash: \"sha256:" in md
    assert "```sql" in md  # 代码块结构必须保留
    assert "## User" in md and "## Assistant" in md


def test_knowledge_markdown_template() -> None:
    md = obsidian.build_knowledge_markdown(
        title="SQL 查询性能优化方法",
        knowledge_type="method",
        status="candidate",
        summary="先看执行计划。",
        body_markdown="## 方法\n1. ...",
        confidence=0.86,
        topics=["SQL"],
        entities=["SQL Server"],
        source_links=["[[DeepSeek - SQL优化 - 2026-09-18]]"],
        created_at="2026-09-18T21:30:00+08:00",
        updated_at="2026-09-18T21:30:00+08:00",
        prompt_version="extractor-v1",
        model="configured-model",
    )
    assert "type: knowledge" in md
    assert "knowledge_type: method" in md
    assert "status: candidate" in md
    assert "confidence: 0.86" in md
    assert "[[DeepSeek - SQL优化 - 2026-09-18]]" in md
    assert "## 来源证据" in md


def test_slugify() -> None:
    assert obsidian.slugify("SQL 优化: 方法?") == "SQL-优化-方法"
    assert obsidian.slugify("") == "untitled"
    assert obsidian.slugify("a\\b/c*d|e\"f<g>h") == "a-b-c-d-e-f-g-h"


def test_write_then_rewrite_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "note.md"
    md = obsidian.build_raw_markdown(_conversation())
    _, changed_first = obsidian.write_markdown(path, md)
    _, changed_second = obsidian.write_markdown(path, md)
    assert changed_first is True
    assert changed_second is False


def test_refuses_to_overwrite_human_edited_file(tmp_path: Path) -> None:
    path = tmp_path / "note.md"
    path.write_text("# 我手动写的笔记\n", encoding="utf-8")
    with pytest.raises(ConflictError):
        obsidian.write_markdown(path, obsidian.build_raw_markdown(_conversation()))


def test_atomic_replace_leaves_no_temp_files(tmp_path: Path) -> None:
    path = tmp_path / "note.md"
    obsidian.write_markdown(path, obsidian.build_raw_markdown(_conversation()))
    leftovers = [p for p in tmp_path.iterdir() if p.name.startswith(".akc-")]
    assert leftovers == []


def test_vault_layout_folders() -> None:
    layout = obsidian.VaultLayout(vault_path=Path("/vault"))
    assert layout.raw_dir("deepseek") == Path("/vault/01_Raw/DeepSeek")
    # 主题域目录：知识按 编程/金融/旅游 等一级域分类（类型在 frontmatter）
    assert layout.knowledge_dir("编程技术") == Path("/vault/03_Knowledge/编程技术")
    assert layout.knowledge_dir("") == Path("/vault/03_Knowledge/其他")
    assert layout.raw_dir("chatgpt") == Path("/vault/01_Raw/ChatGPT")


def test_resolve_vault_raises_when_unset() -> None:
    from akc.errors import ObsidianVaultNotConfiguredError

    with pytest.raises(ObsidianVaultNotConfiguredError):
        obsidian.resolve_vault(None)


def test_sync_knowledge_writes_to_domain_folder(session, settings, tmp_path) -> None:
    """sync_knowledge：按主题域目录落盘（03_Knowledge/<域名>/<slug>.md）。"""
    from akc.repositories import knowledge as kn_repo
    from akc.services import obsidian

    settings.vault_path = tmp_path
    entity = kn_repo.create(
        session,
        knowledge_id="k_dom",
        slug="测试知识条目",
        title="测试知识条目",
        knowledge_type="method",
        domain="编程技术",
        summary="摘要",
        markdown="正文",
    )
    result = obsidian.sync_knowledge(session, settings, [entity.id])
    assert len(result["written"]) == 1
    written = Path(result["written"][0]["path"])
    assert "03_Knowledge" in written.parts and "编程技术" in written.parts
    assert written.exists()


def test_sync_knowledge_skips_missing(session, settings, tmp_path) -> None:
    from akc.services import obsidian

    settings.vault_path = tmp_path
    result = obsidian.sync_knowledge(session, settings, ["k_missing"])
    # 缺失的知识直接 skip，不应抛异常
    assert result["written"] == []
    assert result["skipped"] == [{"id": "k_missing", "reason": "knowledge not found"}]
