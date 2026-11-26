export interface ApiEnvelope<T> {
  requestId: string
  code: number | string
  message: string
  data: T
}

/**
 * 管理后台统一的分页结果。
 *
 * 后台列表全部改成“页码 + 每页条数 + 总数”：
 * 运营需要看到当前第几页、一共多少条，并直接跳到某一页；
 * 客户端的无限滚动仍然使用游标分页，两者场景不同。
 */
export interface PageResult<T> {
  items: T[]
  total: number
  page: number
  pageSize: number
}

export interface AdminProfile {
  id: string
  username: string
  displayName: string
  status: string
  lastLoginAt: string | null
  createdAt: string
}

export interface LoginResult {
  token: string
  tokenType: string
  expiresAt: string
  admin: AdminProfile
  permissions: string[]
}

export interface MeResult {
  admin: AdminProfile
  permissions: string[]
}

export interface PostAuthor {
  id: string
  nickname: string
  avatarUrl: string | null
}

export interface AuthorRecipe {
  ingredients: string[]
  steps: string[]
}

export interface AdminPost {
  id: string
  title: string
  review: string
  source: 'self' | 'takeaway' | 'dine_in' | string
  coverImage: string | null
  images: string[]
  imageCount: number
  author: PostAuthor | null
  status: string
  reviewReason: string | null
  reviewedAt: string | null
  reviewedByName: string | null
  createdAt: string
  publishedAt: string | null
  authorRecipe?: AuthorRecipe | null
  authorPhoneMasked?: string | null
  takeawayStore?: string | null
  dineInAddress?: string | null
  coarseArea?: string | null
  coarseLat?: number | null
  coarseLng?: number | null
  clientRequestId?: string | null
  platformRecipeId?: string | null
  platformRecipeTitle?: string | null
}

export interface AdminUserItem {
  id: string
  nickname: string
  phoneMasked: string
  avatarUrl: string | null
  status: string
  postCount: number
  createdAt: string
}

export interface AdminUserDetail extends AdminUserItem {
  likeCount: number
  favoriteCount: number
}

export interface AuditLogItem {
  id: string
  actorId: string
  actorName: string
  action: string
  targetType: string
  targetId: string
  reason: string | null
  before: Record<string, unknown> | null
  after: Record<string, unknown> | null
  ip: string | null
  requestId: string | null
  createdAt: string
}

export interface PostListParams {
  status?: string
  page?: number
  pageSize?: number
}

export interface UserListParams {
  keyword?: string
  status?: string
  page?: number
  pageSize?: number
}

export interface AuditListParams {
  actorName?: string
  action?: string
  targetType?: string
  targetId?: string
  startAt?: string
  endAt?: string
  page?: number
  pageSize?: number
}

export interface DashboardSummary {
  rangeDays: number
  users: {
    total: number
    newInRange: number
  }
  posts: {
    total: number
    pending: number
    published: number
    publishedToday: number
  }
  events: {
    total: number
    byName: Record<string, number>
  }
  trend: Array<{
    date: string
    events: number
  }>
}

export interface BatchReviewResult {
  succeeded: number
  failed: number
  results: Array<{
    postId: string
    ok: boolean
    status?: string
    changed?: boolean
    errorCode?: string
    message?: string
  }>
}

export interface RecipeIngredient {
  name: string
  amount: string
}

export interface AdminRecipe {
  id: string
  title: string
  coverImage: string
  coverKey: string
  totalMinutes: number
  tools: string[]
  categories: string[]
  servings: number
  mainIngredients: string[]
  ingredients: RecipeIngredient[]
  steps: string[]
  preconditions: string | null
  contentOrigin: 'platform' | 'editor' | string
  validationStatus: 'tested' | 'pending' | 'not_tested' | string
  status: 'draft' | 'published' | 'archived' | string
  createdAt: string
}

