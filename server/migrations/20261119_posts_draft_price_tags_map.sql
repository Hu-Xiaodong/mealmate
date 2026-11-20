-- 2026-11-19 饭帖新增：人均价格、口味标签、店铺坐标、软删除
--
-- 背景：项目没有引入 Alembic（数据库迁移框架），建表依赖
-- Base.metadata.create_all。create_all 只会“补建缺失的表”，
-- 不会给已经存在的表补字段，所以老数据库需要手工执行一次本文件。
--
-- 新数据库不用执行：首次启动 create_all 会直接按最新模型建表。
-- 执行前请先备份数据库。两种数据库二选一，不要都执行。

-- ============================================================
-- PostgreSQL（生产 / Docker Compose 使用的数据库）
-- ============================================================
ALTER TABLE meal_posts ADD COLUMN IF NOT EXISTS avg_price INTEGER;
ALTER TABLE meal_posts ADD COLUMN IF NOT EXISTS taste_tags JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE meal_posts ADD COLUMN IF NOT EXISTS store_lat DOUBLE PRECISION;
ALTER TABLE meal_posts ADD COLUMN IF NOT EXISTS store_lng DOUBLE PRECISION;
ALTER TABLE meal_posts ADD COLUMN IF NOT EXISTS store_poi_id VARCHAR(64);
ALTER TABLE meal_posts ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;

-- 说明：
-- 1. avg_price 允许为空，表示用户没有填写人均价格；
-- 2. taste_tags 默认空数组，老数据不需要回填；
-- 3. store_lat / store_lng 是餐厅坐标，与已有的 coarse_lat / coarse_lng 不同，
--    coarse_* 表示发布者本人的粗略位置；
-- 4. deleted_at 用于软删除，status 同时会变成 deleted。

-- ============================================================
-- SQLite（本地零依赖调试）
-- SQLite 的 ALTER TABLE 一次只能加一列，且不支持 IF NOT EXISTS，
-- 因此下面的语句只能在“还没加过字段”的库上执行一次。
-- ============================================================
-- ALTER TABLE meal_posts ADD COLUMN avg_price INTEGER;
-- ALTER TABLE meal_posts ADD COLUMN taste_tags JSON NOT NULL DEFAULT '[]';
-- ALTER TABLE meal_posts ADD COLUMN store_lat FLOAT;
-- ALTER TABLE meal_posts ADD COLUMN store_lng FLOAT;
-- ALTER TABLE meal_posts ADD COLUMN store_poi_id VARCHAR(64);
-- ALTER TABLE meal_posts ADD COLUMN deleted_at DATETIME;
