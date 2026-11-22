<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'

import { getDashboard } from '@/api/admin'
import type { DashboardSummary } from '@/api/types'

const router = useRouter()
const loading = ref(false)
const days = ref(7)
const data = ref<DashboardSummary | null>(null)

const eventLabels: Record<string, string> = {
  page_view: '页面浏览',
  gallery_change: '切图',
  gallery_auto_state: '轮播暂停/恢复',
  meal_impression: '饭帖曝光',
  meal_open: '饭帖打开',
  recipe_open: '菜谱打开',
  login_open: '登录入口',
  verification_requested: '请求验证码',
  login_result: '登录结果',
  pending_action_resumed: '登录后续办',
  like_result: '点赞结果',
  favorite_result: '收藏结果',
  publish_start: '开始发布',
  source_change: '切换来源',
  publish_result: '发布结果',
  ai_open: '打开 AI',
  ai_hint_impression: 'AI 提示曝光',
  ai_hint_action: 'AI 提示点击',
  ai_message_result: 'AI 回复结果',
  ai_recommendation_open: 'AI 推荐打开',
  nearby_result: '附近结果',
  client_error: '客户端异常',
}

const maxTrend = computed(() => {
  const values = data.value?.trend.map((item) => item.events) || []
  return Math.max(1, ...values)
})

const topEvents = computed(() => {
  const byName = data.value?.events.byName || {}
  return Object.entries(byName)
    .map(([name, count]) => ({
      name,
      label: eventLabels[name] || name,
      count,
    }))
    .sort((a, b) => b.count - a.count)
    .slice(0, 8)
})

const cards = computed(() => {
  if (!data.value) return []
  return [
    { label: '注册用户', value: data.value.users.total, hint: `近 ${days.value} 天新增 ${data.value.users.newInRange}` },
    { label: '饭帖总数', value: data.value.posts.total, hint: `今日公开 ${data.value.posts.publishedToday}` },
    { label: '待审核', value: data.value.posts.pending, hint: '点击进入审核列表', path: '/posts' },
    { label: '已公开', value: data.value.posts.published, hint: '当前公开内容' },
    { label: '埋点事件', value: data.value.events.total, hint: `近 ${days.value} 天接收` },
  ]
})

async function load() {
  loading.value = true
  try {
    data.value = await getDashboard(days.value)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '加载看板失败')
  } finally {
    loading.value = false
  }
}

function changeDays(value: number) {
  days.value = value
  load()
}

onMounted(load)
</script>

