<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh, Search } from '@element-plus/icons-vue'

import { banUser, getUser, listUserPosts, listUsers, unbanUser } from '@/api/admin'
import type { AdminPost, AdminUserDetail, AdminUserItem } from '@/api/types'
import {
  formatDateTime,
  POST_STATUS_META,
  SOURCE_LABELS,
  USER_STATUS_META,
} from '@/utils/format'

const keyword = ref('')
const statusFilter = ref('')
const items = ref<AdminUserItem[]>([])
const loading = ref(false)
const hasMore = ref(false)
const nextCursor = ref<string | null>(null)

const detailVisible = ref(false)
const detailLoading = ref(false)
const activeUserId = ref('')
const detail = ref<AdminUserDetail | null>(null)

const banDialog = reactive({
  visible: false,
  userId: '',
  nickname: '',
  reason: '',
  submitting: false,
})

const userPosts = ref<AdminPost[]>([])
const userPostsLoading = ref(false)
const userPostsHasMore = ref(false)
const userPostsCursor = ref<string | null>(null)
const userPostsStatus = ref('')
const previewPost = ref<AdminPost | null>(null)

function postStatus(status: string) {
  return POST_STATUS_META[status] || { label: status, type: 'info' as const, hint: '' }
}

function sourceLabel(source: string) {
  return SOURCE_LABELS[source] || source
}

function userStatus(status: string) {
  return USER_STATUS_META[status] || { label: status, type: 'info' as const }
}

async function load(reset = false) {
  if (loading.value) {
    return
  }
  loading.value = true
  try {
    const data = await listUsers({
      keyword: keyword.value.trim() || undefined,
      status: statusFilter.value || undefined,
      cursor: reset ? undefined : nextCursor.value || undefined,
      limit: 20,
    })
    items.value = reset ? data.items : [...items.value, ...data.items]
    nextCursor.value = data.nextCursor
    hasMore.value = data.hasMore
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '加载用户失败')
  } finally {
    loading.value = false
  }
}

function search() {
  nextCursor.value = null
  load(true)
}

function reset() {
  keyword.value = ''
  statusFilter.value = ''
  search()
}

async function loadDetail(userId: string) {
  detailLoading.value = true
  try {
    detail.value = await getUser(userId)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '加载用户详情失败')
  } finally {
    detailLoading.value = false
  }
}

async function loadUserPosts(reset = true) {
  if (!activeUserId.value) return
  if (userPostsLoading.value) return
  userPostsLoading.value = true
  try {
    const data = await listUserPosts(activeUserId.value, {
      status: userPostsStatus.value || undefined,
      cursor: reset ? undefined : userPostsCursor.value || undefined,
      limit: 10,
    })
    userPosts.value = reset ? data.items : [...userPosts.value, ...data.items]
    userPostsCursor.value = data.nextCursor
    userPostsHasMore.value = data.hasMore
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '加载用户发布失败')
  } finally {
    userPostsLoading.value = false
  }
}

function openDetail(row: AdminUserItem) {
  activeUserId.value = row.id
  detail.value = null
  userPosts.value = []
  userPostsCursor.value = null
  userPostsHasMore.value = false
  userPostsStatus.value = ''
  detailVisible.value = true
  loadDetail(row.id)
  loadUserPosts(true)
}

function askBan(user: AdminUserItem | AdminUserDetail) {
  banDialog.visible = true
  banDialog.userId = user.id
  banDialog.nickname = user.nickname
  banDialog.reason = ''
}

async function submitBan() {
  const reason = banDialog.reason.trim()
  if (reason.length < 2) {
    ElMessage.warning('请填写至少 2 个字的原因')
    return
  }
  banDialog.submitting = true
  try {
    const result = await banUser(banDialog.userId, reason)
    ElMessage.success(result.changed ? '已封禁该用户，并撤销其全部会话' : '该用户已被封禁')
    banDialog.visible = false
    await load(true)
    if (detailVisible.value) {
      await loadDetail(activeUserId.value)
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '封禁失败')
  } finally {
    banDialog.submitting = false
  }
}

