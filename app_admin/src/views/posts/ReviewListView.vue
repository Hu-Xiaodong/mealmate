<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'

import {
  approvePost,
  batchDeletePosts,
  batchReviewPosts,
  listPosts,
  rejectPost,
  unpublishPost,
} from '@/api/admin'
import type { AdminPost } from '@/api/types'
import { useAdminStore } from '@/stores/admin'
import {
  formatDateTime,
  POST_STATUS_META,
  SOURCE_LABELS,
} from '@/utils/format'
import PostDetailDrawer from './PostDetailDrawer.vue'

const store = useAdminStore()
const canDelete = computed(() => store.hasPermission('post.delete'))

const statusFilter = ref('pending_review')
const items = ref<AdminPost[]>([])
const loading = ref(false)
const hasMore = ref(false)
const nextCursor = ref<string | null>(null)

const drawerVisible = ref(false)
const activePostId = ref('')
const tableRef = ref()
const selectedRows = ref<AdminPost[]>([])

const batchDialog = reactive({
  visible: false,
  action: 'approve' as 'approve' | 'reject' | 'delete',
  reason: '',
  submitting: false,
})
const batchDialogTitle = computed(() =>
  batchDialog.action === 'delete' ? '批量删除' : '批量拒绝',
)

const reasonDialog = reactive({
  visible: false,
  mode: 'reject' as 'reject' | 'unpublish',
  postId: '',
  title: '',
  tip: '',
  reason: '',
  submitting: false,
})

const statusTabs = [
  { value: 'pending_review', label: '待审核' },
  { value: 'published', label: '已公开' },
  { value: 'rejected', label: '已拒绝' },
  { value: 'unpublished', label: '已下架' },
  { value: '', label: '全部' },
]

function statusMeta(status: string) {
  return POST_STATUS_META[status] || {
    label: status,
    type: 'info' as const,
    hint: '',
  }
}

function sourceLabel(source: string) {
  return SOURCE_LABELS[source] || source
}

async function load(reset = false) {
  if (loading.value) {
    return
  }
  loading.value = true
  try {
    const data = await listPosts({
      status: statusFilter.value || undefined,
      cursor: reset ? undefined : nextCursor.value || undefined,
      limit: 20,
    })
    items.value = reset ? data.items : [...items.value, ...data.items]
    nextCursor.value = data.nextCursor
    hasMore.value = data.hasMore
    selectedRows.value = []
    tableRef.value?.clearSelection()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '加载饭帖失败')
  } finally {
    loading.value = false
  }
}

function reload() {
  nextCursor.value = null
  return load(true)
}

function openDetail(row: AdminPost, column?: { type?: string }) {
  // 勾选框那一列不触发详情，否则批量选择时会被抽屉打断。
  if (column?.type === 'selection') return
  activePostId.value = row.id
  drawerVisible.value = true
}

function handleSelectionChange(rows: AdminPost[]) {
  selectedRows.value = rows
}

