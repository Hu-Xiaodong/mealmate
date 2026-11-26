<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh } from '@element-plus/icons-vue'

import {
  listPromptVariables,
  listPromptVersions,
  listPrompts,
  previewPrompt,
  publishPrompt,
  rollbackPrompt,
} from '@/api/admin'
import type {
  LangfusePromptItem,
  LangfusePromptVersion,
  PromptPreviewResult,
  PromptVariableInput,
  PromptVariableItem,
} from '@/api/types'
import { useAdminStore } from '@/stores/admin'
import { formatDateTime } from '@/utils/format'

/**
 * 提示词版本管理（本地数据库为准）。
 *
 * 发布、读取、回滚都不依赖 Langfuse；
 * 配置 Langfuse 后，发布成功会额外镜像一份，失败不影响本地版本。
 * 变量解析在后端完成，预览和真实发送使用同一套逻辑。
 */
const store = useAdminStore()
const loading = ref(false)
const configured = ref(false)
const warning = ref('')
const items = ref<LangfusePromptItem[]>([])
const sharedVariables = ref<PromptVariableItem[]>([])
const canPublish = computed(() => store.hasPermission('ai.config.write'))

const editVisible = ref(false)
const publishing = ref(false)
const editForm = reactive({
  name: '',
  title: '',
  content: '',
  commitMessage: '',
  variables: [] as PromptVariableInput[],
})

const previewVisible = ref(false)
const previewLoading = ref(false)
const previewResult = ref<PromptPreviewResult | null>(null)

const versionVisible = ref(false)
const versionLoading = ref(false)
const versions = ref<LangfusePromptVersion[]>([])
const versionTitle = ref('')
const versionPromptName = ref('')

/** 可插入正文的变量：共用变量 + 当前编辑中的专属变量，同名时专属覆盖共用。 */
const insertableVariables = computed(() => {
  const map = new Map<string, { key: string; scope: string; value: string }>()
  for (const item of sharedVariables.value) {
    map.set(item.key, { key: item.key, scope: '共用', value: item.value })
  }
  for (const item of editForm.variables) {
    const key = item.key.trim()
    if (key) {
      map.set(key, { key, scope: '专属', value: item.value })
    }
  }
  return [...map.values()]
})

async function load() {
  loading.value = true
  try {
    const data = await listPrompts()
    configured.value = data.configured
    warning.value = data.warning
    items.value = data.items
    try {
      const variables = await listPromptVariables()
      sharedVariables.value = variables.items.filter(
        (item) => item.scope === 'shared',
      )
    } catch (error) {
      ElMessage.warning(
        error instanceof Error ? error.message : '加载共用变量失败，变量插入可能不完整',
      )
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '加载提示词失败')
  } finally {
    loading.value = false
  }
}

function openEdit(item: LangfusePromptItem) {
  editForm.name = item.name
  editForm.title = item.title
  editForm.content = item.content
  editForm.commitMessage = ''
  editForm.variables = (item.variables || []).map((variable) => ({ ...variable }))
  editVisible.value = true
}

function addVariable() {
  editForm.variables.push({ key: '', value: '', defaultValue: '' })
}

function removeVariable(index: number) {
  editForm.variables.splice(index, 1)
}

function insertVariable(key: string) {
  if (!key) {
    return
  }
  const token = `{{${key}}}`
  const content = editForm.content
  if (!content) {
    editForm.content = token
    return
  }
  const separator = content.endsWith('\n') || content.endsWith(' ') ? '' : ' '
  editForm.content = `${content}${separator}${token}`
}

async function openPreview() {
  previewVisible.value = true
  previewLoading.value = true
  previewResult.value = null
  try {
    previewResult.value = await previewPrompt(editForm.name, {
      content: editForm.content,
      variables: editForm.variables.filter((item) => item.key.trim()),
    })
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '预览失败')
  } finally {
    previewLoading.value = false
  }
}

async function submitPublish() {
  if (!editForm.content.trim()) {
    ElMessage.warning('提示词内容不能为空')
    return
  }
  if (editForm.variables.some((item) => !item.key.trim())) {
    ElMessage.warning('专属变量存在空 Key，请填写或删除该行')
    return
  }
  publishing.value = true
  try {
    const result = await publishPrompt(editForm.name, {
      content: editForm.content,
      commitMessage: editForm.commitMessage.trim() || undefined,
      variables: editForm.variables.filter((item) => item.key.trim()),
    })
    const mirror = result.langfuseConfigured
      ? result.langfuseVersion
        ? `，已镜像到 Langfuse v${result.langfuseVersion}`
        : '，Langfuse 镜像失败（本地已生效）'
      : '，未配置 Langfuse，仅本地生效'
    ElMessage.success(
      result.version
        ? `已发布本地 v${result.version}${mirror}`
        : `已发布新版本${mirror}`,
    )
    editVisible.value = false
    await load()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '发布失败')
  } finally {
    publishing.value = false
  }
}

