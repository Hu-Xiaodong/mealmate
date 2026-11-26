<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Refresh, Search } from '@element-plus/icons-vue'

import { listAICallLogs } from '@/api/admin'
import type { AICallLogItem } from '@/api/types'
import { formatDateTime } from '@/utils/format'

const router = useRouter()
const loading = ref(false)
const items = ref<AICallLogItem[]>([])
const filters = reactive({ status: '' })
// 页码分页：调用日志会持续增长，不能只展示最近固定条数。
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)

const CONTEXT_LABELS: Record<string, string> = {
  home: '首页',
  post: '饭帖详情',
  recipe_list: '菜谱列表',
  admin_test: '后台测试',
}

async function load() {
  loading.value = true
  try {
    const data = await listAICallLogs({
      status: filters.status || undefined,
      page: page.value,
      pageSize: pageSize.value,
    })
    items.value = data.items
    total.value = data.total
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '加载调用日志失败')
  } finally {
    loading.value = false
  }
}

/** 状态筛选变化后回到第 1 页。 */
function search() {
  page.value = 1
  void load()
}

function changePageSize() {
  page.value = 1
  void load()
}

function contextLabel(value: string) {
  return CONTEXT_LABELS[value] || value
}

/** 打开某一次调用的执行过程明细。 */
function openDetail(row: AICallLogItem) {
  router.push(`/ai-call-logs/${row.id}`)
}

onMounted(load)
</script>

<template>
  <div class="page" v-loading="loading">
    <header class="page-head">
      <div>
        <h1 class="page-title">AI 调用日志</h1>
        <p class="page-subtitle">
          每次模型尝试都会记录耗时、token 与错误。一次提问切换多个模型时，可以看到完整的尝试过程。
        </p>
      </div>
      <div class="head-actions">
        <el-select v-model="filters.status" placeholder="全部状态" clearable class="status-select">
          <el-option label="成功" value="success" />
          <el-option label="失败" value="failed" />
        </el-select>
        <el-button :icon="Search" @click="search">筛选</el-button>
        <el-button :icon="Refresh" @click="load">刷新</el-button>
      </div>
    </header>

    <el-table :data="items" border stripe>
      <el-table-column label="时间" width="180">
        <template #default="{ row }">{{ formatDateTime(row.createdAt) }}</template>
      </el-table-column>
      <el-table-column prop="providerName" label="供应商" width="140" />
      <el-table-column prop="model" label="模型" min-width="150" />
      <el-table-column label="场景" width="110">
        <template #default="{ row }">{{ contextLabel(row.contextType) }}</template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag v-if="row.status === 'success'" type="success" size="small">成功</el-tag>
          <el-tag v-else type="danger" size="small">失败</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="耗时" width="90" align="right">
        <template #default="{ row }">{{ row.latencyMs }} ms</template>
      </el-table-column>
      <el-table-column label="Token" width="150" align="right">
        <template #default="{ row }">
          {{ row.promptTokens }} + {{ row.completionTokens }} = {{ row.totalTokens }}
        </template>
      </el-table-column>
      <el-table-column label="错误" min-width="220">
        <template #default="{ row }">
          <template v-if="row.status === 'success'">
            <span class="muted">-</span>
          </template>
          <template v-else>
            <div class="error-code">{{ row.errorCode || '未知错误' }}</div>
            <div class="muted">{{ row.errorMessage || '-' }}</div>
          </template>
        </template>
      </el-table-column>
      <el-table-column label="请求标识" width="150">
        <template #default="{ row }">
          <span class="muted">{{ row.requestId || '-' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="100" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openDetail(row)">
            查看详情
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <div class="pager">
      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :total="total"
        :page-sizes="[10, 20, 50, 100]"
        layout="total, sizes, prev, pager, next, jumper"
        background
        @current-change="load"
        @size-change="changePageSize"
      />
    </div>
  </div>
</template>

<style scoped>
.head-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.status-select {
  width: 140px;
}

.error-code {
  color: var(--el-color-danger);
  font-weight: 600;
}

.footnote {
  margin-top: 12px;
  font-size: 12px;
}
</style>