export interface RecipeForm {
  title: string
  coverUrl: string
  totalMinutes: number
  toolCodes: string[]
  categoryCodes: string[]
  servings: number
  mainIngredients: string[]
  ingredients: RecipeIngredient[]
  steps: string[]
  preconditions: string | null
  contentOrigin: 'platform' | 'editor'
  validationStatus: 'tested' | 'pending' | 'not_tested'
  status: 'draft' | 'published' | 'archived'
}

export interface RecipeListParams {
  keyword?: string
  status?: string
  page?: number
  pageSize?: number
}

/** 批量上架 / 下架 / 删除菜谱时，后端返回的单条处理结果。 */
export interface RecipeBatchOperationItem {
  recipeId: string
  title: string
  ok: boolean
  skipped?: boolean
  message?: string
  errorCode?: string
}

/** 批量菜谱操作的汇总结果：成功、失败、跳过分别计数。 */
export interface RecipeBatchResult {
  succeeded: number
  failed: number
  skipped: number
  results: RecipeBatchOperationItem[]
}

export interface TasteTagItem {
  name: string
  sortOrder: number
  enabled: boolean
  usageCount: number
  createdAt: string
}

export interface AdminRoleBrief {
  id: string
  code: string
  name: string
}

export interface AdminItem {
  id: string
  username: string
  displayName: string
  status: string
  lastLoginAt: string | null
  createdAt: string
  roles: AdminRoleBrief[]
}

export interface AdminRoleItem {
  id: string
  code: string
  name: string
  permissions: string[]
  adminCount: number
  builtin: boolean
}

export interface PermissionItem {
  code: string
  label: string
}

export interface RoleListResult {
  items: AdminRoleItem[]
  permissions: PermissionItem[]
}

export interface UserPostParams {
  status?: string
  page?: number
  pageSize?: number
}

export interface AIProviderItem {
  id: string
  name: string
  providerType: 'openai_compatible' | string
  kind: 'chat' | 'embedding'
  dimensions: number | null
  baseUrl: string
  apiKeyMasked: string
  model: string
  enabled: boolean
  priority: number
  timeoutSeconds: number
  maxOutputTokens: number
  contextWindowTokens: number
  lastTestAt: string | null
  lastTestOk: boolean | null
  lastTestMessage: string | null
  createdAt: string
  updatedAt: string
}

export interface AIProviderForm {
  name: string
  providerType: 'openai_compatible'
  kind: 'chat' | 'embedding'
  dimensions: number | null
  baseUrl: string
  apiKey: string
  model: string
  enabled: boolean
  priority: number
  timeoutSeconds: number
  maxOutputTokens: number
  contextWindowTokens: number
}

export interface AIProviderTestResult {
  ok: boolean
  latencyMs: number
  errorCode: string | null
  message: string
}

export interface AICallLogItem {
  id: string
  requestId: string | null
  subjectRef: string
  contextType: string
  providerId: string | null
  providerName: string
  model: string
  status: string
  latencyMs: number
  promptTokens: number
  completionTokens: number
  totalTokens: number
  errorCode: string | null
  errorMessage: string | null
  createdAt: string
}

export interface AICallLogParams {
  status?: string
  providerId?: string
  page?: number
  pageSize?: number
}

/** 一次调用过程中的单个执行步骤，详情页按 seq 升序拼成时间线。 */
export interface AICallTraceItem {
  id: string
  seq: number
  step: string
  title: string
  status: string
  detail: string | null
  durationMs: number
  createdAt: string
}

export interface AICallLogDetail extends AICallLogItem {
  traces: AICallTraceItem[]
}

export interface KbBatchOperationItem {
  documentId: string
  title: string
  ok: boolean
  skipped?: boolean
  message?: string
  errorCode?: string
}

export interface KbBatchOperationResult {
  succeeded: number
  failed: number
  skipped: number
  results: KbBatchOperationItem[]
}

