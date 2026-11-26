import { createRouter, createWebHistory } from 'vue-router'

import { useAdminStore } from '@/stores/admin'

declare module 'vue-router' {
  interface RouteMeta {
    title?: string
    permission?: string
    public?: boolean
  }
}

export const NAV_ITEMS = [
  { path: '/dashboard', label: '数据看板', permission: 'dashboard.read' },
  { path: '/posts', label: '饭帖审核', permission: 'post.review' },
  { path: '/recipes', label: '菜谱管理', permission: 'recipe.manage' },
  { path: '/taste-tags', label: '口味标签', permission: 'taste_tag.manage' },
  { path: '/ai-providers', label: '模型配置', permission: 'ai.config.write' },
  { path: '/ai-call-logs', label: 'AI 调用日志', permission: 'ai.log.read' },
  { path: '/ai-observability', label: 'AI 观测', permission: 'ai.log.read' },
  { path: '/ai-prompts', label: '提示词管理', permission: 'ai.log.read' },
  { path: '/prompt-variables', label: '变量管理', permission: 'ai.log.read' },
  { path: '/knowledge-base', label: '知识库', permission: 'kb.document.manage' },
  { path: '/users', label: '用户管理', permission: 'user.read' },
  { path: '/admins', label: '管理员与角色', permission: 'admin.manage' },
  { path: '/audit-logs', label: '审计日志', permission: 'audit.read' },
]

export function firstAllowedPath(permissions: string[]): string {
  const item = NAV_ITEMS.find((nav) => permissions.includes(nav.permission))
  return item?.path || '/no-access'
}

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/LoginView.vue'),
      meta: { public: true, title: '登录' },
    },
    {
      path: '/no-access',
      name: 'no-access',
      component: () => import('@/views/NoAccessView.vue'),
      meta: { title: '无可用权限' },
    },
    {
      path: '/',
      component: () => import('@/layouts/AdminLayout.vue'),
      redirect: '/dashboard',
      children: [
        {
          path: 'dashboard',
          name: 'dashboard',
          component: () => import('@/views/dashboard/DashboardView.vue'),
          meta: { title: '数据看板', permission: 'dashboard.read' },
        },
        {
          path: 'posts',
          name: 'posts',
          component: () => import('@/views/posts/ReviewListView.vue'),
          meta: { title: '饭帖审核', permission: 'post.review' },
        },
        {
          path: 'recipes',
          name: 'recipes',
          component: () => import('@/views/recipes/RecipeListView.vue'),
          meta: { title: '菜谱管理', permission: 'recipe.manage' },
        },
        {
          path: 'taste-tags',
          name: 'taste-tags',
          component: () => import('@/views/tags/TasteTagView.vue'),
          meta: { title: '口味标签', permission: 'taste_tag.manage' },
        },
        {
          path: 'ai-providers',
          name: 'ai-providers',
          component: () => import('@/views/ai/AIProviderView.vue'),
          meta: { title: '模型配置', permission: 'ai.config.write' },
        },
        {
          path: 'ai-call-logs',
          name: 'ai-call-logs',
          component: () => import('@/views/ai/AICallLogView.vue'),
          meta: { title: 'AI 调用日志', permission: 'ai.log.read' },
        },
        {
          path: 'ai-observability',
          name: 'ai-observability',
          component: () => import('@/views/ai/LangfuseDashboardView.vue'),
          meta: { title: 'AI 观测', permission: 'ai.log.read' },
        },
        {
          path: 'ai-prompts',
          name: 'ai-prompts',
          component: () => import('@/views/ai/LangfusePromptView.vue'),
          meta: { title: '提示词管理', permission: 'ai.log.read' },
        },
        {
          path: 'prompt-variables',
          name: 'prompt-variables',
          component: () => import('@/views/ai/PromptVariableView.vue'),
          meta: { title: '变量管理', permission: 'ai.log.read' },
        },
        {
          // 详情页从日志列表进入，不出现在左侧菜单，权限沿用日志查看权限。
          path: 'ai-call-logs/:id',
          name: 'ai-call-log-detail',
          component: () => import('@/views/ai/AICallLogDetailView.vue'),
          meta: { title: '调用详情', permission: 'ai.log.read' },
        },
        {
          path: 'knowledge-base',
          name: 'knowledge-base',
          component: () => import('@/views/kb/KnowledgeBaseView.vue'),
          meta: { title: '知识库', permission: 'kb.document.manage' },
        },
        {
          path: 'users',
          name: 'users',
          component: () => import('@/views/users/UserListView.vue'),
          meta: { title: '用户管理', permission: 'user.read' },
        },
        {
          path: 'admins',
          name: 'admins',
          component: () => import('@/views/admins/AdminListView.vue'),
          meta: { title: '管理员与角色', permission: 'admin.manage' },
        },
        {
          path: 'audit-logs',
          name: 'audit-logs',
          component: () => import('@/views/audit/AuditLogView.vue'),
          meta: { title: '审计日志', permission: 'audit.read' },
        },
      ],
    },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

router.beforeEach(async (to) => {
  const store = useAdminStore()

  if (to.meta.public) {
    if (to.name === 'login' && store.isLoggedIn) {
      if (!store.profile) {
        try {
          await store.fetchMe()
        } catch {
          store.clearSession()
          return true
        }
      }
      return firstAllowedPath(store.permissions)
    }
    return true
  }

  if (!store.isLoggedIn) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }

  // 刷新页面后内存中的管理员信息会丢失，这里用令牌重新拉取一次。
  if (!store.profile) {
    try {
      await store.fetchMe()
    } catch {
      store.clearSession()
      return { path: '/login', query: { redirect: to.fullPath } }
    }
  }

  if (to.path === '/no-access') {
    return true
  }

  const permission = to.meta.permission
  if (permission && !store.hasPermission(permission)) {
    return firstAllowedPath(store.permissions)
  }
  return true
})

router.afterEach((to) => {
  document.title = to.meta.title
    ? `${to.meta.title} · MealMate 管理后台`
    : 'MealMate · 管理后台'
})

export default router
