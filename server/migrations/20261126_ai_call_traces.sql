-- 2026-11-26 新增：AI 调用过程明细表（管理后台“模型调用详情”页使用）
--
-- 背景：ai_call_logs 只保存一次调用尝试的汇总结果（耗时、token、错误码），
-- 排查问题时看不到“提示词写了什么、模型原样返回了什么、在哪一步被校验拦下”。
-- 本次新增 ai_call_traces，把一次调用过程中的每个步骤单独记一行，按 seq 排序展示。
--
-- 与已有迁移脚本一致，项目没有引入 Alembic：
-- 1. 正常启动应用时 Base.metadata.create_all 会自动补建缺失的新表；
-- 2. 生产环境通常不允许应用账号自动建表，需要由数据库管理员审阅后执行本脚本；
-- 3. 本脚本同时作为表结构与索引的书面记录，方便代码评审和回溯。
--
-- 执行前请先备份数据库。两种数据库二选一，不要都执行。

-- ============================================================
-- PostgreSQL（生产 / Docker Compose 使用的数据库）
-- ============================================================

CREATE TABLE IF NOT EXISTS ai_call_traces (
  id VARCHAR(40) PRIMARY KEY,
  -- 所属调用日志编号，对应 ai_call_logs.id。故意不做外键：
  -- 日志是历史事实，不应因为上层记录被清理而级联删除。
  call_log_id VARCHAR(40) NOT NULL,
  -- 冗余保存请求标识，便于按一次用户提问串联多次模型尝试。
  request_id VARCHAR(64),
  -- 步骤顺序号，从 1 开始，保证详情页时间线顺序稳定。
  seq INTEGER NOT NULL DEFAULT 0,
  -- 机器可读的步骤标识：model_request、model_response、output_parse、fallback 等。
  step VARCHAR(40) NOT NULL,
  -- 中文标题，详情页直接展示，前端不再维护翻译表。
  title VARCHAR(80) NOT NULL,
  -- success 成功、failed 失败、info 中性信息。
  status VARCHAR(20) NOT NULL DEFAULT 'info',
  -- 提示词、模型原始输出、校验结果等长文本。
  detail TEXT,
  -- 该步骤自身耗时（毫秒），不是整次调用耗时。
  duration_ms INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 详情页固定按“调用日志编号”查询，必须建索引，否则日志变多后会是全表扫描。
CREATE INDEX IF NOT EXISTS ix_ai_call_traces_call_log_id ON ai_call_traces (call_log_id);
CREATE INDEX IF NOT EXISTS ix_ai_call_traces_request_id ON ai_call_traces (request_id);
CREATE INDEX IF NOT EXISTS ix_ai_call_traces_created_at ON ai_call_traces (created_at);

-- ============================================================
-- SQLite（本地零依赖调试）
-- 与 PostgreSQL 的差异：没有 TIMESTAMPTZ，用 DATETIME；默认时间用 CURRENT_TIMESTAMP。
-- ============================================================
-- CREATE TABLE IF NOT EXISTS ai_call_traces (
--   id VARCHAR(40) PRIMARY KEY,
--   call_log_id VARCHAR(40) NOT NULL,
--   request_id VARCHAR(64),
--   seq INTEGER NOT NULL DEFAULT 0,
--   step VARCHAR(40) NOT NULL,
--   title VARCHAR(80) NOT NULL,
--   status VARCHAR(20) NOT NULL DEFAULT 'info',
--   detail TEXT,
--   duration_ms INTEGER NOT NULL DEFAULT 0,
--   created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
-- );
--
-- CREATE INDEX IF NOT EXISTS ix_ai_call_traces_call_log_id ON ai_call_traces (call_log_id);
-- CREATE INDEX IF NOT EXISTS ix_ai_call_traces_request_id ON ai_call_traces (request_id);
-- CREATE INDEX IF NOT EXISTS ix_ai_call_traces_created_at ON ai_call_traces (created_at);
