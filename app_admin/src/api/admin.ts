import { request } from './client'
import type {
  AdminItem,
  AdminPost,
  AdminRecipe,
  AdminRoleItem,
  AdminUserDetail,
  AdminUserItem,
  AICallLogDetail,
  AICallLogItem,
  AICallLogParams,
  AICallScoreItem,
  AIProviderForm,
  AIProviderItem,
  AIProviderTestResult,
  AuditListParams,
  AuditLogItem,
  BatchReviewResult,
  DashboardSummary,
  KbBatchDeleteResult,
  KbBatchOperationResult,
  KbChunkPage,
  KbDocumentItem,
  KbImportBatchItem,
  KbIndexVersionForm,
  KbIndexVersionItem,
  KbSearchParams,
  KbSearchResult,
  LangfuseMetrics,
  LangfusePromptItem,
  LangfusePromptVersion,
  LangfuseStatus,
  LoginResult,
  MeResult,
  PageResult,
  PromptPreviewResult,
  PromptVariableInput,
  PromptVariableItem,
  PromptVariableSaveRequest,
  PostListParams,
  RecipeBatchResult,
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

export function batchDeletePosts(postIds: string[], reason: string) {
  return request<BatchReviewResult>({
    url: '/admin/posts/batch-delete',
    method: 'post',
    data: { postIds, reason },
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

/** 批量上架菜谱：已上架的会在结果里标记为跳过。 */
export function batchPublishRecipes(recipeIds: string[]) {
  return request<RecipeBatchResult>({
    url: '/admin/recipes/batch-publish',
    method: 'post',
    data: { recipeIds },
  })
}

/** 批量下架菜谱：软下架，历史饭帖关联保留。 */
export function batchArchiveRecipes(recipeIds: string[]) {
  return request<RecipeBatchResult>({
    url: '/admin/recipes/batch-archive',
    method: 'post',
    data: { recipeIds },
  })
}

/** 批量删除菜谱：被饭帖引用的菜谱会被后端跳过并说明原因。 */
export function batchDeleteRecipes(recipeIds: string[]) {
  return request<RecipeBatchResult>({
    url: '/admin/recipes/batch-delete',
    method: 'post',
    data: { recipeIds },
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
  return request<PageResult<AICallLogItem>>({
    url: '/admin/ai-call-logs',
    params,
  })
}

/** 查询一次模型调用的完整执行过程，用于“调用详情”页。 */
export function getAICallLog(logId: string) {
  return request<AICallLogDetail>({
    url: `/admin/ai-call-logs/${logId}`,
  })
}

/** 给一次模型调用提交人工评分。 */
export function scoreAICallLog(
  logId: string,
  data: { score: number; comment?: string },
) {
  return request<AICallScoreItem>({
    url: `/admin/ai-call-logs/${logId}/scores`,
    method: 'post',
    data,
  })
}

export function getLangfuseStatus() {
  return request<LangfuseStatus>({ url: '/admin/langfuse/status' })
}

/** 本地指标：不依赖 Langfuse，直接聚合调用日志与评分。 */
export function getLocalAiMetrics(days: number) {
  return request<LangfuseMetrics>({
    url: '/admin/ai-metrics',
    params: { days },
  })
}

export function getLangfuseMetrics(days: number) {
  return request<LangfuseMetrics>({
    url: '/admin/langfuse/metrics',
    params: { days },
  })
}

export function listPrompts() {
  return request<{ configured: boolean; warning: string; items: LangfusePromptItem[] }>({
    url: '/admin/prompts',
  })
}

export function listPromptVersions(name: string) {
  return request<{ items: LangfusePromptVersion[] }>({
    url: `/admin/prompts/${encodeURIComponent(name)}/versions`,
  })
}

export function publishPrompt(
  name: string,
  data: {
    content: string
    commitMessage?: string
    variables?: PromptVariableInput[]
  },
) {
  return request<{
    name: string
    version: number | null
    labels: string[]
    langfuseVersion: number | null
    langfuseConfigured: boolean
  }>({
    url: `/admin/prompts/${encodeURIComponent(name)}/publish`,
    method: 'post',
    data,
  })
}

export function previewPrompt(
  name: string,
  data: { content?: string; variables?: PromptVariableInput[] },
) {
  return request<PromptPreviewResult>({
    url: `/admin/prompts/${encodeURIComponent(name)}/preview`,
    method: 'post',
    data,
  })
}

export function rollbackPrompt(
  name: string,
  data: { version: number; commitMessage?: string },
) {
  return request<{
    name: string
    version: number
    rollbackFrom: number
    langfuseVersion: number | null
    langfuseConfigured: boolean
  }>({
    url: `/admin/prompts/${encodeURIComponent(name)}/rollback`,
    method: 'post',
    data,
  })
}

export function listPromptVariables(promptName?: string) {
  return request<{
    items: PromptVariableItem[]
    prompts: Array<{ name: string; title: string }>
  }>({
    url: '/admin/prompt-variables',
    params: promptName ? { promptName } : undefined,
  })
}

export function savePromptVariable(data: PromptVariableSaveRequest) {
  return request<PromptVariableItem>({
    url: '/admin/prompt-variables',
    method: 'post',
    data,
  })
}

export function deletePromptVariable(id: string) {
  return request<{ id: string }>({
    url: `/admin/prompt-variables/${encodeURIComponent(id)}`,
    method: 'delete',
  })
}

export function listKbDocuments(params?: {
  status?: string
  keyword?: string
  page?: number
  pageSize?: number
}) {
  return request<{
    items: KbDocumentItem[]
    total: number
    page: number
    pageSize: number
  }>({
    url: '/admin/kb/documents',
    params,
  })
}

export function uploadKbDocument(file: File, images: File[] = [], title?: string) {
  // multipart/form-data 交给浏览器生成边界；手动设置 Content-Type 反而会丢边界。
  const form = new FormData()
  form.append('file', file)
  // 图片可选，用同一个字段名重复追加；后端按文件名匹配 Markdown 里的图片引用。
  for (const image of images) {
    form.append('images', image)
  }
  if (title && title.trim()) {
    form.append('title', title.trim())
  }
  return request<KbDocumentItem>({
    url: '/admin/kb/documents',
    method: 'post',
    data: form,
    // 上传后要立即解析与切片，耗时明显高于普通查询，单独放宽超时。
    timeout: 120000,
  })
}

/**
 * 创建批量导入批次。
 *
 * 为什么单独传 archive：浏览器一次只能展开一个压缩包，后端也只支持一个；
 * 普通文件与文件夹则通过重复的 files 字段提交。
 * paths 与 files 顺序一一对应，用于保留文件夹里的相对路径，
 * 后端据此把同目录图片和文档配到一起。
 */
export function createKbImportBatch(payload: {
  files: File[]
  paths?: string[]
  archive?: File | null
  label?: string
}) {
  const form = new FormData()
  for (const file of payload.files) {
    form.append('files', file)
  }
  if (payload.paths?.length) {
    form.append('paths', JSON.stringify(payload.paths))
  }
  if (payload.archive) {
    form.append('archive', payload.archive)
  }
  if (payload.label?.trim()) {
    form.append('label', payload.label.trim())
  }
  return request<KbImportBatchItem>({
    url: '/admin/kb/import-batches',
    method: 'post',
    data: form,
    // 上传几十 MB 的压缩包本身就需要时间，进度由后端后台任务单独推进。
    timeout: 300000,
  })
}

export function getKbImportBatch(batchId: string) {
  return request<KbImportBatchItem>({
    url: `/admin/kb/import-batches/${batchId}`,
  })
}

/** 只重新处理失败的文件，成功后不需要重新上传整批。 */
export function retryKbImportBatch(batchId: string) {
  return request<KbImportBatchItem>({
    url: `/admin/kb/import-batches/${batchId}/retry`,
    method: 'post',
  })
}

/** 按当前启用索引版本重新切片，结果进入切片列表，不生成向量。 */
export function rechunkKbDocument(documentId: string) {
  return request<KbDocumentItem>({
    url: `/admin/kb/documents/${documentId}/rechunk`,
    method: 'post',
    timeout: 120000,
  })
}

/** 把切片列表里的切片建立成可检索的索引（调用嵌入模型）。 */
export function buildKbIndex(documentId: string) {
  return request<KbDocumentItem>({
    url: `/admin/kb/documents/${documentId}/index`,
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

/** 批量重新切片：逐篇执行，返回每篇结果。 */
export function batchRechunkKbDocuments(documentIds: string[]) {
  return request<KbBatchOperationResult>({
    url: '/admin/kb/documents/batch-rechunk',
    method: 'post',
    data: { documentIds },
    // 每篇都要读取原文件重新切分，批量操作比普通请求慢，放宽到 5 分钟。
    timeout: 300000,
  })
}

/** 批量生成菜谱草稿：已发布的菜谱会被跳过。 */
export function batchGenerateKbRecipeDrafts(documentIds: string[]) {
  return request<KbBatchOperationResult>({
    url: '/admin/kb/documents/batch-recipe-draft',
    method: 'post',
    data: { documentIds },
    timeout: 300000,
  })
}

/** 批量建立索引：每篇都要调用嵌入模型，是三个批量操作里最慢的。 */
export function batchBuildKbIndex(documentIds: string[]) {
  return request<KbBatchOperationResult>({
    url: '/admin/kb/documents/batch-index',
    method: 'post',
    data: { documentIds },
    timeout: 300000,
  })
}

/** 把知识库文档按固定模板解析成菜谱草稿，已存在的草稿会被更新。 */
export function generateKbRecipeDraft(documentId: string) {
  return request<{
    recipeId: string
    title: string
    created: boolean
    skipped: boolean
    message: string
  }>({
    url: `/admin/kb/documents/${documentId}/recipe-draft`,
    method: 'post',
  })
}

/** 批量删除知识库文档：一次提交多个编号，后端逐条处理并返回结果。 */
export function batchDeleteKbDocuments(documentIds: string[]) {
  return request<KbBatchDeleteResult>({
    url: '/admin/kb/documents/batch-delete',
    method: 'post',
    data: { documentIds },
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
