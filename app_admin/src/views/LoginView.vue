<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { Lock, User } from '@element-plus/icons-vue'

import { firstAllowedPath } from '@/router'
import { useAdminStore } from '@/stores/admin'

const route = useRoute()
const router = useRouter()
const store = useAdminStore()

const formRef = ref<FormInstance>()
const loading = ref(false)
const form = reactive({
  username: '',
  password: '',
})

const rules: FormRules = {
  username: [{ required: true, message: '请输入管理员用户名', trigger: 'blur' }],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 8, message: '密码至少 8 位', trigger: 'blur' },
  ],
}

async function submit() {
  if (!formRef.value) {
    return
  }
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) {
    return
  }
  loading.value = true
  try {
    await store.login(form.username.trim(), form.password)
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : ''
    await router.replace(redirect || firstAllowedPath(store.permissions))
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '登录失败，请稍后重试')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login">
    <section class="login__brand">
      <div class="brand-top">
        <span class="brand-top__dot" />
        MealMate · 内部系统
      </div>

      <div class="brand-copy">
        <p class="eyebrow">CONTENT OPERATIONS</p>
        <h1>让每一餐<br />都值得被看见。</h1>
        <p class="desc">
          审核用户提交的饭帖，处理违规内容与账号，
          <br />
          每一次操作都有迹可循。
        </p>
      </div>

      <div class="feature-list">
        <div class="feature">
          <strong>01</strong>
          <span>饭帖审核<small>通过、拒绝、下架</small></span>
        </div>
        <div class="feature">
          <strong>02</strong>
          <span>用户治理<small>查看详情、封禁与解封</small></span>
        </div>
        <div class="feature">
          <strong>03</strong>
          <span>审计追踪<small>操作人、原因、来源地址</small></span>
        </div>
      </div>

      <div class="brand-foot">仅限内部授权人员使用 · 请勿共享账号</div>
    </section>

    <section class="login__panel">
      <div class="login-card">
        <div class="login-card__head">
          <div class="login-card__mark">今</div>
          <h2>登录管理后台</h2>
          <p>使用管理员用户名和密码继续</p>
        </div>

        <el-form
          ref="formRef"
          :model="form"
          :rules="rules"
          label-position="top"
          size="large"
          @submit.prevent="submit"
        >
          <el-form-item label="用户名" prop="username">
            <el-input
              v-model="form.username"
              :prefix-icon="User"
              placeholder="请输入管理员用户名"
              autocomplete="username"
            />
          </el-form-item>
          <el-form-item label="密码" prop="password">
            <el-input
              v-model="form.password"
              type="password"
              show-password
              :prefix-icon="Lock"
              placeholder="请输入密码"
              autocomplete="current-password"
              @keyup.enter="submit"
            />
          </el-form-item>
          <el-button
            type="primary"
            size="large"
            class="submit"
            :loading="loading"
            @click="submit"
          >
            进入后台
          </el-button>
        </el-form>

        <p class="login-card__hint">
          登录状态 1 天后失效；同一用户名与来源地址连续失败 5 次将锁定 15 分钟。
        </p>
      </div>
    </section>
  </div>
</template>

<style scoped>
.login {
  display: grid;
  grid-template-columns: 1.15fr 1fr;
  min-height: 100vh;
  background: #fff;
}

.login__brand {
  position: relative;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  padding: 42px 56px;
  background:
    radial-gradient(circle at 85% 12%, rgba(255, 185, 150, 0.34), transparent 30%),
    radial-gradient(circle at 12% 88%, rgba(204, 70, 44, 0.36), transparent 34%),
    linear-gradient(145deg, #17191d 0%, #26201d 55%, #3a211b 100%);
  color: #fff;
}

.login__brand::after {
  position: absolute;
  right: -120px;
  bottom: -120px;
  width: 380px;
  height: 380px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 50%;
  box-shadow:
    0 0 0 70px rgba(255, 255, 255, 0.025),
    0 0 0 140px rgba(255, 255, 255, 0.018);
  content: "";
}

.brand-top {
  display: flex;
  align-items: center;
  gap: 10px;
  color: #d5d8dd;
  font-size: 12px;
  letter-spacing: 2px;
}

.brand-top__dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #e5694c;
  box-shadow: 0 0 0 5px rgba(229, 105, 76, 0.16);
}

.brand-copy {
  margin-top: 96px;
}

.eyebrow {
  margin: 0 0 18px;
  color: #e8a28f;
  font-size: 11px;
  letter-spacing: 3px;
}

.brand-copy h1 {
  margin: 0;
  font-size: clamp(38px, 4.4vw, 62px);
  font-weight: 650;
  letter-spacing: -1.5px;
  line-height: 1.16;
}

.desc {
  margin: 24px 0 0;
  color: #b9bdc5;
  font-size: 14px;
  line-height: 1.9;
}

.feature-list {
  display: flex;
  flex-direction: column;
  gap: 18px;
  margin-top: auto;
  padding-top: 48px;
}

.feature {
  display: flex;
  align-items: baseline;
  gap: 16px;
}

.feature strong {
  color: #e8a28f;
  font-size: 12px;
  font-weight: 500;
  letter-spacing: 1px;
}

.feature span {
  font-size: 14px;
  font-weight: 500;
}

.feature small {
  display: block;
  margin-top: 3px;
  color: #8f96a3;
  font-size: 11px;
  font-weight: 400;
}

.brand-foot {
  margin-top: 44px;
  padding-top: 18px;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
  color: #7b8290;
  font-size: 11px;
  letter-spacing: 0.5px;
}

.login__panel {
  display: grid;
  place-items: center;
  padding: 40px;
  background:
    radial-gradient(circle at 70% 20%, rgba(204, 70, 44, 0.05), transparent 32%),
    #fbfbfc;
}

.login-card {
  width: min(400px, 100%);
}

.login-card__head {
  margin-bottom: 32px;
}

.login-card__mark {
  display: none;
}

.login-card__head h2 {
  margin: 0;
  font-size: 28px;
  font-weight: 650;
  letter-spacing: -0.5px;
}

.login-card__head p {
  margin: 10px 0 0;
  color: var(--admin-muted);
  font-size: 13px;
}

.submit {
  width: 100%;
  height: 46px;
  margin-top: 8px;
  border: 0;
  background: linear-gradient(135deg, #d2553b, #a93420);
  box-shadow: 0 10px 24px rgba(204, 70, 44, 0.24);
  font-size: 14px;
  letter-spacing: 1px;
}

.login-card__hint {
  margin: 22px 0 0;
  padding-top: 18px;
  border-top: 1px solid var(--admin-line);
  color: #9aa0a8;
  font-size: 11px;
  line-height: 1.8;
}

@media (max-width: 860px) {
  .login {
    grid-template-columns: 1fr;
  }

  .login__brand {
    display: none;
  }

  .login__panel {
    padding: 28px;
  }

  .login-card__mark {
    display: grid;
    place-items: center;
    width: 44px;
    height: 44px;
    margin-bottom: 20px;
    border-radius: 12px;
    background: linear-gradient(135deg, #e5694c, #b33226);
    color: #fff;
    font-size: 20px;
    font-weight: 700;
  }
}
</style>
