-- 提示词变量：共用变量 + 专属变量
--
-- 适用数据库：PostgreSQL（开发/生产）与 SQLite（单元测试）。
-- SQLite 没有 JSONB 和部分索引的某些写法差异，文件末尾给出 SQLite 版本；
-- 测试环境通过 Base.metadata.create_all 建表，不需要手工执行这份脚本。

ALTER TABLE ai_prompt_versions
    ADD COLUMN IF NOT EXISTS variables JSONB;

CREATE TABLE IF NOT EXISTS ai_prompt_variables (
    id VARCHAR(40) PRIMARY KEY,
    key VARCHAR(80) NOT NULL,
    value TEXT NOT NULL DEFAULT '',
    default_value TEXT,
    scope VARCHAR(20) NOT NULL,
    prompt_name VARCHAR(80),
    updated_by VARCHAR(80) NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_ai_prompt_variable_scope CHECK (scope IN ('shared', 'prompt'))
);

CREATE INDEX IF NOT EXISTS ix_ai_prompt_variables_key
    ON ai_prompt_variables (key);
CREATE INDEX IF NOT EXISTS ix_ai_prompt_variables_scope
    ON ai_prompt_variables (scope);
CREATE INDEX IF NOT EXISTS ix_ai_prompt_variables_prompt_name
    ON ai_prompt_variables (prompt_name);
CREATE INDEX IF NOT EXISTS ix_ai_prompt_variables_updated_at
    ON ai_prompt_variables (updated_at);

-- 共用变量：同一个 key 只能有一条。
CREATE UNIQUE INDEX IF NOT EXISTS uq_ai_prompt_variable_shared_key
    ON ai_prompt_variables (key)
    WHERE scope = 'shared';

-- 专属变量：同一个提示词下同一个 key 只能有一条。
CREATE UNIQUE INDEX IF NOT EXISTS uq_ai_prompt_variable_prompt_key
    ON ai_prompt_variables (prompt_name, key)
    WHERE scope = 'prompt';

-- 默认共用变量：不是后端硬编码限制，维护者可以在变量管理页修改。
INSERT INTO ai_prompt_variables
    (id, key, value, default_value, scope, prompt_name, updated_by, created_at, updated_at)
SELECT 'aiv_default_' || seed.key, seed.key, seed.value, NULL, 'shared', NULL,
       'system', now(), now()
FROM (
    VALUES
        ('max_recipes', '3'),
        ('max_reply_chars', '200'),
        ('max_reason_chars', '30'),
        ('max_summary_chars', '300')
) AS seed(key, value)
WHERE NOT EXISTS (
    SELECT 1
    FROM ai_prompt_variables existing
    WHERE existing.scope = 'shared' AND existing.key = seed.key
);

-- SQLite 版本（在 SQLite 中手工执行时使用；测试环境无需执行）：
-- ALTER TABLE ai_prompt_versions ADD COLUMN variables JSON;
-- CREATE TABLE ai_prompt_variables (
--     id VARCHAR(40) PRIMARY KEY,
--     key VARCHAR(80) NOT NULL,
--     value TEXT NOT NULL DEFAULT '',
--     default_value TEXT,
--     scope VARCHAR(20) NOT NULL,
--     prompt_name VARCHAR(80),
--     updated_by VARCHAR(80) NOT NULL DEFAULT '',
--     created_at DATETIME NOT NULL,
--     updated_at DATETIME NOT NULL,
--     CONSTRAINT ck_ai_prompt_variable_scope CHECK (scope IN ('shared', 'prompt'))
-- );
-- CREATE UNIQUE INDEX uq_ai_prompt_variable_shared_key
--     ON ai_prompt_variables (key) WHERE scope = 'shared';
-- CREATE UNIQUE INDEX uq_ai_prompt_variable_prompt_key
--     ON ai_prompt_variables (prompt_name, key) WHERE scope = 'prompt';
