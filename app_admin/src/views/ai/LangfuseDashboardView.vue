<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'

import {
  getLangfuseMetrics,
  getLangfuseStatus,
  getLocalAiMetrics,
} from '@/api/admin'
import type { LangfuseMetrics, LangfuseStatus } from '@/api/types'

/**
 * AI 观测看板。
 *
 * 默认使用本地数据库统计，完全不依赖 Langfuse：
 * 调用量、错误率、延迟、Token、成本、评分、提示词版本都来自
 * ai_call_logs / ai_call_scores。Langfuse 配置后可以切换成第二数据源，
 * 用来对比“本地统计”和“观测平台口径”，也可以继续看调用链。
 */
const loading = ref(false)
const days = ref(7)
const dataSource = ref<'local' | 'langfuse'>('local')
const status = ref<LangfuseStatus | null>(null)
const metrics = ref<LangfuseMetrics | null>(null)

const summaryCards = computed(() => {
  const summary = metrics.value?.summary || {}
  return [
    { label: '模型调用次数', value: formatNumber(summary.calls), hint: `最近 ${days.value} 天` },
    {
      label: '错误率',
      value: `${((summary.errorRate || 0) * 100).toFixed(2)}%`,
      hint: `失败 ${formatNumber(summary.errors)} 次`,
    },
    {
      label: '平均延迟',
      value: `${formatNumber(summary.avgLatencyMs)} ms`,
      hint: '首包到结束的整体耗时',
    },
    {
      label: 'P95 延迟',
      value: `${formatNumber(summary.p95LatencyMs)} ms`,
      hint: '95% 的调用快于这个值',
    },
    { label: '总 Token', value: formatNumber(summary.totalTokens), hint: '输入 + 输出' },
    {
      label: '总成本',
      value: `$${(summary.totalCost || 0).toFixed(4)}`,
      hint: '按模型配置里的单价计算',
    },
    {
      label: '平均评分',
      value: metrics.value?.scores.average
        ? `${metrics.value.scores.average.toFixed(2)} / 5`
        : '—',
      hint: `共 ${formatNumber(metrics.value?.scores.count)} 条人工评分`,
    },
  ]
})

const maxCalls = computed(() => {
  const rows = metrics.value?.trend || []
  return Math.max(1, ...rows.map((row) => row.calls))
})

function formatNumber(value?: number | null): string {
  if (value === undefined || value === null) {
    return '0'
  }
  return Math.round(value).toLocaleString('zh-CN')
}

function barWidth(calls: number): string {
  return `${Math.max(2, Math.round((calls / maxCalls.value) * 100))}%`
}

function dayLabel(value: string): string {
  return value?.slice(5) || '-'
}

function promptSourceLabel(source: string | null): string {
  if (source === 'local') {
    return '本地'
  }
  if (source === 'langfuse') {
    return 'Langfuse'
  }
  return '代码默认'
}

async function load() {
  loading.value = true
  try {
    // 状态查询只用于决定是否展示“切到 Langfuse”的选项。
    const [statusData, metricsData] = await Promise.all([
      getLangfuseStatus().catch(() => null),
      dataSource.value === 'local'
        ? getLocalAiMetrics(days.value)
        : getLangfuseMetrics(days.value),
    ])
    status.value = statusData
    metrics.value = metricsData
    if (dataSource.value === 'langfuse' && metricsData.message) {
      ElMessage.warning(metricsData.message)
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '加载观测数据失败')
  } finally {
    loading.value = false
  }
}

function changeRange(value: number) {
  days.value = value
  load()
}

function changeSource(value: string | number | boolean | undefined) {
  dataSource.value = value === 'langfuse' ? 'langfuse' : 'local'
  load()
}

onMounted(load)
</script>

