"""JSON Schema 校验。

扩展与后端共用 ``packages/schema/schema/*.json`` 这一份契约：
* 导入请求必须满足 ``universal-conversation.schema.json``；
* Claude 输出必须满足 ``compiler-output.schema.json``，否则视为不可重试错误。
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from akc.errors import ValidationFailedError

# apps/backend/akc/compiler/validator.py -> 仓库根/packages/schema/schema
_SCHEMA_DIR = Path(__file__).resolve().parents[4] / "packages" / "schema" / "schema"

UNIVERSAL_CONVERSATION_SCHEMA = "universal-conversation.schema.json"
COMPILER_OUTPUT_SCHEMA = "compiler-output.schema.json"


def schema_dir() -> Path:
    return _SCHEMA_DIR


@lru_cache(maxsize=8)
def _load(name: str) -> dict[str, Any]:
    path = _SCHEMA_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"json schema not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=8)
def _validator(name: str) -> Draft202012Validator:
    return Draft202012Validator(_load(name))


def _first_error(name: str, payload: Any) -> str | None:
    validator = _validator(name)
    for error in validator.iter_errors(payload):
        location = "/".join(str(part) for part in error.absolute_path) or "<root>"
        return f"{location}: {error.message}"
    return None


def validate_universal_conversation(payload: dict[str, Any]) -> None:
    reason = _first_error(UNIVERSAL_CONVERSATION_SCHEMA, payload)
    if reason:
        raise ValidationFailedError(
            "conversation does not satisfy the Universal Conversation Schema",
            details={"reason": reason},
        )


def validate_compiler_output(payload: dict[str, Any]) -> None:
    reason = _first_error(COMPILER_OUTPUT_SCHEMA, payload)
    if reason:
        raise ValidationFailedError(
            "compiler output does not satisfy the CompilerOutput schema",
            details={"reason": reason},
        )
