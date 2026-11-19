<script setup lang="ts">
import { onLoad } from "@dcloudio/uni-app";
import { computed, ref } from "vue";

import { api } from "../../api/client";
import type { Recipe } from "../../api/types";
import AppHeader from "../../components/AppHeader.vue";
import EmptyState from "../../components/EmptyState.vue";
import { resolveMedia } from "../../config";
import { showError, toolLabels } from "../../utils/format";
import { requireLogin } from "../../utils/gate";

const recipe = ref<Recipe | null>(null);
const loading = ref(true);

const tools = computed(() => (recipe.value ? toolLabels(recipe.value.tools) : []));

async function load(id: string) {
  loading.value = true;
  try {
    recipe.value = await api.recipe(id);
  } catch (error) {
    showError(error);
  } finally {
    loading.value = false;
  }
}

function toggleSave() {
  const current = recipe.value;
  if (!current) return;
  requireLogin(async () => {
    try {
      const result = await api.setFavorite("recipe", current.id, !current.savedByMe);
      current.savedByMe = result.saved;
      uni.showToast({ title: result.saved ? "已收藏菜谱" : "已取消收藏", icon: "none" });
    } catch (error) {
      showError(error);
    }
  });
}

onLoad((options) => {
  const id = options?.id;
  if (!id) {
    showError(new Error("缺少菜谱编号"));
    loading.value = false;
    return;
  }
  void load(id);
});
</script>

<template>
  <view class="page">
    <AppHeader title="菜谱" :subtitle="recipe ? `${recipe.totalMinutes} 分钟 · ${recipe.servings} 人份` : ''" back />

    <view v-if="recipe" class="content">
      <image class="cover" :src="resolveMedia(recipe.coverImage)" mode="aspectFill" />

      <view class="card main">
        <text class="title">{{ recipe.title }}</text>
        <view class="chips">
          <text class="chip strong">{{ recipe.totalMinutes }} 分钟</text>
          <text v-for="tool in tools" :key="tool" class="chip">{{ tool }}</text>
          <text class="chip">{{ recipe.servings }} 人份</text>
        </view>
        <view v-if="recipe.preconditions" class="pre">
          <text class="pre-label">前提</text>
          <text class="pre-text">{{ recipe.preconditions }}</text>
        </view>
      </view>

      <view class="card">
        <text class="section-title">食材</text>
        <view v-for="item in recipe.ingredients" :key="item.name" class="ingredient">
          <text class="ingredient-name">{{ item.name }}</text>
          <text class="ingredient-amount">{{ item.amount }}</text>
        </view>
      </view>

      <view class="card">
        <text class="section-title">步骤</text>
        <view v-for="(step, index) in recipe.steps" :key="`${index}-${step}`" class="step">
          <text class="step-no">{{ index + 1 }}</text>
          <text class="step-text">{{ step }}</text>
        </view>
      </view>

      <view class="source">
        <text class="source-text">内容来源：{{ recipe.contentOrigin === "platform" ? "平台试做菜谱" : recipe.contentOrigin }} · {{ recipe.validationStatus === "tested" ? "已试做核对" : recipe.validationStatus }}</text>
      </view>
    </view>

    <EmptyState v-else-if="!loading" title="这道菜谱看不到" description="可能已经下架，去看看其他快手菜。" />

    <view v-if="recipe" class="bar">
      <view class="bar-save" :class="{ saved: recipe.savedByMe }" @tap="toggleSave">
        <text class="bar-icon">{{ recipe.savedByMe ? "★" : "☆" }}</text>
        <text class="bar-text">{{ recipe.savedByMe ? "已收藏" : "收藏这道菜" }}</text>
      </view>
    </view>
  </view>
</template>

<style>
.page {
  padding: 0 16px calc(20px + env(safe-area-inset-bottom));
}

.content {
  padding-top: 8px;
  padding-bottom: 84px;
}

.cover {
  width: 100%;
  height: 280px;
  border-radius: var(--radius-lg);
  background: var(--c-peach);
}

.card {
  background: var(--c-card);
  border-radius: var(--radius-lg);
  padding: 18px;
  margin-top: 14px;
  box-shadow: 0 6px 18px rgba(36, 36, 36, 0.05);
}

.title {
  font-size: 22px;
  font-weight: 700;
}

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}

.chip {
  font-size: 12px;
  color: var(--c-muted);
  background: var(--c-bg);
  border-radius: 999px;
  padding: 4px 10px;
}

.chip.strong {
  color: var(--c-primary-deep);
  background: var(--c-peach);
}

.pre {
  margin-top: 14px;
  padding-top: 14px;
  border-top: 1px solid var(--c-line);
  display: flex;
  gap: 10px;
}

.pre-label {
  font-size: 13px;
  color: var(--c-faint);
  flex-shrink: 0;
}

.pre-text {
  font-size: 13px;
  color: var(--c-muted);
  line-height: 1.6;
}

.section-title {
  font-size: 16px;
  font-weight: 700;
  color: var(--c-primary-deep);
  margin-bottom: 10px;
}

.ingredient {
  display: flex;
  justify-content: space-between;
  padding: 9px 0;
  border-bottom: 1px solid var(--c-line);
}

.ingredient:last-child {
  border-bottom: none;
}

.ingredient-name {
  font-size: 14px;
}

.ingredient-amount {
  font-size: 13px;
  color: var(--c-muted);
}

.step {
  display: flex;
  gap: 10px;
  padding: 7px 0;
}

.step-no {
  width: 20px;
  height: 20px;
  border-radius: 10px;
  background: var(--c-peach);
  color: var(--c-primary-deep);
  font-size: 12px;
  text-align: center;
  line-height: 20px;
  flex-shrink: 0;
}

.step-text {
  flex: 1;
  font-size: 14px;
  line-height: 1.6;
}

.source {
  padding: 14px 6px 0;
}

.source-text {
  font-size: 11px;
  color: var(--c-faint);
  line-height: 1.6;
}

.bar {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  padding: 10px 16px calc(10px + env(safe-area-inset-bottom));
  background: rgba(255, 255, 255, 0.96);
  border-top: 1px solid var(--c-line);
}

.bar-save {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  background: var(--c-primary);
  border-radius: 999px;
  padding: 12px 0;
}

.bar-save.saved {
  background: var(--c-peach);
  border: 1px solid rgba(204, 70, 44, 0.35);
}

.bar-icon {
  font-size: 16px;
  color: #ffffff;
}

.bar-save.saved .bar-icon {
  color: var(--c-primary-deep);
}

.bar-text {
  font-size: 14px;
  font-weight: 600;
  color: #ffffff;
}

.bar-save.saved .bar-text {
  color: var(--c-primary-deep);
}
</style>
