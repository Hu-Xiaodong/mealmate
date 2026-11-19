<script setup lang="ts">
import { onReachBottom, onShow } from "@dcloudio/uni-app";
import { ref } from "vue";

import { api } from "../../api/client";
import type { PostCard as PostCardModel } from "../../api/types";
import AppHeader from "../../components/AppHeader.vue";
import EmptyState from "../../components/EmptyState.vue";
import PostCard from "../../components/PostCard.vue";
import { useSessionStore } from "../../stores/session";
import { showError } from "../../utils/format";

const session = useSessionStore();

const posts = ref<PostCardModel[]>([]);
const cursor = ref<string | null>(null);
const hasMore = ref(false);
const loading = ref(false);
const loadedOnce = ref(false);

async function load(reset: boolean) {
  if (loading.value || !session.isLoggedIn) return;
  loading.value = true;
  if (reset) cursor.value = null;
  try {
    const page = await api.myPosts(reset ? null : cursor.value, 20);
    posts.value = reset ? page.items : posts.value.concat(page.items);
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

function goPublish() {
  uni.navigateTo({ url: "/pages/publish/publish" });
}

async function toggleLike(post: PostCardModel) {
  try {
    const result = await api.setLike(post.id, !post.likedByMe);
    post.likedByMe = result.liked;
    post.likeCount = result.likeCount;
  } catch (error) {
    showError(error);
  }
}

onShow(() => {
  if (session.isLoggedIn) void load(true);
});

onReachBottom(() => {
  if (hasMore.value && !loading.value) void load(false);
});
</script>

<template>
  <view class="page">
    <AppHeader title="我的发布" subtitle="记录每一顿认真吃过的饭" back>
      <template #action>
        <view class="publish" @tap="goPublish">
          <text class="publish-text">发布</text>
        </view>
      </template>
    </AppHeader>

    <EmptyState
      v-if="!session.isLoggedIn"
      title="登录后查看发布"
      description="登录后可以管理自己发布的饭帖和审核状态。"
      action-text="手机号登录"
      @action="goLogin"
    />

    <view v-else class="list">
      <PostCard v-for="post in posts" :key="post.id" :post="post" @like="toggleLike(post)" />

      <view v-if="loading" class="hint"><text>加载中…</text></view>
      <EmptyState
        v-else-if="loadedOnce && !posts.length"
        title="还没有发布过"
        description="拍下今天的这一餐，第一条饭帖由你开始。"
        action-text="去发布"
        @action="goPublish"
      />
      <view v-else-if="posts.length && !hasMore" class="hint"><text>发布记录都在这里了</text></view>
    </view>
  </view>
</template>

<style>
.page {
  padding: 0 16px 32px;
}

.publish {
  padding: 8px 16px;
  border-radius: 999px;
  background: var(--c-peach);
}

.publish-text {
  font-size: 13px;
  color: var(--c-primary-deep);
  font-weight: 600;
}

.list {
  display: flex;
  flex-direction: column;
}

.hint {
  padding: 18px 0;
  text-align: center;
  font-size: 12px;
  color: var(--c-faint);
}
</style>
