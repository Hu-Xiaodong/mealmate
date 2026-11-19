<script setup lang="ts">
withDefaults(
  defineProps<{
    title: string;
    description?: string;
    actionText?: string;
  }>(),
  { description: "", actionText: "" },
);

const emit = defineEmits<{ (event: "action"): void }>();
</script>

<template>
  <view class="empty">
    <view class="mark"></view>
    <text class="title">{{ title }}</text>
    <text v-if="description" class="description">{{ description }}</text>
    <view v-if="actionText" class="button" @tap="emit('action')">
      <text class="button-text">{{ actionText }}</text>
    </view>
  </view>
</template>

<style>
.empty {
  padding: 56px 32px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
}

.mark {
  width: 54px;
  height: 54px;
  border-radius: 27px;
  background: var(--c-peach);
  border: 2px dashed rgba(204, 70, 44, 0.4);
}

.title {
  font-size: 16px;
  font-weight: 600;
  color: var(--c-text);
  margin-top: 4px;
}

.description {
  font-size: 13px;
  color: var(--c-muted);
  text-align: center;
  line-height: 1.6;
}

.button {
  margin-top: 10px;
  padding: 9px 22px;
  border-radius: 999px;
  background: var(--c-primary);
}

.button-text {
  font-size: 13px;
  color: #ffffff;
}
</style>
