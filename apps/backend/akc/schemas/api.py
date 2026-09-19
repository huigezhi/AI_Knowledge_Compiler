"""API 请求/响应模型。

控制器只做「解析 → 调用 service → 格式化」，所有结构在此定义。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ImportOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    write_raw_to_obsidian: bool = False
    compile: bool = False


class ImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation: dict[str, Any]
    options: ImportOptions = Field(default_factory=ImportOptions)


class ImportResponse(BaseModel):
    conversation_id: str
    created: bool
    created_messages: int
    updated_messages: int
    content_hash: str
    obsidian_path: str | None = None
    job_id: str | None = None
    warnings: list[str] = Field(default_factory=list)


class CompileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: str
    idempotency_key: str | None = None


class SyncRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    conversation_ids: list[str] = Field(default_factory=list)


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str  # verify | reject | archive | review
    reason: str = ""


class MergeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_knowledge_id: str
    reason: str = ""


class ReclassifyRequest(BaseModel):
    """重新分类与归并：先 dry_run 预览，确认后再 dry_run=False 执行。"""

    model_config = ConfigDict(extra="forbid")

    domain: str | None = None
    force: bool = False
    dry_run: bool = True


class ObsidianSyncRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    knowledge_ids: list[str] = Field(default_factory=list)
    conversation_ids: list[str] = Field(default_factory=list)
    include_raw: bool = False


class SettingsUpdate(BaseModel):
    """PUT /api/v1/settings —— 只允许写入白名单键（见 repositories.settings）。"""

    model_config = ConfigDict(extra="forbid")

    values: dict[str, Any]
