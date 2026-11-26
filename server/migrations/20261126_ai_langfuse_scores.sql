-- 2026-11-26 新增：Langfuse 可观测接入所需字段与人工评分表
--
-- 背景：
-- 1. 模型配置增加输入/输出单价，调用上报时可计算成本；
-- 2. 新增人工评分表，评分先存本地，再尽力同步 Langfuse；
-- 3. 评分保留期跟随调用日志（180 天），由每日清理任务删除。
--
-- 执行前请先备份数据库。两种数据库二选一，不要都执行。

-- ============================================================
-- PostgreSQL（生产 / Docker Compose 使用的数据库）
-- ============================================================

-- 单价单位：美元 / 1000 token。默认 0 表示运营尚未填写，
-- 此时成本显示为 0，但不影响 Token 与调用次数统计。
ALTER TABLE ai_providers
  ADD COLUMN IF NOT EXISTS input_price_per_1k DOUBLE PRECISION NOT NULL DEFAULT 0;
ALTER TABLE ai_providers
  ADD COLUMN IF NOT EXISTS output_price_per_1k DOUBLE PRECISION NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS ai_call_scores (
  id VARCHAR(40) PRIMARY KEY,
  -- 被评分的调用日志编号。不建外键：日志按 180 天清理，评分跟随同一策略。
  call_log_id VARCHAR(40) NOT NULL,
  -- 1-5 分，5 表示最好。
  score INTEGER NOT NULL,
  -- 评语，可空。
  comment VARCHAR(500),
  -- 评分人显示名快照。
  scorer_name VARCHAR(80) NOT NULL,
  -- manual 人工评分；以后可扩展 auto 自动评测。
  source VARCHAR(20) NOT NULL DEFAULT 'manual',
  -- 是否已成功推送到 Langfuse。
  langfuse_synced BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_ai_call_scores_call_log_id
  ON ai_call_scores (call_log_id);
CREATE INDEX IF NOT EXISTS ix_ai_call_scores_created_at
  ON ai_call_scores (created_at);

-- ============================================================
-- SQLite（本地零依赖调试）
-- 差异：没有 TIMESTAMPTZ 与 DOUBLE PRECISION（用 DATETIME / REAL）；
-- ADD COLUMN 不支持 IF NOT EXISTS，只在首次变更时执行一次。
-- ============================================================
-- ALTER TABLE ai_providers ADD COLUMN input_price_per_1k REAL NOT NULL DEFAULT 0;
-- ALTER TABLE ai_providers ADD COLUMN output_price_per_1k REAL NOT NULL DEFAULT 0;
--
-- CREATE TABLE IF NOT EXISTS ai_call_scores (
--   id VARCHAR(40) PRIMARY KEY,
--   call_log_id VARCHAR(40) NOT NULL,
--   score INTEGER NOT NULL,
--   comment VARCHAR(500),
--   scorer_name VARCHAR(80) NOT NULL,
--   source VARCHAR(20) NOT NULL DEFAULT 'manual',
--   langfuse_synced BOOLEAN NOT NULL DEFAULT 0,
--   created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
-- );
-- CREATE INDEX IF NOT EXISTS ix_ai_call_scores_call_log_id ON ai_call_scores (call_log_id);
-- CREATE INDEX IF NOT EXISTS ix_ai_call_scores_created_at ON ai_call_scores (created_at);
