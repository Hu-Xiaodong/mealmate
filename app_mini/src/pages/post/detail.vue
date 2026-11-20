<script setup lang="ts">
import { onLoad } from "@dcloudio/uni-app";
import { computed, ref } from "vue";

import { api, mapStaticUrl } from "../../api/client";
import type { AIChatResult, PostDetail } from "../../api/types";
import AppHeader from "../../components/AppHeader.vue";
import EmptyState from "../../components/EmptyState.vue";
import { resolveMedia } from "../../config";
import { showError, sourceLabel, timeLabel } from "../../utils/format";
import { requireLogin } from "../../utils/gate";

const post = ref<PostDetail | null>(null);
const loading = ref(true);
const aiOpen = ref(false);
const aiMessage = ref("");
const aiSending = ref(false);
const aiResult = ref<AIChatResult | null>(null);
const mapBroken = ref(false);

const storeMapUrl = computed(() => {
  const store = post.value?.storeLocation;
  if (!store) return "";
  return mapStaticUrl({ lat: store.lat, lng: store.lng, zoom: 16, width: 640, height: 320 });
});

const recipeTitle = computed(() => {
  if (!post.value) return "";
  if (post.value.authorRecipe) return "作者随饭帖提供的做法";
  if (post.value.recipe) return post.value.recipeLabel || "平台参考做法";
  return "";
});

const ingredientLines = computed(() => {
  if (!post.value) return [];
  if (post.value.authorRecipe) return post.value.authorRecipe.ingredients;
  if (post.value.recipe) {
    return post.value.recipe.ingredients.map((item) => `${item.name} ${item.amount}`);
  }
  return [];
});

const stepLines = computed(() => {
  if (!post.value) return [];
  if (post.value.authorRecipe) return post.value.authorRecipe.steps;
  if (post.value.recipe) return post.value.recipe.steps;
  return [];
});

async function load(id: string) {
  loading.value = true;
  try {
    post.value = await api.post(id);
  } catch (error) {
    showError(error);
  } finally {
    loading.value = false;
  }
}

function toggleLike() {
  const current = post.value;
  if (!current) return;
  requireLogin(async () => {
    try {
      const result = await api.setLike(current.id, !current.likedByMe);
      current.likedByMe = result.liked;
      current.likeCount = result.likeCount;
    } catch (error) {
      showError(error);
    }
  });
}

function toggleSave() {
  const current = post.value;
  if (!current) return;
  requireLogin(async () => {
    try {
      const result = await api.setFavorite("post", current.id, !current.savedByMe);
      current.savedByMe = result.saved;
      uni.showToast({ title: result.saved ? "已收藏" : "已取消收藏", icon: "none" });
    } catch (error) {
      showError(error);
    }
  });
}

async function sendAI() {
  if (!post.value || !aiMessage.value.trim() || aiSending.value) return;
  aiSending.value = true;
  try {
    aiResult.value = await api.aiChat({
      contextType: "post",
      contextId: post.value.id,
      message: aiMessage.value.trim(),
    });
  } catch (error) {
    showError(error);
  } finally {
    aiSending.value = false;
  }
}

function openRecipe(id: string) {
  uni.navigateTo({ url: `/pages/recipe/detail?id=${id}` });
}

function openNavigation() {
  const current = post.value;
  const store = current?.storeLocation;
  if (!current || !store) return;
  uni.openLocation({
    latitude: store.lat,
    longitude: store.lng,
    name: current.takeawayStore || current.title,
    address: current.dineInAddress || current.takeawayStore || current.coarseArea || "",
    fail: () => uni.showToast({ title: "打开地图失败", icon: "none" }),
  });
}

onLoad((options) => {
  const id = options?.id;
  if (!id) {
    showError(new Error("缺少饭帖编号"));
    loading.value = false;
    return;
  }
  void load(id);
});
</script>

