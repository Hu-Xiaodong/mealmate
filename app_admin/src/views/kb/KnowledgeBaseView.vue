<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox, type UploadFile } from 'element-plus'
import {
  Delete,
  Document,
  Plus,
  Refresh,
  Search,
  UploadFilled,
  View,
} from '@element-plus/icons-vue'

import {
  activateKbIndexVersion,
  createKbIndexVersion,
  deleteKbDocument,
  listKbChunks,
  listKbDocuments,
  listKbIndexVersions,
  reindexKbDocument,
  searchKb,
  uploadKbDocument,
} from '@/api/admin'
import type {
  KbChunkItem,
  KbDocumentItem,
  KbIndexVersionItem,
  KbSearchResult,
} from '@/api/types'
import { formatDateTime } from '@/utils/format'

const CHUNK_PAGE = 20

const loading = ref(false)
const documents = ref<KbDocumentItem[]>([])
const versions = ref<KbIndexVersionItem[]>([])
const keyword = ref('')
const statusFilter = ref('')

const uploadVisible = ref(false)
const uploadTitle = ref('')
const uploadFile = ref<File | null>(null)
const uploading = ref(false)
const processingId = ref('')

const chunkVisible = ref(false)
const chunkDocument = ref<KbDocumentItem | null>(null)
const chunkItems = ref<KbChunkItem[]>([])
const chunkTotal = ref(0)
const chunkOffset = ref(0)
const chunkLoading = ref(false)

const versionVisible = ref(false)
const versionSaving = ref(false)
const versionForm = reactive({ name: '', chunkSize: 400, chunkOverlap: 80 })

const searchForm = reactive({ query: '', topK: 5, threshold: 0.2 })
const searching = ref(false)
const searchResult = ref<KbSearchResult | null>(null)

const activeVersion = computed(
  () => versions.value.find((item) => item.status === 'active') || null,
)

const statusMap: Record<
  string,
  { label: string; type: 'success' | 'warning' | 'danger' | 'info' }
> = {
  uploaded: { label: '已上传', type: 'info' },
  parsing: { label: '解析中', type: 'warning' },
  chunking: { label: '切片中', type: 'warning' },
  indexing: { label: '生成向量', type: 'warning' },
  ready: { label: '可用', type: 'success' },
  failed: { label: '失败', type: 'danger' },
}

function statusOf(status: string) {
  return statusMap[status] || { label: status, type: 'info' as const }
}

