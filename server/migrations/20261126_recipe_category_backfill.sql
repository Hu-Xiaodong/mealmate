-- ============================================================
-- 已发布菜谱补默认分类（2026-11-26）
--
-- 背景：客户端菜谱列表是按分类筛选的（推荐/快手/一锅/少食材），
-- 筛选条件来自分类关联表 recipe_categories。知识库生成的菜谱草稿
-- 过去没有写分类，批量上架后状态虽然是 published，但列表查不到，
-- 表现为“管理后台已发布、移动端没有同步”。
--
-- 修复策略：
-- 1. 代码侧：知识库草稿默认归入“推荐”；新增/编辑/批量上架时，
--    已发布但没有任何分类的菜谱自动补“推荐”并同步关联表。
-- 2. 数据侧：本脚本一次性回填历史数据，让已经上架的菜谱立即出现在
--    App 的“推荐”分类里。
--
-- 为什么把 recipes.category_codes 和 recipe_categories 一起改：
--   前者用于详情展示，后者用于列表筛选，只改一边会出现
--   “详情显示有分类、列表却查不到”的脏数据。
--
-- 适用数据库：PostgreSQL
-- 执行方式：psql -d <数据库名> -f 20261126_recipe_category_backfill.sql
-- 说明：脚本可重复执行；已有关联的菜谱不会被重复处理。
-- ============================================================

BEGIN;

-- 第一步：补齐 JSON 字段，详情页和后台编辑表单都能看到“推荐”分类。
UPDATE recipes
SET category_codes = '["recommended"]'::json
WHERE status = 'published'
  AND json_array_length(category_codes) = 0
  AND NOT EXISTS (
      SELECT 1 FROM recipe_categories rc WHERE rc.recipe_id = recipes.id
  );

-- 第二步：补齐关联表，客户端按 recommended 筛选时能查到这些菜谱。
-- id 规则与代码里的 new_id("rc") 一致：固定前缀 + 16 位十六进制随机串。
INSERT INTO recipe_categories (id, recipe_id, code)
SELECT 'rc_' || substr(md5(random()::text || r.id), 1, 16), r.id, 'recommended'
FROM recipes r
WHERE r.status = 'published'
  AND NOT EXISTS (
      SELECT 1 FROM recipe_categories rc WHERE rc.recipe_id = r.id
  );

COMMIT;
