-- 2026-11-20 新增：口味标签字典表、用户最近定位表
--
-- 背景：项目没有引入 Alembic（数据库迁移框架），建表依赖
-- Base.metadata.create_all。create_all 只会“补建缺失的表”，
-- 不会修改已存在的表结构，所以老数据库需要手工执行一次本文件。
--
-- 新数据库不用执行：首次启动 create_all 会直接按最新模型建表，
-- 并且应用启动时会自动补齐口味标签的默认数据。
-- 执行前请先备份数据库。两种数据库二选一，不要都执行。

-- ============================================================
-- PostgreSQL（生产 / Docker Compose 使用的数据库）
-- ============================================================

-- 口味标签字典：前端展示哪些标签、按什么顺序，全部以这张表为准。
CREATE TABLE IF NOT EXISTS taste_tags (
  name VARCHAR(20) PRIMARY KEY,
  sort_order INTEGER NOT NULL DEFAULT 0,
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 初始数据与旧前端页面展示的 9 个标签完全一致。
-- ON CONFLICT DO NOTHING 保证重复执行不会报错，也不会覆盖运营改过的顺序。
INSERT INTO taste_tags (name, sort_order, enabled) VALUES
  ('清淡', 1, TRUE),
  ('正常', 2, TRUE),
  ('香辣', 3, TRUE),
  ('酸甜', 4, TRUE),
  ('咸鲜', 5, TRUE),
  ('油炸', 6, TRUE),
  ('烧烤', 7, TRUE),
  ('汤羹', 8, TRUE),
  ('面食', 9, TRUE)
ON CONFLICT (name) DO NOTHING;

-- 用户最近一次定位：每个账号一条，主键即账号编号。
-- 用途：手机定位不可用时，用上一次成功定位作为地图中心点。
CREATE TABLE IF NOT EXISTS user_locations (
  account_id VARCHAR(40) PRIMARY KEY REFERENCES users(id),
  lat DOUBLE PRECISION NOT NULL,
  lng DOUBLE PRECISION NOT NULL,
  area VARCHAR(80),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- SQLite（本地零依赖调试）
-- 与 PostgreSQL 的差异：
-- 1. SQLite 没有 BOOLEAN，用 INTEGER 的 0/1 表示；
-- 2. 没有 TIMESTAMPTZ，用 DATETIME；
-- 3. 没有 ON CONFLICT ... DO NOTHING 的旧版本可改用 INSERT OR IGNORE。
-- ============================================================
-- CREATE TABLE IF NOT EXISTS taste_tags (
--   name VARCHAR(20) PRIMARY KEY,
--   sort_order INTEGER NOT NULL DEFAULT 0,
--   enabled INTEGER NOT NULL DEFAULT 1,
--   created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
-- );
-- INSERT OR IGNORE INTO taste_tags (name, sort_order, enabled) VALUES
--   ('清淡', 1, 1), ('正常', 2, 1), ('香辣', 3, 1), ('酸甜', 4, 1), ('咸鲜', 5, 1),
--   ('油炸', 6, 1), ('烧烤', 7, 1), ('汤羹', 8, 1), ('面食', 9, 1);
--
-- CREATE TABLE IF NOT EXISTS user_locations (
--   account_id VARCHAR(40) PRIMARY KEY REFERENCES users(id),
--   lat FLOAT NOT NULL,
--   lng FLOAT NOT NULL,
--   area VARCHAR(80),
--   updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
-- );
