<script setup lang="ts">
import { onReachBottom, onShow } from "@dcloudio/uni-app";
import { ref } from "vue";

import { api } from "../../api/client";
import type { DraftCard, PostCard as PostCardModel } from "../../api/types";
import AppHeader from "../../components/AppHeader.vue";
import EmptyState from "../../components/EmptyState.vue";
import PostCard from "../../components/PostCard.vue";
import { resolveMedia } from "../../config";
import { useSessionStore } from "../../stores/session";
import { dateTimeLabel, showError } from "../../utils/format";

type TabKey = "published" | "drafts";

const session = useSessionStore();

const tab = ref<TabKey>("published");

const posts = ref<PostCardModel[]>([]);
const postsCursor = ref<string | null>(null);
const postsHasMore = ref(false);
const postsLoading = ref(false);
const postsLoaded = ref(false);

const drafts = ref<DraftCard[]>([]);
const draftsCursor = ref<string | null>(null);
const draftsHasMore = ref(false);
const draftsLoading = ref(false);
const draftsLoaded = ref(false);

async function loadPublished(reset: boolean) {
  if (postsLoading.value || !session.isLoggedIn) return;
  postsLoading.value = true;
  if (reset) postsCursor.value = null;
  try {
    const page = await api.myPosts(reset ? null : postsCursor.value, 20);
    posts.value = reset ? page.items : posts.value.concat(page.items);
    postsCursor.value = page.nextCursor;
    postsHasMore.value = page.hasMore;
    postsLoaded.value = true;
  } catch (error) {
    showError(error);
  } finally {
    postsLoading.value = false;
  }
}

async function loadDrafts(reset: boolean) {
  if (draftsLoading.value || !session.isLoggedIn) return;
  draftsLoading.value = true;
  if (reset) draftsCursor.value = null;
  try {
    const page = await api.myDrafts(reset ? null : draftsCursor.value, 20);
    drafts.value = reset ? page.items : drafts.value.concat(page.items);
    draftsCursor.value = page.nextCursor;
    draftsHasMore.value = page.hasMore;
    draftsLoaded.value = true;
  } catch (error) {
    showError(error);
  } finally {
    draftsLoading.value = false;
  }
}

function loadActive(reset: boolean) {
  if (tab.value === "published") return loadPublished(reset);
  return loadDrafts(reset);
}

function switchTab(key: TabKey) {
  if (tab.value === key) return;
  tab.value = key;
  if (key === "published" && !postsLoaded.value) void loadPublished(true);
  if (key === "drafts" && !draftsLoaded.value) void loadDrafts(true);
}

function goLogin() {
  uni.navigateTo({ url: "/pages/login/login" });
}

function goPublish() {
  uni.navigateTo({ url: "/pages/publish/publish" });
}

