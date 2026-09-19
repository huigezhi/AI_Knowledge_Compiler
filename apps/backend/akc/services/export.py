"""Markdown / JSON 导出（需求文档 §3.1）。

Raw 导出与 Obsidian 写入共用同一套模板，保证「导出的」与「写入 Vault 的」一致。
"""

from __future__ import annotations

import json
from typing import Any

from akc.services.obsidian import build_raw_markdown


def export_conversation(conversation: dict[str, Any], *, fmt: str = "markdown") -> tuple[str, str]:
    """返回 ``(content, media_type)``。"""
    if fmt == "json":
        return json.dumps(conversation, ensure_ascii=False, indent=2), "application/json"
    if fmt == "markdown":
        return build_raw_markdown(conversation), "text/markdown"
    raise ValueError(f"unsupported export format: {fmt}")


def export_knowledge_bundle(items: list[dict[str, Any]]) -> str:
    """把多条知识打包成一个 JSON（便于备份与人工审阅）。"""
    return json.dumps({"version": 1, "items": items}, ensure_ascii=False, indent=2)
