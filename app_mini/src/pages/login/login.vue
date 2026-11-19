<script setup lang="ts">
import { onUnload } from "@dcloudio/uni-app";
import { ref } from "vue";

import { api, ApiError } from "../../api/client";
import AppHeader from "../../components/AppHeader.vue";
import { useSessionStore } from "../../stores/session";
import { showError } from "../../utils/format";
import { resumePending } from "../../utils/gate";

const session = useSessionStore();

const phone = ref("");
const code = ref("");
const challengeId = ref("");
const devCode = ref("");
const agreed = ref(false);
const sending = ref(false);
const submitting = ref(false);
const countdown = ref(0);

let timer: ReturnType<typeof setInterval> | null = null;

function startCountdown(seconds: number) {
  countdown.value = Math.max(seconds, 0);
  if (timer) clearInterval(timer);
  timer = setInterval(() => {
    countdown.value -= 1;
    if (countdown.value <= 0) {
      countdown.value = 0;
      if (timer) {
        clearInterval(timer);
        timer = null;
      }
    }
  }, 1000);
}

async function sendCode() {
  if (sending.value || countdown.value > 0) return;
  if (!/^1\d{10}$/.test(phone.value)) {
    uni.showToast({ title: "请输入正确的手机号", icon: "none" });
    return;
  }
  sending.value = true;
  try {
    const result = await api.sendSmsCode(phone.value);
    challengeId.value = result.challengeId;
    devCode.value = result.devCode || "";
    if (result.devCode) code.value = result.devCode;
    startCountdown(result.retryAfter);
    uni.showToast({ title: "验证码已发送", icon: "none" });
  } catch (error) {
    if (error instanceof ApiError && error.code === "SMS_RATE_LIMITED") {
      const retry = (error.data as { retryAfter?: number } | null)?.retryAfter;
      startCountdown(retry ?? 60);
    }
    showError(error);
  } finally {
    sending.value = false;
  }
}

function finish() {
  const next = () => {
    void resumePending();
  };
  uni.navigateBack({
    success: next,
    fail: () => uni.switchTab({ url: "/pages/home/home", success: next }),
  });
}

async function submit() {
  if (submitting.value) return;
  if (!challengeId.value) {
    uni.showToast({ title: "请先获取验证码", icon: "none" });
    return;
  }
  if (!/^\d{6}$/.test(code.value)) {
    uni.showToast({ title: "请输入 6 位验证码", icon: "none" });
    return;
  }
  if (!agreed.value) {
    uni.showToast({ title: "请先阅读并同意用户协议与隐私说明", icon: "none" });
    return;
  }
  submitting.value = true;
  try {
    const result = await api.login({
      challengeId: challengeId.value,
      code: code.value,
      agreementAccepted: true,
    });
    session.apply(result);
    uni.showToast({ title: result.isNewAccount ? "欢迎加入" : "登录成功", icon: "none" });
    finish();
  } catch (error) {
    showError(error);
  } finally {
    submitting.value = false;
  }
}

onUnload(() => {
  if (timer) {
    clearInterval(timer);
    timer = null;
  }
});
</script>

<template>
  <view class="page">
    <AppHeader title="手机号登录" subtitle="登录后可点赞、收藏与发布" back />

    <view class="hero card">
      <text class="hero-title">MealMate</text>
      <text class="hero-desc">用手机号快速登录，未注册的号码会自动创建账号。</text>
    </view>

    <view class="form card">
      <view class="field">
        <text class="label">手机号</text>
        <input
          v-model="phone"
          class="input"
          type="number"
          :maxlength="11"
          placeholder="请输入 11 位手机号"
          placeholder-class="ph"
        />
      </view>

      <view class="field">
        <text class="label">验证码</text>
        <view class="code-row">
          <input
            v-model="code"
            class="input code-input"
            type="number"
            :maxlength="6"
            placeholder="6 位验证码"
            placeholder-class="ph"
          />
          <view
            class="code-btn"
            :class="{ disabled: countdown > 0 || sending }"
            @tap="sendCode"
          >
            <text class="code-text">
              {{ countdown > 0 ? `${countdown}s 后重试` : "获取验证码" }}
            </text>
          </view>
        </view>
        <text v-if="devCode" class="dev-hint">
          开发环境验证码 {{ devCode }}，已自动填入
        </text>
      </view>

      <view class="agreement" @tap="agreed = !agreed">
        <view class="checkbox" :class="{ checked: agreed }">
          <text v-if="agreed" class="tick">✓</text>
        </view>
        <text class="agreement-text">我已阅读并同意《用户协议》与《隐私说明》</text>
      </view>

      <view class="submit" :class="{ busy: submitting }" @tap="submit">
        <text class="submit-text">{{ submitting ? "登录中…" : "登录 / 注册" }}</text>
      </view>

      <text class="footnote">验证码 5 分钟内有效，连续输错 5 次需重新获取。</text>
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

.hero {
  padding: 24px 22px;
  background: linear-gradient(135deg, #fff3ee 0%, #ffffff 70%);
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.hero-title {
  font-size: 24px;
  font-weight: 700;
  color: var(--c-primary-deep);
}

.hero-desc {
  font-size: 13px;
  color: var(--c-muted);
  line-height: 1.6;
}

.form {
  margin-top: 14px;
  padding: 22px;
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.label {
  font-size: 13px;
  color: var(--c-muted);
}

.input {
  height: 44px;
  padding: 0 14px;
  border-radius: 12px;
  background: var(--c-bg);
  font-size: 16px;
  color: var(--c-text);
}

.ph {
  color: var(--c-faint);
  font-size: 14px;
}

.code-row {
  display: flex;
  gap: 10px;
}

.code-input {
  flex: 1;
}

.code-btn {
  padding: 0 16px;
  height: 44px;
  border-radius: 12px;
  background: var(--c-peach);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.code-btn.disabled {
  opacity: 0.6;
}

.code-text {
  font-size: 13px;
  color: var(--c-primary-deep);
  font-weight: 600;
}

.dev-hint {
  font-size: 12px;
  color: var(--c-primary);
}

.agreement {
  display: flex;
  align-items: center;
  gap: 8px;
}

.checkbox {
  width: 18px;
  height: 18px;
  border-radius: 9px;
  border: 1px solid var(--c-line);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.checkbox.checked {
  background: var(--c-primary);
  border-color: var(--c-primary);
}

.tick {
  font-size: 11px;
  color: #ffffff;
  line-height: 1;
}

.agreement-text {
  font-size: 12px;
  color: var(--c-muted);
  line-height: 1.5;
}

.submit {
  padding: 13px 0;
  border-radius: 999px;
  background: var(--c-primary);
  box-shadow: 0 10px 20px rgba(204, 70, 44, 0.22);
  display: flex;
  align-items: center;
  justify-content: center;
}

.submit.busy {
  opacity: 0.7;
}

.submit-text {
  font-size: 15px;
  font-weight: 600;
  color: #ffffff;
}

.footnote {
  font-size: 12px;
  color: var(--c-faint);
  text-align: center;
}
</style>
