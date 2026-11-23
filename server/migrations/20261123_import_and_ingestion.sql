-- ============================================================
-- 数据导入与后台任务表（2026-11-23）
--
-- 适用数据库：PostgreSQL（开发与生产）
-- 执行方式：psql -f 20261123_import_and_ingestion.sql
--          或在数据库客户端中整段执行
--
-- 为什么需要这份脚本：
-- 1. SQLAlchemy 的 create_all 只会新建“整张表”，不会给已有表补列，
--    所以菜谱来源字段必须用 ALTER TABLE 升级；
-- 2. 生产环境通常由数据库管理员执行脚本，不直接跑应用启动逻辑；
-- 3. 脚本中的 IF NOT EXISTS 保证重复执行不会报错，便于演练和回滚后重跑。
--
-- SQLite 说明：
-- 本地测试使用临时 SQLite 文件，每次测试都会重新建库，
-- 新表和新列由模型自动创建，不需要执行这份脚本。
-- ============================================================

BEGIN;

-- ------------------------------------------------------------
-- 1. 导入批次表
--    必须先创建，因为 recipes.import_batch_id 会引用它。
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS import_batches (
    id            VARCHAR(40)  PRIMARY KEY,
    source_type   VARCHAR(20)  NOT NULL,
    source_uri    VARCHAR(255) NOT NULL,
    source_ref    VARCHAR(80),
    checksum      VARCHAR(64),
    status        VARCHAR(20)  NOT NULL DEFAULT 'pending',
    stats         JSON         NOT NULL DEFAULT '{}'::json,
    error_message VARCHAR(500),
    created_by    VARCHAR(40),
    created_at    TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    finished_at   TIMESTAMP WITH TIME ZONE
);

CREATE INDEX IF NOT EXISTS ix_import_batches_source_type
    ON import_batches (source_type);
CREATE INDEX IF NOT EXISTS ix_import_batches_status
    ON import_batches (status);

-- ------------------------------------------------------------
-- 2. 菜谱来源字段
-- ------------------------------------------------------------
ALTER TABLE recipes
    ADD COLUMN IF NOT EXISTS description      TEXT,
    ADD COLUMN IF NOT EXISTS tips             TEXT,
    ADD COLUMN IF NOT EXISTS difficulty       VARCHAR(20),
    ADD COLUMN IF NOT EXISTS tags             JSON NOT NULL DEFAULT '[]'::json,
    ADD COLUMN IF NOT EXISTS source_type      VARCHAR(20) NOT NULL DEFAULT 'manual',
    ADD COLUMN IF NOT EXISTS source_uri       VARCHAR(255),
    ADD COLUMN IF NOT EXISTS source_checksum  VARCHAR(64),
    ADD COLUMN IF NOT EXISTS source_license   VARCHAR(40),
    ADD COLUMN IF NOT EXISTS import_batch_id  VARCHAR(40)
        REFERENCES import_batches (id),
    ADD COLUMN IF NOT EXISTS source_meta      JSON;

-- 外部菜谱可能没写总时长，允许为空。
-- 不能填 0：0 表示“零分钟”，会干扰按时间筛选。
ALTER TABLE recipes
    ALTER COLUMN total_minutes DROP NOT NULL;

CREATE INDEX IF NOT EXISTS ix_recipes_source_type
    ON recipes (source_type);
CREATE INDEX IF NOT EXISTS ix_recipes_import_batch_id
    ON recipes (import_batch_id);

-- 同一来源的同一个文件只能对应一条菜谱。
-- 手工菜谱的 source_uri 为空，数据库允许多行空值，不受唯一约束影响。
CREATE UNIQUE INDEX IF NOT EXISTS uq_recipes_source
    ON recipes (source_type, source_uri);

-- ------------------------------------------------------------
-- 3. 后台任务表
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ingestion_jobs (
    id            VARCHAR(40) PRIMARY KEY,
    batch_id      VARCHAR(40) NOT NULL REFERENCES import_batches (id),
    job_type      VARCHAR(30) NOT NULL,
    status        VARCHAR(20) NOT NULL DEFAULT 'pending',
    attempts      INTEGER     NOT NULL DEFAULT 0,
    payload       JSON        NOT NULL DEFAULT '{}'::json,
    result        JSON,
    error_message VARCHAR(500),
    run_after     TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    locked_at     TIMESTAMP WITH TIME ZONE,
    locked_by     VARCHAR(64),
    created_at    TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at    TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_ingestion_jobs_batch_id
    ON ingestion_jobs (batch_id);
CREATE INDEX IF NOT EXISTS ix_ingestion_jobs_job_type
    ON ingestion_jobs (job_type);
CREATE INDEX IF NOT EXISTS ix_ingestion_jobs_status
    ON ingestion_jobs (status);
CREATE INDEX IF NOT EXISTS ix_ingestion_jobs_run_after
    ON ingestion_jobs (run_after);

-- ------------------------------------------------------------
-- 4. 模型供应商增加“用途”和“向量维度”
--    聊天模型不需要维度；嵌入模型必须填写，并与知识库向量列一致。
-- ------------------------------------------------------------
ALTER TABLE ai_providers
    ADD COLUMN IF NOT EXISTS kind VARCHAR(20) NOT NULL DEFAULT 'chat',
    ADD COLUMN IF NOT EXISTS dimensions INTEGER;

COMMIT;
