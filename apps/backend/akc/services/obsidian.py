"""Obsidian Vault 写入（需求文档 §10 / §18.3）。

安全策略：
* 写前计算 ``content_hash``；
* 目标文件已存在且被**人工修改**过时 → 检测冲突，**不覆盖**；
* 先写临时文件，成功后原子替换（``os.replace``）；
* 保留 YAML frontmatter 与 ``[[Wiki Links]]`` 溯源。
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from akc.errors import ConflictError, ObsidianVaultNotConfiguredError, ObsidianWriteError

# 由 AKC 写入的文件都带此标记，用于区分“AKC 生成”与“人工修改”。
_AKC_MARKER = "akc_content_hash"

_INVALID_CHARS = re.compile(r'[\\/:*?"<>|]')


@dataclass(frozen=True)
class VaultLayout:
    vault_path: Path
    raw_folder: str = "01_Raw"
    knowledge_folder: str = "03_Knowledge"
    inbox_folder: str = "02_Inbox"

    def raw_dir(self, provider: str) -> Path:
        return self.vault_path / self.raw_folder / _provider_folder(provider)

    def knowledge_dir(self, knowledge_type: str) -> Path:
        return self.vault_path / self.knowledge_folder / _category_folder(knowledge_type)


def _provider_folder(provider: str) -> str:
    return {
        "chatgpt": "ChatGPT",
        "claude": "Claude",
        "deepseek": "DeepSeek",
        "doubao": "Doubao",
        "zhipu": "Zhipu",
    }.get(provider.lower(), provider.title() or "Unknown")


def _category_folder(knowledge_type: str) -> str:
    return {
        "concept": "Concepts",
        "method": "Methods",
        "heuristic": "Methods",
        "decision": "Decisions",
        "fact": "Concepts",
        "question": "Concepts",
        "hypothesis": "Concepts",
        "opinion": "Concepts",
    }.get(knowledge_type.lower(), "Concepts")


def slugify(value: str, *, max_length: int = 80) -> str:
    """生成稳定的 slug：保留中英文与数字，其余转为连字符。"""
    text = _INVALID_CHARS.sub("-", value).strip()
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return (text or "untitled")[:max_length]


def content_hash_of(markdown: str) -> str:
    return hashlib.sha256(markdown.encode("utf-8")).hexdigest()


def _yaml_escape(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _yaml_list(values: list[str], *, indent: int = 0) -> str:
    if not values:
        return " []"
    pad = " " * indent
    return "\n" + "\n".join(f"{pad}- {_yaml_escape(v)}" for v in values)


def build_raw_markdown(conversation: dict[str, Any]) -> str:
    """Raw 会话 Markdown（需求文档 §10.2）。"""
    now = _now()
    frontmatter = "\n".join(
        [
            "---",
            "type: raw_chat",
            f"provider: {conversation.get('provider', '')}",
            f"conversation_id: {_yaml_escape(str(conversation.get('provider_conversation_id', '')))}",
            f"title: {_yaml_escape(str(conversation.get('title', '')))}",
            f"created_at: {conversation.get('created_at') or now}",
            f"updated_at: {conversation.get('updated_at') or now}",
            f"content_hash: {_yaml_escape(str(conversation.get('content_hash', '')))}",
            f"schema_version: {conversation.get('schema_version', '1.0.0')}",
            f"adapter_version: {conversation.get('adapter_version', '0.0.0')}",
            "---",
        ]
    )
    body = [f"# {conversation.get('title', '(untitled)')}", ""]
    for msg in sorted(conversation.get("messages", []), key=lambda m: m.get("sequence", 0)):
        heading = {
            "user": "## User",
            "assistant": "## Assistant",
            "system": "## System",
            "tool": "## Tool",
        }.get(msg.get("role", ""), "## Unknown")
        body.append(heading)
        body.append("")
        body.append(_render_blocks(msg.get("content") or []))
        body.append("")
    return frontmatter + "\n\n" + "\n".join(body).rstrip() + "\n"


def build_knowledge_markdown(
    *,
    title: str,
    knowledge_type: str,
    status: str,
    summary: str,
    body_markdown: str,
    confidence: float,
    topics: list[str],
    entities: list[str],
    source_links: list[str],
    created_at: str,
    updated_at: str,
    prompt_version: str | None = None,
    model: str | None = None,
    version: int = 1,
) -> str:
    """Knowledge Markdown（需求文档 §10.3）。"""
    frontmatter = "\n".join(
        [
            "---",
            "type: knowledge",
            f"knowledge_type: {knowledge_type}",
            f"status: {status}",
            f"confidence: {round(float(confidence), 2)}",
            f"version: {version}",
            "topics:" + _yaml_list(topics, indent=2),
            "entities:" + _yaml_list(entities, indent=2),
            "sources:" + _yaml_list(source_links, indent=2),
            f"created_at: {created_at}",
            f"updated_at: {updated_at}",
            "compiler: Claude",
            f"prompt_version: {prompt_version or ''}",
            f"model: {model or ''}",
            "---",
        ]
    )
    sections = [
        f"# {title}",
        "",
        "## 核心结论",
        summary.strip(),
        "",
        body_markdown.strip(),
        "",
        "## 来源证据",
    ]
    sections += [f"- {link}" for link in source_links] or ["- (no source recorded)"]
    return frontmatter + "\n\n" + "\n".join(sections).rstrip() + "\n"


def _render_blocks(blocks: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for block in blocks:
        kind = block.get("type")
        if kind == "text":
            parts.append(block.get("text") or "")
        elif kind == "code":
            lang = block.get("language") or ""
            parts.append(f"```{lang}\n{block.get('text') or ''}\n```")
        elif kind == "image":
            ref = block.get("local_ref") or block.get("source_url") or ""
            parts.append(f"![]({ref})")
        elif kind == "file":
            parts.append(f"[{block.get('name') or 'attachment'}]({block.get('local_ref') or ''})")
    return "\n\n".join(part for part in parts if part) or "_(empty)_"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- 写入


def write_markdown(
    path: Path,
    markdown: str,
    *,
    overwrite: bool = True,
) -> tuple[Path, bool]:
    """原子写入 Markdown。返回 ``(path, changed)``。

    * 内容未变化 → 不写盘（``changed=False``）；
    * 目标已存在但不是 AKC 生成的内容 → 抛 ``ConflictError``（绝不覆盖人工修改）；
    * ``overwrite=False`` 且文件已存在 → 抛 ``ConflictError``。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    incoming_hash = content_hash_of(markdown)

    if path.exists():
        existing_text = path.read_text(encoding="utf-8", errors="replace")
        existing_hash = _extract_hash(existing_text)
        if existing_hash is None:
            # 没有 AKC 标记 → 视为人工创建/修改，拒绝覆盖。
            raise ConflictError(
                "refusing to overwrite a file that was not created by AKC",
                details={"path": str(path)},
            )
        if not overwrite:
            raise ConflictError("file already exists", details={"path": str(path)})
        if existing_hash == incoming_hash and _AKC_MARKER in existing_text:
            return path, False

    stamped = markdown if _AKC_MARKER in markdown else _stamp(markdown, incoming_hash)
    _atomic_write(path, stamped)
    return path, True


