-- 003 down：移除主题域列（SQLite 3.35+ 支持 DROP COLUMN）
ALTER TABLE knowledge DROP COLUMN domain;
