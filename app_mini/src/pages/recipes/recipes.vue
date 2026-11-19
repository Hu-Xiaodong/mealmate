<script setup lang="ts">
import { onLoad, onPullDownRefresh, onReachBottom } from "@dcloudio/uni-app";
import { ref } from "vue";

import { api } from "../../api/client";
import type { Recipe, RecipeCategory } from "../../api/types";
import AppHeader from "../../components/AppHeader.vue";
import EmptyState from "../../components/EmptyState.vue";
import RecipeCard from "../../components/RecipeCard.vue";
import { showError } from "../../utils/format";

const categories: { code: RecipeCategory; label: string }[] = [
  { code: "recommended", label: "推荐" },
  { code: "quick", label: "快手" },
  { code: "one_pot", label: "一锅" },
  { code: "few", label: "少食材" },
];

const category = ref<RecipeCategory>("recommended");
const recipes = ref<Recipe[]>([]);
const cursor = ref<string | null>(null);
const hasMore = ref(false);
const loading = ref(false);
const loaded = ref(false);

async function load(reset: boolean) {
  if (loading.value) return;
  loading.value = true;
  if (reset) cursor.value = null;
  try {
    const page = await api.recipes({
      category: category.value,
      cursor: reset ? null : cursor.value,
      limit: 20,
    });
    recipes.value = reset ? page.items : recipes.value.concat(page.items);
    cursor.value = page.nextCursor;
    hasMore.value = page.hasMore;
  } catch (error) {
    showError(error);
  } finally {
    loading.value = false;
    loaded.value = true;
  }
}

function switchCategory(next: RecipeCategory) {
  if (category.value === next) return;
  category.value = next;
  void load(true);
}

onLoad(() => {
  void load(true);
});

onPullDownRefresh(async () => {
  await load(true);
  uni.stopPullDownRefresh();
});

onReachBottom(() => {
  if (hasMore.value && !loading.value) void load(false);
});
</script>

<template>
  <view class="page">
    <AppHeader title="菜谱" subtitle="平台试做 · 可核实的简单做法" />

    <scroll-view class="chips" scroll-x :show-scrollbar="false">
      <view class="chips-inner">
        <view
          v-for="item in categories"
          :key="item.code"
          class="chip"
          :class="{ active: category === item.code }"
          @tap="switchCategory(item.code)"
        >
          <text>{{ item.label }}</text>
        </view>
      </view>
    </scroll-view>

    <view class="list">
      <RecipeCard v-for="recipe in recipes" :key="recipe.id" :recipe="recipe" />
      <view v-if="loading && !recipes.length" class="hint"><text>加载中…</text></view>
      <EmptyState
        v-else-if="loaded && !recipes.length"
        title="这个分类还没有菜谱"
        description="菜谱需要经过试做和来源核对，我们会慢慢补齐。"
      />
      <view v-else-if="recipes.length && !hasMore" class="hint"><text>已经到底了</text></view>
    </view>
  </view>
</template>

<style>
.page {
  padding: 0 16px 24px;
}

.chips {
  width: 100%;
  white-space: nowrap;
  padding: 8px 4px 14px;
}

.chips-inner {
  display: inline-flex;
  gap: 8px;
  padding-right: 8px;
}

.chip {
  padding: 7px 16px;
  border-radius: 999px;
  background: var(--c-card);
  color: var(--c-muted);
  font-size: 13px;
  border: 1px solid var(--c-line);
}

.chip.active {
  background: var(--c-peach);
  color: var(--c-primary-deep);
  border-color: rgba(204, 70, 44, 0.35);
  font-weight: 600;
}

.hint {
  text-align: center;
  padding: 20px 0;
  color: var(--c-faint);
  font-size: 12px;
}
</style>
