"""哈希策略测试（需求文档 §16.1）。

``test_ts_parity_golden`` 中的期望值由 ``packages/schema/src/hash.ts`` 生成，
用于保证 TypeScript 与 Python 两侧实现逐字节一致。
"""

from __future__ import annotations

from akc.services.hasher import (
    canonical_json,
    content_hash,
    hash_conversation,
    hash_message,
    message_text,
    normalize_for_hash,
    sha256_hex,
)


def test_normalize_collapses_spaces_but_keeps_paragraphs() -> None:
    assert normalize_for_hash("  a \t b  ") == "a b"
    assert normalize_for_hash("a\n\n\nb") == "a\nb"
    assert normalize_for_hash("a\r\nb") == "a\nb"


def test_normalize_strips_zero_width() -> None:
    assert normalize_for_hash("a\u200bb\ufeffc") == "abc"


def test_normalize_is_nfc_stable() -> None:
    assert normalize_for_hash("e\u0301") == normalize_for_hash("\u00e9")


def test_content_hash_prefix_and_determinism() -> None:
    value = content_hash("hello world")
    assert value.startswith("sha256:")
    assert value == content_hash("hello   world")
    assert value != content_hash("hello world!")


def test_sha256_known_vector() -> None:
    assert sha256_hex("abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_ts_parity_golden() -> None:
    """与 packages/schema/src/hash.ts 对拍（golden value 由 TS 侧生成）。"""
    sample = "  SQL  优化\r\n\r\n第二步：看执行计划  \n"
    assert content_hash(sample) == (
        "sha256:5cb1e027b81484def6e977382db08ce80906026c7ddfaa508c342ebb7abde27b"
    )


def test_canonical_json_is_key_order_stable() -> None:
    assert canonical_json({"b": 1, "a": {"d": 2, "c": 3}}) == canonical_json(
        {"a": {"c": 3, "d": 2}, "b": 1}
    )
    assert canonical_json({"b": 1, "a": 2}) != canonical_json({"b": 1, "a": 3})


def test_hash_message_includes_sequence() -> None:
    content = [{"type": "text", "text": "same body"}]
    assert hash_message("c1", "user", 0, content) != hash_message("c1", "user", 1, content)


def test_hash_conversation_changes_with_messages() -> None:
    messages = [{"id": "m1", "role": "user", "sequence": 0, "content": [{"type": "text", "text": "a"}]}]
    first = hash_conversation("deepseek", "ext-1", messages)
    messages.append(
        {"id": "m2", "role": "assistant", "sequence": 1, "content": [{"type": "text", "text": "b"}]}
    )
    assert first != hash_conversation("deepseek", "ext-1", messages)


def test_message_text_preserves_code_structure() -> None:
    text = message_text([{"type": "code", "language": "python", "text": "print(1)"}])
    assert text == "```python\nprint(1)\n```"
