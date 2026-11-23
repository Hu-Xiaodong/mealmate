export interface ApiEnvelope<T> {
  requestId: string
  code: number | string
  message: string
  data: T
}

export interface PageResult<T> {
  items: T[]
  nextCursor: string | null
  hasMore: boolean
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
  cursor?: string
  limit?: number
}

export interface UserListParams {
  keyword?: string
  status?: string
  cursor?: string
  limit?: number
}

export interface AuditListParams {
  actorName?: string
  action?: string
  targetType?: string
  targetId?: string
  startAt?: string
  endAt?: string
  cursor?: string
  limit?: number
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
  cursor?: string
  limit?: number
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
  cursor?: string
  limit?: number
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
  limit?: number
}

export interface KbDocumentItem {
  id: string
  title: string
  sourceType: string
  mime: string
  bytes: number
  checksum: string
  status: 'uploaded' | 'parsing' | 'chunking' | 'indexing' | 'ready' | 'failed'
  errorMessage: string | null
  indexVersionId: string | null
  uploadedBy: string | null
  chunkCount: number
  createdAt: string
  updatedAt: string
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
  indexVersion: KbIndexVersionItem
  tookMs: number
  items: KbSearchItem[]
}
