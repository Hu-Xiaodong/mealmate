<script setup lang="ts">
import { computed, ref } from "vue";

import { api } from "../../api/client";
import AppHeader from "../../components/AppHeader.vue";
import { useSessionStore } from "../../stores/session";
import { showError } from "../../utils/format";
import { requireLogin } from "../../utils/gate";

const session = useSessionStore();
const initial = computed(() => (session.profile?.nickname || "饭").slice(0, 1));
const loggingOut = ref(false);

function goLogin() {
  uni.navigateTo({ url: "/pages/login/login" });
}

function openMyPosts() {
  requireLogin(() => {
    uni.navigateTo({ url: "/pages/my-posts/my-posts" });
  });
}

function openFavorites() {
  requireLogin(() => {
    uni.navigateTo({ url: "/pages/favorites/favorites" });
  });
}

function goPublish() {
  uni.navigateTo({ url: "/pages/publish/publish" });
}

async function logout() {
  if (loggingOut.value) return;
  loggingOut.value = true;
  try {
    await api.logout();
  } catch {
    // 会话可能已失效，仍然清理本地状态。
  } finally {
    session.clear();
    loggingOut.value = false;
    uni.showToast({ title: "已退出登录", icon: "none" });
  }
}
</script>

<template>
  <view class="page">
    <view v-if="!session.isLoggedIn" class="guest card">
      <view class="guest-mark">
        <text class="guest-text">饭</text>
      </view>
      <text class="guest-title">还没有登录</text>
      <text class="guest-desc">登录后可以点赞、收藏，也能把今天的饭发布出来。</text>
      <view class="primary" @tap="goLogin"><text class="primary-text">手机号登录</text></view>
    </view>

    <view v-else class="profile card">
      <view class="avatar">
        <text class="avatar-text">{{ initial }}</text>
      </view>
      <view class="profile-info">
        <text class="nickname">{{ session.profile?.nickname || "饭友" }}</text>
        <text class="phone">{{ session.profile?.phoneMasked || "" }}</text>
      </view>
      <view class="logout" @tap="logout"><text class="logout-text">退出</text></view>
    </view>

    <view class="menu card">
      <view class="menu-item" @tap="openMyPosts">
        <text class="menu-label">我的发布</text>
        <text class="menu-arrow">›</text>
      </view>
      <view class="menu-item" @tap="openFavorites">
        <text class="menu-label">我的收藏</text>
        <text class="menu-arrow">›</text>
      </view>
      <view class="menu-item" @tap="goPublish">
        <text class="menu-label">发布今天的饭</text>
        <text class="menu-arrow">›</text>
      </view>
    </view>

    <view class="tip card">
      <text class="tip-title">AI 每日额度</text>
      <text class="tip-desc">游客每天 5 次问答，登录后每天 20 次。AI 只推荐平台核对过的菜谱，不代替真实烹饪判断。</text>
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

.guest {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 30px 22px 26px;
  text-align: center;
}

.guest-mark {
  width: 58px;
  height: 58px;
  border-radius: 29px;
  background: var(--c-peach);
  display: flex;
  align-items: center;
  justify-content: center;
}

.guest-text {
  color: var(--c-primary-deep);
  font-size: 20px;
  font-weight: 700;
}

.guest-title {
  margin-top: 14px;
  font-size: 18px;
  font-weight: 700;
}

.guest-desc {
  margin-top: 6px;
  font-size: 13px;
  color: var(--c-muted);
  line-height: 1.6;
}

.primary {
  margin-top: 18px;
  padding: 11px 34px;
  border-radius: 999px;
  background: var(--c-primary);
  box-shadow: 0 8px 18px rgba(204, 70, 44, 0.22);
}

.primary-text {
  color: #ffffff;
  font-size: 14px;
  font-weight: 600;
}

.profile {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 20px;
}

.avatar {
  width: 54px;
  height: 54px;
  border-radius: 27px;
  background: var(--c-peach);
  display: flex;
  align-items: center;
  justify-content: center;
}

.avatar-text {
  font-size: 20px;
  font-weight: 700;
  color: var(--c-primary-deep);
}

.profile-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.nickname {
  font-size: 18px;
  font-weight: 700;
}

.phone {
  font-size: 13px;
  color: var(--c-muted);
}

.logout {
  padding: 6px 14px;
  border-radius: 999px;
  border: 1px solid var(--c-line);
}

.logout-text {
  font-size: 12px;
  color: var(--c-muted);
}

.menu {
  margin-top: 14px;
  padding: 4px 18px;
}

.menu-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 0;
  border-bottom: 1px solid var(--c-line);
}

.menu-item:last-child {
  border-bottom: none;
}

.menu-label {
  font-size: 15px;
  color: var(--c-text);
}

.menu-arrow {
  font-size: 20px;
  color: var(--c-faint);
}

.tip {
  margin-top: 14px;
  padding: 18px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.tip-title {
  font-size: 14px;
  font-weight: 600;
}

.tip-desc {
  font-size: 12px;
  color: var(--c-muted);
  line-height: 1.6;
}
</style>