async function openBatch(action: 'approve' | 'reject' | 'delete') {
  if (!selectedRows.value.length) {
    ElMessage.warning('请先勾选要处理的饭帖')
    return
  }
  if (action === 'reject' || action === 'delete') {
    batchDialog.action = action
    batchDialog.reason = ''
    batchDialog.visible = true
    return
  }
  try {
    await ElMessageBox.confirm(
      `确认批量通过已勾选的 ${selectedRows.value.length} 条饭帖？`,
      '批量通过',
      { type: 'warning', confirmButtonText: '确认通过', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  submitBatch('approve')
}

async function submitBatch(action: 'approve' | 'reject' | 'delete') {
  const ids = selectedRows.value.map((row) => row.id)
  if (!ids.length) {
    ElMessage.warning('请先勾选要处理的饭帖')
    return
  }
  if ((action === 'reject' || action === 'delete') && batchDialog.reason.trim().length < 2) {
    ElMessage.warning(
      action === 'delete'
        ? '请填写至少 2 个字的删除原因'
        : '请填写至少 2 个字的拒绝原因',
    )
    return
  }
  batchDialog.submitting = true
  try {
    const result =
      action === 'delete'
        ? await batchDeletePosts(ids, batchDialog.reason.trim())
        : await batchReviewPosts(
            ids,
            action,
            action === 'reject' ? batchDialog.reason.trim() : undefined,
          )
    const failed = result.results.filter((item) => !item.ok)
    if (result.failed) {
      const first = failed[0]
      ElMessage.warning(
        `成功 ${result.succeeded} 条，失败 ${result.failed} 条。首条失败原因：${first?.message || first?.errorCode || '未知'}`,
      )
    } else {
      const actionLabel =
        action === 'approve' ? '通过' : action === 'reject' ? '拒绝' : '删除'
      ElMessage.success(`已${actionLabel} ${result.succeeded} 条`)
    }
    batchDialog.visible = false
    await reload()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '批量操作失败')
  } finally {
    batchDialog.submitting = false
  }
}

async function approve(row: AdminPost) {
  try {
    await ElMessageBox.confirm(
      `确认通过《${row.title}》？通过后会立即出现在首页与热榜。`,
      '审核通过',
      {
        type: 'warning',
        confirmButtonText: '确认通过',
        cancelButtonText: '取消',
      },
    )
  } catch {
    return
  }
  try {
    const result = await approvePost(row.id)
    ElMessage.success(result.changed ? '已通过审核' : '该饭帖已经是公开状态')
    await reload()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '操作失败')
  }
}

function openReason(row: AdminPost, mode: 'reject' | 'unpublish') {
  reasonDialog.visible = true
  reasonDialog.mode = mode
  reasonDialog.postId = row.id
  reasonDialog.title = mode === 'reject' ? '拒绝饭帖' : '下架饭帖'
  reasonDialog.tip =
    mode === 'reject'
      ? `拒绝《${row.title}》后，作者会在“我的发布”看到原因。`
      : `下架《${row.title}》后，首页与热榜将立即不再展示。`
  reasonDialog.reason = ''
}

async function submitReason() {
  const reason = reasonDialog.reason.trim()
  if (reason.length < 2) {
    ElMessage.warning('请填写至少 2 个字的原因')
    return
  }
  reasonDialog.submitting = true
  try {
    const result =
      reasonDialog.mode === 'reject'
        ? await rejectPost(reasonDialog.postId, reason)
        : await unpublishPost(reasonDialog.postId, reason)
    ElMessage.success(
      result.changed
        ? reasonDialog.mode === 'reject'
          ? '已拒绝该饭帖'
          : '已下架该饭帖'
        : '操作已完成，当前状态未变化',
    )
    reasonDialog.visible = false
    await reload()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '操作失败')
  } finally {
    reasonDialog.submitting = false
  }
}

onMounted(() => load(true))
</script>

