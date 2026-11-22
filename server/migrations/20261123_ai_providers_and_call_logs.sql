-- 2026-11-23 新增：大模型供应商配置表、AI 调用日志表
--
-- 背景：项目没有引入 Alembic（数据库迁移框架），建表依赖
-- Base.metadata.create_all。create_all 会补建“缺失的表”，
-- 所以正常启动应用时，这两张新表会自动创建，本脚本不是必须执行。
--
-- 这个脚本的用途：
-- 1. 生产环境通常不允许应用账号自动建表，需要由数据库管理员审阅后执行；
-- 2. 明确记录表结构与索引，方便代码评审和回溯；
-- 3. 需要手工初始化或修复表结构时有一份可执行依据。
--
-- 执行前请先备份数据库。两种数据库二选一，不要都执行。

-- ============================================================
-- PostgreSQL（生产 / Docker Compose 使用的数据库）
-- ============================================================

-- 大模型供应商配置。密钥只保存 Fernet 密文，
-- 明文只在内存中出现，列表接口只返回掩码。
CREATE TABLE IF NOT EXISTS ai_providers (
  id VARCHAR(40) PRIMARY KEY,
  name VARCHAR(40) NOT NULL UNIQUE,
  provider_type VARCHAR(30) NOT NULL DEFAULT 'openai_compatible',
  base_url VARCHAR(255) NOT NULL,
  api_key_encrypted TEXT NOT NULL,
  model VARCHAR(80) NOT NULL,
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  -- 数字越小越先尝试；自动分配按 priority 升序逐个调用。
  priority INTEGER NOT NULL DEFAULT 100,
  timeout_seconds INTEGER NOT NULL DEFAULT 20,
  max_output_tokens INTEGER NOT NULL DEFAULT 800,
  last_test_at TIMESTAMPTZ,
  last_test_ok BOOLEAN,
  last_test_message VARCHAR(200),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 每次模型调用尝试记一行。provider_id 故意不做外键：
-- 供应商配置被删除后，历史调用记录仍然要保留，provider_name 保存的是当时的名称快照。
CREATE TABLE IF NOT EXISTS ai_call_logs (
  id VARCHAR(40) PRIMARY KEY,
  -- 与接口响应头 X-Request-Id 一致，用于把一次提问和多次模型尝试串起来。
  request_id VARCHAR(64),
  subject_ref VARCHAR(80) NOT NULL,
  context_type VARCHAR(20) NOT NULL,
  provider_id VARCHAR(40),
  provider_name VARCHAR(40) NOT NULL,
  model VARCHAR(80) NOT NULL,
  status VARCHAR(20) NOT NULL,
  latency_ms INTEGER NOT NULL DEFAULT 0,
  prompt_tokens INTEGER NOT NULL DEFAULT 0,
  completion_tokens INTEGER NOT NULL DEFAULT 0,
  total_tokens INTEGER NOT NULL DEFAULT 0,
  error_code VARCHAR(40),
  error_message VARCHAR(200),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_ai_call_logs_request_id ON ai_call_logs (request_id);
CREATE INDEX IF NOT EXISTS ix_ai_call_logs_subject_ref ON ai_call_logs (subject_ref);
CREATE INDEX IF NOT EXISTS ix_ai_call_logs_status ON ai_call_logs (status);
CREATE INDEX IF NOT EXISTS ix_ai_call_logs_created_at ON ai_call_logs (created_at);

-- ============================================================
-- SQLite（本地零依赖调试）
-- 与 PostgreSQL 的差异：
-- 1. SQLite 没有 BOOLEAN，用 INTEGER 的 0/1 表示；
-- 2. 没有 TIMESTAMPTZ，用 DATETIME；
-- 3. 索引用 CREATE INDEX IF NOT EXISTS 即可。
-- ============================================================
-- CREATE TABLE IF NOT EXISTS ai_providers (
--   id VARCHAR(40) PRIMARY KEY,
--   name VARCHAR(40) NOT NULL UNIQUE,
--   provider_type VARCHAR(30) NOT NULL DEFAULT 'openai_compatible',
--   base_url VARCHAR(255) NOT NULL,
--   api_key_encrypted TEXT NOT NULL,
--   model VARCHAR(80) NOT NULL,
--   enabled INTEGER NOT NULL DEFAULT 1,
--   priority INTEGER NOT NULL DEFAULT 100,
--   timeout_seconds INTEGER NOT NULL DEFAULT 20,
--   max_output_tokens INTEGER NOT NULL DEFAULT 800,
--   last_test_at DATETIME,
--   last_test_ok INTEGER,
--   last_test_message VARCHAR(200),
--   created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
--   updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
-- );
--
-- CREATE TABLE IF NOT EXISTS ai_call_logs (
--   id VARCHAR(40) PRIMARY KEY,
--   request_id VARCHAR(64),
--   subject_ref VARCHAR(80) NOT NULL,
--   context_type VARCHAR(20) NOT NULL,
--   provider_id VARCHAR(40),
--   provider_name VARCHAR(40) NOT NULL,
--   model VARCHAR(80) NOT NULL,
--   status VARCHAR(20) NOT NULL,
--   latency_ms INTEGER NOT NULL DEFAULT 0,
--   prompt_tokens INTEGER NOT NULL DEFAULT 0,
--   completion_tokens INTEGER NOT NULL DEFAULT 0,
--   total_tokens INTEGER NOT NULL DEFAULT 0,
--   error_code VARCHAR(40),
--   error_message VARCHAR(200),
--   created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
-- );
--
-- CREATE INDEX IF NOT EXISTS ix_ai_call_logs_request_id ON ai_call_logs (request_id);
-- CREATE INDEX IF NOT EXISTS ix_ai_call_logs_subject_ref ON ai_call_logs (subject_ref);
-- CREATE INDEX IF NOT EXISTS ix_ai_call_logs_status ON ai_call_logs (status);
-- CREATE INDEX IF NOT EXISTS ix_ai_call_logs_created_at ON ai_call_logs (created_at);
