<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh } from '@element-plus/icons-vue'

import {
  createAIProvider,
  deleteAIProvider,
  listAIProviders,
  testAIProvider,
  updateAIProvider,
} from '@/api/admin'
import type { AIProviderForm, AIProviderItem } from '@/api/types'
import { formatDateTime } from '@/utils/format'

const loading = ref(false)
const saving = ref(false)
const testingId = ref('')
const items = ref<AIProviderItem[]>([])
const dialogVisible = ref(false)
const editingId = ref('')

function emptyForm(): AIProviderForm {
  return {
    name: '',
    providerType: 'openai_compatible',
    baseUrl: 'https://api.deepseek.com/v1',
    apiKey: '',
    model: 'deepseek-chat',
    enabled: true,
    priority: 100,
    timeoutSeconds: 20,
    maxOutputTokens: 800,
  }
}

const form = reactive<AIProviderForm>(emptyForm())

async function load() {
  loading.value = true
  try {
    items.value = (await listAIProviders()).items
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '加载模型配置失败')
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editingId.value = ''
  Object.assign(form, emptyForm())
  dialogVisible.value = true
}

function openEdit(item: AIProviderItem) {
  editingId.value = item.id
  Object.assign(form, {
    name: item.name,
    providerType: 'openai_compatible',
    baseUrl: item.baseUrl,
    // 编辑页不回填密钥：后端只保存密文，前端也没有必要接触明文。
    apiKey: '',
    model: item.model,
    enabled: item.enabled,
    priority: item.priority,
    timeoutSeconds: item.timeoutSeconds,
    maxOutputTokens: item.maxOutputTokens,
  })
  dialogVisible.value = true
}

function validate(): boolean {
  if (!form.name.trim() || !form.baseUrl.trim() || !form.model.trim()) {
    ElMessage.warning('请填写名称、接口地址和模型名')
    return false
  }
  if (!/^https?:\/\//.test(form.baseUrl.trim())) {
    ElMessage.warning('接口地址需要以 http:// 或 https:// 开头')
    return false
  }
  if (!editingId.value && !form.apiKey.trim()) {
    ElMessage.warning('首次新增必须填写 API Key')
    return false
  }
  return true
}

async function save() {
  if (!validate()) {
    return
  }
  saving.value = true
  try {
    const payload: Partial<AIProviderForm> = {
      name: form.name.trim(),
      providerType: 'openai_compatible',
      baseUrl: form.baseUrl.trim().replace(/\/+$/, ''),
      model: form.model.trim(),
      enabled: form.enabled,
      priority: form.priority,
      timeoutSeconds: form.timeoutSeconds,
      maxOutputTokens: form.maxOutputTokens,
    }
    // 编辑时留空表示保留原密钥，不把空字符串发给后端覆盖。
    if (form.apiKey.trim()) {
      payload.apiKey = form.apiKey.trim()
    }
    if (editingId.value) {
      await updateAIProvider(editingId.value, payload)
      ElMessage.success('模型配置已保存')
    } else {
      await createAIProvider(payload as AIProviderForm)
      ElMessage.success('模型配置已新增')
    }
    dialogVisible.value = false
    await load()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '保存失败')
  } finally {
    saving.value = false
  }
}

async function test(item: AIProviderItem) {
  testingId.value = item.id
  try {
    const result = await testAIProvider(item.id)
    if (result.ok) {
      ElMessage.success(`连接正常，耗时 ${result.latencyMs} 毫秒：${result.message}`)
    } else {
      ElMessage.error(`连接失败：${result.errorCode || '未知错误'} ${result.message}`)
    }
    await load()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '测试连接失败')
  } finally {
    testingId.value = ''
  }
}

async function toggle(item: AIProviderItem, enabled: boolean) {
  try {
    await updateAIProvider(item.id, { enabled })
    item.enabled = enabled
    ElMessage.success(enabled ? '已启用，将参与自动分配' : '已停用，不再参与自动分配')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '保存失败')
  }
}