export interface KbDocumentItem {
  id: string
  title: string
  sourceType: string
  mime: string
  bytes: number
  checksum: string
  status:
    | 'uploaded'
    | 'parsing'
    | 'chunking'
    | 'chunked'
    | 'indexing'
    | 'ready'
    | 'failed'
  errorMessage: string | null
  indexVersionId: string | null
  uploadedBy: string | null
  chunkCount: number
  /** 仅上传响应返回：成功关联到 Markdown 引用的图片数量。 */
  imageCount?: number
  /** 仅上传响应返回：正文里有、但没有匹配到上传文件的图片引用数量。 */
  unmatchedImageCount?: number
  /** 待建立索引的切片数量；大于 0 时列表显示“去新建索引”。 */
  draftChunkCount: number
  /** 待索引切片的长度；没有待索引切片时为 null。 */
  chunkSize: number | null
  /** 待索引切片的相邻重叠长度；没有待索引切片时为 null。 */
  chunkOverlap: number | null
  /** 待索引切片的生成时间；没有待索引切片时为 null。 */
  chunkedAt: string | null
  createdAt: string
  updatedAt: string
}

/** 批量删除知识库文档的逐条结果。 */
export interface KbBatchDeleteResult {
  succeeded: number
  failed: number
  results: Array<{
    documentId: string
    ok: boolean
    errorCode?: string
    message?: string
  }>
}

/** 批量导入中的一个文件任务。 */
export interface KbImportJobItem {
  id: string
  /** 文件夹或压缩包内的相对路径，例如 资料/菜谱/白灼虾.md。 */
  relativePath: string
  filename: string
  title: string
  status: 'pending' | 'running' | 'succeeded' | 'failed' | 'skipped' | 'dead'
  errorMessage: string | null
  /** 第几次处理；重试后递增。 */
  attempts: number
  documentId: string | null
  chunkCount: number
  imageCount: number
  unmatchedImageCount: number
  updatedAt: string
}

/** 一次批量导入的整体状态与统计。 */
export interface KbImportBatchItem {
  id: string
  /** 批次名称：运营手填、压缩包文件名或文件夹名。 */
  label: string
  status: 'pending' | 'running' | 'succeeded' | 'partial' | 'failed'
  stats: {
    total: number
    pending: number
    running: number
    succeeded: number
    failed: number
    skipped: number
    images: number
    ignored: number
    unusedImages: number
    /** 未被任何文档引用的图片，给出相对路径方便定位（如 `recipes/img/封面.png`）。 */
    unusedImagePaths?: string[]
  }
  errorMessage: string | null
  createdAt: string
  finishedAt: string | null
  items: KbImportJobItem[]
}

export interface KbIndexVersionItem {
  id: string
  name: string
  embedProvider: string
  embedModel: string
  dimensions: number
  chunkSize: number
  chunkOverlap: number
  status: 'building' | 'active' | 'archived'
  createdAt: string
  activatedAt: string | null
}

export interface KbIndexVersionForm {
  name: string
  chunkSize: number
  chunkOverlap: number
}

export interface KbChunkItem {
  id: string
  ordinal: number
  content: string
  tokenCount: number
  metadata: {
    heading?: string
    headingPath?: string
    sectionIndex?: number
  } | null
}

export interface KbChunkPage {
  items: KbChunkItem[]
  total: number
  offset: number
  limit: number
  hasMore: boolean
  /** draft：待建立索引的切片；indexed：已经建立索引的切片。 */
  source: 'draft' | 'indexed'
}

export interface KbSearchParams {
  query: string
  topK: number
  threshold: number
}

export interface KbSearchItem {
  chunkId: string
  documentId: string
  documentTitle: string
  ordinal: number
  content: string
  score: number
  metadata: Record<string, unknown> | null
}

export interface KbSearchResult {
  query: string
  topK: number
  threshold: number
  /** vector：语义检索；keyword：嵌入模型不可用时的关键词降级检索。 */
  mode: 'vector' | 'keyword'
  /** 降级原因，正常语义检索时为空。 */
  warning: string | null
  indexVersion: KbIndexVersionItem
  tookMs: number
  items: KbSearchItem[]
}