async function handleUnban(user: AdminUserItem | AdminUserDetail) {
  try {
    await ElMessageBox.confirm(
      `确认解封“${user.nickname}”？解封后该用户需要重新登录。`,
      '解封用户',
      {
        type: 'warning',
        confirmButtonText: '确认解封',
        cancelButtonText: '取消',
      },
    )
  } catch {
    return
  }
  try {
    const result = await unbanUser(user.id)
    ElMessage.success(result.changed ? '已解封' : '该用户当前可正常使用')
    await load(true)
    if (detailVisible.value) {
      await loadDetail(activeUserId.value)
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '解封失败')
  }
}

onMounted(() => load(true))
</script>

<template>
  <div class="page">
    <header class="page-head">
      <div>
        <h1 class="page-title">用户管理</h1>
        <p class="page-subtitle">
          手机号默认脱敏展示。封禁会立即撤销该用户的全部会话，解封后需要重新登录。
        </p>
      </div>
      <el-button :icon="Refresh" :loading="loading" @click="load(true)">
        刷新
      </el-button>
    </header>

    <section class="panel">
      <div class="toolbar">
        <el-input
          v-model="keyword"
          placeholder="搜索昵称或手机号后四位"
          clearable
          style="width: 260px"
          :prefix-icon="Search"
          @keyup.enter="search"
        />
        <el-select
          v-model="statusFilter"
          placeholder="全部状态"
          clearable
          style="width: 150px"
        >
          <el-option label="正常" value="active" />
          <el-option label="已封禁" value="disabled" />
          <el-option label="系统账号" value="system" />
        </el-select>
        <el-button type="primary" @click="search">查询</el-button>
        <el-button @click="reset">重置</el-button>
        <span class="toolbar-spacer" />
        <span class="muted">共加载 {{ items.length }} 位用户</span>
      </div>
    </section>

    <section class="panel">
      <el-table
        :data="items"
        v-loading="loading"
        row-key="id"
        row-class-name="clickable-row"
        @row-click="openDetail"
      >
        <el-table-column label="用户" min-width="220">
          <template #default="{ row }">
            <div class="user-cell">
              <el-avatar :size="36" :src="row.avatarUrl || undefined">
                {{ row.nickname?.slice(0, 1) }}
              </el-avatar>
              <div>
                <div class="user-cell__name">{{ row.nickname }}</div>
                <div class="user-cell__id mono">{{ row.id }}</div>
              </div>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="手机号" width="150">
          <template #default="{ row }">
            <span class="mono">{{ row.phoneMasked }}</span>
          </template>
        </el-table-column>

        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="userStatus(row.status).type" effect="light">
              {{ userStatus(row.status).label }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column label="发布数" width="100">
          <template #default="{ row }">{{ row.postCount }}</template>
        </el-table-column>

        <el-table-column label="注册时间" width="180">
          <template #default="{ row }">
            <span class="muted">{{ formatDateTime(row.createdAt) }}</span>
          </template>
        </el-table-column>

        <el-table-column label="操作" width="170" fixed="right">
          <template #default="{ row }">
            <div class="row-actions" @click.stop>
              <el-button link type="primary" @click="openDetail(row)">
                详情
              </el-button>
              <el-button
                v-if="row.status === 'active'"
                link
                type="danger"
                @click="askBan(row)"
              >
                封禁
              </el-button>
              <el-button
                v-else-if="row.status === 'disabled'"
                link
                type="success"
                @click="handleUnban(row)"
              >
                解封
              </el-button>
            </div>
          </template>
        </el-table-column>

        <template #empty>
          <el-empty description="暂无符合条件的用户" />
        </template>
      </el-table>

      <div v-if="hasMore" class="load-more">
        <el-button :loading="loading" @click="load(false)">加载更多</el-button>
      </div>
    </section>

    <el-drawer v-model="detailVisible" title="用户详情" size="520px" destroy-on-close>
      <div v-loading="detailLoading" class="user-detail">
        <template v-if="detail">
          <div class="profile">
            <el-avatar :size="56" :src="detail.avatarUrl || undefined">
              {{ detail.nickname?.slice(0, 1) }}
            </el-avatar>
            <div class="profile__text">
              <div class="profile__name">
                {{ detail.nickname }}
                <el-tag :type="userStatus(detail.status).type" effect="light">
                  {{ userStatus(detail.status).label }}
                </el-tag>
              </div>
              <div class="profile__id mono">{{ detail.id }}</div>
            </div>
          </div>

          <div class="stat-grid detail__stats">
            <div class="stat-card">
              <div class="stat-card__value">{{ detail.postCount }}</div>
              <div class="stat-card__label">发布饭帖</div>
            </div>
            <div class="stat-card">
              <div class="stat-card__value">{{ detail.likeCount }}</div>
              <div class="stat-card__label">有效点赞</div>
            </div>
            <div class="stat-card">
              <div class="stat-card__value">{{ detail.favoriteCount }}</div>
              <div class="stat-card__label">收藏</div>
            </div>
          </div>

          <div class="drawer-section">
            <div class="drawer-section__head">
              <h3 class="drawer-section__title">Ta 的发布</h3>
              <el-select
                v-model="userPostsStatus"
                size="small"
                placeholder="全部状态"
                clearable
                style="width: 130px"
                @change="loadUserPosts(true)"
              >
                <el-option label="待审核" value="pending_review" />
                <el-option label="已公开" value="published" />
                <el-option label="已拒绝" value="rejected" />
                <el-option label="已下架" value="unpublished" />
              </el-select>
            </div>
            <div v-loading="userPostsLoading" class="user-post-list">
              <div
                v-for="post in userPosts"
                :key="post.id"
                class="user-post"
                @click="previewPost = post"
              >
                <el-image
                  v-if="post.coverImage"
                  :src="post.coverImage"
                  fit="cover"
                  class="user-post__cover"
                />
                <div v-else class="user-post__cover" />
                <div class="user-post__main">
                  <div class="user-post__title">
                    {{ post.title }}
                    <el-tag :type="postStatus(post.status).type" size="small">
                      {{ postStatus(post.status).label }}
                    </el-tag>
                  </div>
                  <div class="user-post__review">{{ post.review }}</div>
                  <div class="user-post__meta">
                    {{ sourceLabel(post.source) }} ·
                    {{ formatDateTime(post.createdAt) }}
                  </div>
                </div>
              </div>
              <el-empty
                v-if="!userPostsLoading && !userPosts.length"
                description="该用户还没有公开或待审核内容"
                :image-size="60"
              />
              <div v-if="userPostsHasMore" class="load-more">
                <el-button size="small" :loading="userPostsLoading" @click="loadUserPosts(false)">
                  加载更多
                </el-button>
              </div>
            </div>
          </div>

          <div class="drawer-section">
            <h3 class="drawer-section__title">账号信息</h3>
            <el-descriptions :column="1" border size="small">
              <el-descriptions-item label="手机号">
                {{ detail.phoneMasked }}
              </el-descriptions-item>
              <el-descriptions-item label="注册时间">
                {{ formatDateTime(detail.createdAt) }}
              </el-descriptions-item>
              <el-descriptions-item label="账号状态">
                {{ userStatus(detail.status).label }}
              </el-descriptions-item>
            </el-descriptions>
            <p class="phone-tip">
              完整手机号属于敏感个人信息，第一阶段只展示脱敏结果。后续如需查看，
              应增加独立权限点并记录审计日志。
            </p>
          </div>

          <div class="drawer-section">
            <h3 class="drawer-section__title">账号处置</h3>
            <div class="actions">
              <el-button
                v-if="detail.status === 'active'"
                type="danger"
                @click="askBan(detail)"
              >
                封禁该用户
              </el-button>
              <el-button
                v-else-if="detail.status === 'disabled'"
                type="success"
                @click="handleUnban(detail)"
              >
                解封该用户
              </el-button>
              <span v-else class="muted">系统账号不参与封禁。</span>
            </div>
            <p class="phone-tip">
              封禁后该用户的全部登录会话立即失效，已发布内容不会自动下架。
            </p>
          </div>
        </template>
      </div>
    </el-drawer>

    <el-dialog
      :model-value="Boolean(previewPost)"
      title="发布详情"
      width="620px"
      @close="previewPost = null"
    >
      <template v-if="previewPost">
        <div class="preview-head">
          <h3 class="preview-title">{{ previewPost.title }}</h3>
          <el-tag :type="postStatus(previewPost.status).type">
            {{ postStatus(previewPost.status).label }}
          </el-tag>
        </div>
        <p class="preview-review">{{ previewPost.review }}</p>
        <div v-if="previewPost.images.length" class="preview-images">
          <el-image
            v-for="(image, index) in previewPost.images"
            :key="image + index"
            :src="image"
            :preview-src-list="previewPost.images"
            :initial-index="index"
            fit="cover"
            preview-teleported
          />
        </div>
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="来源">
            {{ sourceLabel(previewPost.source) }}
          </el-descriptions-item>
          <el-descriptions-item label="提交时间">
            {{ formatDateTime(previewPost.createdAt) }}
          </el-descriptions-item>
          <el-descriptions-item label="外卖店家">
            {{ previewPost.takeawayStore || '-' }}
          </el-descriptions-item>
          <el-descriptions-item label="到店地址">
            {{ previewPost.dineInAddress || '-' }}
          </el-descriptions-item>
          <el-descriptions-item label="粗略位置">
            {{ previewPost.coarseArea || '-' }}
          </el-descriptions-item>
          <el-descriptions-item label="平台菜谱">
            {{ previewPost.platformRecipeTitle || '-' }}
          </el-descriptions-item>
        </el-descriptions>
        <p v-if="previewPost.reviewReason" class="phone-tip">
          审核原因：{{ previewPost.reviewReason }}
        </p>
      </template>
      <template #footer>
        <el-button @click="previewPost = null">关闭</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="banDialog.visible" title="封禁用户" width="480px" destroy-on-close>
      <p class="dialog-tip">
        即将封禁“{{ banDialog.nickname }}”。封禁后该用户全部会话立即失效，
        原因会写入审计日志。
      </p>
      <el-input
        v-model="banDialog.reason"
        type="textarea"
        :rows="4"
        maxlength="200"
        show-word-limit
        placeholder="请填写具体原因，至少 2 个字"
      />
      <template #footer>
        <el-button @click="banDialog.visible = false">取消</el-button>
        <el-button type="danger" :loading="banDialog.submitting" @click="submitBan">
          确认封禁
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.row-actions {
  display: flex;
  align-items: center;
  gap: 2px;
}

.profile {
  display: flex;
  align-items: center;
  gap: 14px;
}

.profile__name {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 18px;
  font-weight: 650;
}

.profile__id {
  margin-top: 4px;
  color: var(--admin-muted);
}

.detail__stats {
  margin-top: 20px;
}

.phone-tip {
  margin: 12px 0 0;
  color: #8b9199;
  font-size: 12px;
  line-height: 1.7;
}

.actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.drawer-section__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.drawer-section__head .drawer-section__title {
  margin-bottom: 0;
}

.user-post-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.user-post {
  display: flex;
  gap: 10px;
  padding: 10px;
  border: 1px solid var(--admin-line);
  border-radius: 10px;
  cursor: pointer;
  transition: border-color 0.2s ease;
}

.user-post:hover {
  border-color: #e5a08f;
}

.user-post__cover {
  width: 56px;
  height: 56px;
  flex: none;
  border-radius: 8px;
  background: #f2f3f5;
}

.user-post__main {
  min-width: 0;
}

.user-post__title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 600;
}

.user-post__review {
  overflow: hidden;
  margin-top: 4px;
  color: #4b5563;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.user-post__meta {
  margin-top: 6px;
  color: #9aa0a8;
  font-size: 11px;
}

.preview-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.preview-title {
  margin: 0;
  font-size: 17px;
}

.preview-review {
  margin: 10px 0 14px;
  color: #4b5563;
  line-height: 1.7;
}

.preview-images {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 14px;
}

.preview-images .el-image {
  width: 100px;
  height: 100px;
  border-radius: 8px;
}
</style>