<template>
  <div class="page" v-loading="loading">
    <header class="page-head">
      <div>
        <h1 class="page-title">数据看板</h1>
        <p class="page-subtitle">
          数字来自业务表与客户端埋点，不使用演示数据。趋势按服务端接收时间统计。
        </p>
      </div>
      <div class="head-actions">
        <el-radio-group
          :model-value="days"
          @change="(value: string | number | boolean) => changeDays(Number(value))"
        >
          <el-radio-button :value="7">近 7 天</el-radio-button>
          <el-radio-button :value="14">近 14 天</el-radio-button>
          <el-radio-button :value="30">近 30 天</el-radio-button>
        </el-radio-group>
        <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
      </div>
    </header>

    <section class="metric-grid">
      <div
        v-for="card in cards"
        :key="card.label"
        class="metric"
        :class="{ 'metric--link': card.path }"
        @click="card.path && router.push(card.path)"
      >
        <div class="metric__label">{{ card.label }}</div>
        <div class="metric__value">{{ card.value }}</div>
        <div class="metric__hint">{{ card.hint }}</div>
      </div>
    </section>

    <section class="panel">
      <div class="panel-head">
        <h2 class="panel-title">埋点趋势</h2>
        <span class="muted">单位：条</span>
      </div>
      <div v-if="data && data.trend.length" class="bars">
        <div v-for="item in data.trend" :key="item.date" class="bar-column">
          <span class="bar-value">{{ item.events }}</span>
          <div class="bar-track">
            <div
              class="bar-fill"
              :style="{ height: `${Math.max(4, (item.events / maxTrend) * 100)}%` }"
            />
          </div>
          <span class="bar-date">{{ item.date.slice(5) }}</span>
        </div>
      </div>
      <el-empty v-else description="暂无埋点数据" />
    </section>

    <section class="two-columns">
      <div class="panel">
        <div class="panel-head">
          <h2 class="panel-title">事件分布</h2>
          <span class="muted">近 {{ days }} 天</span>
        </div>
        <div v-if="topEvents.length" class="event-list">
          <div v-for="item in topEvents" :key="item.name" class="event-row">
            <span class="event-row__label">{{ item.label }}</span>
            <div class="event-row__bar">
              <div
                class="event-row__fill"
                :style="{ width: `${(item.count / topEvents[0].count) * 100}%` }"
              />
            </div>
            <span class="event-row__count mono">{{ item.count }}</span>
          </div>
        </div>
        <el-empty v-else description="暂无事件" />
      </div>

      <div class="panel">
        <div class="panel-head">
          <h2 class="panel-title">内容健康度</h2>
        </div>
        <el-descriptions v-if="data" :column="1" border size="small">
          <el-descriptions-item label="待审核饭帖">
            {{ data.posts.pending }}
          </el-descriptions-item>
          <el-descriptions-item label="已公开饭帖">
            {{ data.posts.published }}
          </el-descriptions-item>
          <el-descriptions-item label="今日新公开">
            {{ data.posts.publishedToday }}
          </el-descriptions-item>
          <el-descriptions-item label="统计范围">
            近 {{ data.rangeDays }} 天
          </el-descriptions-item>
        </el-descriptions>
        <p class="note">
          埋点只用于分析浏览与操作路径，不代表实际购买、实际吃过或真实饮食偏好。
        </p>
      </div>
    </section>
  </div>
</template>

<style scoped>
.head-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 12px;
}

.metric {
  padding: 18px;
  border: 1px solid var(--admin-line);
  border-radius: 12px;
  background: var(--admin-surface);
}

.metric--link {
  cursor: pointer;
  border-color: #f0c8bf;
  background: #fff8f6;
}

.metric__label {
  color: var(--admin-muted);
  font-size: 12px;
}

.metric__value {
  margin-top: 8px;
  font-size: 28px;
  font-weight: 700;
  line-height: 1.1;
}

.metric__hint {
  margin-top: 8px;
  color: #9aa0a8;
  font-size: 11px;
}

.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}

.panel-title {
  margin: 0;
  font-size: 15px;
  font-weight: 650;
}

.bars {
  display: flex;
  align-items: flex-end;
  gap: 10px;
  height: 220px;
  padding-top: 8px;
}

.bar-column {
  display: flex;
  flex: 1;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  height: 100%;
}

.bar-value {
  color: var(--admin-muted);
  font-size: 11px;
}

.bar-track {
  display: flex;
  align-items: flex-end;
  width: 100%;
  max-width: 36px;
  height: 100%;
  border-radius: 6px;
  background: #f3f4f6;
}

.bar-fill {
  width: 100%;
  border-radius: 6px;
  background: linear-gradient(180deg, #e5694c, #b33226);
  transition: height 0.3s ease;
}

.bar-date {
  color: #9aa0a8;
  font-size: 11px;
}

.two-columns {
  display: grid;
  grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr);
  gap: 16px;
}

.event-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.event-row {
  display: grid;
  grid-template-columns: 110px minmax(0, 1fr) 56px;
  align-items: center;
  gap: 10px;
  font-size: 12px;
}

.event-row__label {
  overflow: hidden;
  color: #374151;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.event-row__bar {
  overflow: hidden;
  height: 8px;
  border-radius: 999px;
  background: #f1f2f4;
}

.event-row__fill {
  height: 100%;
  border-radius: 999px;
  background: #cc462c;
}

.event-row__count {
  color: var(--admin-muted);
  text-align: right;
}

.note {
  margin: 14px 0 0;
  color: #8b9199;
  font-size: 12px;
  line-height: 1.7;
}

@media (max-width: 1200px) {
  .metric-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .two-columns {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 900px) {
  .metric-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
