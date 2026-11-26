<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh } from '@element-plus/icons-vue'

import {
  deletePromptVariable,
  listPromptVariables,
  savePromptVariable,
} from '@/api/admin'
import type { PromptVariableItem } from '@/api/types'
import { useAdminStore } from '@/stores/admin'
import { formatDateTime } from '@/utils/format'

/**
 * 提示词变量管理。
 *
 * 共用变量所有提示词都能引用；专属变量绑定单个提示词。
 * 这里只维护 Key / Value / 默认值，提示词正文里用 {{key}} 引用。
 */
const store = useAdminStore()
const canWrite = computed(() => store.hasPermission('ai.config.write'))

const loading = ref(false)
const saving = ref(false)
const items = ref<PromptVariableItem[]>([])
const prompts = ref<Array<{ name: string; title: string }>>([])
const filter = ref('all')

const visible = ref(false)
const editingId = ref('')
const form = reactive({
  scope: 'shared' as 'shared' | 'prompt',
  promptName: '',
  key: '',
  value: '',
  defaultValue: '',
})

const filtered = computed(() => {
  if (filter.value === 'shared') {
    return items.value.filter((item) => item.scope === 'shared')
  }
  if (filter.value === 'prompt') {
    return items.value.filter((item) => item.scope === 'prompt')
  }
  if (filter.value.startsWith('prompt:')) {
    const name = filter.value.slice('prompt:'.length)
    return items.value.filter(
      (item) =>
        item.scope === 'shared' ||
        (item.scope === 'prompt' && item.promptName === name),
    )
  }
  return items.value
})

function promptTitle(name: string | null) {
  if (!name) {
    return '—'
  }
  return prompts.value.find((item) => item.name === name)?.title || name
}

async function load() {
  loading.value = true
  try {
    const data = await listPromptVariables()
    items.value = data.items
    prompts.value = data.prompts
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '加载变量失败')
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editingId.value = ''
  form.scope = filter.value.startsWith('prompt:') ? 'prompt' : 'shared'
  form.promptName = filter.value.startsWith('prompt:')
    ? filter.value.slice('prompt:'.length)
    : prompts.value[0]?.name || ''
  form.key = ''
  form.value = ''
  form.defaultValue = ''
  visible.value = true
}

function openEdit(item: PromptVariableItem) {
  editingId.value = item.id
  form.scope = item.scope
  form.promptName = item.promptName || prompts.value[0]?.name || ''
  form.key = item.key
  form.value = item.value
  form.defaultValue = item.defaultValue || ''
  visible.value = true
}

async function submit() {
  if (!form.key.trim()) {
    ElMessage.warning('请填写变量 Key')
    return
  }
  if (form.scope === 'prompt' && !form.promptName) {
    ElMessage.warning('请选择专属变量绑定的提示词')
    return
  }
  saving.value = true
  try {
    await savePromptVariable({
      scope: form.scope,
      promptName: form.scope === 'prompt' ? form.promptName : null,
      key: form.key.trim(),
      value: form.value,
      defaultValue: form.defaultValue.trim() || null,
    })
    ElMessage.success(
      form.scope === 'shared'
        ? '共用变量已保存，所有提示词立即生效'
        : '专属变量已保存为草稿，发布对应提示词后生效',
    )
    visible.value = false
    await load()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '保存失败')
  } finally {
    saving.value = false
  }
}

async function remove(item: PromptVariableItem) {
  try {
    await ElMessageBox.confirm(
      item.scope === 'shared'
        ? `删除共用变量 ${item.key} 后，所有提示词都无法再引用它。确认删除？`
        : `删除 ${promptTitle(item.promptName)} 的专属变量 ${item.key}？`,
      '删除变量',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await deletePromptVariable(item.id)
    ElMessage.success('变量已删除')
    await load()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '删除失败')
  }
}

onMounted(load)
</script>