<template>
  <view class="page">
    <AppHeader title="饭帖" :subtitle="post ? timeLabel(post.publishedAt) : ''" back />

    <view v-if="post" class="content">
      <swiper
        v-if="post.images.length"
        class="gallery"
        :indicator-dots="post.images.length > 1"
        indicator-active-color="#CC462C"
        circular
      >
        <swiper-item v-for="image in post.images" :key="image">
          <image class="gallery-image" :src="resolveMedia(image)" mode="aspectFill" />
        </swiper-item>
      </swiper>

      <view class="card main">
        <view class="title-row">
          <text class="title">{{ post.title }}</text>
          <text class="badge">{{ sourceLabel(post.source) }}</text>
        </view>
        <text class="review">{{ post.review }}</text>

        <view class="author">
          <view class="avatar">
            <text class="avatar-text">{{ (post.author?.nickname || "饭").slice(0, 1) }}</text>
          </view>
          <text class="name">{{ post.author?.nickname || "饭友" }}</text>
          <text class="time">{{ timeLabel(post.publishedAt) }}</text>
        </view>

        <view v-if="post.takeawayStore" class="info-row">
          <text class="info-label">外卖店家</text>
          <text class="info-value">{{ post.takeawayStore }}</text>
        </view>
        <view v-if="post.dineInAddress" class="info-row">
          <text class="info-label">到店地址</text>
          <text class="info-value">{{ post.dineInAddress }}</text>
        </view>
        <view v-if="post.coarseArea" class="info-row">
          <text class="info-label">附近</text>
          <text class="info-value">{{ post.coarseArea }}</text>
        </view>
        <view v-if="post.avgPrice !== null && post.avgPrice !== undefined" class="info-row">
          <text class="info-label">人均</text>
          <text class="info-value">¥{{ post.avgPrice }}</text>
        </view>
        <view v-if="post.tasteTags && post.tasteTags.length" class="tag-row">
          <text v-for="tag in post.tasteTags" :key="tag" class="tag">{{ tag }}</text>
        </view>
      </view>

      <view v-if="post.storeLocation" class="card">
        <text class="section-title">店铺位置</text>
        <image
          v-if="!mapBroken"
          class="store-map"
          :src="storeMapUrl"
          mode="aspectFill"
          @error="mapBroken = true"
        />
        <view v-else class="map-fallback">
          <text class="map-fallback-text">地图暂不可用</text>
        </view>
        <view class="nav-btn" @tap="openNavigation">
          <text class="nav-btn-text">打开地图导航</text>
        </view>
      </view>

      <view v-if="ingredientLines.length" class="card">
        <view class="section-head">
          <text class="section-title">{{ recipeTitle }}</text>
          <text
            v-if="post.recipe && !post.authorRecipe"
            class="link"
            @tap="openRecipe(post.recipe.id)"
          >
            完整菜谱 ›
          </text>
        </view>
        <text class="label">食材</text>
        <view v-for="line in ingredientLines" :key="line" class="ingredient">
          <view class="dot"></view>
          <text class="ingredient-text">{{ line }}</text>
        </view>
        <text class="label">步骤</text>
        <view v-for="(step, index) in stepLines" :key="`${index}-${step}`" class="step">
          <text class="step-no">{{ index + 1 }}</text>
          <text class="step-text">{{ step }}</text>
        </view>
      </view>

      <view v-else class="card note">
        <text class="note-text">这条饭帖没有可核实的做法，AI 也不会凭图片补出一套菜谱。</text>
      </view>

      <view class="card ai">
        <view class="ai-head" @tap="aiOpen = !aiOpen">
          <text class="ai-title">问问 AI</text>
          <text class="ai-toggle">{{ aiOpen ? "收起" : "展开" }}</text>
        </view>
        <text class="ai-desc">结合这条饭帖帮你再想想，只推荐平台核对过的菜谱。</text>

        <view v-if="aiOpen" class="ai-body">
          <textarea
            v-model="aiMessage"
            class="ai-input"
            placeholder="例如：只有 15 分钟，还能加点什么？"
            maxlength="200"
            auto-height
          />
          <view class="ai-send" :class="{ disabled: aiSending }" @tap="sendAI">
            <text class="ai-send-text">{{ aiSending ? "思考中…" : "发送" }}</text>
          </view>

          <view v-if="aiResult" class="ai-answer">
            <text class="ai-message">{{ aiResult.message }}</text>
            <view
              v-for="item in aiResult.recommendations"
              :key="item.targetId"
              class="recommend"
              @tap="openRecipe(item.targetId)"
            >
              <image class="recommend-cover" :src="resolveMedia(item.coverImage)" mode="aspectFill" />
              <view class="recommend-info">
                <text class="recommend-title">{{ item.title }}</text>
                <text class="recommend-reason">{{ item.reason }}</text>
              </view>
            </view>
            <text class="quota">今日剩余 {{ aiResult.quota.remaining }} 次</text>
          </view>
        </view>
      </view>
    </view>

    <EmptyState v-else-if="!loading" title="这条饭帖看不到" description="可能已被作者删除或还未通过审核。" />

    <view v-if="post" class="bar">
      <view class="bar-item" @tap="toggleLike">
        <text class="bar-icon" :class="{ active: post.likedByMe }">
          {{ post.likedByMe ? "♥" : "♡" }}
        </text>
        <text class="bar-label">{{ post.likeCount }}</text>
      </view>
      <view class="bar-item" @tap="toggleSave">
        <text class="bar-icon" :class="{ active: post.savedByMe }">★</text>
        <text class="bar-label">{{ post.savedByMe ? "已收藏" : "收藏" }}</text>
      </view>
      <view class="bar-ai" @tap="aiOpen = !aiOpen">
        <text class="bar-ai-text">问 AI 今晚吃啥</text>
      </view>
    </view>
  </view>
