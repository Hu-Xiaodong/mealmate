<script setup lang="ts">
import { onLoad, onPullDownRefresh, onReachBottom } from "@dcloudio/uni-app";
import { computed, ref } from "vue";

import { api } from "../../api/client";
import type { PostCard as PostCardModel } from "../../api/types";
import AppHeader from "../../components/AppHeader.vue";
import EmptyState from "../../components/EmptyState.vue";
import PostCard from "../../components/PostCard.vue";
import { dateLabel, showError } from "../../utils/format";
import { requireLogin } from "../../utils/gate";

const posts = ref<PostCardModel[]>([]);
const filter = ref<"all" | "near">("all");
const cursor = ref<string | null>(null);
const hasMore = ref(false);
const loading = ref(false);
const firstLoaded = ref(false);
const businessDate = ref("");
const coords = ref<{ lat: number; lng: number } | null>(null);

const subtitle = computed(() =>
  businessDate.value ? `今天 · ${dateLabel(businessDate.value)}` : "今天的饭，都在这里",
);

function locate(): Promise<{ lat: number; lng: number }> {
  return new Promise((resolve, reject) => {
    uni.getLocation({
      type: "gcj02",
      success: (result) => resolve({ lat: result.latitude, lng: result.longitude }),
      fail: () => reject(new Error("允许位置权限后才能查看附近的饭")),
    });
  });
}

async function load(reset: boolean) {
  if (loading.value) return;
  loading.value = true;
  if (reset) cursor.value = null;
  try {
    if (filter.value === "near" && !coords.value) {
      coords.value = await locate();
    }
    const page = await api.feed({
      filter: filter.value,
      cursor: reset ? null : cursor.value,
      limit: 10,
      lat: coords.value?.lat,
      lng: coords.value?.lng,
    });
    businessDate.value = page.businessDate;
    posts.value = reset ? page.items : posts.value.concat(page.items);
    cursor.value = page.nextCursor;
    hasMore.value = page.hasMore;
  } catch (error) {
    if (filter.value === "near") {
      filter.value = "all";
      coords.value = null;
    }
    showError(error);
  } finally {
    loading.value = false;
    firstLoaded.value = true;
  }
}

function switchFilter(next: "all" | "near") {
  if (filter.value === next) return;
  filter.value = next;
  void load(true);
}

function toggleLike(post: PostCardModel) {
  requireLogin(async () => {
    try {
      const result = await api.setLike(post.id, !post.likedByMe);
      post.likedByMe = result.liked;
      post.likeCount = result.likeCount;
    } catch (error) {
      showError(error);
    }
  });
}

function goPublish() {
  uni.navigateTo({ url: "/pages/publish/publish" });
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
    <AppHeader title="MealMate" :subtitle="subtitle">
      <template #action>
        <view class="publish" @tap="goPublish">
          <text class="plus">＋</text>
          <text class="publish-text">发布</text>
        </view>
      </template>
    </AppHeader>

    <view class="filters">
      <view class="seg">
        <view class="seg-item" :class="{ active: filter === 'all' }" @tap="switchFilter('all')">
          <text>全部</text>
        </view>
        <view class="seg-item" :class="{ active: filter === 'near' }" @tap="switchFilter('near')">
          <text>附近 3 公里</text>
        </view>
      </view>
    </view>

    <view class="list">
      <PostCard
        v-for="post in posts"
        :key="post.id"
        :post="post"
        :show-distance="filter === 'near'"
        @like="toggleLike(post)"
      />

      <view v-if="loading" class="hint"><text>加载中…</text></view>
      <EmptyState
        v-else-if="firstLoaded && !posts.length"
        title="今天还没有饭帖"
        description="拍下你的这一餐，成为今天的第一条。"
        action-text="去发布"
        @action="goPublish"
      />
      <view v-else-if="posts.length && !hasMore" class="hint"><text>今天就看到这里</text></view>
    </view>
  </view>
</template>

<style>
.page {
  padding: 0 16px 24px;
}

.publish {
  display: flex;
  align-items: center;
  gap: 2px;
  background: var(--c-primary);
  border-radius: 999px;
  padding: 8px 16px;
  box-shadow: 0 6px 14px rgba(204, 70, 44, 0.22);
}

.plus {
  color: #ffffff;
  font-size: 13px;
}

.publish-text {
  color: #ffffff;
  font-size: 13px;
  font-weight: 600;
}

.filters {
  padding: 10px 4px 14px;
}

.seg {
  display: flex;
  background: #ececee;
  border-radius: 999px;
  padding: 3px;
}

.seg-item {
  flex: 1;
  text-align: center;
  padding: 8px 0;
  border-radius: 999px;
  font-size: 13px;
  color: var(--c-muted);
}

.seg-item.active {
  background: var(--c-card);
  color: var(--c-primary-deep);
  font-weight: 600;
  box-shadow: 0 2px 8px rgba(36, 36, 36, 0.08);
}

.list {
  min-height: 200px;
}

.hint {
  text-align: center;
  padding: 16px 0 8px;
  color: var(--c-faint);
  font-size: 12px;
}
</style>
