<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowLeft, Refresh } from '@element-plus/icons-vue'

import { getAICallLog, scoreAICallLog } from '@/api/admin'
import type { AICallLogDetail } from '@/api/types'
import { useAdminStore } from '@/stores/admin'
import { formatDateTime, type TagType } from '@/utils/format'

const route = useRoute()
const router = useRouter()
const store = useAdminStore()

const loading = ref(false)
const detail = ref<AICallLogDetail | null>(null)
const scoring = ref(false)
const scoreForm = reactive({ score: 5, comment: '' })
// 评分属于“评测写入”，与查看日志分开授权：运营可以打分，但改不了模型配置。
const canScore = computed(() => store.hasPermission('ai.eval.write'))

const CONTEXT_LABELS: Record<string, string> = {
  home: '首页',
  post: '饭帖详情',
  recipe_list: '菜谱列表',
  admin_test: '后台测试',
  kb_embedding: '知识库嵌入',
  history_compress: '历史压缩',
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

// 提示词来源决定排查方向：本地改过就看后台，代码默认值就要发版本。
const PROMPT_SOURCE_LABELS: Record<string, string> = {
  local: '本地数据库',
  langfuse: 'Langfuse',
  default: '代码默认值',
}

function promptSourceLabel(value?: string | null) {
  if (!value) {
    return '-'
  }
  return PROMPT_SOURCE_LABELS[value] || value
}

// 精确到 6 位小数：单次调用可能只有 0.0001 美元，四舍五入过早会全显示成 0。
function formatCost(value?: number | null) {
  return `$${(value ?? 0).toFixed(6)}`
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
    `成本：${formatCost(log.costUsd)}（按调用时单价固定，后续调价不改写历史）`,
    `提示词：${log.promptName || '-'} / v${log.promptVersion ?? '-'} / 来源 ${promptSourceLabel(log.promptSource)}`,
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

/**
 * 提交人工评分。
 *
 * 评分先保存在本地数据库，再尽力同步到 Langfuse。
 * 所以即使 Langfuse 未配置或网络失败，这里也会返回成功，
 * 列表里用“已同步 / 未同步”标签区分，便于以后补推。
 */
async function submitScore() {
  const log = detail.value
  if (!log) {
    return
  }
  scoring.value = true
  try {
    const item = await scoreAICallLog(log.id, {
      score: scoreForm.score,
      comment: scoreForm.comment.trim() || undefined,
    })
    log.scores.unshift(item)
    scoreForm.comment = ''
    ElMessage.success(
      item.langfuseSynced ? '评分已保存并同步到 Langfuse' : '评分已保存（Langfuse 未同步）',
    )
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '评分失败')
  } finally {
    scoring.value = false
  }
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
          <el-descriptions-item label="提示词版本">
            <template v-if="detail.promptName">
              <span class="mono">{{ detail.promptName }}</span>
              <el-tag size="small" effect="plain" class="prompt-tag">
                v{{ detail.promptVersion ?? '-' }}
              </el-tag>
              <el-tag size="small" type="info" effect="plain">
                {{ promptSourceLabel(detail.promptSource) }}
              </el-tag>
            </template>
            <span v-else class="muted">未记录（功能上线前的日志）</span>
          </el-descriptions-item>
          <el-descriptions-item label="成本">
            {{ formatCost(detail.costUsd) }}
          </el-descriptions-item>
          <el-descriptions-item label="调用编号">
            <span class="mono">{{ detail.id }}</span>
          </el-descriptions-item>
        </el-descriptions>
      </section>

      <section class="panel">
        <h3 class="drawer-section__title">人工评测</h3>
        <div v-if="detail.scores.length" class="score-list">
          <div v-for="item in detail.scores" :key="item.id" class="score-item">
            <el-rate :model-value="item.score" disabled show-score />
            <el-tag
              :type="item.langfuseSynced ? 'success' : 'info'"
              size="small"
              effect="plain"
            >
              {{ item.langfuseSynced ? '已同步 Langfuse' : '未同步 Langfuse' }}
            </el-tag>
            <span class="muted score-meta">
              {{ item.scorerName }} · {{ formatDateTime(item.createdAt) }}
            </span>
            <p v-if="item.comment" class="score-comment">{{ item.comment }}</p>
          </div>
        </div>
        <p v-else class="muted">还没有评分。评分用于对比不同提示词版本的回答质量。</p>

        <div v-if="canScore" class="score-form">
          <el-rate v-model="scoreForm.score" show-text :texts="['很差', '较差', '一般', '不错', '很好']" />
          <el-input
            v-model="scoreForm.comment"
            type="textarea"
            :rows="2"
            maxlength="500"
            show-word-limit
            placeholder="可选：为什么给这个分，例如“推荐菜谱正确但回答太长”"
          />
          <el-button type="primary" :loading="scoring" @click="submitScore">
            提交评分
          </el-button>
        </div>
        <p v-else class="muted">当前账号没有评测写入权限，只能查看已有评分。</p>
        <p class="footnote muted">
          评分先写入本地数据库，再尽力同步 Langfuse。Langfuse 未配置或网络失败时，
          评分仍然保留，标签会显示“未同步”。
        </p>
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

.score-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-bottom: 16px;
}

.score-item {
  padding: 10px 12px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: var(--el-fill-color-lighter);
}

.score-meta {
  margin-left: 10px;
  font-size: 12px;
}

.score-comment {
  margin: 6px 0 0;
  font-size: 13px;
  line-height: 1.6;
}

.score-form {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 10px;
  max-width: 560px;
}

.prompt-tag {
  margin: 0 0 0 6px;
}
</style>
