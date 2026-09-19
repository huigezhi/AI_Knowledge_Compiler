"""内容哈希。

与 ``packages/schema/src/hash.ts`` **逐字节一致**，任何一侧修改都必须同步并跑对拍测试。

策略：
1. Unicode NFC 归一化；
2. 换行统一为 ``\\n``；
3. 删除零宽字符（U+200B / U+200C / U+200D / U+FEFF）；
4. 行内连续空格与制表符折叠为单个空格；
5. 每行两端去空白；
6. 删除空行后 join，整体 trim。

即：**不区分空格数量差异，但保留段落结构**。
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Any

_ZERO_WIDTH = re.compile("[​-‍﻿]")
_SPACES = re.compile(r"[ \t]+")


def normalize_for_hash(value: str) -> str:
    text = unicodedata.normalize("NFC", value)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _ZERO_WIDTH.sub("", text)
    lines = [_SPACES.sub(" ", line).strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line).strip()


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def content_hash(value: str) -> str:
    """带 ``sha256:`` 前缀的哈希，与数据库 ``content_hash`` 列格式一致。"""
    return f"sha256:{sha256_hex(normalize_for_hash(value))}"


def canonical_json(value: Any) -> str:
    """稳定序列化：键按字典序排列，``None`` 归一为 ``null``。"""
    return json.dumps(_canonicalize(value), ensure_ascii=False, sort_keys=False, separators=(",", ":"))


def _canonicalize(value: Any) -> Any:
    if value is None or not isinstance(value, (dict, list)):
        return value
    if isinstance(value, list):
        return [_canonicalize(item) for item in value]
    return {key: _canonicalize(value[key]) for key in sorted(value)}


def message_text(content_blocks: list[dict[str, Any]]) -> str:
    """从 ContentBlock 列表提取纯文本（用于哈希、检索与 Prompt 输入）。"""
    parts: list[str] = []
    for block in content_blocks or []:
        kind = block.get("type")
        if kind in ("text", "code"):
            text = block.get("text") or ""
            if kind == "code":
                lang = block.get("language") or ""
                parts.append(f"```{lang}\n{text}\n```")
            else:
                parts.append(text)
        elif kind == "image":
            parts.append(f"[image:{block.get('source_url') or block.get('local_ref') or ''}]")
        elif kind == "file":
            parts.append(f"[file:{block.get('name') or block.get('local_ref') or ''}]")
    return "\n".join(parts)


def hash_message(conversation_id: str, role: str, sequence: int, content: list[dict[str, Any]]) -> str:
    """消息内容哈希：角色 + 序号 + 正文。序号参与计算，保证顺序变化可被发现。"""
    return content_hash(canonical_json(
        {"conversation_id": conversation_id, "role": role, "sequence": sequence,
         "body": normalize_for_hash(message_text(content))}
    ))


def hash_conversation(
    provider: str,
    external_id: str,
    messages: list[dict[str, Any]],
) -> str:
    """会话级哈希：基于所有消息的 (id, role, sequence, body) 序列。"""
    digest = hashlib.sha256()
    digest.update(f"{provider}\x00{external_id}\x00".encode("utf-8"))
    for msg in messages:
        body = normalize_for_hash(message_text(msg.get("content") or []))
        digest.update(
            f"{msg.get('id','')}\x00{msg.get('role','')}\x00{msg.get('sequence',0)}\x00{body}\x01".encode("utf-8")
        )
    return f"sha256:{digest.hexdigest()}"
