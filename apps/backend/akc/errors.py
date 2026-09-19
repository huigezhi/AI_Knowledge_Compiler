"""类型化错误体系。

约定（需求文档 §11.2）：
* 所有对外错误统一为 ``{"error": {code, message, retryable, details}, request_id}``；
* 客户端永远看不到堆栈与内部细节；
* ``retryable`` 决定任务队列是否自动重试，不可恢复错误不得无限重试。
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from akc.logging_setup import get_request_id, get_logger


class ErrorCode(str, Enum):
    """稳定错误码。前端据此映射为可读文案，禁止依赖 message 文本做分支。"""

    INTERNAL = "INTERNAL"
    BAD_REQUEST = "BAD_REQUEST"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    SCHEMA_VALIDATION_FAILED = "SCHEMA_VALIDATION_FAILED"
    UNAUTHORIZED = "UNAUTHORIZED"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    ADAPTER_PARSE_FAILED = "ADAPTER_PARSE_FAILED"
    CLAUDE_REQUEST_FAILED = "CLAUDE_REQUEST_FAILED"
    CLAUDE_OUTPUT_INVALID = "CLAUDE_OUTPUT_INVALID"
    OBSIDIAN_WRITE_FAILED = "OBSIDIAN_WRITE_FAILED"
    OBSIDIAN_VAULT_NOT_CONFIGURED = "OBSIDIAN_VAULT_NOT_CONFIGURED"
    JOB_NOT_RUNNABLE = "JOB_NOT_RUNNABLE"


class AppError(Exception):
    """所有业务错误的基类。"""

    code: ErrorCode = ErrorCode.INTERNAL
    http_status: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    retryable: bool = False

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        code: ErrorCode | None = None,
        http_status: int | None = None,
        retryable: bool | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}
        if code is not None:
            self.code = code
        if http_status is not None:
            self.http_status = http_status
        if retryable is not None:
            self.retryable = retryable

    def to_payload(self, request_id: str) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code.value,
                "message": self.message,
                "retryable": self.retryable,
                "details": self.details,
            },
            "request_id": request_id,
        }


class BadRequestError(AppError):
    code = ErrorCode.BAD_REQUEST
    http_status = status.HTTP_400_BAD_REQUEST


class ValidationFailedError(AppError):
    code = ErrorCode.SCHEMA_VALIDATION_FAILED
    http_status = status.HTTP_422_UNPROCESSABLE_ENTITY


class UnauthorizedError(AppError):
    code = ErrorCode.UNAUTHORIZED
    http_status = status.HTTP_401_UNAUTHORIZED


class NotFoundError(AppError):
    code = ErrorCode.NOT_FOUND
    http_status = status.HTTP_404_NOT_FOUND


class ConflictError(AppError):
    code = ErrorCode.CONFLICT
    http_status = status.HTTP_409_CONFLICT


class AdapterParseError(AppError):
    """第三方页面结构变化。不可重试 —— 必须更新 adapter 与 fixture。"""

    code = ErrorCode.ADAPTER_PARSE_FAILED
    http_status = status.HTTP_422_UNPROCESSABLE_ENTITY
    retryable = False


class ClaudeRequestError(AppError):
    """外部 AI API 调用失败。网络/限流类错误可重试。"""

    code = ErrorCode.CLAUDE_REQUEST_FAILED
    http_status = status.HTTP_502_BAD_GATEWAY
    retryable = True


class ClaudeOutputInvalidError(AppError):
    """Claude 输出未通过 JSON Schema 校验。单次重试通常无意义，故不可自动重试。"""

    code = ErrorCode.CLAUDE_OUTPUT_INVALID
    http_status = status.HTTP_502_BAD_GATEWAY
    retryable = False


class ObsidianWriteError(AppError):
    code = ErrorCode.OBSIDIAN_WRITE_FAILED
    http_status = status.HTTP_500_INTERNAL_SERVER_ERROR


class ObsidianVaultNotConfiguredError(AppError):
    code = ErrorCode.OBSIDIAN_VAULT_NOT_CONFIGURED
    http_status = status.HTTP_400_BAD_REQUEST


def error_payload(
    code: ErrorCode, message: str, *, retryable: bool, details: dict[str, Any] | None = None
) -> dict[str, Any]:
    """供中间件/非异常路径构造统一错误体。"""
    return {
        "error": {
            "code": code.value,
            "message": message,
            "retryable": retryable,
            "details": details or {},
        },
        "request_id": get_request_id(),
    }


def register_exception_handlers(app: FastAPI) -> None:
    """全局错误处理：任何异常都转换为规范化的错误结构。"""

    @app.exception_handler(AppError)
    async def _handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.http_status, content=exc.to_payload(get_request_id())
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_request_validation(
        _: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # FastAPI 的 errors() 里可能包含输入片段，只保留结构化位置信息，避免回显敏感内容。
        details = {
            "errors": [
                {"loc": list(e.get("loc", [])), "type": e.get("type")} for e in exc.errors()
            ]
        }
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=error_payload(
                ErrorCode.VALIDATION_FAILED,
                "request payload failed validation",
                retryable=False,
                details=details,
            ),
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        # 记录完整堆栈到日志，但只回传规范化错误体，绝不泄露内部细节。
        get_logger().exception("unhandled_exception", extra={"error_type": type(exc).__name__})
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_payload(
                ErrorCode.INTERNAL, "internal server error", retryable=True
            ),
        )
