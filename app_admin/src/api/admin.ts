import { request } from './client'
import type {
  AdminItem,
  AdminPost,
  AdminRecipe,
  AdminRoleItem,
  AdminUserDetail,
  AdminUserItem,
  AICallLogItem,
  AICallLogParams,
  AIProviderForm,
  AIProviderItem,
  AIProviderTestResult,
  AuditListParams,
  AuditLogItem,
  BatchReviewResult,
  DashboardSummary,
  KbChunkPage,
  KbDocumentItem,
  KbIndexVersionForm,
  KbIndexVersionItem,
  KbSearchParams,
  KbSearchResult,
  LoginResult,
  MeResult,
  PageResult,
  PostListParams,
  RecipeForm,
  RecipeListParams,
  RoleListResult,
  TasteTagItem,
  UserListParams,
  UserPostParams,
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

export function batchReviewPosts(
  postIds: string[],
  action: 'approve' | 'reject',
  reason?: string,
) {
  return request<BatchReviewResult>({
    url: '/admin/posts/batch-review',
    method: 'post',
    data: { postIds, action, reason },
  })
}

export function listUserPosts(userId: string, params: UserPostParams) {
  return request<PageResult<AdminPost>>({
    url: `/admin/users/${userId}/posts`,
    params,
  })
}

export function getDashboard(days = 7) {
  return request<DashboardSummary>({
    url: '/admin/dashboard',
    params: { days },
  })
}

export function listRecipes(params: RecipeListParams) {
  return request<PageResult<AdminRecipe>>({
    url: '/admin/recipes',
    params,
  })
}

export function getRecipe(recipeId: string) {
  return request<AdminRecipe>({ url: `/admin/recipes/${recipeId}` })
}

export function createRecipe(data: RecipeForm) {
  return request<AdminRecipe>({
    url: '/admin/recipes',
    method: 'post',
    data,
  })
}

export function updateRecipe(recipeId: string, data: RecipeForm) {
  return request<AdminRecipe>({
    url: `/admin/recipes/${recipeId}`,
    method: 'put',
    data,
  })
}

export function archiveRecipe(recipeId: string) {
  return request<{ id: string; status: string; changed: boolean }>({
    url: `/admin/recipes/${recipeId}/archive`,
    method: 'post',
  })
}

export function listTasteTags() {
  return request<{ items: TasteTagItem[] }>({ url: '/admin/taste-tags' })
}

export function createTasteTag(data: {
  name: string
  sortOrder: number
  enabled: boolean
}) {
  return request<TasteTagItem>({
    url: '/admin/taste-tags',
    method: 'post',
    data,
  })
}

export function updateTasteTag(
  name: string,
  data: { sortOrder?: number; enabled?: boolean },
) {
  return request<TasteTagItem>({
    url: `/admin/taste-tags/${encodeURIComponent(name)}`,
    method: 'put',
    data,
  })
}

export function deleteTasteTag(name: string) {
  return request<{ name: string; deleted: boolean }>({
    url: `/admin/taste-tags/${encodeURIComponent(name)}`,
    method: 'delete',
  })
}

export function listAdmins(params: {
  keyword?: string
  status?: string
}) {
  return request<{ items: AdminItem[] }>({
    url: '/admin/admins',
    params,
  })
}

export function createAdmin(data: {
  username: string
  password: string
  displayName: string
  roleIds: string[]
}) {
  return request<AdminItem>({
    url: '/admin/admins',
    method: 'post',
    data,
  })
}

export function updateAdmin(
  adminId: string,
  data: {
    displayName?: string
    password?: string
    status?: 'active' | 'disabled'
    roleIds?: string[]
  },
) {
  return request<AdminItem>({
    url: `/admin/admins/${adminId}`,
    method: 'put',
    data,
  })
}

export function listRoles() {
  return request<RoleListResult>({ url: '/admin/roles' })
}

export function createRole(data: {
  code: string
  name: string
  permissions: string[]
}) {
  return request<AdminRoleItem>({
    url: '/admin/roles',
    method: 'post',
    data,
  })
}

export function updateRole(
  roleId: string,
  data: { name?: string; permissions?: string[] },
) {
  return request<AdminRoleItem>({
    url: `/admin/roles/${roleId}`,
    method: 'put',
    data,
  })
}

export function deleteRole(roleId: string) {
  return request<{ id: string; deleted: boolean }>({
    url: `/admin/roles/${roleId}`,
    method: 'delete',
  })
}

export function listAIProviders() {
  return request<{ items: AIProviderItem[] }>({ url: '/admin/ai-providers' })
}

export function createAIProvider(data: AIProviderForm) {
  return request<AIProviderItem>({
    url: '/admin/ai-providers',
    method: 'post',
    data,
  })
}

export function updateAIProvider(
  providerId: string,
  data: Partial<AIProviderForm>,
) {
  return request<AIProviderItem>({
    url: `/admin/ai-providers/${providerId}`,
    method: 'put',
    data,
  })
}

export function deleteAIProvider(providerId: string) {
  return request<{ id: string; deleted: boolean }>({
    url: `/admin/ai-providers/${providerId}`,
    method: 'delete',
  })
}

export function testAIProvider(providerId: string) {
  return request<AIProviderTestResult>({
    url: `/admin/ai-providers/${providerId}/test`,
    method: 'post',
  })
}

export function listAICallLogs(params: AICallLogParams) {
  return request<{ items: AICallLogItem[] }>({
    url: '/admin/ai-call-logs',
    params,
  })
}

export function listKbDocuments(params?: {
  status?: string
  keyword?: string
  limit?: number
}) {
  return request<{ items: KbDocumentItem[] }>({
    url: '/admin/kb/documents',
    params,
  })
}

export function uploadKbDocument(file: File, title?: string) {
  // multipart/form-data 交给浏览器生成边界；手动设置 Content-Type 反而会丢边界。
  const form = new FormData()
  form.append('file', file)
  if (title && title.trim()) {
    form.append('title', title.trim())
  }
  return request<KbDocumentItem>({
    url: '/admin/kb/documents',
    method: 'post',
    data: form,
    // 上传后要立即切片与生成向量，耗时明显高于普通查询，单独放宽超时。
    timeout: 120000,
  })
}

export function reindexKbDocument(documentId: string) {
  return request<KbDocumentItem>({
    url: `/admin/kb/documents/${documentId}/reindex`,
    method: 'post',
    timeout: 120000,
  })
}

export function deleteKbDocument(documentId: string) {
  return request<{ id: string; deleted: boolean }>({
    url: `/admin/kb/documents/${documentId}`,
    method: 'delete',
  })
}

export function listKbChunks(documentId: string, offset = 0, limit = 50) {
  return request<KbChunkPage>({
    url: `/admin/kb/documents/${documentId}/chunks`,
    params: { offset, limit },
  })
}

export function listKbIndexVersions() {
  return request<{ items: KbIndexVersionItem[] }>({
    url: '/admin/kb/index-versions',
  })
}

export function createKbIndexVersion(data: KbIndexVersionForm) {
  return request<KbIndexVersionItem>({
    url: '/admin/kb/index-versions',
    method: 'post',
    data,
  })
}

export function activateKbIndexVersion(versionId: string) {
  return request<KbIndexVersionItem>({
    url: `/admin/kb/index-versions/${versionId}/activate`,
    method: 'post',
  })
}

export function searchKb(data: KbSearchParams) {
  return request<KbSearchResult>({
    url: '/admin/kb/search-test',
    method: 'post',
    data,
    timeout: 60000,
  })
}