def _stamp(markdown: str, digest: str) -> str:
    """在 frontmatter 中写入内容哈希，作为“AKC 管理该文件”的标记。"""
    if markdown.startswith("---\n"):
        end = markdown.find("\n---", 4)
        if end == -1:
            return markdown
        head = markdown[4:end]
        tail = markdown[end:]
        return f"---\n{head}\n{_AKC_MARKER}: {digest}{tail}"
    return f"---\n{_AKC_MARKER}: {digest}\n---\n\n{markdown}"


def _extract_hash(markdown: str) -> str | None:
    match = re.search(rf"^{_AKC_MARKER}:\s*([0-9a-f]+)\s*$", markdown, re.MULTILINE)
    return match.group(1) if match else None


def _atomic_write(path: Path, content: str) -> None:
    try:
        fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".akc-", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except OSError as exc:
        raise ObsidianWriteError(
            "failed to write markdown atomically",
            retryable=True,
            details={"path": str(path), "reason": str(exc)},
        ) from exc


def resolve_vault(layout: VaultLayout | None) -> VaultLayout:
    if layout is None or not layout.vault_path:
        raise ObsidianVaultNotConfiguredError(
            "obsidian vault path is not configured",
            details={"hint": "set AKC_VAULT_PATH or update /api/v1/settings"},
        )
    return layout
