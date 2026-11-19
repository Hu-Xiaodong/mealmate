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