<template>
  <div class="page" v-loading="loading">
    <header class="page-head">
      <div>
        <h1 class="page-title">变量管理</h1>
        <p class="page-subtitle">
          维护提示词里 <code v-text="'{{key}}'"></code> 形式的变量。共用变量所有提示词都能引用；
          专属变量只属于一个提示词，并跟随它发布和回滚。
        </p>
      </div>
      <div class="head-actions">
        <el-button :icon="Refresh" @click="load">刷新</el-button>
        <el-button
          v-if="canWrite"
          type="primary"
          :icon="Plus"
          @click="openCreate"
        >
          新增变量
        </el-button>
      </div>
    </header>

    <div class="filter-bar">
      <el-radio-group v-model="filter">
        <el-radio-button value="all">全部</el-radio-button>
        <el-radio-button value="shared">共用变量</el-radio-button>
        <el-radio-button value="prompt">全部专属变量</el-radio-button>
        <el-radio-button
          v-for="prompt in prompts"
          :key="prompt.name"
          :value="`prompt:${prompt.name}`"
        >
          {{ prompt.title }}
        </el-radio-button>
      </el-radio-group>
    </div>

    <el-alert
      v-if="!canWrite"
      type="info"
      show-icon
      :closable="false"
      title="当前账号只有查看权限，不能新增或修改变量"
    />

    <el-table :data="filtered" border stripe>
      <el-table-column prop="key" label="Key" min-width="150">
        <template #default="{ row }">
          <code class="mono">{{ row.key }}</code>
        </template>
      </el-table-column>
      <el-table-column label="类型" width="120">
        <template #default="{ row }">
          <el-tag :type="row.scope === 'shared' ? 'success' : 'warning'" size="small">
            {{ row.scope === 'shared' ? '共用' : '专属' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="绑定提示词" min-width="180">
        <template #default="{ row }">
          {{ row.scope === 'shared' ? '所有提示词' : promptTitle(row.promptName) }}
        </template>
      </el-table-column>
      <el-table-column label="值" min-width="190">
        <template #default="{ row }">
          <span class="value-text">{{ row.value || '（空）' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="默认值" min-width="120">
        <template #default="{ row }">
          {{ row.defaultValue || '—' }}
        </template>
      </el-table-column>
      <el-table-column label="被引用" min-width="180">
        <template #default="{ row }">
          <template v-if="row.usedBy.length">
            <el-tag
              v-for="name in row.usedBy"
              :key="name"
              size="small"
              effect="plain"
              class="used-tag"
            >
              {{ promptTitle(name) }}
            </el-tag>
          </template>
          <span v-else class="muted">暂无线上引用</span>
        </template>
      </el-table-column>
      <el-table-column label="更新" width="190">
        <template #default="{ row }">
          <div class="muted update-cell">
            <span>{{ row.updatedBy || '—' }}</span>
            <span>{{ row.updatedAt ? formatDateTime(row.updatedAt) : '—' }}</span>
          </div>
        </template>
      </el-table-column>
      <el-table-column v-if="canWrite" label="操作" width="140" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="openEdit(row)">编辑</el-button>
          <el-button size="small" type="danger" plain @click="remove(row)">
            删除
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog
      v-model="visible"
      :title="editingId ? '编辑变量' : '新增变量'"
      width="520px"
      destroy-on-close
    >
      <el-form label-position="top">
        <el-form-item label="变量类型">
          <el-radio-group v-model="form.scope" :disabled="Boolean(editingId)">
            <el-radio value="shared">共用变量（所有提示词可用）</el-radio>
            <el-radio value="prompt">专属变量（绑定单个提示词）</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="form.scope === 'prompt'" label="绑定提示词">
          <el-select v-model="form.promptName" :disabled="Boolean(editingId)">
            <el-option
              v-for="prompt in prompts"
              :key="prompt.name"
              :label="prompt.title"
              :value="prompt.name"
            />
          </el-select>
          <p class="muted hint">
            专属变量保存为草稿，需要在「提示词管理」重新发布后才影响线上，并随版本回滚。
          </p>
        </el-form-item>
        <el-form-item label="Key">
          <el-input
            v-model="form.key"
            :disabled="Boolean(editingId)"
            placeholder="例如 max_recipes"
            maxlength="80"
          />
          <p class="muted hint">
            正文里用 <code v-text="'{{' + (form.key || 'key') + '}}'"></code> 引用；
            同名 Key 优先取专属值，其次共用值，最后默认值。
          </p>
        </el-form-item>
        <el-form-item label="值">
          <el-input v-model="form.value" type="textarea" :rows="3" maxlength="20000" />
        </el-form-item>
        <el-form-item label="默认值（可选）">
          <el-input
            v-model="form.defaultValue"
            maxlength="20000"
            placeholder="专属值和共用值都为空时使用"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="visible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submit">保存</el-button>
      </template>
    </el-dialog>
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
  gap: 8px;
}

.filter-bar {
  margin: 16px 0;
}

.used-tag {
  margin-right: 6px;
  margin-bottom: 4px;
}

.value-text {
  white-space: pre-wrap;
  word-break: break-word;
}

.update-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 12px;
}

.hint {
  margin: 6px 0 0;
  font-size: 12px;
}
</style>
