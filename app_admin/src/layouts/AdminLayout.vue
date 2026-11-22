<script setup lang="ts">
import { computed, type Component } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Avatar,
  ArrowDown,
  Cpu,
  DataAnalysis,
  Dish,
  Document,
  List,
  PriceTag,
  SwitchButton,
  Tickets,
  User,
} from '@element-plus/icons-vue'

import { NAV_ITEMS } from '@/router'
import { useAdminStore } from '@/stores/admin'

const route = useRoute()
const router = useRouter()
const store = useAdminStore()

const iconMap: Record<string, Component> = {
  '/dashboard': DataAnalysis,
  '/posts': Document,
  '/recipes': Dish,
  '/taste-tags': PriceTag,
  '/ai-providers': Cpu,
  '/ai-call-logs': Tickets,
  '/users': User,
  '/admins': Avatar,
  '/audit-logs': List,
}

const menuItems = computed(() =>
  NAV_ITEMS.filter((item) => store.hasPermission(item.permission)),
)
const pageTitle = computed(() => String(route.meta.title || '管理后台'))
const avatarText = computed(
  () => (store.profile?.displayName || store.profile?.username || '管').slice(0, 1),
)

async function handleCommand(command: string) {
  if (command !== 'logout') {
    return
  }
  try {
    await ElMessageBox.confirm('退出后需要重新输入用户名和密码。', '退出登录', {
      type: 'warning',
      confirmButtonText: '退出',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    await store.logout()
  } catch (error) {
    ElMessage.warning(error instanceof Error ? error.message : '注销请求失败，已在本地退出')
  }
  router.replace('/login')
}
</script>

<template>
  <el-container class="shell">
    <el-aside width="232px" class="sidebar">
      <div class="brand">
        <div class="brand__mark">M</div>
        <div>
          <div class="brand__name">MealMate</div>
          <div class="brand__sub">管理后台</div>
        </div>
      </div>

      <el-menu
        :default-active="route.path"
        router
        class="menu"
        background-color="transparent"
        text-color="#aeb4bf"
        active-text-color="#ffffff"
      >
        <el-menu-item
          v-for="item in menuItems"
          :key="item.path"
          :index="item.path"
        >
          <el-icon><component :is="iconMap[item.path]" /></el-icon>
          <span>{{ item.label }}</span>
        </el-menu-item>
      </el-menu>

      <div class="sidebar__footer">
        内部系统 · 仅限授权人员
        <br />
        操作全程记录审计日志
      </div>
    </el-aside>

    <el-container>
      <el-header class="header">
        <div class="header__crumb">
          <span class="muted">内部管理</span>
          <span class="sep">/</span>
          <strong>{{ pageTitle }}</strong>
        </div>

        <el-dropdown trigger="click" @command="handleCommand">
          <div class="account">
            <el-avatar :size="32" class="account__avatar">{{ avatarText }}</el-avatar>
            <div class="account__text">
              <div class="account__name">
                {{ store.profile?.displayName || '管理员' }}
              </div>
              <div class="account__role">@{{ store.profile?.username }}</div>
            </div>
            <el-icon class="account__arrow"><ArrowDown /></el-icon>
          </div>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="logout" :icon="SwitchButton">
                退出登录
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </el-header>

      <el-main class="main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<style scoped>
.shell {
  height: 100vh;
}

.sidebar {
  display: flex;
  flex-direction: column;
  background: var(--admin-sidebar);
  color: #fff;
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 26px 22px 22px;
}

.brand__mark {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  border-radius: 12px;
  background: linear-gradient(135deg, #e5694c, #b33226);
  box-shadow: 0 6px 18px rgba(204, 70, 44, 0.35);
  color: #fff;
  font-size: 20px;
  font-weight: 700;
}

.brand__name {
  font-size: 16px;
  font-weight: 650;
  letter-spacing: 0.3px;
}

.brand__sub {
  margin-top: 2px;
  color: #8f96a3;
  font-size: 11px;
  letter-spacing: 1.5px;
}

.menu {
  flex: 1;
  border-right: 0;
  padding: 8px 12px;
}

.menu :deep(.el-menu-item) {
  height: 44px;
  margin-bottom: 4px;
  border-radius: 9px;
  font-size: 13px;
}

.menu :deep(.el-menu-item:hover) {
  background: var(--admin-sidebar-soft) !important;
  color: #fff;
}

.menu :deep(.el-menu-item.is-active) {
  background: linear-gradient(135deg, #cc462c, #a93420) !important;
  box-shadow: 0 6px 16px rgba(204, 70, 44, 0.28);
}

.sidebar__footer {
  padding: 18px 22px 24px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
  color: #7b8290;
  font-size: 11px;
  line-height: 1.8;
}

.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 64px;
  padding: 0 28px;
  border-bottom: 1px solid var(--admin-line);
  background: rgba(255, 255, 255, 0.92);
  backdrop-filter: blur(8px);
}

.header__crumb {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}

.header__crumb .sep {
  color: #c3c7ce;
}

.account {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 8px;
  border-radius: 10px;
  cursor: pointer;
  transition: background 0.2s ease;
}

.account:hover {
  background: #f5f6f7;
}

.account__avatar {
  background: #faeae6;
  color: var(--admin-primary);
  font-weight: 700;
}

.account__text {
  line-height: 1.3;
}

.account__name {
  font-size: 13px;
  font-weight: 600;
}

.account__role {
  color: var(--admin-muted);
  font-size: 11px;
}

.account__arrow {
  color: #9aa0a8;
  font-size: 12px;
}

.main {
  overflow-y: auto;
  padding: 26px 28px 40px;
  background: var(--admin-bg);
}

@media (max-width: 900px) {
  .sidebar {
    width: 72px !important;
  }

  .brand {
    justify-content: center;
    padding: 20px 8px;
  }

  .brand > div:last-child,
  .sidebar__footer,
  .menu :deep(.el-menu-item span) {
    display: none;
  }

  .menu :deep(.el-menu-item) {
    justify-content: center;
    padding: 0 !important;
  }

  .main {
    padding: 18px;
  }
}
</style>