function goDraft(id: string) {
  uni.navigateTo({ url: `/pages/publish/publish?id=${id}` });
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

function confirmDelete(id: string, target: TabKey) {
  uni.showModal({
    title: "删除确认",
    content: target === "drafts" ? "删除后这份草稿无法恢复，确定删除吗？" : "删除后饭帖将不再展示，确定删除吗？",
    confirmText: "删除",
    confirmColor: "#CC462C",
    success: async (result) => {
      if (!result.confirm) return;
      try {
        await api.deletePost(id);
        if (target === "published") {
          posts.value = posts.value.filter((item) => item.id !== id);
        } else {
          drafts.value = drafts.value.filter((item) => item.id !== id);
        }
        uni.showToast({ title: "已删除", icon: "none" });
      } catch (error) {
        showError(error);
      }
    },
  });
}

onShow(() => {
  if (session.isLoggedIn) void loadActive(true);
});

onReachBottom(() => {
  if (tab.value === "published") {
    if (postsHasMore.value && !postsLoading.value) void loadPublished(false);
    return;
  }
  if (draftsHasMore.value && !draftsLoading.value) void loadDrafts(false);
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

    <view v-else>
      <view class="tabs">
        <view
          class="tab"
          :class="{ active: tab === 'published' }"
          @tap="switchTab('published')"
        >
          <text class="tab-text">已发布</text>
        </view>
        <view class="tab" :class="{ active: tab === 'drafts' }" @tap="switchTab('drafts')">
          <text class="tab-text">草稿</text>
        </view>
      </view>

      <view v-if="tab === 'published'" class="list">
        <view v-for="post in posts" :key="post.id" class="post-wrap">
          <PostCard :post="post" @like="toggleLike(post)" />
          <view class="post-delete" @tap.stop="confirmDelete(post.id, 'published')">
            <text class="post-delete-text">删除</text>
          </view>
        </view>

        <view v-if="postsLoading" class="hint"><text>加载中…</text></view>
        <EmptyState
          v-else-if="postsLoaded && !posts.length"
          title="还没有发布过"
          description="拍下今天的这一餐，第一条饭帖由你开始。"
          action-text="去发布"
          @action="goPublish"
        />
        <view v-else-if="posts.length && !postsHasMore" class="hint">
          <text>发布记录都在这里了</text>
        </view>
      </view>

      <view v-else class="list">
        <view
          v-for="draft in drafts"
          :key="draft.id"
          class="draft-card"
          @tap="goDraft(draft.id)"
        >
          <image
            v-if="draft.coverImage"
            class="draft-cover"
            :src="resolveMedia(draft.coverImage)"
            mode="aspectFill"
          />
          <view v-else class="draft-cover empty">
            <text class="draft-cover-text">暂无封面</text>
          </view>
          <view class="draft-body">
            <text class="draft-title">{{ draft.title || "未命名草稿" }}</text>
            <text class="draft-time">更新于 {{ dateTimeLabel(draft.updatedAt) }}</text>
          </view>
          <view class="draft-delete" @tap.stop="confirmDelete(draft.id, 'drafts')">
            <text class="draft-delete-text">删除</text>
          </view>
        </view>

        <view v-if="draftsLoading" class="hint"><text>加载中…</text></view>
        <EmptyState
          v-else-if="draftsLoaded && !drafts.length"
          title="草稿箱是空的"
          description="写了一半的饭帖可以先存成草稿，之后再来继续。"
          action-text="去发布"
          @action="goPublish"
        />
        <view v-else-if="drafts.length && !draftsHasMore" class="hint">
          <text>草稿都在这里了</text>
        </view>
      </view>
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

.tabs {
  display: flex;
  padding: 4px;
  border-radius: 12px;
  background: var(--c-card);
  box-shadow: 0 6px 18px rgba(36, 36, 36, 0.05);
  margin-bottom: 14px;
}

.tab {
  flex: 1;
  padding: 10px 0;
  border-radius: 9px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.tab.active {
  background: var(--c-peach);
}

.tab-text {
  font-size: 13px;
  color: var(--c-muted);
}

.tab.active .tab-text {
  color: var(--c-primary-deep);
  font-weight: 600;
}

.list {
  display: flex;
  flex-direction: column;
}

.post-wrap {
  position: relative;
}

.post-delete {
  position: absolute;
  top: 14px;
  right: 14px;
  z-index: 2;
  padding: 4px 12px;
  border-radius: 999px;
  background: rgba(36, 36, 36, 0.55);
}

.post-delete-text {
  font-size: 11px;
  color: #ffffff;
}

.draft-card {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 12px;
  margin-bottom: 12px;
  border-radius: var(--radius-lg);
  background: var(--c-card);
  box-shadow: 0 6px 18px rgba(36, 36, 36, 0.05);
}

.draft-cover {
  width: 76px;
  height: 76px;
  border-radius: 12px;
  background: var(--c-peach);
  flex-shrink: 0;
}

.draft-cover.empty {
  display: flex;
  align-items: center;
  justify-content: center;
}

.draft-cover-text {
  font-size: 11px;
  color: var(--c-primary-deep);
}

.draft-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.draft-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--c-text);
}

.draft-time {
  font-size: 12px;
  color: var(--c-faint);
}

.draft-delete {
  padding: 6px 12px;
  border-radius: 999px;
  border: 1px solid var(--c-line);
  flex-shrink: 0;
}

.draft-delete-text {
  font-size: 11px;
  color: var(--c-muted);
}

.hint {
  padding: 18px 0;
  text-align: center;
  font-size: 12px;
  color: var(--c-faint);
}
</style>
