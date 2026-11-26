<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowLeft, Refresh } from '@element-plus/icons-vue'

import { getAICallLog } from '@/api/admin'
import type { AICallLogDetail } from '@/api/types'
import { formatDateTime, type TagType } from '@/utils/format'

const route = useRoute()
const router = useRouter()

const loading = ref(false)
const detail = ref<AICallLogDetail | null>(null)

const CONTEXT_LABELS: Record<string, string> = {
  home: '首页',
  post: '饭帖详情',
  recipe_list: '菜谱列表',
  admin_test: '后台测试',
  kb_embedding: '知识库嵌入',
}

const STATUS_META: Record<string, { label: string; type: TagType }> = {
  success: { label: '成功', type: 'success' },
  failed: { label: '失败', type: 'danger' },
  info: { label: '信息', type: 'info' },
}

// 调试时毫秒很关键：调用间隔、首字延迟都靠它区分。
const preciseFormatter = new Intl.DateTimeFormat('zh-CN', {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
})

function formatPrecise(value?: string | null): string {
  if (!value) {
    return '-'
  }
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }
  const text = preciseFormatter.format(date).replace(/\//g, '-')
  return `${text}.${String(date.getMilliseconds()).padStart(3, '0')}`
}

function contextLabel(value: string) {
  return CONTEXT_LABELS[value] || value
}

function statusMeta(value: string) {
  return STATUS_META[value] || { label: value || '-', type: 'info' as TagType }
}

/**
 * 把所有步骤拼成一份连续文本。
 *
 * 为什么不继续用可折叠时间线：
 * 这个页面是给开发者调试用的，排查时需要一次性看到完整链路并复制到工单里；
 * 逐步展开会增加点击成本，也容易漏看失败步骤。这里默认全部展开，
 * 并在顶部保留概要，复制出去就是一份自包含的排查记录。
 */
const traceText = computed(() => {
  const log = detail.value
  if (!log) {
    return ''
  }
  const lines = [
    '==== MealMate 模型调用详情 ====',
    `调用编号：${log.id}`,
    `请求标识：${log.requestId || '-'}`,
    `调用时间：${formatPrecise(log.createdAt)}`,
    `场景：${contextLabel(log.contextType)}`,
    `供应商 / 模型：${log.providerName || '-'} / ${log.model || '-'}`,
    `状态：${statusMeta(log.status).label}`,
    `耗时：${log.latencyMs} ms`,
    `Token：输入 ${log.promptTokens} / 输出 ${log.completionTokens} / 合计 ${log.totalTokens}`,
    `调用者：${log.subjectRef || '-'}`,
  ]
  if (log.errorCode || log.errorMessage) {
    lines.push(`错误码：${log.errorCode || '-'}`)
    lines.push(`错误信息：${log.errorMessage || '-'}`)
  }
  lines.push('', `==== 执行过程（共 ${log.traces.length} 步）====`)
  if (!log.traces.length) {
    lines.push('', '（这条日志没有过程明细，可能产生于明细功能上线之前）')
    return lines.join('\n')
  }
  for (const step of log.traces) {
    lines.push('')
    lines.push(
      `[${step.seq}] ${formatPrecise(step.createdAt)} | ${step.title} | ` +
        `${statusMeta(step.status).label}` +
        (step.durationMs ? ` | ${step.durationMs} ms` : ''),
    )
    lines.push('-'.repeat(64))
    lines.push(step.detail || '（无详情）')
  }
  return lines.join('\n')
})

async function copyAll() {
  try {
    await navigator.clipboard.writeText(traceText.value)
    ElMessage.success('已复制完整执行日志')
  } catch {
    ElMessage.error('复制失败，请手动选择文本复制')
  }
}

async function load() {
  const logId = String(route.params.id || '')
  if (!logId) {
    return
  }
  loading.value = true
  // 切换记录时先清空旧数据，避免上一页的内容在加载失败时残留。
  detail.value = null
  try {
    detail.value = await getAICallLog(logId)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '加载调用详情失败')
  } finally {
    loading.value = false
  }
}

function back() {
  router.push('/ai-call-logs')
}

onMounted(load)
// 从同一列表连续打开不同记录时，组件会被复用，必须监听编号变化重新加载。
watch(() => route.params.id, load)
</script>

<template>
  <div class="page" v-loading="loading">
    <header class="page-head">
      <div class="head-left">
        <el-button :icon="ArrowLeft" circle title="返回调用日志" @click="back" />
        <div>
          <h1 class="page-title">模型调用详情</h1>
          <p class="page-subtitle">
            面向开发者的调试视图：包含函数调用链、HTTP 请求参数、完整提示词、供应商原始返回、
            解析与校验结果、流式分包统计、异常堆栈，以及工具、MCP、插件调用检查。
          </p>
        </div>
      </div>
      <el-button :icon="Refresh" @click="load">刷新</el-button>
    </header>

    <template v-if="detail">
      <div
        v-if="detail.status === 'failed'"
        class="review-banner review-banner--danger"
      >
        <strong>{{ detail.errorCode || '调用失败' }}</strong>
        <span>{{ detail.errorMessage || '没有记录错误信息' }}</span>
      </div>

      <section class="panel">
        <h3 class="drawer-section__title">调用概要</h3>
        <el-descriptions :column="3" border>
          <el-descriptions-item label="调用时间">
            {{ formatDateTime(detail.createdAt) }}
          </el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="statusMeta(detail.status).type" size="small">
              {{ statusMeta(detail.status).label }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="场景">
            {{ contextLabel(detail.contextType) }}
          </el-descriptions-item>
          <el-descriptions-item label="供应商">
            {{ detail.providerName || '-' }}
          </el-descriptions-item>
          <el-descriptions-item label="模型">
            <span class="mono">{{ detail.model || '-' }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="调用者">
            <span class="mono">{{ detail.subjectRef || '-' }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="耗时">
            {{ detail.latencyMs }} ms
          </el-descriptions-item>
          <el-descriptions-item label="Token">
            输入 {{ detail.promptTokens }} / 输出 {{ detail.completionTokens }} /
            合计 {{ detail.totalTokens }}
          </el-descriptions-item>
          <el-descriptions-item label="请求标识">
            <span class="mono">{{ detail.requestId || '-' }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="调用编号" :span="3">
            <span class="mono">{{ detail.id }}</span>
          </el-descriptions-item>
        </el-descriptions>
      </section>

      <section class="panel">
        <div class="trace-head">
          <h3 class="drawer-section__title">
            执行过程（共 {{ detail.traces.length }} 步，默认全部展开）
          </h3>
          <el-button
            v-if="detail.traces.length"
            size="small"
            @click="copyAll"
          >
            复制全部日志
          </el-button>
        </div>
        <pre class="json-block trace-full">{{ traceText }}</pre>
        <p class="footnote muted">
          单条明细最多保存 2 万字符，超出会标注“已截断”。工具、MCP、插件环节会单独列一步：
          未接入时会明确写“未触发”，避免误以为漏记。
        </p>
      </section>
    </template>

    <el-empty
      v-else-if="!loading"
      description="没有找到这条调用日志，可能已被清理"
    >
      <el-button @click="back">返回调用日志</el-button>
    </el-empty>
  </div>
</template>

<style scoped>
.head-left {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}

.trace-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.trace-head .drawer-section__title {
  margin-bottom: 0;
}

.trace-full {
  max-height: 70vh;
  margin: 0;
  font-size: 12px;
  line-height: 1.7;
}

.footnote {
  margin: 12px 0 0;
  font-size: 12px;
  line-height: 1.7;
}
</style>
