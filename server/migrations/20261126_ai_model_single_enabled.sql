-- ============================================================
-- 同一用途只允许启用一个模型（2026-11-26）
--
-- 背景：产品要求“模型开关，同一个类型只能开一个；调用时使用开启的那个”。
-- 原来的逻辑是“所有启用的模型按优先级依次尝试”，允许多个同时启用；
-- 现在改为“每个用途（聊天 chat / 嵌入 embedding）同时只有一个启用模型”。
--
-- 本脚本做两件事：
-- 1. 回填历史数据：同一用途如果有多条启用记录，保留优先级最高的一条，
--    其余自动停用（不删除配置，随时可以在后台重新启用）。
-- 2. 增加部分唯一索引：从数据库层保证同一用途最多只有一条 enabled = true，
--    避免两个管理员同时操作、或以后新增接口时绕过服务层校验。
--
-- 适用数据库：PostgreSQL
-- 执行方式：psql -d <数据库名> -f 20261126_ai_model_single_enabled.sql
-- 说明：脚本可重复执行；回填只影响同一用途下排名第二及以后的启用记录。
-- ============================================================

BEGIN;

-- 第一步：每个用途只保留优先级最高的启用模型。
-- 优先级数字越小越优先；相同时取创建时间更早、编号更小的，保证结果确定。
WITH ranked AS (
    SELECT
        id,
        row_number() OVER (
            PARTITION BY kind
            ORDER BY priority ASC, created_at ASC, id ASC
        ) AS rn
    FROM ai_providers
    WHERE enabled = TRUE
)
UPDATE ai_providers AS provider
SET enabled = FALSE,
    updated_at = now()
FROM ranked
WHERE provider.id = ranked.id
  AND ranked.rn > 1;

-- 第二步：数据库层约束。部分索引只覆盖 enabled = true 的行，
-- 因此停用的配置可以有任意多条，启用项每个 kind 最多一条。
CREATE UNIQUE INDEX IF NOT EXISTS uq_ai_providers_enabled_kind
    ON ai_providers (kind)
    WHERE enabled = TRUE;

COMMIT;
