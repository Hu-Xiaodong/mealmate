-- ============================================================
-- 知识库批量导入（2026-11-25）
--
-- 背景：原来的上传接口一次只接收一篇文档。批量导入支持：
-- 1. 一次选择多个文件，或整个文件夹（含 Markdown、TXT、图片）；
-- 2. 上传一个 ZIP 压缩包，由服务端安全解压后逐篇处理；
-- 3. 每篇文档对应一条后台任务，失败项可以单独重试。
--
-- 复用已有表：
--   import_batches   记录“一次导入”的整体状态与统计；
--   ingestion_jobs   记录“一个文件”的处理状态与失败原因。
-- 本脚本只新增 kb_documents.import_batch_id，用来反查文档来自哪个批次。
--
-- 适用数据库：PostgreSQL（本地开发库与生产库）
-- 执行方式：psql -d <数据库名> -f 20261125_kb_batch_import.sql
-- 说明：脚本可重复执行；ADD COLUMN IF NOT EXISTS 不会覆盖已有数据。
-- ============================================================

BEGIN;

ALTER TABLE kb_documents
    ADD COLUMN IF NOT EXISTS import_batch_id VARCHAR(40)
        REFERENCES import_batches (id);

-- 批次详情需要按批次查文档，例如展示“这批成功写入了哪些文档”。
CREATE INDEX IF NOT EXISTS ix_kb_documents_import_batch_id
    ON kb_documents (import_batch_id);

COMMIT;
