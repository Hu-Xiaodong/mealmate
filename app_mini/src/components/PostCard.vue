<script setup lang="ts">
import { computed } from "vue";

import type { PostCard } from "../api/types";
import { resolveMedia } from "../config";
import { distanceLabel, sourceLabel, timeLabel } from "../utils/format";

const props = withDefaults(
  defineProps<{
    post: PostCard;
    showDistance?: boolean;
  }>(),
  { showDistance: false },
);

const emit = defineEmits<{ (event: "like"): void }>();

const initial = computed(() => (props.post.author?.nickname || "饭").slice(0, 1));
const distance = computed(() => distanceLabel(props.post.distanceMeters));
const pendingReview = computed(() => props.post.status !== "published");

function open() {
  uni.navigateTo({ url: `/pages/post/detail?id=${props.post.id}` });
}
</script>

<template>
  <view class="post-card" @tap="open">
    <image class="cover" :src="resolveMedia(post.coverImage)" mode="aspectFill" />
    <view class="badge-row">
      <text class="badge source" :class="post.source">{{ sourceLabel(post.source) }}</text>
      <text v-if="showDistance && distance" class="badge distance">{{ distance }}</text>
      <text v-if="pendingReview" class="badge pending">审核中</text>
    </view>
    <view class="body">
      <text class="title">{{ post.title }}</text>
      <text class="review">{{ post.review }}</text>
      <view class="meta">
        <view class="author">
          <view class="avatar">{{ initial }}</view>
          <text class="name">{{ post.author?.nickname || "饭友" }}</text>
          <text class="time">{{ timeLabel(post.publishedAt) }}</text>
        </view>
        <view class="like" @tap.stop="emit('like')">
          <text class="heart" :class="{ active: post.likedByMe }">
            {{ post.likedByMe ? "♥" : "♡" }}
          </text>
          <text class="count">{{ post.likeCount }}</text>
        </view>
      </view>
    </view>
  </view>
</template>

<style>
.post-card {
  position: relative;
  background: var(--c-card);
  border-radius: var(--radius-lg);
  overflow: hidden;
  box-shadow: 0 6px 18px rgba(36, 36, 36, 0.06);
  margin-bottom: 16px;
}

.cover {
  width: 100%;
  height: 290px;
  background: var(--c-peach);
}

.badge-row {
  position: absolute;
  top: 14px;
  left: 14px;
  display: flex;
  gap: 6px;
}

.badge {
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 11px;
  line-height: 1.4;
  color: #ffffff;
  background: rgba(36, 36, 36, 0.55);
}

.badge.source {
  background: rgba(204, 70, 44, 0.92);
}

.badge.distance {
  background: rgba(255, 255, 255, 0.9);
  color: var(--c-primary-deep);
}

.badge.pending {
  background: rgba(61, 125, 82, 0.9);
}

.body {
  padding: 14px 16px 16px;
}

.title {
  display: block;
  font-size: 19px;
  font-weight: 700;
  color: var(--c-text);
}

.review {
  display: block;
  margin-top: 6px;
  font-size: 14px;
  color: var(--c-muted);
  line-height: 1.55;
}

.meta {
  margin-top: 14px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.author {
  display: flex;
  align-items: center;
  gap: 8px;
}

.avatar {
  width: 26px;
  height: 26px;
  border-radius: 13px;
  background: var(--c-peach);
  color: var(--c-primary-deep);
  font-size: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 600;
}

.name {
  font-size: 13px;
  color: var(--c-text);
}

.time {
  font-size: 12px;
  color: var(--c-faint);
}

.like {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  border-radius: 999px;
  background: var(--c-bg);
}

.heart {
  font-size: 16px;
  color: var(--c-muted);
}

.heart.active {
  color: var(--c-primary);
}

.count {
  font-size: 12px;
  color: var(--c-muted);
}
</style>