function versionStatusOf(status: string) {
  if (status === 'active') {
    return { label: '启用中', type: 'success' as const }
  }
  if (status === 'building') {
    return { label: '构建中', type: 'warning' as const }
  }
  return { label: '已归档', type: 'info' as const }
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) {
    return `${bytes} B`
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`
  }
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function formatScore(score: number): string {
  return `${(score * 100).toFixed(1)}%`
}

async function load() {
  loading.value = true
  try {
    const [documentResult, versionResult] = await Promise.all([
      listKbDocuments({
        status: statusFilter.value || undefined,
        keyword: keyword.value.trim() || undefined,
      }),
      listKbIndexVersions(),
    ])
    documents.value = documentResult.items
    versions.value = versionResult.items
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '加载知识库失败')
  } finally {
    loading.value = false
  }
}

function openUpload() {
  uploadTitle.value = ''
  uploadFile.value = null
  uploadVisible.value = true
}

function handleFileChange(file: UploadFile) {
  uploadFile.value = file.raw || null
}

async function submitUpload() {
  if (!uploadFile.value) {
    ElMessage.warning('请先选择 .md 或 .txt 文件')
    return
  }
  if (!/\.(md|txt)$/i.test(uploadFile.value.name)) {
    ElMessage.warning('仅支持 .md 与 .txt 文件')
    return
  }
  uploading.value = true
  try {
    const document = await uploadKbDocument(uploadFile.value, uploadTitle.value)
    if (document.status === 'ready') {
      ElMessage.success(`上传成功，共生成 ${document.chunkCount} 个切片`)
    } else {
      ElMessage.warning(document.errorMessage || '文档已保存，但索引失败')
    }
    uploadVisible.value = false
    await load()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '上传失败')
  } finally {
    uploading.value = false
  }
}

async function reindex(document: KbDocumentItem) {
  try {
    await ElMessageBox.confirm(
      `按当前启用的索引版本重新切片并生成向量，确认重建「${document.title}」？`,
      '重建索引',
      { type: 'warning', confirmButtonText: '重建', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  processingId.value = document.id
  try {
    const updated = await reindexKbDocument(document.id)
    if (updated.status === 'ready') {
      ElMessage.success(`重建完成，共 ${updated.chunkCount} 个切片`)
    } else {
      ElMessage.warning(updated.errorMessage || '重建失败')
    }
    await load()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '重建失败')
  } finally {
    processingId.value = ''
  }
}

async function remove(document: KbDocumentItem) {
  try {
    await ElMessageBox.confirm(
      `删除后原始文件与全部切片都会移除，且无法恢复。确认删除「${document.title}」？`,
      '删除文档',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await deleteKbDocument(document.id)
    ElMessage.success('文档已删除')
    await load()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '删除失败')
  }
}

async function openChunks(document: KbDocumentItem) {
  chunkDocument.value = document
  chunkItems.value = []
  chunkOffset.value = 0
  chunkVisible.value = true
  await loadChunks(true)
}

async function loadChunks(reset = false) {
  if (!chunkDocument.value) {
    return
  }
  chunkLoading.value = true
  try {
    const page = await listKbChunks(
      chunkDocument.value.id,
      reset ? 0 : chunkOffset.value,
      CHUNK_PAGE,
    )
    chunkTotal.value = page.total
    chunkItems.value = reset
      ? page.items
      : [...chunkItems.value, ...page.items]
    chunkOffset.value = chunkItems.value.length
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '加载切片失败')
  } finally {
    chunkLoading.value = false
  }
}

function openVersionDialog() {
  versionForm.name = `索引 v${versions.value.length + 1}`
  versionForm.chunkSize = 400
  versionForm.chunkOverlap = 80
  versionVisible.value = true
}

async function submitVersion() {
  if (!versionForm.name.trim()) {
    ElMessage.warning('请填写版本名称')
    return
  }
  if (versionForm.chunkOverlap >= versionForm.chunkSize) {
    ElMessage.warning('重叠长度必须小于切片长度')
    return
  }
  versionSaving.value = true
  try {
    await createKbIndexVersion({
      name: versionForm.name.trim(),
      chunkSize: versionForm.chunkSize,
      chunkOverlap: versionForm.chunkOverlap,
    })
    ElMessage.success('索引版本已创建，启用后对文档执行重建即可生效')
    versionVisible.value = false
    await load()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '创建失败')
  } finally {
    versionSaving.value = false
  }
}

async function activate(version: KbIndexVersionItem) {
  try {
    await ElMessageBox.confirm(
      `检索会立即改用「${version.name}」。该版本没有切片时检索结果会为空，确认启用？`,
      '启用索引版本',
      { type: 'warning', confirmButtonText: '启用', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await activateKbIndexVersion(version.id)
    ElMessage.success('索引版本已启用')
    await load()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '启用失败')
  }
}

async function runSearch() {
  if (!searchForm.query.trim()) {
    ElMessage.warning('请输入要检索的问题')
    return
  }
  searching.value = true
  try {
    searchResult.value = await searchKb({
      query: searchForm.query.trim(),
      topK: searchForm.topK,
      threshold: searchForm.threshold,
    })
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '检索失败')
  } finally {
    searching.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="page" v-loading="loading">
    <header class="page-head">
      <div>
        <h1 class="page-title">知识库</h1>
        <p class="page-subtitle">
          上传 Markdown / 纯文本文档，自动切片并生成向量；检索测试用于验证召回效果。
        </p>
      </div>
      <div class="head-actions">
        <el-button :icon="Refresh" @click="load">刷新</el-button>
        <el-button type="primary" :icon="UploadFilled" @click="openUpload">
          上传文档
        </el-button>
      </div>
    </header>

    <el-alert
      type="info"
      show-icon
      :closable="false"
      class="hint"
      title="向量检索依赖嵌入模型"
      description="请先在「模型配置」中新增用途为 embedding 的供应商；未配置时上传的文档会保存为「失败」，补好配置后点「重建」即可。"
    />

    <el-card shadow="never" class="section">
      <div class="toolbar">
        <el-input
          v-model="keyword"
          placeholder="按标题搜索"
          clearable
          class="toolbar__search"
          @keyup.enter="load"
        />
        <el-select v-model="statusFilter" placeholder="全部状态" clearable class="toolbar__status">
          <el-option label="可用" value="ready" />
          <el-option label="处理中" value="indexing" />
          <el-option label="失败" value="failed" />
        </el-select>
        <el-button @click="load">查询</el-button>
      </div>

      <el-table :data="documents" border stripe>
        <el-table-column label="文档" min-width="240">
          <template #default="{ row }">
            <div class="doc-title">{{ row.title }}</div>
            <div class="muted">{{ formatBytes(row.bytes) }} · {{ row.mime }}</div>
            <div v-if="row.errorMessage" class="error-text">{{ row.errorMessage }}</div>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="110" align="center">
          <template #default="{ row }">
            <el-tag :type="statusOf(row.status).type" size="small">
              {{ statusOf(row.status).label }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="chunkCount" label="切片数" width="90" align="center" />
        <el-table-column label="索引版本" min-width="120">
          <template #default="{ row }">
            <span class="muted">{{ row.indexVersionId || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="更新时间" width="170">
          <template #default="{ row }">
            <span class="muted">{{ formatDateTime(row.updatedAt) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="230">
          <template #default="{ row }">
            <el-button link type="primary" :icon="View" @click="openChunks(row)">
              切片
            </el-button>
            <el-button
              link
              type="primary"
              :loading="processingId === row.id"
              @click="reindex(row)"
            >
              重建
            </el-button>
            <el-button link type="danger" :icon="Delete" @click="remove(row)">
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-row :gutter="16">
      <el-col :xs="24" :lg="13">
        <el-card shadow="never" class="section">
          <template #header>
            <div class="card-head">
              <span>索引版本</span>
              <el-button link type="primary" :icon="Plus" @click="openVersionDialog">
                新建版本
              </el-button>
            </div>
          </template>
          <el-table :data="versions" border>
            <el-table-column label="版本" min-width="140">
              <template #default="{ row }">
                <div class="doc-title">{{ row.name }}</div>
                <div class="muted">
                  切片 {{ row.chunkSize }} / 重叠 {{ row.chunkOverlap }}
                </div>
              </template>
            </el-table-column>
            <el-table-column label="嵌入模型" min-width="140">
              <template #default="{ row }">
                <div>{{ row.embedModel || '尚未写入' }}</div>
                <div class="muted">{{ row.dimensions }} 维</div>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="100" align="center">
              <template #default="{ row }">
                <el-tag :type="versionStatusOf(row.status).type" size="small">
                  {{ versionStatusOf(row.status).label }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="90" align="center">
              <template #default="{ row }">
                <el-button
                  v-if="row.status !== 'active'"
                  link
                  type="primary"
                  @click="activate(row)"
                >
                  启用
                </el-button>
                <span v-else class="muted">当前使用</span>
              </template>
            </el-table-column>
          </el-table>
          <p class="muted footnote">
            当前启用版本：{{ activeVersion ? activeVersion.name : '无' }}。切换版本后，旧文档需要逐个「重建」才会写入新版本。
          </p>
        </el-card>
      </el-col>

      <el-col :xs="24" :lg="11">
        <el-card shadow="never" class="section">
          <template #header>
            <div class="card-head">
              <span>检索测试</span>
              <el-tag v-if="searchResult" type="info" size="small">
                耗时 {{ searchResult.tookMs }} 毫秒
              </el-tag>
            </div>
          </template>
          <div class="search-form">
            <el-input
              v-model="searchForm.query"
              placeholder="例如：番茄怎么保存"
              @keyup.enter="runSearch"
            />
            <div class="search-options">
              <span class="muted">返回条数</span>
              <el-input-number v-model="searchForm.topK" :min="1" :max="20" size="small" />
              <span class="muted">最低相似度</span>
              <el-input-number
                v-model="searchForm.threshold"
                :min="0"
                :max="1"
                :step="0.05"
                :precision="2"
                size="small"
              />
              <el-button type="primary" :icon="Search" :loading="searching" @click="runSearch">
                检索
              </el-button>
            </div>
          </div>

          <el-empty
            v-if="!searchResult || searchResult.items.length === 0"
            :description="searchResult ? '没有达到阈值的结果，试试降低相似度' : '输入问题后查看召回片段'"
          />
          <div v-else class="search-results">
            <div v-for="item in searchResult.items" :key="item.chunkId" class="result">
              <div class="result__head">
                <el-tag type="success" size="small">{{ formatScore(item.score) }}</el-tag>
                <span class="result__doc">{{ item.documentTitle }}</span>
                <span class="muted">第 {{ item.ordinal + 1 }} 段</span>
              </div>
              <div class="result__content">{{ item.content }}</div>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-dialog v-model="uploadVisible" title="上传知识文档" width="520px">
      <el-form label-width="90px">
        <el-form-item label="文档标题">
          <el-input
            v-model="uploadTitle"
            maxlength="120"
            placeholder="留空则使用文件名"
          />
        </el-form-item>
        <el-form-item label="文件">
          <el-upload
            drag
            :auto-upload="false"
            :show-file-list="true"
            accept=".md,.txt"
            :on-change="handleFileChange"
            class="uploader"
          >
            <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
            <div class="el-upload__text">把文件拖到这里，或<em>点击选择</em></div>
            <template #tip>
              <div class="muted form-hint">仅支持 UTF-8 编码的 .md / .txt，单个文件不超过 5 MB。</div>
            </template>
          </el-upload>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="uploadVisible = false">取消</el-button>
        <el-button type="primary" :loading="uploading" @click="submitUpload">
          上传并索引
        </el-button>
      </template>
    </el-dialog>

    <el-drawer
      v-model="chunkVisible"
      :title="chunkDocument ? `切片预览 · ${chunkDocument.title}` : '切片预览'"
      size="620px"
    >
      <div v-loading="chunkLoading">
        <p class="muted">
          共 {{ chunkTotal }} 个切片。每个切片开头的【文档｜章节】是检索时补的上下文头。
        </p>
        <div v-for="chunk in chunkItems" :key="chunk.id" class="chunk">
          <div class="chunk__head">
            <el-tag size="small" type="info">第 {{ chunk.ordinal + 1 }} 段</el-tag>
            <span class="muted">{{ chunk.tokenCount }} 字/词</span>
            <span v-if="chunk.metadata?.headingPath" class="muted">
              {{ chunk.metadata.headingPath }}
            </span>
          </div>
          <pre class="chunk__body">{{ chunk.content }}</pre>
        </div>
        <el-empty v-if="!chunkLoading && chunkItems.length === 0" description="暂无切片" />
        <div v-if="chunkItems.length < chunkTotal" class="chunk__more">
          <el-button :loading="chunkLoading" @click="loadChunks(false)">加载更多</el-button>
        </div>
      </div>
    </el-drawer>

    <el-dialog v-model="versionVisible" title="新建索引版本" width="480px">
      <el-form label-width="110px">
        <el-form-item label="版本名称">
          <el-input v-model="versionForm.name" maxlength="80" />
        </el-form-item>
        <el-form-item label="切片长度">
          <el-input-number v-model="versionForm.chunkSize" :min="200" :max="1000" :step="50" />
          <div class="muted form-hint">每个片段的目标字符数，越大上下文越完整、检索越粗。</div>
        </el-form-item>
        <el-form-item label="重叠长度">
          <el-input-number v-model="versionForm.chunkOverlap" :min="0" :max="200" :step="10" />
          <div class="muted form-hint">相邻片段重复的字符数，必须小于切片长度。</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="versionVisible = false">取消</el-button>
        <el-button type="primary" :loading="versionSaving" @click="submitVersion">
          创建
        </el-button>
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

.section {
  margin-bottom: 16px;
  border-radius: 12px;
}

.toolbar {
  display: flex;
  gap: 10px;
  margin-bottom: 14px;
}

.toolbar__search {
  width: 260px;
}

.toolbar__status {
  width: 150px;
}

.doc-title {
  font-weight: 600;
}

.error-text {
  margin-top: 4px;
  color: #c45656;
  font-size: 12px;
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.footnote {
  margin: 10px 0 0;
  font-size: 12px;
  line-height: 1.6;
}

.search-form {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.search-options {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.search-results {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-top: 14px;
  max-height: 460px;
  overflow-y: auto;
}

.result {
  padding: 12px 14px;
  border: 1px solid var(--admin-line);
  border-radius: 10px;
  background: #fbfbfc;
}

.result__head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.result__doc {
  font-weight: 600;
}

.result__content {
  color: #4b5058;
  font-size: 13px;
  line-height: 1.7;
  white-space: pre-wrap;
}

.uploader {
  width: 100%;
}

.form-hint {
  margin-top: 2px;
  font-size: 12px;
}

.chunk {
  padding: 12px 14px;
  margin-bottom: 12px;
  border: 1px solid var(--admin-line);
  border-radius: 10px;
  background: #fbfbfc;
}

.chunk__head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
  font-size: 12px;
}

.chunk__body {
  margin: 0;
  color: #3c414a;
  font-family: inherit;
  font-size: 13px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}

.chunk__more {
  display: flex;
  justify-content: center;
  padding: 8px 0 20px;
}

@media (max-width: 900px) {
  .toolbar {
    flex-wrap: wrap;
  }
}
</style>
