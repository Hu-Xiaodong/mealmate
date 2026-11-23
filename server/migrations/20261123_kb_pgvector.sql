-- ============================================================
-- 知识库表（需要 pgvector 扩展，2026-11-23）
--
-- 适用数据库：PostgreSQL
--
-- 执行前置条件（缺一不可）：
-- 1. 数据库已安装 pgvector 扩展。官方安装说明：
--    https://github.com/pgvector/pgvector
-- 2. 执行账号有创建扩展和建表权限。
-- 3. 已确认嵌入模型的向量维度。本脚本固定 1024，
--    因为首版使用云端 OpenAI 兼容嵌入接口，输出 1024 维。
--    换模型必须新建索引版本并整体重建，不能直接改列维度。
--
-- 本地执行情况（2026-11-23）：
-- 本地 PostgreSQL 18 已安装 pgvector 0.8.6 并在 meal_dev 启用，
-- 本脚本已执行成功，生成三张知识库表与 HNSW 索引。
-- 新环境仍必须先安装与数据库大版本匹配的 pgvector，再执行本脚本。
-- 本脚本不影响菜谱导入：导入只依赖
-- 20261123_import_and_ingestion.sql。
--
-- 为什么向量列不直接加在菜谱表上：
-- 菜谱是业务数据，向量是索引产物。换嵌入模型、换切片规则时
-- 需要整体重建向量；如果向量和菜谱同表，重建会锁住业务表。
-- 单独建表可以按索引版本重建、对比效果、随时回退。
-- ============================================================

BEGIN;

CREATE EXTENSION IF NOT EXISTS vector;

-- ------------------------------------------------------------
-- 1. 索引版本
--    一次“切片 + 嵌入”产物的编号。
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS kb_index_versions (
    id             VARCHAR(40) PRIMARY KEY,
    name           VARCHAR(80) NOT NULL,
    embed_provider VARCHAR(40) NOT NULL,
    embed_model    VARCHAR(60) NOT NULL,
    dimensions     INTEGER     NOT NULL,
    chunk_size     INTEGER     NOT NULL,
    chunk_overlap  INTEGER     NOT NULL,
    status         VARCHAR(20) NOT NULL DEFAULT 'building',
    created_at     TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    activated_at   TIMESTAMP WITH TIME ZONE
);

-- ------------------------------------------------------------
-- 2. 知识库文档
--    storage_key 是对象存储中的路径；checksum 用于判断重复上传。
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS kb_documents (
    id               VARCHAR(40)  PRIMARY KEY,
    title            VARCHAR(120) NOT NULL,
    source_type      VARCHAR(20)  NOT NULL,
    storage_key      VARCHAR(255) NOT NULL,
    mime             VARCHAR(80)  NOT NULL,
    bytes            INTEGER      NOT NULL,
    checksum         VARCHAR(64)  NOT NULL,
    status           VARCHAR(20)  NOT NULL DEFAULT 'uploaded',
    error_message    VARCHAR(500),
    index_version_id VARCHAR(40),
    uploaded_by      VARCHAR(40),
    created_at       TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at       TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_kb_documents_source_type
    ON kb_documents (source_type);
CREATE INDEX IF NOT EXISTS ix_kb_documents_status
    ON kb_documents (status);
CREATE INDEX IF NOT EXISTS ix_kb_documents_checksum
    ON kb_documents (checksum);
CREATE INDEX IF NOT EXISTS ix_kb_documents_index_version_id
    ON kb_documents (index_version_id);

-- ------------------------------------------------------------
-- 3. 切片
--    metadata 保存页码、章节标题等定位信息，回答时用于给出来源。
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS kb_chunks (
    id               VARCHAR(40) PRIMARY KEY,
    document_id      VARCHAR(40) NOT NULL REFERENCES kb_documents (id),
    index_version_id VARCHAR(40) NOT NULL REFERENCES kb_index_versions (id),
    ordinal          INTEGER     NOT NULL,
    content          TEXT        NOT NULL,
    token_count      INTEGER     NOT NULL DEFAULT 0,
    embedding        vector(1024),
    metadata         JSON,
    created_at       TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_kb_chunks_document_id
    ON kb_chunks (document_id);
CREATE INDEX IF NOT EXISTS ix_kb_chunks_index_version_id
    ON kb_chunks (index_version_id);

-- 同一次索引下，同一篇文档的切片序号唯一，防止重复写入。
CREATE UNIQUE INDEX IF NOT EXISTS uq_kb_chunks_ordinal
    ON kb_chunks (document_id, index_version_id, ordinal);

-- 向量相似度索引。HNSW 适合在线查询，召回率和速度平衡较好；
-- vector_cosine_ops 表示按余弦距离比较，适合文本嵌入。
-- m 和 ef_construction 是建索引参数：值越大越准，但建索引越慢、
-- 占用内存越多。16 和 64 是常见起点。
CREATE INDEX IF NOT EXISTS ix_kb_chunks_embedding_hnsw
    ON kb_chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

COMMIT;
