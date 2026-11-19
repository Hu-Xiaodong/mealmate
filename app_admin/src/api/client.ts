import axios, { AxiosError, type AxiosRequestConfig } from 'axios'

import type { ApiEnvelope } from './types'

const TOKEN_KEY = 'mealmate_admin_token'

export class ApiError extends Error {
  readonly code: number | string
  readonly status: number
  readonly data: unknown

  constructor(message: string, code: number | string, status: number, data?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
    this.data = data
  }
}

export function getToken(): string {
  try {
    return localStorage.getItem(TOKEN_KEY) || ''
  } catch {
    return ''
  }
}

export function setToken(token: string): void {
  try {
    localStorage.setItem(TOKEN_KEY, token)
  } catch {
    // 隐私模式下 localStorage 可能不可用，此时只保留内存中的登录态。
  }
}

export function clearToken(): void {
  try {
    localStorage.removeItem(TOKEN_KEY)
  } catch {
    // 忽略存储异常。
  }
}

const http = axios.create({
  // 开发环境由 Vite 代理到 FastAPI，生产环境同域部署时也使用这个前缀。
  baseURL: import.meta.env.VITE_API_BASE || '/api/v1',
  timeout: 20000,
})

http.interceptors.request.use((config) => {
  const token = getToken()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

http.interceptors.response.use(
  (response) => response,
  (error: AxiosError<ApiEnvelope<unknown>>) => {
    const status = error.response?.status ?? 0
    const body = error.response?.data
    const message =
      body?.message ||
      (status === 0 ? '无法连接服务器，请确认后端已启动' : '请求失败，请稍后重试')
    const apiError = new ApiError(message, body?.code ?? 'NETWORK_ERROR', status, body?.data)

    if (status === 401) {
      clearToken()
      // 登录接口本身返回 401 时由登录页展示错误，不跳转，避免页面刷新丢失提示。
      if (!window.location.pathname.startsWith('/login')) {
        const redirect = encodeURIComponent(
          window.location.pathname + window.location.search,
        )
        window.location.replace(`/login?redirect=${redirect}`)
      }
    }
    return Promise.reject(apiError)
  },
)

export async function request<T>(config: AxiosRequestConfig): Promise<T> {
  const response = await http.request<ApiEnvelope<T>>(config)
  const body = response.data
  if (!body || body.code !== 0) {
    throw new ApiError(
      body?.message || '响应格式不正确',
      body?.code ?? 'INVALID_RESPONSE',
      response.status,
      body?.data,
    )
  }
  return body.data
}
