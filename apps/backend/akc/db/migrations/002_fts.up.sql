-- 002 fts — FTS5 全文检索（原始消息 + 知识），需求文档 §16.4 性能基线
-- 外部内容表（external content）模式：FTS 索引不复制正文，避免双写不一致。

CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    message_id UNINDEXED,
    conversation_id UNINDEXED,
    title,
    body,
    tokenize = 'unicode61 remove_diacritics 2'
);

CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
    knowledge_id UNINDEXED,
    title,
    summary,
    body,
    tokenize = 'unicode61 remove_diacritics 2'
);

-- 保持 FTS 与源表同步的触发器（messages）
CREATE TRIGGER IF NOT EXISTS messages_fts_ai AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts (message_id, conversation_id, title, body)
    SELECT
        new.id,
        new.conversation_id,
        COALESCE((SELECT title FROM conversations WHERE id = new.conversation_id), ''),
        COALESCE((
            SELECT group_concat(
                CASE
                    WHEN json_valid(value) AND json_extract(value, '$.type') IN ('text', 'code')
                        THEN COALESCE(json_extract(value, '$.text'), '')
                    ELSE ''
                END, char(10))
            FROM json_each(new.content_json)
        ), '');
END;

CREATE TRIGGER IF NOT EXISTS messages_fts_ad AFTER DELETE ON messages BEGIN
    DELETE FROM messages_fts WHERE message_id = old.id;
END;

CREATE TRIGGER IF NOT EXISTS messages_fts_au AFTER UPDATE ON messages BEGIN
    DELETE FROM messages_fts WHERE message_id = old.id;
    INSERT INTO messages_fts (message_id, conversation_id, title, body)
    SELECT
        new.id,
        new.conversation_id,
        COALESCE((SELECT title FROM conversations WHERE id = new.conversation_id), ''),
        COALESCE((
            SELECT group_concat(
                CASE
                    WHEN json_valid(value) AND json_extract(value, '$.type') IN ('text', 'code')
                        THEN COALESCE(json_extract(value, '$.text'), '')
                    ELSE ''
                END, char(10))
            FROM json_each(new.content_json)
        ), '');
END;

-- 保持 FTS 与源表同步的触发器（knowledge）
CREATE TRIGGER IF NOT EXISTS knowledge_fts_ai AFTER INSERT ON knowledge BEGIN
    INSERT INTO knowledge_fts (knowledge_id, title, summary, body)
    VALUES (new.id, new.title, new.summary, new.markdown);
END;

CREATE TRIGGER IF NOT EXISTS knowledge_fts_ad AFTER DELETE ON knowledge BEGIN
    DELETE FROM knowledge_fts WHERE knowledge_id = old.id;
END;

CREATE TRIGGER IF NOT EXISTS knowledge_fts_au AFTER UPDATE ON knowledge BEGIN
    DELETE FROM knowledge_fts WHERE knowledge_id = old.id;
    INSERT INTO knowledge_fts (knowledge_id, title, summary, body)
    VALUES (new.id, new.title, new.summary, new.markdown);
END;
