"""数据库模型（需求文档 §5.2）。

约束要点：
* ``conversations(provider_id, external_id)`` 唯一；
* ``messages(conversation_id, external_id)`` 在可获得 provider_message_id 时唯一；
* ``content_hash``（SHA-256）用于二次幂等；
* Raw Message 永不因编译失败而删除；
* Knowledge 以 ``version`` 递增，支持回滚。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from akc.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class Provider(Base, TimestampMixin):
    __tablename__ = "providers"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # chatgpt / claude / ...
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    enabled: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    adapter_version: Mapped[str] = mapped_column(String, default="0.0.0", nullable=False)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class Conversation(Base, TimestampMixin):
    __tablename__ = "conversations"
    __table_args__ = (UniqueConstraint("provider_id", "external_id", name="uq_conv_provider_ext"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    provider_id: Mapped[str] = mapped_column(
        String, ForeignKey("providers.id"), nullable=False, index=True
    )
    external_id: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, default="", nullable=False)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    content_hash: Mapped[str] = mapped_column(String, nullable=False)
    schema_version: Mapped[str] = mapped_column(String, default="1.0.0", nullable=False)
    adapter_version: Mapped[str] = mapped_column(String, default="0.0.0", nullable=False)
    raw_payload_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    tags_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    compiled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", lazy="selectin"
    )


class Message(Base, TimestampMixin):
    """原始消息 —— **永不因编译失败而删除**。"""

    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "external_id", name="uq_msg_conv_external"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        String, ForeignKey("conversations.id"), nullable=False, index=True
    )
    external_id: Mapped[str | None] = mapped_column(String, nullable=True)
    role: Mapped[str] = mapped_column(String, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    content_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    content_hash: Mapped[str] = mapped_column(String, nullable=False, index=True)
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    parent_message_id: Mapped[str | None] = mapped_column(String, nullable=True)
    provider_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    conversation: Mapped[Conversation] = relationship(back_populates="messages", lazy="joined")


class SyncRun(Base, TimestampMixin):
    __tablename__ = "sync_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    provider_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String, default="running", nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stats_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class Job(Base, TimestampMixin):
    """SQLite 任务队列（需求文档 §15）。"""

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    job_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String, default="pending", nullable=False, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    next_run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )
    stage: Mapped[str | None] = mapped_column(String, nullable=True)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Knowledge(Base, TimestampMixin):
    """知识实体。Raw → Knowledge 的映射通过 knowledge_sources 溯源。"""

    __tablename__ = "knowledge"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    slug: Mapped[str] = mapped_column(String, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, default="candidate", nullable=False, index=True)
    knowledge_type: Mapped[str] = mapped_column(String, default="fact", nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    markdown: Mapped[str] = mapped_column(Text, default="", nullable=False)
    content_hash: Mapped[str] = mapped_column(String, default="", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    needs_verification: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    topics_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    entities_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    superseded_by: Mapped[str | None] = mapped_column(String, nullable=True)
    obsidian_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String, nullable=True)
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    # 主题域（编程技术 / 金融投资 / 休闲旅游 / 工作职场 / 学习成长 / 生活健康 / 其他），
    # 决定 Obsidian 侧 03_Knowledge/<domain>/ 的一级目录
    domain: Mapped[str] = mapped_column(String, default="其他", nullable=False, server_default="其他")


class KnowledgeSource(Base):
    """知识溯源：每条 Knowledge 至少对应一个 Raw Message。"""

    __tablename__ = "knowledge_sources"
    __table_args__ = (
        UniqueConstraint(
            "knowledge_id", "message_id", "relation_type", name="uq_ksource_knowledge_msg"
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    knowledge_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    message_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    conversation_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    relation_type: Mapped[str] = mapped_column(String, default="supports", nullable=False)


class Entity(Base, TimestampMixin):
    __tablename__ = "entities"
    __table_args__ = (UniqueConstraint("type", "canonical_name", name="uq_entity_type_canonical"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)
    canonical_name: Mapped[str] = mapped_column(String, nullable=False)


class Relation(Base, TimestampMixin):
    __tablename__ = "relations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    source_entity_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    relation: Mapped[str] = mapped_column(String, nullable=False)
    target_entity_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)


class KnowledgeLink(Base):
    __tablename__ = "knowledge_links"
    __table_args__ = (
        UniqueConstraint(
            "knowledge_id", "related_knowledge_id", "link_type", name="uq_klink_pair_type"
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    knowledge_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    related_knowledge_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    link_type: Mapped[str] = mapped_column(String, default="related", nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)


class CompileRun(Base, TimestampMixin):
    """一次 Claude 编译的记录，保证问题可复现。"""

    __tablename__ = "compile_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    job_id: Mapped[str | None] = mapped_column(String, nullable=True)
    model: Mapped[str] = mapped_column(String, default="", nullable=False)
    prompt_version: Mapped[str] = mapped_column(String, default="", nullable=False)
    compiler_version: Mapped[str] = mapped_column(String, default="", nullable=False)
    adapter_version: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="pending", nullable=False)
    input_digest: Mapped[str] = mapped_column(String, default="", nullable=False)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    event_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String, default="", nullable=False)
    entity_id: Mapped[str] = mapped_column(String, default="", nullable=False, index=True)
    detail_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )


class SchemaMigration(Base):
    __tablename__ = "schema_migrations"

    version: Mapped[str] = mapped_column(String, primary_key=True)
    applied_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
