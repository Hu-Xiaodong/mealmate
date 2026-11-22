<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh, Search } from '@element-plus/icons-vue'

import { archiveRecipe, createRecipe, listRecipes, updateRecipe } from '@/api/admin'
import type { AdminRecipe, RecipeForm, RecipeIngredient } from '@/api/types'
import { formatDateTime } from '@/utils/format'

const loading = ref(false)
const saving = ref(false)
const items = ref<AdminRecipe[]>([])
const nextCursor = ref<string | null>(null)
const hasMore = ref(false)
const keyword = ref('')
const statusFilter = ref('')

const dialogVisible = ref(false)
const editingId = ref<string | null>(null)
const formRef = ref()

const categoryOptions = [
  { value: 'recommended', label: '推荐' },
  { value: 'quick', label: '15 分钟' },
  { value: 'one_pot', label: '一锅出' },
  { value: 'few', label: '少食材' },
]

const toolOptions = [
  { value: 'wok', label: '炒锅' },
  { value: 'pot', label: '汤锅' },
  { value: 'microwave', label: '微波炉' },
  { value: 'rice_cooker', label: '电饭煲' },
  { value: 'steamer', label: '蒸锅' },
  { value: 'oven', label: '烤箱' },
]

const statusOptions = [
  { value: 'draft', label: '草稿' },
  { value: 'published', label: '已发布' },
  { value: 'archived', label: '已下架' },
]

const emptyForm = (): RecipeForm => ({
  title: '',
  coverUrl: '',
  totalMinutes: 15,
  toolCodes: [],
  categoryCodes: [],
  servings: 1,
  mainIngredients: [],
  ingredients: [{ name: '', amount: '' }],
  steps: [''],
  preconditions: null,
  contentOrigin: 'platform',
  validationStatus: 'pending',
  status: 'published',
})

const form = reactive<RecipeForm>(emptyForm())

const rules = {
  title: [{ required: true, message: '请输入菜名', trigger: 'blur' }],
  coverUrl: [{ required: true, message: '请输入封面对象键或图片地址', trigger: 'blur' }],
  totalMinutes: [{ required: true, message: '请输入总耗时', trigger: 'blur' }],
}

function resetForm(recipe?: AdminRecipe) {
  Object.assign(form, emptyForm())
  if (recipe) {
    Object.assign(form, {
      title: recipe.title,
      coverUrl: recipe.coverKey,
      totalMinutes: recipe.totalMinutes,
      toolCodes: [...recipe.tools],
      categoryCodes: [...recipe.categories],
      servings: recipe.servings,
      mainIngredients: [...recipe.mainIngredients],
      ingredients: recipe.ingredients.map((item) => ({ ...item })),
      steps: [...recipe.steps],
      preconditions: recipe.preconditions || null,
      contentOrigin: recipe.contentOrigin === 'editor' ? 'editor' : 'platform',
      validationStatus:
        recipe.validationStatus === 'tested'
          ? 'tested'
          : recipe.validationStatus === 'not_tested'
            ? 'not_tested'
            : 'pending',
      status: recipe.status === 'draft' || recipe.status === 'archived' ? recipe.status : 'published',
    })
  }
  if (!form.steps.length) form.steps = ['']
  if (!form.ingredients.length) form.ingredients = [{ name: '', amount: '' }]
}

async function load(reset = true) {
  loading.value = true
  try {
    const data = await listRecipes({
      keyword: keyword.value || undefined,
      status: statusFilter.value || undefined,
      cursor: reset ? undefined : nextCursor.value || undefined,
      limit: 20,
    })
    items.value = reset ? data.items : [...items.value, ...data.items]
    nextCursor.value = data.nextCursor
    hasMore.value = data.hasMore
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '加载菜谱失败')
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editingId.value = null
  resetForm()
  dialogVisible.value = true
}

function openEdit(recipe: AdminRecipe) {
  editingId.value = recipe.id
  resetForm(recipe)
  dialogVisible.value = true
}

function addIngredient() {
  form.ingredients.push({ name: '', amount: '' })
}

