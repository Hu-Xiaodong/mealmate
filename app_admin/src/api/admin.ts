import { request } from './client'
import type {
  AdminPost,
  AdminUserDetail,
  AdminUserItem,
  AuditListParams,
  AuditLogItem,
  LoginResult,
  MeResult,
  PageResult,
  PostListParams,
  UserListParams,
} from './types'

export function login(username: string, password: string) {
  return request<LoginResult>({
    url: '/admin/auth/login',
    method: 'post',
    data: { username, password },
  })
}

export function logout() {
  return request<{ revoked: boolean }>({
    url: '/admin/auth/logout',
    method: 'post',
  })
}

export function me() {
  return request<MeResult>({ url: '/admin/auth/me' })
}

export function listPosts(params: PostListParams) {
  return request<PageResult<AdminPost>>({
    url: '/admin/posts',
    params,
  })
}

export function getPost(postId: string) {
  return request<AdminPost>({ url: `/admin/posts/${postId}` })
}

export function approvePost(postId: string) {
  return request<{ id: string; status: string; changed: boolean }>({
    url: `/admin/posts/${postId}/approve`,
    method: 'post',
  })
}

export function rejectPost(postId: string, reason: string) {
  return request<{ id: string; status: string; changed: boolean }>({
    url: `/admin/posts/${postId}/reject`,
    method: 'post',
    data: { reason },
  })
}

export function unpublishPost(postId: string, reason: string) {
  return request<{ id: string; status: string; changed: boolean }>({
    url: `/admin/posts/${postId}/unpublish`,
    method: 'post',
    data: { reason },
  })
}

export function listUsers(params: UserListParams) {
  return request<PageResult<AdminUserItem>>({
    url: '/admin/users',
    params,
  })
}

export function getUser(userId: string) {
  return request<AdminUserDetail>({ url: `/admin/users/${userId}` })
}

export function banUser(userId: string, reason: string) {
  return request<{ id: string; status: string; changed: boolean }>({
    url: `/admin/users/${userId}/ban`,
    method: 'post',
    data: { reason },
  })
}

export function unbanUser(userId: string) {
  return request<{ id: string; status: string; changed: boolean }>({
    url: `/admin/users/${userId}/unban`,
    method: 'post',
  })
}

export function listAuditLogs(params: AuditListParams) {
  return request<PageResult<AuditLogItem>>({
    url: '/admin/audit-logs',
    params,
  })
}
