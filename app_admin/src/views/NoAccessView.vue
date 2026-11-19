<script setup lang="ts">
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Lock } from '@element-plus/icons-vue'

import { useAdminStore } from '@/stores/admin'

const router = useRouter()
const store = useAdminStore()

async function backToLogin() {
  try {
    await store.logout()
  } catch (error) {
    ElMessage.warning(error instanceof Error ? error.message : '注销请求失败，已在本地退出')
  }
  router.replace('/login')
}
</script>

<template>
  <div class="no-access">
    <div class="no-access__card">
      <el-icon class="no-access__icon"><Lock /></el-icon>
      <h1>当前账号没有可访问的功能</h1>
      <p>
        第一阶段只开放饭帖审核、用户管理和审计日志。
        请联系超级管理员为账号分配对应角色，或使用其他管理员账号登录。
      </p>
      <el-button type="primary" @click="backToLogin">退出并重新登录</el-button>
    </div>
  </div>
</template>

<style scoped>
.no-access {
  display: grid;
  place-items: center;
  min-height: 100vh;
  padding: 24px;
  background: var(--admin-bg);
}

.no-access__card {
  width: min(460px, 100%);
  padding: 40px;
  border: 1px solid var(--admin-line);
  border-radius: 16px;
  background: #fff;
  box-shadow: 0 16px 40px rgba(15, 23, 42, 0.06);
  text-align: center;
}

.no-access__icon {
  width: 48px;
  height: 48px;
  margin-bottom: 18px;
  border-radius: 14px;
  background: #faeae6;
  color: var(--admin-primary);
  font-size: 22px;
}

h1 {
  margin: 0;
  font-size: 20px;
}

p {
  margin: 12px 0 24px;
  color: var(--admin-muted);
  font-size: 13px;
  line-height: 1.8;
}
</style>
