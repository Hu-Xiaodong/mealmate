<script setup lang="ts">
import { onReachBottom, onShow } from "@dcloudio/uni-app";
import { ref } from "vue";

import { api } from "../../api/client";
import type { FavoriteItem } from "../../api/types";
import AppHeader from "../../components/AppHeader.vue";
import EmptyState from "../../components/EmptyState.vue";
import { resolveMedia } from "../../config";
import { useSessionStore } from "../../stores/session";
import { dateLabel, showError } from "../../utils/format";

const session = useSessionStore();

const items = ref<FavoriteItem[]>([]);
const cursor = ref<string | null>(null);
const hasMore = ref(false);
const loading = ref(false);
const loadedOnce = ref(false);

async function load(reset: boolean) {
  if (loading.value || !session.isLoggedIn) return;
  loading.value = true;
  if (reset) cursor.value = null;
  try {
    const page = await api.myFavorites(reset ? null : cursor.value, 20);
    items.value = reset ? page.items : items.value.concat(page.items);
    cursor.value = page.nextCursor;
    hasMore.value = page.hasMore;
    loadedOnce.value = true;
  } catch (error) {
    showError(error);
  } finally {
    loading.value = false;
  }
}

function goLogin() {
  uni.navigateTo({ url: "/pages/login/login" });
}

function open(item: FavoriteItem) {
  if (!item.available) {
    showError(new Error("这条内容已下架或被作者删除"));
    return;
  }
  const url =
    item.targetType === "post"
      ? `/pages/post/detail?id=${item.targetId}`
      : `/pages/recipe/detail?id=${item.targetId}`;
  uni.navigateTo({ url });
}

async function remove(item: FavoriteItem) {
  try {
    await api.setFavorite(item.targetType, item.targetId, false);
    items.value = items.value.filter(
      (row) => !(row.targetType === item.targetType && row.targetId === item.targetId),
    );
    uni.showToast({ title: "已取消收藏", icon: "none" });
  } catch (error) {
    showError(error);
  }
}

onShow(() => {
  if (session.isLoggedIn && !loadedOnce.value) void load(true);
});

onReachBottom(() => {
  if (hasMore.value && !loading.value) void load(false);
});
</script>

<template>
  <view class="page">
    <AppHeader title="我的收藏" subtitle="想再吃一次的味道" back />

    <EmptyState
      v-if="!session.isLoggedIn"
      title="登录后查看收藏"
      description="收藏的饭帖和菜谱会保存在账号里，换设备也能看到。"
      action-text="手机号登录"
      @action="goLogin"
    />

    <view v-else class="list">
      <view
        v-for="item in items"
        :key="`${item.targetType}-${item.targetId}`"
        class="row card"
        @tap="open(item)"
      >
        <image class="thumb" :src="resolveMedia(item.coverImage)" mode="aspectFill" />
        <view class="info">
          <text class="title" :class="{ faded: !item.available }">{{ item.title }}</text>
          <text class="summary">{{ item.summary }}</text>
          <text class="meta">
            {{ item.targetType === "post" ? "饭帖" : "菜谱" }} ·
            {{ dateLabel(item.savedAt.slice(0, 10)) }}
          </text>
        </view>
        <view class="remove" @tap.stop="remove(item)">
          <text class="remove-text">取消</text>
        </view>
      </view>

      <view v-if="loading" class="hint"><text>加载中…</text></view>
      <EmptyState
        v-else-if="loadedOnce && !items.length"
        title="还没有收藏"
        description="在饭帖或菜谱详情页点收藏，就会出现在这里。"
      />
      <view v-else-if="items.length && !hasMore" class="hint"><text>收藏都在这里了</text></view>
    </view>
  </view>
</template>

<style>
.page {
  padding: 0 16px 32px;
}

.card {
  background: var(--c-card);
  border-radius: var(--radius-lg);
  box-shadow: 0 6px 18px rgba(36, 36, 36, 0.05);
}

.list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px;
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
  gap: 4px;
}

.title {
  font-size: 15px;
  font-weight: 600;
  color: var(--c-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.title.faded {
  color: var(--c-faint);
}

.summary {
  font-size: 12px;
  color: var(--c-muted);
  line-height: 1.5;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.meta {
  font-size: 11px;
  color: var(--c-faint);
}

.remove {
  padding: 6px 12px;
  border-radius: 999px;
  border: 1px solid var(--c-line);
  flex-shrink: 0;
}

.remove-text {
  font-size: 12px;
  color: var(--c-muted);
}

.hint {
  padding: 18px 0;
  text-align: center;
  font-size: 12px;
  color: var(--c-faint);
}
</style>
