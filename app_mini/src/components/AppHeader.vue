<script setup lang="ts">
withDefaults(
  defineProps<{
    title: string;
    subtitle?: string;
    back?: boolean;
  }>(),
  { subtitle: "", back: false },
);

function goBack() {
  uni.navigateBack({
    fail: () => uni.switchTab({ url: "/pages/home/home" }),
  });
}
</script>

<template>
  <view class="app-header">
    <view class="bar">
      <view v-if="back" class="back" @tap="goBack">
        <text class="arrow">‹</text>
      </view>
      <view class="titles">
        <text class="title">{{ title }}</text>
        <text v-if="subtitle" class="subtitle">{{ subtitle }}</text>
      </view>
      <view class="action">
        <slot name="action" />
      </view>
    </view>
  </view>
</template>

<style>
.app-header {
  padding: calc(var(--status-bar-height) + 10px) 20px 6px;
  background: var(--c-bg);
}

.bar {
  display: flex;
  align-items: center;
  gap: 12px;
}

.back {
  width: 34px;
  height: 34px;
  border-radius: 17px;
  background: var(--c-card);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
}

.arrow {
  font-size: 22px;
  color: var(--c-text);
  line-height: 1;
  margin-top: -3px;
}

.titles {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
}

.title {
  font-size: 26px;
  font-weight: 700;
  letter-spacing: 0.5px;
}

.subtitle {
  margin-top: 2px;
  font-size: 13px;
  color: var(--c-muted);
}

.action {
  flex-shrink: 0;
}
</style>
