import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { login as loginApi, logout as logoutApi, me as meApi } from '@/api/admin'
import { clearToken, getToken, setToken } from '@/api/client'
import type { AdminProfile } from '@/api/types'

export const useAdminStore = defineStore('admin', () => {
  const token = ref(getToken())
  const profile = ref<AdminProfile | null>(null)
  const permissions = ref<string[]>([])

  const isLoggedIn = computed(() => Boolean(token.value))

  function hasPermission(code: string): boolean {
    return permissions.value.includes(code)
  }

  async function login(username: string, password: string): Promise<void> {
    const result = await loginApi(username, password)
    token.value = result.token
    setToken(result.token)
    profile.value = result.admin
    permissions.value = result.permissions
  }

  async function fetchMe(): Promise<void> {
    if (!token.value) {
      return
    }
    const result = await meApi()
    profile.value = result.admin
    permissions.value = result.permissions
  }

  function clearSession(): void {
    token.value = ''
    profile.value = null
    permissions.value = []
    clearToken()
  }

  async function logout(): Promise<void> {
    try {
      if (token.value) {
        await logoutApi()
      }
    } finally {
      clearSession()
    }
  }

  return {
    token,
    profile,
    permissions,
    isLoggedIn,
    hasPermission,
    login,
    fetchMe,
    clearSession,
    logout,
  }
})
