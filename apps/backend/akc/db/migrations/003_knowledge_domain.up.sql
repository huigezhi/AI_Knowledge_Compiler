-- 003 knowledge domain — 知识按主题域分类（编程技术 / 金融投资 / 休闲旅游 / 工作……）
-- 需求：知识库结果要有主题分类，Obsidian 侧按 03_Knowledge/<主题域>/<slug>.md 落盘。
-- 直接存中文域名（SQLite / Obsidian 都无障碍），历史行统一落「其他」，由重新同步或重编译纠正。

ALTER TABLE knowledge ADD COLUMN domain VARCHAR NOT NULL DEFAULT '其他';
