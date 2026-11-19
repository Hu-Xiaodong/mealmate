<script setup lang="ts">
import { onLoad, onPullDownRefresh } from "@dcloudio/uni-app";
import { ref } from "vue";

import { api } from "../../api/client";
import type { RankItem } from "../../api/types";
import AppHeader from "../../components/AppHeader.vue";
import EmptyState from "../../components/EmptyState.vue";
import { resolveMedia } from "../../config";
import { showError, sourceLabel } from "../../utils/format";

const items = ref<RankItem[]>([]);
const statDate = ref("");
const loading = ref(false);
const loaded = ref(false);

async function load() {
  loading.value = true;
  try {
    const data = await api.rank();
    items.value = data.items;
    statDate.value = data.statDate;
  } catch (error) {
    showError(error);
  } finally {
    loading.value = false;
    loaded.value = true;
  }
}

function open(item: RankItem) {
  uni.navigateTo({ url: `/pages/post/detail?id=${item.id}` });
}

onLoad(() => {
  void load();
});

onPullDownRefresh(async () => {
  await load();
  uni.stopPullDownRefresh();
});
</script>

<template>
  <view class="page">
    <AppHeader title="热榜" :subtitle="statDate ? `${statDate} · 有效赞排序` : '今日有效赞排序'" />

    <view class="notice">
      <text class="notice-text">每天按有效赞数排序，最多 20 条。榜单每天零点重新开始。</text>
    </view>

    <view class="list">
      <view v-for="item in items" :key="item.id" class="row" @tap="open(item)">
        <view class="rank" :class="{ top: item.rank <= 3 }">
          <text class="rank-text">{{ item.rank }}</text>
        </view>
        <image class="thumb" :src="resolveMedia(item.coverImage)" mode="aspectFill" />
        <view class="info">
          <text class="title">{{ item.title }}</text>
          <view class="chips">
            <text v-for="name in item.mainIngredients.slice(0, 3)" :key="name" class="chip">
              {{ name }}
            </text>
            <text v-if="!item.mainIngredients.length" class="chip">{{ sourceLabel(item.source) }}</text>
          </view>
          <view class="meta">
            <text class="likes">♥ {{ item.effectiveLikeCount }}</text>
            <text class="author">{{ item.author?.nickname || "饭友" }}</text>
          </view>
        </view>
      </view>

      <view v-if="loading && !items.length" class="hint"><text>正在结算今天的赞…</text></view>
      <EmptyState
        v-else-if="loaded && !items.length"
        title="今天还没有上榜饭帖"
        description="去首页给喜欢的饭帖点个赞，榜单会实时更新。"
      />
    </view>
  </view>
</template>

<style>
.page {
  padding: 0 16px 24px;
}

.notice {
  margin: 8px 4px 14px;
  padding: 10px 14px;
  border-radius: var(--radius-sm);
  background: var(--c-peach);
}

.notice-text {
  font-size: 12px;
  color: var(--c-primary-deep);
  line-height: 1.5;
}

.row {
  display: flex;
  align-items: center;
  gap: 12px;
  background: var(--c-card);
  border-radius: var(--radius-md);
  padding: 12px;
  margin-bottom: 10px;
  box-shadow: 0 4px 14px rgba(36, 36, 36, 0.05);
}

.rank {
  width: 28px;
  height: 28px;
  border-radius: 14px;
  background: var(--c-bg);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.rank.top {
  background: var(--c-primary);
}

.rank-text {
  font-size: 13px;
  font-weight: 700;
  color: var(--c-muted);
}

.rank.top .rank-text {
  color: #ffffff;
}

.thumb {
  width: 88px;
  height: 88px;
  border-radius: 12px;
  background: var(--c-peach);
  flex-shrink: 0;
}

.info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
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

.meta {
  display: flex;
  align-items: center;
  gap: 12px;
}

.likes {
  font-size: 12px;
  color: var(--c-primary);
  font-weight: 600;
}

.author {
  font-size: 12px;
  color: var(--c-faint);
}

.hint {
  text-align: center;
  padding: 24px 0;
  color: var(--c-faint);
  font-size: 12px;
}
</style>