</template>

<style>
.page {
  padding: 0 16px calc(96px + env(safe-area-inset-bottom));
}

.content {
  padding-top: 8px;
}

.gallery {
  width: 100%;
  height: 360px;
  border-radius: var(--radius-lg);
  overflow: hidden;
}

.gallery-image {
  width: 100%;
  height: 360px;
  background: var(--c-peach);
}

.card {
  background: var(--c-card);
  border-radius: var(--radius-lg);
  padding: 18px;
  margin-top: 14px;
  box-shadow: 0 6px 18px rgba(36, 36, 36, 0.05);
}

.title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.title {
  font-size: 22px;
  font-weight: 700;
  flex: 1;
}

.badge {
  font-size: 11px;
  color: var(--c-primary-deep);
  background: var(--c-peach);
  border-radius: 999px;
  padding: 4px 10px;
  flex-shrink: 0;
}

.review {
  display: block;
  margin-top: 10px;
  font-size: 15px;
  color: var(--c-muted);
  line-height: 1.7;
}

.author {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 16px;
}

.avatar {
  width: 30px;
  height: 30px;
  border-radius: 15px;
  background: var(--c-peach);
  display: flex;
  align-items: center;
  justify-content: center;
}

.avatar-text {
  font-size: 13px;
  color: var(--c-primary-deep);
  font-weight: 600;
}

.name {
  font-size: 13px;
}

.time {
  font-size: 12px;
  color: var(--c-faint);
}

.info-row {
  display: flex;
  gap: 12px;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--c-line);
}

.info-label {
  font-size: 13px;
  color: var(--c-faint);
  width: 64px;
  flex-shrink: 0;
}

.info-value {
  font-size: 13px;
  color: var(--c-text);
  flex: 1;
}

.tag-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--c-line);
}

.tag {
  padding: 5px 12px;
  border-radius: 999px;
  background: var(--c-peach);
  color: var(--c-primary-deep);
  font-size: 11px;
}

.store-map {
  display: block;
  width: 100%;
  height: 180px;
  margin-top: 10px;
  border-radius: 12px;
  background: var(--c-peach);
}

