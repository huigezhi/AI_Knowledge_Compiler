"""Claude API 客户端。

设计约束：
* 模型 ID 来自配置，**业务代码不得硬编码模型名**；
* 只暴露“返回结构化 JSON”的方法，输出必须过 JSON Schema；
* 错误分两类：可重试（网络/限流/5xx）与不可重试（鉴权/参数/输出非法）；
* 日志只记录输入摘要，**绝不记录完整外发 payload 与 API Key**。
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

from akc.errors import ClaudeOutputInvalidError, ClaudeRequestError
from akc.logging_setup import get_logger, log_event

_ANTHROPIC_VERSION = "2023-06-01"
_JSON_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


class ClaudeSettings:
    """运行期最小配置视图（避免 compiler 层依赖全局 Settings）。"""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "https://api.anthropic.com",
        timeout_seconds: float = 120.0,
        max_context_tokens: int = 50_000,
    ) -> None:
        if not api_key:
            raise ValueError("claude api key is required")
        if not model:
            raise ValueError("claude model id must be provided via configuration")
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_context_tokens = max_context_tokens


class ClaudeClient:
    """Anthropic Messages API 的极简客户端（仅同步接口，供任务队列调用）。"""

    def __init__(self, settings: ClaudeSettings, *, transport: httpx.BaseTransport | None = None):
        self._settings = settings
        self._client = httpx.Client(
            base_url=settings.base_url,
            timeout=settings.timeout_seconds,
            headers={
                "x-api-key": settings.api_key,
                "anthropic-version": _ANTHROPIC_VERSION,
                "content-type": "application/json",
            },
            transport=transport,
        )

    # ------------------------------------------------------------------ 公开
    @property
    def model(self) -> str:
        return self._settings.model

    def complete_json(self, system: str, user: str, *, max_tokens: int = 4096) -> dict[str, Any]:
        """调用模型并返回**已解析**的 JSON 对象。

        只返回 JSON；任何非 JSON 输出都视为 ``ClaudeOutputInvalidError``（不可自动重试）。
        """
        payload = {
            "model": self._settings.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        data = self._post("/v1/messages", payload)
        text = self._extract_text(data)
        return self._parse_json(text)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> ClaudeClient:  # pragma: no cover - 便利方法
        return self

    def __exit__(self, *_: object) -> None:  # pragma: no cover
        self.close()

    # ------------------------------------------------------------------ 内部
    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self._client.post(path, json=payload)
        except httpx.TimeoutException as exc:
            raise ClaudeRequestError(
                "claude request timed out", retryable=True, details={"timeout": str(exc)}
            ) from exc
        except httpx.TransportError as exc:
            raise ClaudeRequestError(
                "claude request failed at the transport layer",
                retryable=True,
                details={"type": type(exc).__name__},
            ) from exc

        if response.status_code == 429 or response.status_code >= 500:
            raise ClaudeRequestError(
                f"claude api returned {response.status_code}",
                retryable=True,
                details={"status": response.status_code},
            )
        if response.status_code == 401 or response.status_code == 403:
            # 鉴权问题重试无意义；不回显响应体，避免泄露细节。
            raise ClaudeRequestError(
                "claude api rejected the credentials", retryable=False, details={}
            )
        if response.status_code >= 400:
            raise ClaudeRequestError(
                f"claude api returned {response.status_code}",
                retryable=False,
                details={"status": response.status_code},
            )
        return response.json()

    @staticmethod
    def _extract_text(data: dict[str, Any]) -> str:
        blocks = data.get("content") or []
        parts = [
            block.get("text", "")
            for block in blocks
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        text = "\n".join(parts).strip()
        if not text:
            raise ClaudeOutputInvalidError("claude returned no text content")
        return text

    @staticmethod
    def _parse_json(text: str) -> dict[str, Any]:
        cleaned = _JSON_FENCE.sub("", text).strip()
        # 兼容模型在 JSON 前后附加少量说明的情况：截取首个 { 与最后一个 }。
        if not cleaned.startswith("{"):
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start == -1 or end <= start:
                raise ClaudeOutputInvalidError("claude output is not a JSON object")
            cleaned = cleaned[start : end + 1]
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            get_logger().warning(
                "claude_output_not_json", extra={"extra_fields": {"reason": str(exc)}}
            )
            raise ClaudeOutputInvalidError(
                "claude output is not valid JSON", details={"reason": str(exc)}
            ) from exc
        if not isinstance(parsed, dict):
            raise ClaudeOutputInvalidError("claude output must be a JSON object")
        log_event("claude_json_parsed", keys=sorted(parsed))
        return parsed
