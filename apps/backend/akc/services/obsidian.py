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

    def knowledge_dir(self, domain: str) -> Path:
        """知识一级目录 = 主题域（编程技术 / 金融投资 / 休闲旅游 / 工作……）。

        需求变更：以前按 knowledge_type 分目录（Concepts / Methods），用户实际
        想要的是"按主题找知识"——旅游的去旅游文件夹、编程的去编程文件夹。
        类型信息保留在 frontmatter 的 knowledge_type 里。
        """
        return self.vault_path / self.knowledge_folder / _domain_folder(domain)


def _provider_folder(provider: str) -> str:
    return {
        "chatgpt": "ChatGPT",
        "claude": "Claude",
        "deepseek": "DeepSeek",
        "doubao": "Doubao",
        "zhipu": "Zhipu",
    }.get(provider.lower(), provider.title() or "Unknown")


def _domain_folder(domain: str) -> str:
    """主题域 → 目录名：只保留安全字符，空值落「其他」。"""
    text = _INVALID_CHARS.sub("", str(domain or "").strip())
    return text or "其他"


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
    compiler: str | None = None,
) -> str:
    """Knowledge Markdown（需求文档 §10.3）。

    ``compiler`` 是实际跑编译的模型/服务标识。早先硬编码成 ``Claude``，
    于是用 DeepSeek 编译出来的笔记也自称 Claude 出品，溯源信息是错的。
    """
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
            f"compiler: {compiler or model or 'unknown'}",
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


# ------------------------------------------------------------------ 批量同步
def wiki_link_for_message(session, message_id: str) -> str | None:
    """把 Raw Message 映射为其所属会话的 Wiki Link（保持溯源可点击）。"""
    from akc.repositories import conversation as conv_repo
    from akc.repositories import message as msg_repo

    message = msg_repo.get(session, message_id)
    if message is None:
        return None
    conv = conv_repo.get(session, message.conversation_id)
    if conv is None:
        return None
    date_part = (conv.created_at or conv.updated_at).strftime("%Y-%m-%d")
    return f"[[{conv.provider_id.title()} - {conv.title} - {date_part}]]"


def sync_knowledge(session, settings, knowledge_ids: list[str]) -> dict[str, list]:
    """把一批知识实体落盘为 Obsidian Markdown。

    路由（手动同步）与编译任务（自动落盘）共用这一份逻辑，避免两处维护。
    单条失败不拖垮整批，失败条目进 ``skipped``（含原因）。
    """
    from akc.repositories import knowledge as kn_repo

    layout = VaultLayout(
        vault_path=settings.vault_path,
        raw_folder=settings.vault_raw_folder,
        knowledge_folder=settings.vault_knowledge_folder,
        inbox_folder=settings.vault_inbox_folder,
    )
    written: list[dict] = []
    skipped: list[dict] = []

    for knowledge_id in knowledge_ids:
        item = kn_repo.get(session, knowledge_id)
        if item is None:
            skipped.append({"id": knowledge_id, "reason": "knowledge not found"})
            continue
        source_message_ids = [link.message_id for link in kn_repo.sources_for(session, knowledge_id)]
        source_links = []
        for mid in source_message_ids:
            link = wiki_link_for_message(session, mid)
            if link:
                source_links.append(link)
        markdown = build_knowledge_markdown(
            title=item.title,
            knowledge_type=item.knowledge_type,
            status=item.status,
            summary=item.summary,
            body_markdown=item.markdown,
            confidence=item.confidence,
            topics=list(item.topics_json or []),
            entities=list(item.entities_json or []),
            source_links=source_links,
            created_at=item.created_at.isoformat() if item.created_at else "",
            updated_at=item.updated_at.isoformat() if item.updated_at else "",
            prompt_version=item.prompt_version,
            model=item.model,
            version=item.version,
            compiler=item.model,
        )
        path = layout.knowledge_dir(item.domain) / f"{item.slug}.md"
        try:
            target, changed = write_markdown(path, markdown)
        except Exception as exc:  # noqa: BLE001 - 单条失败不影响其它条目
            skipped.append({"id": knowledge_id, "reason": str(exc)})
            continue
        item.obsidian_path = str(target)
        written.append({"id": knowledge_id, "path": str(target), "changed": changed})

    session.commit()
    return {"written": written, "skipped": skipped}