function removeIngredient(index: number) {
  form.ingredients.splice(index, 1)
  if (!form.ingredients.length) form.ingredients.push({ name: '', amount: '' })
}

function addStep() {
  form.steps.push('')
}

function removeStep(index: number) {
  form.steps.splice(index, 1)
  if (!form.steps.length) form.steps.push('')
}

function payload(): RecipeForm | null {
  const ingredients = form.ingredients
    .map((item) => ({ name: item.name.trim(), amount: item.amount.trim() }))
    .filter((item) => item.name && item.amount) as RecipeIngredient[]
  const steps = form.steps.map((step) => step.trim()).filter(Boolean)
  if (!ingredients.length) {
    ElMessage.warning('至少填写一种食材，且名称和用量都不能为空')
    return null
  }
  if (!steps.length) {
    ElMessage.warning('至少填写一个步骤')
    return null
  }
  return {
    ...form,
    title: form.title.trim(),
    coverUrl: form.coverUrl.trim(),
    ingredients,
    steps,
    preconditions: form.preconditions?.trim() || null,
    mainIngredients: ingredients.slice(0, 3).map((item) => item.name),
  }
}

async function save() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  const data = payload()
  if (!data) return
  saving.value = true
  try {
    if (editingId.value) {
      await updateRecipe(editingId.value, data)
      ElMessage.success('菜谱已保存')
    } else {
      await createRecipe(data)
      ElMessage.success('菜谱已创建')
    }
    dialogVisible.value = false
    await load()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '保存失败')
  } finally {
    saving.value = false
  }
}