async function openVersions(item: LangfusePromptItem) {
  versionTitle.value = item.title
  versionPromptName.value = item.name
  versionVisible.value = true
  versionLoading.value = true
  versions.value = []
  try {
    versions.value = (await listPromptVersions(item.name)).items
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '加载版本历史失败')
  } finally {
    versionLoading.value = false
  }
}

async function rollbackVersion(item: LangfusePromptVersion) {
  try {
    await ElMessageBox.confirm(
      `回滚会把 v${item.version} 的正文和专属变量恢复，并发布成一个新版本，不会删除历史。确认继续？`,
      '回滚提示词',
      { type: 'warning', confirmButtonText: '回滚', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    const result = await rollbackPrompt(versionPromptName.value, {
      version: item.version,
    })
    ElMessage.success(
      result.version
        ? `已回滚到 v${item.version}，并发布为 v${result.version}`
        : '已回滚',
    )
    versionVisible.value = false
    await load()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '回滚失败')
  }
}

function sourceLabel(source: string) {
  if (source === 'local') {
    return '本地线上版本'
  }
  if (source === 'langfuse') {
    return 'Langfuse 版本'
  }
  return '代码默认值'
}

function variableSourceLabel(source: string) {
  return (
    {
      prompt: '专属值',
      shared: '共用值',
      prompt_default: '专属默认值',
      shared_default: '共用默认值',
    }[source] || source
  )
}

onMounted(load)
</script>

<template>
  <div class="page" v-loading="loading">
    <header class="page-head">
      <div>
        <h1 class="page-title">提示词管理</h1>
        <p class="page-subtitle">
          管理 AI 对话与历史压缩使用的提示词。发布后生成新版本，
          production 标签指向线上版本；正文可用
          <code v-text="'{{key}}'"></code> 引用变量。
        </p>
      </div>
      <el-button :icon="Refresh" @click="load">刷新</el-button>
    </header>

    <el-alert
      v-if="!configured"
      type="info"
      show-icon
      :closable="false"
      title="Langfuse 未配置，提示词只保存在本地数据库"
    >
      <p>
        发布、读取、回滚都正常可用；配置 Langfuse 后，新版本会额外镜像一份，
        方便在观测平台对比。未配置不会影响 AI 问答。
      </p>
    </el-alert>
    <el-alert
      v-else-if="warning"
      type="warning"
      show-icon
      :closable="false"
      title="提示词列表读取不完整"
      :description="warning"
    />

    <section class="prompt-list">
      <article v-for="item in items" :key="item.name" class="panel prompt-card">
        <div class="prompt-head">
          <div>
            <h3 class="prompt-title">{{ item.title }}</h3>
            <p class="prompt-desc">{{ item.description }}</p>
            <p class="prompt-name mono">{{ item.name }}</p>
          </div>
          <div class="prompt-actions">
            <el-tag size="small" effect="plain">{{ sourceLabel(item.source) }}</el-tag>
            <el-tag v-if="item.version" size="small" type="success">
              v{{ item.version }}
            </el-tag>
            <el-button size="small" @click="openVersions(item)">历史版本</el-button>
            <el-button
              v-if="canPublish"
              size="small"
              type="primary"
              @click="openEdit(item)"
            >
              编辑并发布
            </el-button>
          </div>
        </div>
        <el-alert
          v-if="item.missingKeys.length"
          type="warning"
          show-icon
          :closable="false"
          :title="`缺少变量：${item.missingKeys.join('、')}`"
        />
        <pre class="prompt-content">{{ item.preview || item.content }}</pre>
        <p class="muted prompt-meta">
          <span v-if="item.variables.length">
            专属变量 {{ item.variables.length }} 个
          </span>
          <span v-if="item.versions.length"> · 共 {{ item.versions.length }} 个本地版本</span>
          <span v-if="item.updatedAt"> · 最近更新 {{ formatDateTime(item.updatedAt) }}</span>
          <span v-if="item.langfuseVersion"> · 已镜像 Langfuse v{{ item.langfuseVersion }}</span>
          <span v-if="!canPublish"> · 当前账号没有发布权限</span>
        </p>
      </article>
    </section>

    <el-dialog
      v-model="editVisible"
      :title="`发布新版本：${editForm.title}`"
      width="920px"
      destroy-on-close
    >
      <el-form label-position="top">
        <el-form-item label="提示词正文">
          <el-input
            v-model="editForm.content"
            type="textarea"
            :rows="14"
            maxlength="20000"
            show-word-limit
          />
        </el-form-item>
        <el-form-item label="插入变量">
          <div v-if="insertableVariables.length" class="variable-tags">
            <el-button
              v-for="item in insertableVariables"
              :key="`${item.scope}-${item.key}`"
              size="small"
              @click="insertVariable(item.key)"
            >
              {{ item.key }}
              <el-tag size="small" effect="plain" class="tag-gap">
                {{ item.scope }}
              </el-tag>
            </el-button>
          </div>
          <span v-else class="muted">
            还没有可用变量，可在下方新增专属变量，或去「变量管理」新增共用变量。
          </span>
        </el-form-item>
        <el-form-item label="专属变量（只属于当前提示词，随发布和回滚）">
          <el-table :data="editForm.variables" size="small" border>
            <el-table-column label="Key" width="180">
              <template #default="{ row }">
                <el-input v-model="row.key" maxlength="80" placeholder="例如 tone" />
              </template>
            </el-table-column>
            <el-table-column label="值">
              <template #default="{ row }">
                <el-input v-model="row.value" maxlength="20000" />
              </template>
            </el-table-column>
            <el-table-column label="默认值（可选）" width="190">
              <template #default="{ row }">
                <el-input v-model="row.defaultValue" maxlength="20000" />
              </template>
            </el-table-column>
            <el-table-column label="操作" width="80">
              <template #default="{ $index }">
                <el-button
                  size="small"
                  type="danger"
                  plain
                  @click="removeVariable($index)"
                >
                  删除
                </el-button>
              </template>
            </el-table-column>
          </el-table>
          <el-button class="add-variable" :icon="Plus" size="small" @click="addVariable">
            新增专属变量
          </el-button>
        </el-form-item>
        <el-form-item label="变更说明（可选）">
          <el-input
            v-model="editForm.commitMessage"
            maxlength="200"
            placeholder="例如：把推荐数量改成可配置变量"
          />
        </el-form-item>
      </el-form>
      <p class="muted">
        发布后会创建新版本，旧版本保留；production 标签会指向新版本。
        专属变量会随版本一起保存，回滚时一并恢复。
      </p>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button :loading="previewLoading" @click="openPreview">预览替换结果</el-button>
        <el-button type="primary" :loading="publishing" @click="submitPublish">
          发布
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="previewVisible"
      title="预览替换结果"
      width="760px"
      destroy-on-close
    >
      <div v-loading="previewLoading">
        <el-alert
          v-if="previewResult?.missingKeys.length"
          type="warning"
          show-icon
          :closable="false"
          :title="`缺少变量：${previewResult.missingKeys.join('、')}，发布会失败`"
        />
        <pre class="prompt-content preview-content">{{ previewResult?.content }}</pre>
        <p v-if="previewResult && Object.keys(previewResult.sources).length" class="muted">
          取值来源：
          <span v-for="(source, key) in previewResult.sources" :key="key" class="source-item">
            {{ key }} = {{ variableSourceLabel(source) }}
          </span>
        </p>
      </div>
    </el-dialog>

    <el-drawer
      v-model="versionVisible"
      :title="`历史版本：${versionTitle}`"
      size="720px"
    >
      <div v-loading="versionLoading">
        <template v-if="versions.length">
          <div v-for="item in versions" :key="item.version" class="version-item">
            <div class="version-head">
              <strong>v{{ item.version }}</strong>
              <el-tag
                v-for="label in item.labels"
                :key="label"
                size="small"
                :type="label === 'production' ? 'success' : 'info'"
              >
                {{ label }}
              </el-tag>
              <span class="muted">{{ formatDateTime(item.createdAt) }}</span>
              <span v-if="item.createdBy" class="muted">· {{ item.createdBy }}</span>
              <span v-if="item.langfuseVersion" class="muted">
                · Langfuse v{{ item.langfuseVersion }}
              </span>
              <el-button
                v-if="canPublish && !item.labels.includes('production')"
                size="small"
                class="rollback-button"
                @click="rollbackVersion(item)"
              >
                回滚到此版本
              </el-button>
            </div>
            <p v-if="item.commitMessage" class="version-note">
              变更说明：{{ item.commitMessage }}
            </p>
            <p v-if="item.variables?.length" class="version-note">
              专属变量：
              <code v-for="variable in item.variables" :key="variable.key" class="variable-chip">
                {{ variable.key }}={{ variable.value || variable.defaultValue || '空' }}
              </code>
            </p>
            <pre class="prompt-content version-content">{{ item.content }}</pre>
          </div>
        </template>
        <el-empty v-else description="暂无历史版本" :image-size="72" />
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.page-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.prompt-list {
  display: flex;
  flex-direction: column;
  gap: 14px;
  margin-top: 16px;
}

.prompt-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 10px;
}

.prompt-title {
  margin: 0 0 4px;
  font-size: 15px;
}

.prompt-desc,
.prompt-name {
  margin: 0;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.prompt-name {
  margin-top: 4px;
}

.prompt-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.prompt-content {
  max-height: 220px;
  margin: 0;
  padding: 12px;
  overflow: auto;
  font-size: 12px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
  background: var(--el-fill-color-lighter);
  border-radius: 8px;
}

.prompt-meta {
  margin: 10px 0 0;
  font-size: 12px;
}

.variable-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.tag-gap {
  margin-left: 6px;
}

.add-variable {
  margin-top: 8px;
}

.preview-content {
  max-height: 420px;
  margin-top: 12px;
}

.source-item {
  margin-right: 12px;
}

.version-item {
  padding-bottom: 14px;
  margin-bottom: 14px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.version-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}

.rollback-button {
  margin-left: auto;
}

.version-content {
  max-height: 300px;
}

.version-note {
  margin: 0 0 8px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.variable-chip {
  margin-right: 8px;
  padding: 1px 6px;
  background: var(--el-fill-color-lighter);
  border-radius: 4px;
}
</style>
