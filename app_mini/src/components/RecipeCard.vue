<script setup lang="ts">
import { computed } from "vue";

import type { Recipe } from "../api/types";
import { resolveMedia } from "../config";
import { toolLabels } from "../utils/format";

const props = defineProps<{ recipe: Recipe }>();

const tools = computed(() => toolLabels(props.recipe.tools));

function open() {
  uni.navigateTo({ url: `/pages/recipe/detail?id=${props.recipe.id}` });
}
</script>

<template>
  <view class="recipe-card" @tap="open">
    <image class="cover" :src="resolveMedia(recipe.coverImage)" mode="aspectFill" />
    <view class="info">
      <text class="title">{{ recipe.title }}</text>
      <view class="chips">
        <text class="chip strong">{{ recipe.totalMinutes }} 分钟</text>
        <text v-for="tool in tools" :key="tool" class="chip">{{ tool }}</text>
        <text class="chip">{{ recipe.servings }} 人份</text>
      </view>
      <text v-if="recipe.preconditions" class="pre">{{ recipe.preconditions }}</text>
    </view>
    <view class="favorite" :class="{ active: recipe.savedByMe }">
      {{ recipe.savedByMe ? "已收藏" : "" }}
    </view>
  </view>
</template>

<style>
.recipe-card {
  display: flex;
  gap: 14px;
  background: var(--c-card);
  border-radius: var(--radius-md);
  padding: 12px;
  margin-bottom: 12px;
  box-shadow: 0 4px 14px rgba(36, 36, 36, 0.05);
}

.cover {
  width: 96px;
  height: 96px;
  border-radius: 12px;
  background: var(--c-peach);
  flex-shrink: 0;
}

.info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 8px;
}

.title {
  font-size: 16px;
  font-weight: 700;
}

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.chip {
  font-size: 11px;
  color: var(--c-muted);
  background: var(--c-bg);
  border-radius: 999px;
  padding: 3px 8px;
}

.chip.strong {
  color: var(--c-primary-deep);
  background: var(--c-peach);
}

.pre {
  font-size: 12px;
  color: var(--c-faint);
  line-height: 1.4;
}

.favorite {
  font-size: 11px;
  color: var(--c-primary);
  align-self: flex-start;
}
</style>
