<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh, Search } from '@element-plus/icons-vue'

import { listAuditLogs } from '@/api/admin'
import type { AuditLogItem } from '@/api/types'
import {
  ACTION_LABELS,
  ACTION_OPTIONS,
  formatDateTime,
} from '@/utils/format'

const filters = reactive({
  actorName: '',
  action: '',
  range: [] as string[],
})

const items = ref<AuditLogItem[]>([])
const loading = ref(false)
// 页码分页：审计日志会持续追加，运营需要按页核对和回看，而不是只能往下加载。
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)

function actionLabel(action: string) {
  return ACTION_LABELS[action] || action
}

function actionTagType(action: string) {
  if (action === 'post.approve' || action === 'user.unban') {
    return 'success'
  }
  if (action === 'post.reject' || action === 'user.ban' || action === 'post.delete') {
    return 'danger'
  }
  if (action === 'post.unpublish') {
    return 'warning'
  }
  return 'info'
}

function prettyJson(value: Record<string, unknown> | null) {
  if (!value) {
    return '无'
  }
  return JSON.stringify(value, null, 2)
}

async function load() {
  if (loading.value) {
    return
  }
  loading.value = true
  try {
    const data = await listAuditLogs({
      actorName: filters.actorName.trim() || undefined,
      action: filters.action || undefined,
      startAt: filters.range?.[0] || undefined,
      endAt: filters.range?.[1] || undefined,
      page: page.value,
      pageSize: pageSize.value,
    })
    items.value = data.items
    total.value = data.total
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '加载审计日志失败')
  } finally {
    loading.value = false
  }
}

function search() {
  page.value = 1
  load()
}

function changePageSize() {
  page.value = 1
  void load()
}

function reset() {
  filters.actorName = ''
  filters.action = ''
  filters.range = []
  search()
}

onMounted(() => load())
</script>

<template>
  <div class="page">
    <header class="page-head">
      <div>
        <h1 class="page-title">审计日志</h1>
        <p class="page-subtitle">
          只追加、不修改、不删除。每条记录包含操作人、动作、对象、原因、来源地址和请求标识。
        </p>
      </div>
      <el-button :icon="Refresh" :loading="loading" @click="load">
        刷新
      </el-button>
    </header>

    <section class="panel">
      <div class="toolbar">
        <el-input
          v-model="filters.actorName"
          placeholder="操作人名称"
          clearable
          style="width: 180px"
          @keyup.enter="search"
        />
        <el-select
          v-model="filters.action"
          placeholder="全部动作"
          clearable
          style="width: 160px"
        >
          <el-option
            v-for="option in ACTION_OPTIONS"
            :key="option.value"
            :label="option.label"
            :value="option.value"
          />
        </el-select>
        <el-date-picker
          v-model="filters.range"
          type="datetimerange"
          value-format="YYYY-MM-DDTHH:mm:ssZ"
          range-separator="至"
          start-placeholder="开始时间"
          end-placeholder="结束时间"
          style="width: 360px"
        />
        <el-button type="primary" :icon="Search" @click="search">
          查询
        </el-button>
        <el-button @click="reset">重置</el-button>
        <span class="toolbar-spacer" />
        <span class="muted">共加载 {{ items.length }} 条</span>
      </div>
    </section>

    <section class="panel">
      <el-table
        :data="items"
        v-loading="loading"
        row-key="id"
        row-class-name="audit-row"
      >
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="audit-expand">
              <div>
                <p class="json-title">变更前</p>
                <pre class="json-block">{{ prettyJson(row.before) }}</pre>
              </div>
              <div>
                <p class="json-title">变更后</p>
                <pre class="json-block">{{ prettyJson(row.after) }}</pre>
              </div>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="时间" width="172">
          <template #default="{ row }">
            <span class="muted">{{ formatDateTime(row.createdAt) }}</span>
          </template>
        </el-table-column>

        <el-table-column label="操作人" width="130">
          <template #default="{ row }">{{ row.actorName }}</template>
        </el-table-column>

        <el-table-column label="动作" width="120">
          <template #default="{ row }">
            <el-tag :type="actionTagType(row.action)" effect="light">
              {{ actionLabel(row.action) }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column label="对象" min-width="200">
          <template #default="{ row }">
            <div class="target">
              <span>{{ row.targetType }}</span>
              <span class="mono muted">{{ row.targetId }}</span>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="原因" min-width="200">
          <template #default="{ row }">
            <span :class="{ muted: !row.reason }">{{ row.reason || '-' }}</span>
          </template>
        </el-table-column>

        <el-table-column label="来源地址" width="140">
          <template #default="{ row }">
            <span class="mono">{{ row.ip || '-' }}</span>
          </template>
        </el-table-column>

        <el-table-column label="请求标识" width="180">
          <template #default="{ row }">
            <span class="mono muted">{{ row.requestId || '-' }}</span>
          </template>
        </el-table-column>

        <template #empty>
          <el-empty description="暂无审计日志" />
        </template>
      </el-table>

      <div class="pager">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          :total="total"
          :page-sizes="[10, 20, 50]"
          layout="total, sizes, prev, pager, next, jumper"
          background
          @current-change="load"
          @size-change="changePageSize"
        />
      </div>
    </section>
  </div>
</template>

<style scoped>
.audit-expand {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
  padding: 8px 16px 16px 48px;
}

.target {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.audit-row {
  cursor: default;
}

@media (max-width: 900px) {
  .audit-expand {
    grid-template-columns: 1fr;
    padding-left: 16px;
  }
}
</style>