<template>
  <div class="page" v-loading="loading">
    <header class="page-head">
      <div>
        <h1 class="page-title">AI 观测</h1>
        <p class="page-subtitle">
          模型调用量、错误率、延迟、Token、成本、提示词版本与人工评分的趋势。
          默认统计本地数据库，不依赖 Langfuse；单条排障请看“AI 调用日志”。
        </p>
      </div>
      <div class="head-actions">
        <el-radio-group
          v-if="status?.configured"
          :model-value="dataSource"
          size="small"
          @change="changeSource"
        >
          <el-radio-button value="local">本地统计</el-radio-button>
          <el-radio-button value="langfuse">Langfuse</el-radio-button>
        </el-radio-group>
        <el-radio-group :model-value="days" size="small" @change="changeRange">
          <el-radio-button :value="7">7 天</el-radio-button>
          <el-radio-button :value="14">14 天</el-radio-button>
          <el-radio-button :value="30">30 天</el-radio-button>
        </el-radio-group>
        <el-button :icon="Refresh" @click="load">刷新</el-button>
      </div>
    </header>

    <el-alert
      v-if="!status?.configured"
      type="info"
      show-icon
      :closable="false"
      title="当前使用本地统计，Langfuse 未配置"
    >
      <p>
        本地统计直接聚合调用日志与评分，功能完整可用。
        如需调用链对比或提示词镜像，可在 <code>server/.env</code> 填写
        Langfuse 地址与密钥后重启后端。
      </p>
    </el-alert>

    <el-alert
      v-else-if="dataSource === 'langfuse' && metrics && metrics.message"
      type="warning"
      show-icon
      :closable="false"
      title="Langfuse 指标读取失败"
      :description="metrics.message"
    />

    <section class="stat-grid">
      <div v-for="card in summaryCards" :key="card.label" class="stat-card">
        <span class="stat-label">{{ card.label }}</span>
        <strong class="stat-value">{{ card.value }}</strong>
        <span class="stat-hint">{{ card.hint }}</span>
      </div>
    </section>

    <section class="panel">
      <h3 class="panel-title">每日调用趋势</h3>
      <div v-if="metrics?.trend.length" class="trend">
        <div v-for="row in metrics.trend" :key="row.date" class="trend-row">
          <span class="trend-date">{{ dayLabel(row.date) }}</span>
          <div class="trend-bar-wrap">
            <div class="trend-bar" :style="{ width: barWidth(row.calls) }" />
            <span v-if="row.errors" class="trend-error">
              {{ row.errors }} 次失败
            </span>
          </div>
          <span class="trend-value">{{ formatNumber(row.calls) }} 次</span>
          <span class="trend-meta">{{ formatNumber(row.avgLatencyMs) }} ms</span>
          <span class="trend-meta">
            {{ formatNumber(row.totalTokens) }} token / ${{ (row.totalCost || 0).toFixed(4) }}
          </span>
        </div>
      </div>
      <el-empty v-else description="暂无指标数据" :image-size="72" />
    </section>

    <section v-if="metrics?.prompts?.length" class="panel">
      <h3 class="panel-title">按提示词版本对比</h3>
      <el-table :data="metrics.prompts" size="small">
        <el-table-column label="提示词" min-width="220">
          <template #default="{ row }">
            <span class="mono">{{ row.name }}</span>
          </template>
        </el-table-column>
        <el-table-column label="版本" width="80" align="center">
          <template #default="{ row }">
            {{ row.version ? `v${row.version}` : '—' }}
          </template>
        </el-table-column>
        <el-table-column label="来源" width="100" align="center">
          <template #default="{ row }">
            {{ promptSourceLabel(row.source) }}
          </template>
        </el-table-column>
        <el-table-column label="调用次数" width="100" align="right">
          <template #default="{ row }">{{ formatNumber(row.calls) }}</template>
        </el-table-column>
        <el-table-column label="失败" width="80" align="right">
          <template #default="{ row }">{{ formatNumber(row.errors) }}</template>
        </el-table-column>
        <el-table-column label="平均延迟" width="110" align="right">
          <template #default="{ row }">{{ formatNumber(row.avgLatencyMs) }} ms</template>
        </el-table-column>
        <el-table-column label="成本" width="110" align="right">
          <template #default="{ row }">${{ (row.totalCost || 0).toFixed(4) }}</template>
        </el-table-column>
      </el-table>
    </section>

    <p class="footnote muted">
      成本按“模型配置”里的输入 / 输出单价计算，单价填 0 时成本显示为 0。
      本地统计按服务端记录的调用时间聚合；Langfuse 只作为可选第二数据源。
    </p>
  </div>
</template>

<style scoped>
.page-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.head-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.stat-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
  margin: 16px 0;
}

.stat-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 14px 16px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px;
  background: var(--el-bg-color);
}

.stat-label {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.stat-value {
  font-size: 22px;
  line-height: 1.2;
}

.stat-hint {
  font-size: 12px;
  color: var(--el-text-color-placeholder);
}

.panel-title {
  margin: 0 0 14px;
  font-size: 15px;
}

.trend {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.trend-row {
  display: grid;
  grid-template-columns: 52px minmax(160px, 1fr) 70px 90px 180px;
  align-items: center;
  gap: 10px;
  font-size: 13px;
}

.trend-date {
  color: var(--el-text-color-secondary);
}

.trend-bar-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
}

.trend-bar {
  height: 14px;
  border-radius: 4px;
  background: var(--el-color-primary-light-5);
}

.trend-error {
  font-size: 12px;
  color: var(--el-color-danger);
  white-space: nowrap;
}

.trend-value {
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.trend-meta {
  color: var(--el-text-color-secondary);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.footnote {
  margin-top: 12px;
  font-size: 12px;
  line-height: 1.7;
}

@media (max-width: 900px) {
  .trend-row {
    grid-template-columns: 44px minmax(100px, 1fr) 60px;
  }

  .trend-meta {
    display: none;
  }
}
</style>
