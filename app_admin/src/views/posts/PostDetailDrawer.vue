<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import { getPost } from '@/api/admin'
import type { AdminPost } from '@/api/types'
import {
  formatDateTime,
  POST_STATUS_META,
  SOURCE_LABELS,
} from '@/utils/format'

const props = defineProps<{
  modelValue: boolean
  postId: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
}>()

const loading = ref(false)
const post = ref<AdminPost | null>(null)

const visible = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value),
})

const statusMeta = computed(() => {
  const status = post.value?.status || ''
  return (
    POST_STATUS_META[status] || {
      label: status || '-',
      type: 'info' as const,
      hint: '',
    }
  )
})

const bannerClass = computed(() => {
  if (post.value?.status === 'published') {
    return 'review-banner--success'
  }
  if (post.value?.status === 'rejected') {
    return 'review-banner--danger'
  }
  return 'review-banner--muted'
})

const sourceLabel = computed(() =>
  post.value ? SOURCE_LABELS[post.value.source] || post.value.source : '-',
)

const locationText = computed(() => {
  if (!post.value) {
    return '-'
  }
  if (post.value.coarseArea) {
    return post.value.coarseArea
  }
  if (post.value.coarseLat != null && post.value.coarseLng != null) {
    return `${post.value.coarseLat}, ${post.value.coarseLng}`
  }
  return '未公开定位'
})

async function load() {
  if (!props.postId) {
    return
  }
  loading.value = true
  try {
    post.value = await getPost(props.postId)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '加载详情失败')
  } finally {
    loading.value = false
  }
}

watch(
  () => [props.modelValue, props.postId] as const,
  ([open, postId]) => {
    if (open && postId) {
      load()
    }
  },
  { immediate: true },
)
</script>

<template>
  <el-drawer v-model="visible" title="饭帖详情" size="600px" destroy-on-close>
    <div v-loading="loading" class="detail">
      <template v-if="post">
        <div class="review-banner" :class="bannerClass">
          <strong>{{ statusMeta.label }}</strong>
          <span>{{ statusMeta.hint }}</span>
        </div>

        <div v-if="post.reviewReason" class="drawer-section">
          <div class="reason-box">
            <span class="reason-box__label">审核原因</span>
            <span>{{ post.reviewReason }}</span>
          </div>
        </div>

        <div class="drawer-section">
          <h3 class="drawer-section__title">内容</h3>
          <h2 class="detail__title">{{ post.title }}</h2>
          <p class="detail__review">{{ post.review }}</p>

          <div v-if="post.images.length" class="detail-images detail-images--gap">
            <el-image
              v-for="image in post.images"
              :key="image"
              :src="image"
              :preview-src-list="post.images"
              fit="cover"
              preview-teleported
            />
          </div>
        </div>

        <div class="drawer-section">
          <h3 class="drawer-section__title">基础信息</h3>
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="作者">
              {{ post.author?.nickname || '-' }}
            </el-descriptions-item>
            <el-descriptions-item label="作者手机号">
              {{ post.authorPhoneMasked || '-' }}
            </el-descriptions-item>
            <el-descriptions-item label="来源">
              {{ sourceLabel }}
            </el-descriptions-item>
            <el-descriptions-item label="提交时间">
              {{ formatDateTime(post.createdAt) }}
            </el-descriptions-item>
            <el-descriptions-item label="公开时间">
              {{ formatDateTime(post.publishedAt) }}
            </el-descriptions-item>
            <el-descriptions-item label="定位">
              {{ locationText }}
            </el-descriptions-item>
            <el-descriptions-item label="外卖店家">
              {{ post.takeawayStore || '-' }}
            </el-descriptions-item>
            <el-descriptions-item label="到店地址">
              {{ post.dineInAddress || '-' }}
            </el-descriptions-item>
            <el-descriptions-item label="平台菜谱">
              {{ post.platformRecipeTitle || post.platformRecipeId || '-' }}
            </el-descriptions-item>
            <el-descriptions-item label="客户端请求标识">
              <span class="mono">{{ post.clientRequestId || '-' }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="饭帖标识" :span="2">
              <span class="mono">{{ post.id }}</span>
            </el-descriptions-item>
          </el-descriptions>
        </div>

        <div v-if="post.authorRecipe" class="drawer-section">
          <h3 class="drawer-section__title">作者做法</h3>
          <p class="json-title">食材</p>
          <div class="ingredient-tags">
            <el-tag
              v-for="ingredient in post.authorRecipe.ingredients"
              :key="ingredient"
              effect="plain"
              type="info"
            >
              {{ ingredient }}
            </el-tag>
          </div>
          <p class="json-title detail__steps-title">步骤</p>
          <ol class="recipe-steps">
            <li v-for="(step, index) in post.authorRecipe.steps" :key="index">
              {{ step }}
            </li>
          </ol>
        </div>

        <div class="drawer-section">
          <h3 class="drawer-section__title">审核记录</h3>
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="审核人">
              {{ post.reviewedByName || '-' }}
            </el-descriptions-item>
            <el-descriptions-item label="审核时间">
              {{ formatDateTime(post.reviewedAt) }}
            </el-descriptions-item>
            <el-descriptions-item label="审核原因" :span="2">
              {{ post.reviewReason || '-' }}
            </el-descriptions-item>
          </el-descriptions>
        </div>
      </template>
    </div>
  </el-drawer>
</template>

<style scoped>
.detail {
  min-height: 240px;
}

.detail__title {
  margin: 0 0 10px;
  font-size: 20px;
  line-height: 1.4;
}

.detail__review {
  margin: 0;
  color: #4b5563;
  font-size: 13px;
  line-height: 1.9;
  white-space: pre-wrap;
}

.detail-images--gap {
  margin-top: 16px;
}

.detail__steps-title {
  margin-top: 18px;
}

.reason-box {
  display: flex;
  gap: 12px;
  padding: 12px 14px;
  border: 1px solid #f2d7d2;
  border-radius: 10px;
  background: #fdf6f4;
  color: #7a2b22;
  font-size: 13px;
  line-height: 1.7;
}

.reason-box__label {
  flex: none;
  color: #a35a4f;
  font-weight: 600;
}
</style>
