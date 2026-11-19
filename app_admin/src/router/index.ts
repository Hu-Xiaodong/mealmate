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
  { path: '/posts', label: '饭帖审核', permission: 'post.review' },
  { path: '/users', label: '用户管理', permission: 'user.read' },
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
      redirect: '/posts',
      children: [
        {
          path: 'posts',
          name: 'posts',
          component: () => import('@/views/posts/ReviewListView.vue'),
          meta: { title: '饭帖审核', permission: 'post.review' },
        },
        {
          path: 'users',
          name: 'users',
          component: () => import('@/views/users/UserListView.vue'),
          meta: { title: '用户管理', permission: 'user.read' },
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
