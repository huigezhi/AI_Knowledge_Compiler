-- 001 init — 核心表结构（需求文档 §5.2）
-- 说明：迁移以纯 SQL 表达，保证可读性与可回滚性；up/down 成对存在。

CREATE TABLE IF NOT EXISTS providers (
    id                TEXT PRIMARY KEY,
    display_name      TEXT NOT NULL,
    enabled           INTEGER NOT NULL DEFAULT 1,
    adapter_version   TEXT NOT NULL DEFAULT '0.0.0',
    config_json       TEXT NOT NULL DEFAULT '{}',
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS conversations (
    id                  TEXT PRIMARY KEY,
    provider_id         TEXT NOT NULL REFERENCES providers(id),
    external_id         TEXT NOT NULL,
    title               TEXT NOT NULL DEFAULT '',
    url                 TEXT,
    model               TEXT,
    content_hash        TEXT NOT NULL,
    schema_version      TEXT NOT NULL DEFAULT '1.0.0',
    adapter_version     TEXT NOT NULL DEFAULT '0.0.0',
    raw_payload_ref     TEXT,
    provider_created_at TEXT,
    provider_updated_at TEXT,
    tags_json           TEXT NOT NULL DEFAULT '[]',
    compiled_at         TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (provider_id, external_id)
);

CREATE INDEX IF NOT EXISTS ix_conversations_provider ON conversations (provider_id);
CREATE INDEX IF NOT EXISTS ix_conversations_updated ON conversations (updated_at);

CREATE TABLE IF NOT EXISTS messages (
    id                  TEXT PRIMARY KEY,
    conversation_id     TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    external_id         TEXT,
    role                TEXT NOT NULL,
    sequence            INTEGER NOT NULL,
    content_json        TEXT NOT NULL DEFAULT '[]',
    content_hash        TEXT NOT NULL,
    model               TEXT,
    parent_message_id   TEXT,
    provider_created_at TEXT,
    metadata_json       TEXT NOT NULL DEFAULT '{}',
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (conversation_id, external_id)
);

CREATE INDEX IF NOT EXISTS ix_messages_conversation ON messages (conversation_id);
CREATE INDEX IF NOT EXISTS ix_messages_hash ON messages (content_hash);

CREATE TABLE IF NOT EXISTS sync_runs (
    id           TEXT PRIMARY KEY,
    provider_id  TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'running',
    started_at   TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at  TEXT,
    stats_json   TEXT NOT NULL DEFAULT '{}',
    error        TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS jobs (
    id               TEXT PRIMARY KEY,
    job_type         TEXT NOT NULL,
    idempotency_key  TEXT NOT NULL UNIQUE,
    payload_json     TEXT NOT NULL DEFAULT '{}',
    status           TEXT NOT NULL DEFAULT 'pending',
    attempts         INTEGER NOT NULL DEFAULT 0,
    max_attempts     INTEGER NOT NULL DEFAULT 3,
    next_run_at      TEXT NOT NULL DEFAULT (datetime('now')),
    stage            TEXT,
    result_json      TEXT NOT NULL DEFAULT '{}',
    error            TEXT,
    error_code       TEXT,
    finished_at      TEXT,
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS ix_jobs_status ON jobs (status);
CREATE INDEX IF NOT EXISTS ix_jobs_next_run ON jobs (next_run_at);

CREATE TABLE IF NOT EXISTS knowledge (
    id                  TEXT PRIMARY KEY,
    slug                TEXT NOT NULL,
    title               TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'candidate',
    knowledge_type      TEXT NOT NULL DEFAULT 'fact',
    summary             TEXT NOT NULL DEFAULT '',
    markdown            TEXT NOT NULL DEFAULT '',
    content_hash        TEXT NOT NULL DEFAULT '',
    version             INTEGER NOT NULL DEFAULT 1,
    confidence          REAL NOT NULL DEFAULT 0.5,
    needs_verification  INTEGER NOT NULL DEFAULT 1,
    topics_json         TEXT NOT NULL DEFAULT '[]',
    entities_json       TEXT NOT NULL DEFAULT '[]',
    superseded_by       TEXT,
    obsidian_path       TEXT,
    prompt_version      TEXT,
    model               TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS ix_knowledge_status ON knowledge (status);
CREATE INDEX IF NOT EXISTS ix_knowledge_slug ON knowledge (slug);

CREATE TABLE IF NOT EXISTS knowledge_sources (
    id              TEXT PRIMARY KEY,
    knowledge_id    TEXT NOT NULL,
    message_id      TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    relation_type   TEXT NOT NULL DEFAULT 'supports',
    UNIQUE (knowledge_id, message_id, relation_type)
);

CREATE INDEX IF NOT EXISTS ix_ksources_knowledge ON knowledge_sources (knowledge_id);
CREATE INDEX IF NOT EXISTS ix_ksources_message ON knowledge_sources (message_id);

CREATE TABLE IF NOT EXISTS entities (
    id             TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    type           TEXT NOT NULL,
    canonical_name TEXT NOT NULL,
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at     TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (type, canonical_name)
);

CREATE TABLE IF NOT EXISTS relations (
    id               TEXT PRIMARY KEY,
    source_entity_id TEXT NOT NULL,
    relation         TEXT NOT NULL,
    target_entity_id TEXT NOT NULL,
    confidence       REAL NOT NULL DEFAULT 0.5,
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS knowledge_links (
    id                   TEXT PRIMARY KEY,
    knowledge_id         TEXT NOT NULL,
    related_knowledge_id TEXT NOT NULL,
    link_type            TEXT NOT NULL DEFAULT 'related',
    confidence           REAL NOT NULL DEFAULT 0.5,
    UNIQUE (knowledge_id, related_knowledge_id, link_type)
);

CREATE TABLE IF NOT EXISTS compile_runs (
    id               TEXT PRIMARY KEY,
    conversation_id  TEXT NOT NULL,
    job_id           TEXT,
    model            TEXT NOT NULL DEFAULT '',
    prompt_version   TEXT NOT NULL DEFAULT '',
    compiler_version TEXT NOT NULL DEFAULT '',
    adapter_version  TEXT,
    status           TEXT NOT NULL DEFAULT 'pending',
    input_digest     TEXT NOT NULL DEFAULT '',
    result_json      TEXT NOT NULL DEFAULT '{}',
    error            TEXT,
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS ix_compile_runs_conversation ON compile_runs (conversation_id);

CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id          TEXT PRIMARY KEY,
    event_type  TEXT NOT NULL,
    entity_type TEXT NOT NULL DEFAULT '',
    entity_id   TEXT NOT NULL DEFAULT '',
    detail_json TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS ix_audit_entity ON audit_logs (entity_type, entity_id);
CREATE INDEX IF NOT EXISTS ix_audit_created ON audit_logs (created_at);

CREATE TABLE IF NOT EXISTS schema_migrations (
    version    TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
);