async function archive(recipe: AdminRecipe) {
  try {
    await ElMessageBox.confirm(
      `下架后用户端将立即看不到「${recipe.title}」，历史饭帖关联仍保留。`,
      '确认下架',
      { type: 'warning', confirmButtonText: '下架', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await archiveRecipe(recipe.id)
    ElMessage.success('菜谱已下架')
    await load()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '下架失败')
  }
}

function statusTag(status: string) {
  if (status === 'published') return 'success'
  if (status === 'archived') return 'info'
  return 'warning'
}

function statusLabel(status: string) {
  return statusOptions.find((item) => item.value === status)?.label || status
}

onMounted(() => load(true))
</script>

<template>
  <div class="page" v-loading="loading">
    <header class="page-head">
      <div>
        <h1 class="page-title">菜谱管理</h1>
        <p class="page-subtitle">维护平台菜谱的用料、步骤、耗时与上下架状态。</p>
      </div>
      <el-button type="primary" :icon="Plus" @click="openCreate">新增菜谱</el-button>
    </header>

    <div class="toolbar">
      <el-input
        v-model="keyword"
        placeholder="按菜名搜索"
        clearable
        style="width: 220px"
        @keyup.enter="load(true)"
        @clear="load(true)"
      />
      <el-select v-model="statusFilter" placeholder="全部状态" clearable style="width: 140px" @change="load(true)">
        <el-option v-for="item in statusOptions" :key="item.value" :label="item.label" :value="item.value" />
      </el-select>
      <el-button :icon="Search" @click="load(true)">查询</el-button>
      <el-button :icon="Refresh" @click="load(true)">刷新</el-button>
    </div>

    <el-table :data="items" border stripe>
      <el-table-column label="封面" width="92">
        <template #default="{ row }">
          <el-image :src="row.coverImage" fit="cover" class="cover" />
        </template>
      </el-table-column>
      <el-table-column prop="title" label="菜名" min-width="160" />
      <el-table-column label="分类" min-width="160">
        <template #default="{ row }">
          <el-tag v-for="code in row.categories" :key="code" size="small" class="tag">
            {{ categoryOptions.find((item) => item.value === code)?.label || code }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="耗时" width="84">
        <template #default="{ row }">{{ row.totalMinutes }} 分钟</template>
      </el-table-column>
      <el-table-column label="试做" width="90">
        <template #default="{ row }">
          {{ row.validationStatus === 'tested' ? '已试做' : row.validationStatus === 'pending' ? '待试做' : '未试做' }}
        </template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="statusTag(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="创建时间" width="150">
        <template #default="{ row }">{{ formatDateTime(row.createdAt) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="150" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button v-if="row.status !== 'archived'" link type="danger" @click="archive(row)">下架</el-button>
        </template>
      </el-table-column>
    </el-table>

    <div v-if="hasMore" class="load-more">
      <el-button :loading="loading" @click="load(false)">加载更多</el-button>
    </div>

    <el-dialog
      v-model="dialogVisible"
      :title="editingId ? '编辑菜谱' : '新增菜谱'"
      width="760px"
      top="6vh"
      destroy-on-close
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-width="92px">
        <el-form-item label="菜名" prop="title">
          <el-input v-model="form.title" maxlength="40" show-word-limit />
        </el-form-item>
        <el-form-item label="封面" prop="coverUrl">
          <div class="cover-editor">
            <el-input v-model="form.coverUrl" placeholder="对象键如 seed/food_1.jpg，或完整图片地址" />
            <el-image v-if="form.coverUrl" :src="form.coverUrl" fit="cover" class="cover-preview" />
          </div>
        </el-form-item>
        <div class="form-grid">
          <el-form-item label="总耗时" prop="totalMinutes">
            <el-input-number v-model="form.totalMinutes" :min="1" :max="180" />
          </el-form-item>
          <el-form-item label="份量">
            <el-input-number v-model="form.servings" :min="0.5" :max="20" :step="0.5" />
          </el-form-item>
          <el-form-item label="状态">
            <el-select v-model="form.status">
              <el-option v-for="item in statusOptions" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
          </el-form-item>
          <el-form-item label="试做">
            <el-select v-model="form.validationStatus">
              <el-option label="已试做" value="tested" />
              <el-option label="待试做" value="pending" />
              <el-option label="未试做" value="not_tested" />
            </el-select>
          </el-form-item>
        </div>
        <el-form-item label="分类">
          <el-checkbox-group v-model="form.categoryCodes">
            <el-checkbox v-for="item in categoryOptions" :key="item.value" :value="item.value">
              {{ item.label }}
            </el-checkbox>
          </el-checkbox-group>
        </el-form-item>
        <el-form-item label="器具">
          <el-checkbox-group v-model="form.toolCodes">
            <el-checkbox v-for="item in toolOptions" :key="item.value" :value="item.value">
              {{ item.label }}
            </el-checkbox>
          </el-checkbox-group>
        </el-form-item>
        <el-form-item label="前置条件">
          <el-input v-model="form.preconditions" maxlength="200" placeholder="例如：需要提前煮好米饭" />
        </el-form-item>

        <el-form-item label="食材">
          <div class="editor-list">
            <div v-for="(item, index) in form.ingredients" :key="index" class="editor-row">
              <el-input v-model="item.name" placeholder="食材名" style="width: 180px" />
              <el-input v-model="item.amount" placeholder="用量" style="width: 140px" />
              <el-button link type="danger" @click="removeIngredient(index)">删除</el-button>
            </div>
            <el-button link type="primary" @click="addIngredient">+ 添加食材</el-button>
          </div>
        </el-form-item>

        <el-form-item label="步骤">
          <div class="editor-list">
            <div v-for="(_, index) in form.steps" :key="index" class="editor-row">
              <span class="step-index">{{ index + 1 }}</span>
              <el-input v-model="form.steps[index]" placeholder="描述这一步做什么" />
              <el-button link type="danger" @click="removeStep(index)">删除</el-button>
            </div>
            <el-button link type="primary" @click="addStep">+ 添加步骤</el-button>
          </div>
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
.toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 14px;
}

.cover {
  width: 56px;
  height: 56px;
  border-radius: 8px;
}

.tag {
  margin-right: 4px;
}

.load-more {
  display: flex;
  justify-content: center;
  padding: 18px 0;
}

.cover-editor {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
}

.cover-preview {
  width: 64px;
  height: 64px;
  flex: none;
  border-radius: 8px;
  border: 1px solid var(--admin-line);
}

.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0 16px;
}

.editor-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 100%;
}

.editor-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.step-index {
  width: 20px;
  color: var(--admin-muted);
  font-size: 12px;
  text-align: right;
}
</style>
