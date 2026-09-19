"""会话归一化：把扩展送来的任意合法 payload 收敛为 Universal Conversation Schema。

职责：
* JSON Schema 校验（复用 ``packages/schema/schema/*.json``）；
* 补全缺失字段（id / sequence / hash / schema_version）；
* **不猜测**语义：缺失必填字段直接抛出不可重试错误。
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from akc.compiler.validator import validate_universal_conversation
from akc.errors import ValidationFailedError
from akc.services.hasher import (
    content_hash,
    hash_conversation,
    hash_message,
    message_text,
)

_ROLES = {"user", "assistant", "system", "tool", "unknown"}
_BLOCK_TYPES = {"text", "code", "image", "file"}
_HASH_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:24]}"


def normalize_conversation(payload: dict[str, Any]) -> dict[str, Any]:
    """校验并补全会话。返回规范化后的 dict（符合 Universal Conversation Schema v1）。

    顺序：**先校验必填与格式 → 再补全 → 最后对结果做 Schema 校验**。
    这样既能在边界处拒绝脏数据（例如格式非法的 content_hash），
    又不会要求调用方提供由服务端统一计算的派生字段（如 message.conversation_id）。
    """
    if not isinstance(payload, dict):
        raise ValidationFailedError("conversation payload must be an object")

    for field in ("provider", "provider_conversation_id"):
        if not str(payload.get(field) or "").strip():
            raise ValidationFailedError(
                "conversation does not satisfy the Universal Conversation Schema",
                details={"reason": f"<root>: '{field}' is a required property"},
            )
    if not isinstance(payload.get("messages"), list):
        raise ValidationFailedError(
            "conversation does not satisfy the Universal Conversation Schema",
            details={"reason": "<root>: 'messages' is a required property"},
        )
    _validate_provided_hashes(payload)

    conv: dict[str, Any] = dict(payload)
    conv.setdefault("schema_version", "1.0.0")
    conv["provider"] = str(conv["provider"]).strip().lower()
    conv["title"] = (conv.get("title") or "").strip() or "(untitled)"
    conv["tags"] = [str(tag) for tag in (conv.get("tags") or [])]

    messages = _normalize_messages(conv)
    conv["messages"] = messages

    expected = hash_conversation(
        conv["provider"], conv["provider_conversation_id"], messages
    )
    # 若调用方未提供或已过期，则以服务端计算值为准；始终写回，保证幂等键稳定。
    conv["content_hash"] = expected

    try:
        validate_universal_conversation(conv)
    except ValueError as exc:
        raise ValidationFailedError(
            "conversation does not satisfy the Universal Conversation Schema",
            details={"reason": str(exc)},
        ) from exc
    return conv


def _validate_provided_hashes(payload: dict[str, Any]) -> None:
    """调用方提供的哈希必须是 ``sha256:<64 hex>``，否则拒绝（不静默修正脏数据）。"""
    conv_hash = payload.get("content_hash")
    if conv_hash is not None and not _HASH_PATTERN.match(str(conv_hash)):
        raise ValidationFailedError(
            "conversation does not satisfy the Universal Conversation Schema",
            details={"reason": f"<root>/content_hash: {conv_hash!r} does not match '^sha256:[0-9a-f]{64}$'"},
        )
    for index, msg in enumerate(payload.get("messages") or []):
        if not isinstance(msg, dict):
            continue
        msg_hash = msg.get("content_hash")
        if msg_hash is not None and not _HASH_PATTERN.match(str(msg_hash)):
            raise ValidationFailedError(
                "conversation does not satisfy the Universal Conversation Schema",
                details={"reason": f"messages/{index}/content_hash: does not match pattern"},
            )


def _normalize_messages(conv: dict[str, Any]) -> list[dict[str, Any]]:
    raw_messages = conv.get("messages") or []
    conversation_id = conv.get("id") or new_id("conv")
    conv["id"] = conversation_id

    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_messages):
        if not isinstance(raw, dict):
            raise ValidationFailedError(
                "message must be an object", details={"index": index}
            )

        role = str(raw.get("role") or "unknown").lower()
        if role not in _ROLES:
            role = "unknown"

        content = _normalize_content(raw.get("content"))
        sequence = int(raw.get("sequence") if raw.get("sequence") is not None else index)

        msg = {
            "id": str(raw.get("id") or new_id("msg")),
            "conversation_id": conversation_id,
            "role": role,
            "content": content,
            "sequence": sequence,
            "content_hash": raw.get("content_hash") or "",
        }
        for optional in (
            "provider_message_id",
            "parent_message_id",
            "model",
            "created_at",
            "metadata",
        ):
            if raw.get(optional) is not None:
                msg[optional] = raw[optional]

        # 缺 provider_message_id 时用「会话+消息 id」兜底：
        # 不能用内容哈希，否则内容一变 external_id 就变，会被当成新消息而破坏幂等。
        if not msg.get("provider_message_id"):
            msg["provider_message_id"] = f"{conversation_id}:{msg['id']}"

        msg["content_hash"] = hash_message(conversation_id, role, sequence, content)
        normalized.append(msg)

    normalized.sort(key=lambda m: (m["sequence"], m["id"]))
    for index, msg in enumerate(normalized):
        msg["sequence"] = index
    return normalized


def _normalize_content(raw_content: Any) -> list[dict[str, Any]]:
    if raw_content is None:
        return [{"type": "text", "text": ""}]
    if isinstance(raw_content, str):
        return [{"type": "text", "text": raw_content}]
    if not isinstance(raw_content, list):
        raise ValidationFailedError("message.content must be a list of ContentBlock")

    blocks: list[dict[str, Any]] = []
    for block in raw_content:
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        if kind not in _BLOCK_TYPES:
            continue
        clean: dict[str, Any] = {"type": kind}
        if kind in ("text", "code"):
            clean["text"] = block.get("text") or ""
            if kind == "code" and block.get("language"):
                clean["language"] = str(block["language"])
        elif kind == "image":
            for key in ("local_ref", "source_url"):
                if block.get(key):
                    clean[key] = str(block[key])
        elif kind == "file":
            for key in ("local_ref", "name", "mime"):
                if block.get(key):
                    clean[key] = str(block[key])
        blocks.append(clean)
    return blocks or [{"type": "text", "text": ""}]


def conversation_plain_text(conv: dict[str, Any]) -> str:
    """会话纯文本（用于 FTS 摘要与输入 digest）。"""
    parts = []
    for msg in conv.get("messages", []):
        body = message_text(msg.get("content") or [])
        if body.strip():
            parts.append(f"[{msg.get('role')}] {body}")
    return "\n".join(parts)


def digest_text(text: str, limit: int = 400) -> str:
    """输入摘要：日志与 compile_run 只记录摘要，不记录完整外发 payload。"""
    collapsed = " ".join(text.split())
    return collapsed[:limit]
