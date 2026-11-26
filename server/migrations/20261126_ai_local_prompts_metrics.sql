-- 2026-11-26 新增：本地提示词版本与本地指标所需字段
--
-- 目的：让提示词管理、成本统计、按提示词版本对比质量都不依赖 Langfuse。
-- 执行前请备份数据库。两种数据库二选一。
--
-- PostgreSQL
-- ============================================================

ALTER TABLE ai_call_logs
  ADD COLUMN IF NOT EXISTS prompt_name VARCHAR(80);
ALTER TABLE ai_call_logs
  ADD COLUMN IF NOT EXISTS prompt_version INTEGER;
-- local 本地版本、langfuse 远端版本、default 代码默认值
ALTER TABLE ai_call_logs
  ADD COLUMN IF NOT EXISTS prompt_source VARCHAR(20);
-- 调用时按当时单价算好的美元成本，后续调价不改写历史
ALTER TABLE ai_call_logs
  ADD COLUMN IF NOT EXISTS cost_usd DOUBLE PRECISION NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS ix_ai_call_logs_prompt_name
  ON ai_call_logs (prompt_name);

CREATE TABLE IF NOT EXISTS ai_prompt_versions (
  id VARCHAR(40) PRIMARY KEY,
  name VARCHAR(80) NOT NULL,
  version INTEGER NOT NULL,
  content TEXT NOT NULL,
  -- production 线上版本；archived 历史版本
  status VARCHAR(20) NOT NULL DEFAULT 'production',
  commit_message VARCHAR(200),
  created_by VARCHAR(80) NOT NULL,
  -- 镜像到 Langfuse 后的远端版本号，未同步为 NULL
  langfuse_version INTEGER,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_prompt_name_version UNIQUE (name, version)
);

CREATE INDEX IF NOT EXISTS ix_ai_prompt_versions_name
  ON ai_prompt_versions (name);
CREATE INDEX IF NOT EXISTS ix_ai_prompt_versions_status
  ON ai_prompt_versions (status);
CREATE INDEX IF NOT EXISTS ix_ai_prompt_versions_created_at
  ON ai_prompt_versions (created_at);

-- SQLite（本地零依赖调试，按需执行一次）
-- ============================================================
-- ALTER TABLE ai_call_logs ADD COLUMN prompt_name VARCHAR(80);
-- ALTER TABLE ai_call_logs ADD COLUMN prompt_version INTEGER;
-- ALTER TABLE ai_call_logs ADD COLUMN prompt_source VARCHAR(20);
-- ALTER TABLE ai_call_logs ADD COLUMN cost_usd REAL NOT NULL DEFAULT 0;
-- CREATE INDEX IF NOT EXISTS ix_ai_call_logs_prompt_name ON ai_call_logs (prompt_name);
--
-- CREATE TABLE IF NOT EXISTS ai_prompt_versions (
--   id VARCHAR(40) PRIMARY KEY,
--   name VARCHAR(80) NOT NULL,
--   version INTEGER NOT NULL,
--   content TEXT NOT NULL,
--   status VARCHAR(20) NOT NULL DEFAULT 'production',
--   commit_message VARCHAR(200),
--   created_by VARCHAR(80) NOT NULL,
--   langfuse_version INTEGER,
--   created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
--   CONSTRAINT uq_prompt_name_version UNIQUE (name, version)
-- );
-- CREATE INDEX IF NOT EXISTS ix_ai_prompt_versions_name ON ai_prompt_versions (name);
-- CREATE INDEX IF NOT EXISTS ix_ai_prompt_versions_status ON ai_prompt_versions (status);
-- CREATE INDEX IF NOT EXISTS ix_ai_prompt_versions_created_at ON ai_prompt_versions (created_at);