<template>
  <div class="page">
    <header class="page-head">
      <div>
        <h1 class="page-title">饭帖审核</h1>
        <p class="page-subtitle">
          待审核内容不会出现在公开列表。通过后立即进入首页与今日热榜，拒绝或下架时必须填写原因。
        </p>
      </div>
      <el-button :icon="Refresh" :loading="loading" @click="reload">
        刷新
      </el-button>
    </header>

    <section class="panel">
      <div class="toolbar">
        <el-radio-group v-model="statusFilter" @change="() => reload()">
          <el-radio-button
            v-for="tab in statusTabs"
            :key="tab.value || 'all'"
            :value="tab.value"
          >
            {{ tab.label }}
          </el-radio-button>
        </el-radio-group>
        <span class="toolbar-spacer" />
        <template v-if="selectedRows.length">
          <span class="muted">已选 {{ selectedRows.length }} 条</span>
          <el-button size="small" type="success" plain @click="openBatch('approve')">
            批量通过
          </el-button>
          <el-button size="small" type="danger" plain @click="openBatch('reject')">
            批量拒绝
          </el-button>
          <el-button
            v-if="canDelete"
            size="small"
            type="danger"
            @click="openBatch('delete')"
          >
            批量删除
          </el-button>
        </template>
        <span class="muted">共加载 {{ items.length }} 条</span>
      </div>
    </section>

    <section class="panel">
      <el-table
        ref="tableRef"
        :data="items"
        v-loading="loading"
        row-key="id"
        row-class-name="clickable-row"
        @row-click="openDetail"
        @selection-change="handleSelectionChange"
      >
        <el-table-column type="selection" width="46" reserve-selection />
        <el-table-column label="封面" width="82">
          <template #default="{ row }">
            <el-image
              v-if="row.coverImage"
              :src="row.coverImage"
              :preview-src-list="row.images"
              fit="cover"
              class="thumb"
              preview-teleported
            />
            <div v-else class="thumb" />
          </template>
        </el-table-column>

        <el-table-column label="内容" min-width="260">
          <template #default="{ row }">
            <div class="post-cell">
              <span class="post-cell__title">{{ row.title }}</span>
              <span class="post-cell__review">{{ row.review }}</span>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="作者" width="130">
          <template #default="{ row }">
            {{ row.author?.nickname || '-' }}
          </template>
        </el-table-column>

        <el-table-column label="来源" width="92">
          <template #default="{ row }">
            <el-tag effect="plain" type="info">{{ sourceLabel(row.source) }}</el-tag>
          </template>
        </el-table-column>

        <el-table-column label="状态" width="104">
          <template #default="{ row }">
            <el-tag :type="statusMeta(row.status).type" effect="light">
              {{ statusMeta(row.status).label }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column label="提交时间" width="172">
          <template #default="{ row }">
            <span class="muted">{{ formatDateTime(row.createdAt) }}</span>
          </template>
        </el-table-column>

        <el-table-column label="操作" width="210" fixed="right">
          <template #default="{ row }">
            <div class="row-actions" @click.stop>
              <el-button link type="primary" @click="openDetail(row)">
                查看
              </el-button>
              <template v-if="row.status === 'pending_review'">
                <el-button link type="success" @click="approve(row)">
                  通过
                </el-button>
                <el-button link type="danger" @click="openReason(row, 'reject')">
                  拒绝
                </el-button>
              </template>
              <el-button
                v-if="row.status === 'published'"
                link
                type="warning"
                @click="openReason(row, 'unpublish')"
              >
                下架
              </el-button>
            </div>
          </template>
        </el-table-column>

        <template #empty>
          <el-empty
            :description="
              statusFilter === 'pending_review'
                ? '当前没有待审核内容'
                : '暂无符合条件的饭帖'
            "
          />
        </template>
      </el-table>

      <div v-if="hasMore" class="load-more">
        <el-button :loading="loading" @click="load(false)">加载更多</el-button>
      </div>
    </section>

    <el-dialog
      v-model="batchDialog.visible"
      :title="batchDialogTitle"
      width="480px"
      destroy-on-close
    >
      <p class="dialog-tip">
        <template v-if="batchDialog.action === 'delete'">
          将删除已勾选的 {{ selectedRows.length }} 条饭帖。删除后后台列表与公开页面都不再展示，
          记录保留在数据库中，可在审计日志追溯；每条都会写入删除原因。
        </template>
        <template v-else>
          将拒绝已勾选的 {{ selectedRows.length }} 条饭帖，每一条都会写入审核原因与审计日志。
        </template>
      </p>
      <el-input
        v-model="batchDialog.reason"
        type="textarea"
        :rows="4"
        maxlength="200"
        show-word-limit
        placeholder="请填写具体原因，至少 2 个字"
      />
      <template #footer>
        <el-button @click="batchDialog.visible = false">取消</el-button>
        <el-button
          type="danger"
          :loading="batchDialog.submitting"
          @click="submitBatch(batchDialog.action)"
        >
          {{ batchDialog.action === 'delete' ? '确认批量删除' : '确认批量拒绝' }}
        </el-button>
      </template>
    </el-dialog>

    <PostDetailDrawer v-model="drawerVisible" :post-id="activePostId" />

    <el-dialog
      v-model="reasonDialog.visible"
      :title="reasonDialog.title"
      width="480px"
      destroy-on-close
    >
      <p class="dialog-tip">{{ reasonDialog.tip }}</p>
      <el-input
        v-model="reasonDialog.reason"
        type="textarea"
        :rows="4"
        maxlength="200"
        show-word-limit
        placeholder="请填写具体原因，至少 2 个字"
      />
      <template #footer>
        <el-button @click="reasonDialog.visible = false">取消</el-button>
        <el-button
          :type="reasonDialog.mode === 'reject' ? 'danger' : 'warning'"
          :loading="reasonDialog.submitting"
          @click="submitReason"
        >
          {{ reasonDialog.mode === 'reject' ? '确认拒绝' : '确认下架' }}
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
</style>
