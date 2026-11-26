-- 2026-11-26 新增：AI 对话历史（会话、消息）与模型上下文窗口配置
--
-- 背景：
-- 1. 移动端对话采用“本地为主 + 登录后合并上云”：
--    游客消息只在 Redis 保留最近 30 分钟，长期记录存在手机本地；
--    登录用户的会话与消息落库，默认保留 30 天。
-- 2. 每次请求只带最近 8 条消息；历史 token 达到模型上下文窗口 60% 时，
--    把超出窗口的旧消息交给模型压缩成摘要，摘要存在会话表上。
-- 3. 后台新增模型时需要填写上下文窗口大小，用于判断压缩阈值和长度兜底。
--
-- 与已有迁移脚本一致，项目没有引入 Alembic：
-- 1. 正常启动应用时 Base.metadata.create_all 会自动补建缺失的新表；
-- 2. 生产环境通常不允许应用账号自动建表，需要数据库管理员审阅后执行本脚本；
-- 3. 本脚本同时作为表结构、索引和字段变更的书面记录。
--
-- 执行前请先备份数据库。两种数据库二选一，不要都执行。

-- ============================================================
-- PostgreSQL（生产 / Docker Compose 使用的数据库）
-- ============================================================

-- 模型上下文窗口：一次请求最多能容纳多少 token。
-- 默认 32768 只是保守起点，运营应在后台按供应商文档修改。
ALTER TABLE ai_providers
  ADD COLUMN IF NOT EXISTS context_window_tokens INTEGER NOT NULL DEFAULT 32768;

CREATE TABLE IF NOT EXISTS ai_conversations (
  id VARCHAR(40) PRIMARY KEY,
  -- 调用者标识：user:用户编号 或 guest:设备号。
  subject_ref VARCHAR(80) NOT NULL,
  -- 登录用户编号；游客为空。删除账号时按这个字段清理 AI 记录。
  user_id VARCHAR(40),
  -- 客户端本地会话编号，用于登录后重复同步时的幂等判断。
  client_conversation_id VARCHAR(64),
  -- 入口：home、post、recipe_list。
  context_type VARCHAR(20) NOT NULL DEFAULT 'home',
  -- 会话标题，取第一条用户消息的前 30 个字。
  title VARCHAR(60) NOT NULL DEFAULT '',
  -- 旧对话压缩后的摘要。
  summary TEXT,
  -- 已合并进摘要的消息条数（按时间正序）。
  summary_message_count INTEGER NOT NULL DEFAULT 0,
  -- 消息总条数，列表展示用，避免每次 count。
  message_count INTEGER NOT NULL DEFAULT 0,
  -- 最后一次消息时间：30 分钟无操作开新会话，30 天未活跃由清理任务删除。
  last_active_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 同一用户的同一段本地会话只能合并一次，重复同步只会补消息。
CREATE UNIQUE INDEX IF NOT EXISTS uq_ai_conversation_client
  ON ai_conversations (user_id, client_conversation_id);
CREATE INDEX IF NOT EXISTS ix_ai_conversations_subject_ref
  ON ai_conversations (subject_ref);
CREATE INDEX IF NOT EXISTS ix_ai_conversations_user_id
  ON ai_conversations (user_id);
CREATE INDEX IF NOT EXISTS ix_ai_conversations_last_active_at
  ON ai_conversations (last_active_at);

CREATE TABLE IF NOT EXISTS ai_messages (
  id VARCHAR(40) PRIMARY KEY,
  conversation_id VARCHAR(40) NOT NULL REFERENCES ai_conversations(id),
  -- 冗余用户编号，删除账号数据时可直接按 user_id 删除。
  user_id VARCHAR(40),
  -- 客户端生成的唯一编号，服务端自己产生的消息也遵守同一规则。
  client_message_id VARCHAR(64) NOT NULL,
  -- user 用户、assistant 助手。
  role VARCHAR(20) NOT NULL,
  content TEXT NOT NULL,
  -- 估算 token 数，用于判断是否达到窗口 60% 的压缩阈值。
  token_estimate INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 同一会话内客户端消息编号唯一：网络重试、重复同步都不会写入两条相同消息。
CREATE UNIQUE INDEX IF NOT EXISTS uq_ai_message_client
  ON ai_messages (conversation_id, client_message_id);
CREATE INDEX IF NOT EXISTS ix_ai_messages_conversation_id
  ON ai_messages (conversation_id);
CREATE INDEX IF NOT EXISTS ix_ai_messages_user_id
  ON ai_messages (user_id);
CREATE INDEX IF NOT EXISTS ix_ai_messages_created_at
  ON ai_messages (created_at);

-- ============================================================
-- SQLite（本地零依赖调试）
-- 差异：没有 TIMESTAMPTZ（用 DATETIME）、默认时间用 CURRENT_TIMESTAMP；
-- ADD COLUMN 不支持 IF NOT EXISTS，只在首次变更时执行一次。
-- ============================================================
-- ALTER TABLE ai_providers ADD COLUMN context_window_tokens INTEGER NOT NULL DEFAULT 32768;
--
-- CREATE TABLE IF NOT EXISTS ai_conversations (
--   id VARCHAR(40) PRIMARY KEY,
--   subject_ref VARCHAR(80) NOT NULL,
--   user_id VARCHAR(40),
--   client_conversation_id VARCHAR(64),
--   context_type VARCHAR(20) NOT NULL DEFAULT 'home',
--   title VARCHAR(60) NOT NULL DEFAULT '',
--   summary TEXT,
--   summary_message_count INTEGER NOT NULL DEFAULT 0,
--   message_count INTEGER NOT NULL DEFAULT 0,
--   last_active_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
--   created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
--   updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
-- );
-- CREATE UNIQUE INDEX IF NOT EXISTS uq_ai_conversation_client
--   ON ai_conversations (user_id, client_conversation_id);
-- CREATE INDEX IF NOT EXISTS ix_ai_conversations_subject_ref ON ai_conversations (subject_ref);
-- CREATE INDEX IF NOT EXISTS ix_ai_conversations_user_id ON ai_conversations (user_id);
-- CREATE INDEX IF NOT EXISTS ix_ai_conversations_last_active_at ON ai_conversations (last_active_at);
--
-- CREATE TABLE IF NOT EXISTS ai_messages (
--   id VARCHAR(40) PRIMARY KEY,
--   conversation_id VARCHAR(40) NOT NULL REFERENCES ai_conversations(id),
--   user_id VARCHAR(40),
--   client_message_id VARCHAR(64) NOT NULL,
--   role VARCHAR(20) NOT NULL,
--   content TEXT NOT NULL,
--   token_estimate INTEGER NOT NULL DEFAULT 0,
--   created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
-- );
-- CREATE UNIQUE INDEX IF NOT EXISTS uq_ai_message_client
--   ON ai_messages (conversation_id, client_message_id);
-- CREATE INDEX IF NOT EXISTS ix_ai_messages_conversation_id ON ai_messages (conversation_id);
-- CREATE INDEX IF NOT EXISTS ix_ai_messages_user_id ON ai_messages (user_id);
-- CREATE INDEX IF NOT EXISTS ix_ai_messages_created_at ON ai_messages (created_at);