async function remove(item: AIProviderItem) {
  try {
    await ElMessageBox.confirm(
      `确认删除「${item.name}」？删除后历史调用日志仍会保留，但不再参与自动分配。`,
      '删除模型配置',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await deleteAIProvider(item.id)
    ElMessage.success('模型配置已删除')
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
        <h1 class="page-title">模型配置</h1>
        <p class="page-subtitle">
          按优先级从小到大尝试，失败自动切换下一个；全部失败时回退到本地规则推荐。
        </p>
      </div>
      <div class="head-actions">
        <el-button :icon="Refresh" @click="load">刷新</el-button>
        <el-button type="primary" :icon="Plus" @click="openCreate">新增模型</el-button>
      </div>
    </header>

    <el-alert
      v-if="items.length === 0"
      type="info"
      show-icon
      :closable="false"
      title="尚未配置模型"
      description="未配置或全部调用失败时，AI 问答会自动使用本地规则推荐：只从已发布菜谱中筛选，不编造内容。"
      class="hint"
    />

    <el-table :data="items" border stripe>
      <el-table-column label="优先级" width="90" align="center">
        <template #default="{ row }">
          <el-tag type="info">{{ row.priority }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="name" label="名称" min-width="140" />
      <el-table-column label="模型与地址" min-width="240">
        <template #default="{ row }">
          <div class="model-name">{{ row.model }}</div>
          <div class="muted ellipsis">{{ row.baseUrl }}</div>
        </template>
      </el-table-column>
      <el-table-column prop="apiKeyMasked" label="密钥" width="170" />
      <el-table-column label="最近测试" min-width="200">
        <template #default="{ row }">
          <el-tag v-if="row.lastTestOk === true" type="success" size="small">正常</el-tag>
          <el-tag v-else-if="row.lastTestOk === false" type="danger" size="small">失败</el-tag>
          <el-tag v-else type="info" size="small">未测试</el-tag>
          <div v-if="row.lastTestMessage" class="muted ellipsis">
            {{ row.lastTestMessage }}
          </div>
          <div class="muted">{{ formatDateTime(row.lastTestAt) }}</div>
        </template>
      </el-table-column>
      <el-table-column label="启用" width="90">
        <template #default="{ row }">
          <el-switch
            :model-value="row.enabled"
            @change="(value: string | number | boolean) => toggle(row, Boolean(value))"
          />
        </template>
      </el-table-column>
      <el-table-column label="操作" width="190">
        <template #default="{ row }">
          <el-button
            link
            type="primary"
            :loading="testingId === row.id"
            @click="test(row)"
          >
            测试连接
          </el-button>
          <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button link type="danger" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog
      v-model="dialogVisible"
      :title="editingId ? '编辑模型配置' : '新增模型配置'"
      width="560px"
    >
      <el-form label-width="110px">
        <el-form-item label="名称">
          <el-input v-model="form.name" maxlength="40" placeholder="例如：DeepSeek 主力" />
        </el-form-item>
        <el-form-item label="接口地址">
          <el-input
            v-model="form.baseUrl"
            maxlength="255"
            placeholder="https://api.deepseek.com/v1"
          />
          <div class="muted form-hint">
            OpenAI 兼容接口的根地址，服务层会自动补全 /chat/completions。
          </div>
        </el-form-item>
        <el-form-item label="模型名">
          <el-input v-model="form.model" maxlength="80" placeholder="例如：deepseek-chat" />
        </el-form-item>
        <el-form-item label="API Key">
          <el-input
            v-model="form.apiKey"
            type="password"
            show-password
            maxlength="300"
            :placeholder="editingId ? '留空表示保留原密钥' : '粘贴供应商提供的密钥'"
          />
          <div class="muted form-hint">
            密钥会加密保存，列表只展示首尾掩码；编辑时留空不会覆盖原密钥。
          </div>
        </el-form-item>
        <el-form-item label="优先级">
          <el-input-number v-model="form.priority" :min="0" :max="9999" />
          <div class="muted form-hint">数字越小越先尝试，失败后自动切到下一个模型。</div>
        </el-form-item>
        <el-form-item label="超时（秒）">
          <el-input-number v-model="form.timeoutSeconds" :min="3" :max="120" />
        </el-form-item>
        <el-form-item label="最大输出">
          <el-input-number v-model="form.maxOutputTokens" :min="100" :max="4000" />
          <div class="muted form-hint">限制模型单次回复长度，避免异常长回复拖慢响应。</div>
        </el-form-item>
        <el-form-item label="立即启用">
          <el-switch v-model="form.enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.head-actions {
  display: flex;
  gap: 10px;
}

.hint {
  margin-bottom: 16px;
}

.model-name {
  font-weight: 600;
}

.ellipsis {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.form-hint {
  margin-top: 4px;
  font-size: 12px;
  line-height: 1.4;
}
</style>
