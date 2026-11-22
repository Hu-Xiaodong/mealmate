<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh } from '@element-plus/icons-vue'

import {
  createTasteTag,
  deleteTasteTag,
  listTasteTags,
  updateTasteTag,
} from '@/api/admin'
import type { TasteTagItem } from '@/api/types'

const loading = ref(false)
const saving = ref(false)
const items = ref<TasteTagItem[]>([])
const dialogVisible = ref(false)
const createForm = reactive({ name: '', sortOrder: 100, enabled: true })

async function load() {
  loading.value = true
  try {
    items.value = (await listTasteTags()).items
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '加载标签失败')
  } finally {
    loading.value = false
  }
}

function openCreate() {
  Object.assign(createForm, { name: '', sortOrder: 100, enabled: true })
  dialogVisible.value = true
}

async function create() {
  if (!createForm.name.trim()) {
    ElMessage.warning('请输入标签名称')
    return
  }
  saving.value = true
  try {
    await createTasteTag({
      name: createForm.name.trim(),
      sortOrder: createForm.sortOrder,
      enabled: createForm.enabled,
    })
    ElMessage.success('标签已新增')
    dialogVisible.value = false
    await load()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '新增失败')
  } finally {
    saving.value = false
  }
}

async function toggle(item: TasteTagItem, enabled: boolean) {
  try {
    await updateTasteTag(item.name, { enabled })
    item.enabled = enabled
    ElMessage.success(enabled ? '标签已启用' : '标签已停用')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '保存失败')
  }
}

async function saveSort(item: TasteTagItem) {
  try {
    await updateTasteTag(item.name, { sortOrder: item.sortOrder })
    ElMessage.success('排序已保存')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '保存失败')
  }
}

async function remove(item: TasteTagItem) {
  try {
    await ElMessageBox.confirm(
      `确认删除「${item.name}」？已被饭帖使用的标签不能删除，只能停用。`,
      '删除标签',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await deleteTasteTag(item.name)
    ElMessage.success('标签已删除')
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
        <h1 class="page-title">口味标签</h1>
        <p class="page-subtitle">
          标签是发布页和筛选使用的字典。停用后新发布不再展示，历史饭帖仍保留原值。
        </p>
      </div>
      <div class="head-actions">
        <el-button :icon="Refresh" @click="load">刷新</el-button>
        <el-button type="primary" :icon="Plus" @click="openCreate">新增标签</el-button>
      </div>
    </header>

    <el-table :data="items" border stripe>
      <el-table-column prop="name" label="标签名称" min-width="160" />
      <el-table-column label="排序" width="180">
        <template #default="{ row }">
          <div class="sort-cell">
            <el-input-number v-model="row.sortOrder" :min="0" :max="9999" size="small" />
            <el-button link type="primary" @click="saveSort(row)">保存</el-button>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="使用量" width="100">
        <template #default="{ row }">{{ row.usageCount }} 条</template>
      </el-table-column>
      <el-table-column label="启用" width="100">
        <template #default="{ row }">
          <el-switch
            :model-value="row.enabled"
            @change="(value: string | number | boolean) => toggle(row, Boolean(value))"
          />
        </template>
      </el-table-column>
      <el-table-column label="操作" width="100">
        <template #default="{ row }">
          <el-button link type="danger" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialogVisible" title="新增口味标签" width="420px">
      <el-form label-width="80px">
        <el-form-item label="名称">
          <el-input v-model="createForm.name" maxlength="16" show-word-limit placeholder="例如：微辣" />
        </el-form-item>
        <el-form-item label="排序">
          <el-input-number v-model="createForm.sortOrder" :min="0" :max="9999" />
        </el-form-item>
        <el-form-item label="立即启用">
          <el-switch v-model="createForm.enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="create">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.head-actions {
  display: flex;
  gap: 10px;
}

.sort-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}
</style>
