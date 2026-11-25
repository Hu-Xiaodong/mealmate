-- ============================================================
-- 待索引切片表（2026-11-24）
--
-- 背景：原来“上传”会一次性完成切片和向量嵌入。现在拆成两步：
-- 1. 上传只做解析与切片，切片写入 kb_draft_chunks（后台“切片列表”）；
-- 2. 运营确认切片后点“建立索引”，才调用嵌入模型，把
--    kb_draft_chunks 的内容连同向量写入 kb_chunks。
--
-- 适用数据库：PostgreSQL（本地开发库与生产库）
-- 执行方式：psql -d <数据库名> -f 20261124_kb_draft_chunks.sql
-- 说明：脚本可重复执行；已存在的表不会被覆盖。
-- 使用了 pgvector 的环境不需要重复执行 20261123_kb_pgvector.sql。
-- ============================================================

BEGIN;

CREATE TABLE IF NOT EXISTS kb_draft_chunks (
    id            VARCHAR(40) PRIMARY KEY,
    document_id   VARCHAR(40) NOT NULL REFERENCES kb_documents (id),
    ordinal       INTEGER     NOT NULL DEFAULT 0,
    content       TEXT        NOT NULL,
    token_count   INTEGER     NOT NULL DEFAULT 0,
    chunk_size    INTEGER     NOT NULL DEFAULT 400,
    chunk_overlap INTEGER     NOT NULL DEFAULT 80,
    metadata      JSON,
    created_at    TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

-- 切片列表按文档分组查询，并为每篇文档按序号还原顺序。
CREATE INDEX IF NOT EXISTS ix_kb_draft_chunks_document_id
    ON kb_draft_chunks (document_id);

COMMIT;