.map-fallback {
  height: 180px;
  margin-top: 10px;
  border-radius: 12px;
  background: var(--c-peach);
  display: flex;
  align-items: center;
  justify-content: center;
}

.map-fallback-text {
  font-size: 12px;
  color: var(--c-primary-deep);
}

.nav-btn {
  margin-top: 12px;
  padding: 11px 0;
  border-radius: 999px;
  background: var(--c-primary);
  display: flex;
  align-items: center;
  justify-content: center;
}

.nav-btn-text {
  font-size: 13px;
  font-weight: 600;
  color: #ffffff;
}

.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
}

.section-title {
  font-size: 16px;
  font-weight: 700;
  color: var(--c-primary-deep);
}

.link {
  font-size: 12px;
  color: var(--c-primary);
}

.label {
  display: block;
  margin-top: 14px;
  margin-bottom: 8px;
  font-size: 13px;
  font-weight: 600;
  color: var(--c-muted);
}

.ingredient {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 0;
}

.dot {
  width: 5px;
  height: 5px;
  border-radius: 3px;
  background: var(--c-primary);
  flex-shrink: 0;
}

.ingredient-text {
  font-size: 14px;
  color: var(--c-text);
}

.step {
  display: flex;
  gap: 10px;
  padding: 6px 0;
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

.note-text {
  font-size: 13px;
  color: var(--c-muted);
  line-height: 1.6;
}

.ai-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.ai-title {
  font-size: 16px;
  font-weight: 700;
}

.ai-toggle {
  font-size: 12px;
  color: var(--c-faint);
}

.ai-desc {
  display: block;
  margin-top: 6px;
  font-size: 12px;
  color: var(--c-muted);
  line-height: 1.5;
}

.ai-body {
  margin-top: 14px;
}

.ai-input {
  width: 100%;
  min-height: 68px;
  background: var(--c-bg);
  border-radius: var(--radius-sm);
  padding: 10px 12px;
  font-size: 14px;
  line-height: 1.5;
  color: var(--c-text);
}

.ai-send {
  margin-top: 10px;
  align-self: flex-end;
  padding: 8px 20px;
  border-radius: 999px;
  background: var(--c-primary);
  display: inline-flex;
}

.ai-send.disabled {
  opacity: 0.6;
}

.ai-send-text {
  font-size: 13px;
  color: #ffffff;
}

.ai-answer {
  margin-top: 14px;
  padding-top: 14px;
  border-top: 1px solid var(--c-line);
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.ai-message {
  font-size: 13px;
  color: var(--c-muted);
  line-height: 1.7;
}

.recommend {
  display: flex;
  gap: 10px;
  background: var(--c-bg);
  border-radius: var(--radius-sm);
  padding: 8px;
}

.recommend-cover {
  width: 64px;
  height: 64px;
  border-radius: 8px;
  background: var(--c-peach);
  flex-shrink: 0;
}

.recommend-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 4px;
}

.recommend-title {
  font-size: 14px;
  font-weight: 600;
}

.recommend-reason {
  font-size: 11px;
  color: var(--c-muted);
}

.quota {
  font-size: 11px;
  color: var(--c-faint);
}

.bar {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 16px calc(10px + env(safe-area-inset-bottom));
  background: rgba(255, 255, 255, 0.96);
  border-top: 1px solid var(--c-line);
}

.bar-item {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 8px 10px;
}

.bar-icon {
  font-size: 18px;
  color: var(--c-muted);
}

.bar-icon.active {
  color: var(--c-primary);
}

.bar-label {
  font-size: 12px;
  color: var(--c-muted);
}

.bar-ai {
  flex: 1;
  background: var(--c-primary);
  border-radius: 999px;
  padding: 11px 0;
  text-align: center;
}

.bar-ai-text {
  font-size: 13px;
  color: #ffffff;
  font-weight: 600;
}
</style>
