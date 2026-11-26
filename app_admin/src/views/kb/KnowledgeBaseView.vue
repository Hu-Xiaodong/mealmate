<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox, type UploadFile } from 'element-plus'
import {
  Delete,
  Document,
  FolderOpened,
  Plus,
  Refresh,
  Search,
  SetUp,
  UploadFilled,
  View,
} from '@element-plus/icons-vue'

import {
  activateKbIndexVersion,
  batchBuildKbIndex,
  batchDeleteKbDocuments,
  batchGenerateKbRecipeDrafts,
  batchRechunkKbDocuments,
  buildKbIndex,
  createKbImportBatch,
  createKbIndexVersion,
  deleteKbDocument,
  generateKbRecipeDraft,
  getKbImportBatch,
  listKbChunks,
  listKbDocuments,
  listKbIndexVersions,
  rechunkKbDocument,
  retryKbImportBatch,
  searchKb,
  uploadKbDocument,
} from '@/api/admin'
import type {
  KbBatchOperationItem,
  KbChunkItem,
  KbDocumentItem,
  KbImportBatchItem,
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
// 服务端分页：页码从 1 开始，每页 20 条；总数由接口返回。
// 不在前端切数组，因为文档会越来越多，一次取全部既慢又占内存。
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)

const uploadVisible = ref(false)
const uploadTitle = ref('')
const uploadFile = ref<File | null>(null)
const uploadImages = ref<File[]>([])
// Markdown 里引用的本地图片文件名，以及还没在“图片”里选中的部分。
// 这两个值只用于上传前提醒，不参与后端匹配；后端仍以实际提交的文件为准。
const referencedImages = ref<string[]>([])
const missingImages = ref<string[]>([])
const uploading = ref(false)
const processingId = ref('')
// 正在生成菜谱草稿的文档编号，用来只让当前行按钮转圈。
const recipeDraftingId = ref('')
// 勾选中的文档。批量删除按钮根据它是否为空来禁用，
// 避免“没选任何东西却点删除”这种无意义请求。
const selectedDocuments = ref<KbDocumentItem[]>([])
const batchDeleting = ref(false)
// 批量重新切片 / 生成菜谱 / 建立索引：同一时间只允许执行一种，按钮共用 loading。
const batchOperating = ref<'' | 'rechunk' | 'recipe' | 'index'>('')
// 批量操作结果弹窗：只列出失败与被跳过的文档，成功的不逐条罗列。
const batchResultVisible = ref(false)
const batchResultTitle = ref('')
const batchResultItems = ref<KbBatchOperationItem[]>([])

// ---------- 批量导入 ----------
const batchVisible = ref(false)
const batchLabel = ref('')
// 文件夹与多选共用一份列表：file 是浏览器文件对象，path 保留相对目录。
const batchDocs = ref<{ file: File; path: string }[]>([])
const batchZip = ref<File | null>(null)
const batchSubmitting = ref(false)
const batch = ref<KbImportBatchItem | null>(null)
const folderInput = ref<HTMLInputElement | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)
// 轮询定时器的编号。单独的变量而不是 ref：它不参与页面渲染。
let batchTimer: number | undefined

const batchDocCount = computed(
  () => batchDocs.value.filter((item) => /\.(md|txt)$/i.test(item.file.name)).length,
)
const batchImageCount = computed(
  () => batchDocs.value.filter((item) => /\.(jpe?g|png|webp)$/i.test(item.file.name)).length,
)
const batchOtherCount = computed(
  () => batchDocs.value.length - batchDocCount.value - batchImageCount.value,
)

const batchProgress = computed(() => {
  const stats = batch.value?.stats
  if (!stats || !stats.total) {
    return 0
  }
  const settled = stats.succeeded + stats.failed + stats.skipped
  return Math.round((settled / stats.total) * 100)
})

const batchStatusMap: Record<
  string,
  { label: string; type: 'success' | 'warning' | 'danger' | 'info' }
> = {
  pending: { label: '等待处理', type: 'info' },
  running: { label: '处理中', type: 'warning' },
  succeeded: { label: '全部成功', type: 'success' },
  partial: { label: '部分失败', type: 'warning' },
  failed: { label: '失败', type: 'danger' },
}

const jobStatusMap: Record<
  string,
  { label: string; type: 'success' | 'warning' | 'danger' | 'info' }
> = {
  pending: { label: '等待中', type: 'info' },
  running: { label: '处理中', type: 'warning' },
  succeeded: { label: '成功', type: 'success' },
  failed: { label: '失败', type: 'danger' },
  skipped: { label: '已跳过', type: 'info' },
  dead: { label: '多次失败', type: 'danger' },
}

function batchStatusOf(status: string) {
  return batchStatusMap[status] || { label: status, type: 'info' as const }
}

function jobStatusOf(status: string) {
  return jobStatusMap[status] || { label: status, type: 'info' as const }
}

const indexVisible = ref(false)
const indexTarget = ref<KbDocumentItem | null>(null)
const indexing = ref(false)

const chunkVisible = ref(false)
const chunkDocument = ref<{ id: string; title: string } | null>(null)
const chunkItems = ref<KbChunkItem[]>([])
const chunkTotal = ref(0)
const chunkOffset = ref(0)
const chunkLoading = ref(false)
const chunkSource = ref<'draft' | 'indexed'>('draft')

const versionVisible = ref(false)
const versionSaving = ref(false)
const versionForm = reactive({ name: '', chunkSize: 400, chunkOverlap: 80 })

const searchForm = reactive({ query: '', topK: 5, threshold: 0.2 })
const searching = ref(false)
const searchResult = ref<KbSearchResult | null>(null)

const activeVersion = computed(
  () => versions.value.find((item) => item.status === 'active') || null,
)

// 当前列表里还有待索引切片的文档数量，用于工具栏提示。
const pendingChunkCount = computed(
  () => documents.value.filter((item) => item.draftChunkCount > 0).length,
)

const statusMap: Record<
  string,
  { label: string; type: 'success' | 'warning' | 'danger' | 'info' }
> = {
  uploaded: { label: '已上传', type: 'info' },
  parsing: { label: '解析中', type: 'warning' },
  chunking: { label: '切片中', type: 'warning' },
  chunked: { label: '待建索引', type: 'info' },
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

type ContentSegment =
  | { type: 'text'; text: string }
  | { type: 'image'; url: string; alt: string }

// 匹配 Markdown 图片，例如 ![白灼虾](/media/kb/kbd_xxx/images/白灼虾.webp)。
const IMAGE_PATTERN = /!\[([^\]]*)\]\(([^)\s]+)(?:\s+["'][^"']*["'])?\)/g

/**
 * 把切片正文拆成“文字 / 图片”片段。
 *
 * 为什么不用完整的 Markdown 渲染库：后台只需要把图片显示出来，
 * 引入 marked 之类的库还要再配一份 HTML 清洗（防止脚本注入），
 * 这里用 Vue 模板直接渲染文字和 <img>，不产生 v-html，安全且依赖更少。
 */
function contentSegments(content: string): ContentSegment[] {
  const segments: ContentSegment[] = []
  let cursor = 0
  for (const match of content.matchAll(IMAGE_PATTERN)) {
    const index = match.index ?? 0
    if (index > cursor) {
      segments.push({ type: 'text', text: content.slice(cursor, index) })
    }
    segments.push({
      type: 'image',
      url: match[2],
      alt: match[1] || '切片图片',
    })
    cursor = index + match[0].length
  }
  if (cursor < content.length) {
    segments.push({ type: 'text', text: content.slice(cursor) })
  }
  return segments
}

async function load() {
  loading.value = true
  try {
    const [documentResult, versionResult] = await Promise.all([
      listKbDocuments({
        status: statusFilter.value || undefined,
        keyword: keyword.value.trim() || undefined,
        page: page.value,
        pageSize: pageSize.value,
      }),
      listKbIndexVersions(),
    ])
    documents.value = documentResult.items
    total.value = documentResult.total
    versions.value = versionResult.items
    // 刷新后旧行的勾选已经没有意义，一并清空，避免误删不在当前列表里的文档。
    selectedDocuments.value = []
    // 删除或筛选后当前页可能已经空了：自动退回上一页，而不是给运营一个空表格。
    if (!documents.value.length && page.value > 1) {
      page.value -= 1
      await load()
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '加载知识库失败')
  } finally {
    loading.value = false
  }
}

/**
 * 查询：筛选条件变化后必须回到第 1 页。
 * 否则在第 5 页搜一个只有 2 条结果的关键词，会直接看到空表格。
 */
function query() {
  page.value = 1
  void load()
}

/** 修改每页条数后同样回到第 1 页，避免页码越界。 */
function onPageSizeChange() {
  page.value = 1
  void load()
}

function openUpload() {
  uploadTitle.value = ''
  uploadFile.value = null
  uploadImages.value = []
  referencedImages.value = []
  missingImages.value = []
  uploadVisible.value = true
}

/** 从 Markdown 里提取本地图片引用，返回文件名（去掉 ./、../ 和 URL 编码）。 */
function extractImageNames(content: string): string[] {
  const names = new Set<string>()
  // 与后端使用同一条规则：只处理 Markdown 图片语法，外链不参与本地匹配。
  const pattern = /!\[[^\]]*\]\(([^)\s]+)(?:\s+["'][^"']*["'])?\)/g
  for (const match of content.matchAll(pattern)) {
    const url = match[1]
    if (/^(https?:|data:|\/\/)/i.test(url)) continue
    let path = url.split('?')[0].split('#')[0].replace(/\\/g, '/')
    try {
      path = decodeURIComponent(path)
    } catch {
      // 地址里有非法百分号时保留原文，不影响后续按文件名匹配。
    }
    const name = path.split('/').pop()
    if (name) names.add(name)
  }
  return [...names]
}

function refreshImageCheck() {
  const selected = new Set(uploadImages.value.map((file) => file.name.toLowerCase()))
  missingImages.value = referencedImages.value.filter(
    (name) => !selected.has(name.toLowerCase()),
  )
}

async function handleFileChange(file: UploadFile) {
  uploadFile.value = file.raw || null
  referencedImages.value = []
  missingImages.value = []
  if (uploadFile.value && /\.(md|txt)$/i.test(uploadFile.value.name)) {
    // 浏览器只能读取用户主动选中的文件；这里提前解析正文，提示还需要哪些图片，
    // 避免上传完才发现切片里只有一个图片地址。
    referencedImages.value = extractImageNames(await uploadFile.value.text())
    refreshImageCheck()
  }
}

function handleImagesChange(_file: UploadFile, fileList: UploadFile[]) {
  // el-upload 的文件列表包含已删除的文件，每次以最新列表为准重建数组。
  uploadImages.value = fileList.flatMap((item) => (item.raw ? [item.raw] : []))
  refreshImageCheck()
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
  if (missingImages.value.length) {
    try {
      await ElMessageBox.confirm(
        `Markdown 引用了这些图片，但还没有选择：${missingImages.value.join('、')}。继续上传后，切片里只会保留图片地址，预览不会显示图片。`,
        '还有图片未选择',
        {
          confirmButtonText: '仍然上传',
          cancelButtonText: '返回选择图片',
          type: 'warning',
        },
      )
    } catch {
      return
    }
  }
  uploading.value = true
  try {
    const document = await uploadKbDocument(uploadFile.value, uploadImages.value, uploadTitle.value)
    if (document.status === 'chunked') {
      const imageHint = document.imageCount ? `，已关联 ${document.imageCount} 张图片` : ''
      ElMessage.success(
        `上传成功，已切出 ${document.chunkCount} 个切片${imageHint}，点该行的「去新建索引」即可生成向量`,
      )
      if (document.unmatchedImageCount) {
        ElMessage.warning(
          `有 ${document.unmatchedImageCount} 处图片引用没有匹配到上传文件，已保留原地址`,
        )
      }
    } else {
      ElMessage.warning(document.errorMessage || '文档已保存，但切片失败')
    }
    uploadVisible.value = false
    await load()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '上传失败')
  } finally {
    uploading.value = false
  }
}

async function rechunk(document: KbDocumentItem) {
  try {
    await ElMessageBox.confirm(
      `按当前启用的索引版本重新切片，新切片会替换旧的待索引切片，确认重新切片「${document.title}」？`,
      '重新切片',
      { type: 'warning', confirmButtonText: '重新切片', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  processingId.value = document.id
  try {
    const updated = await rechunkKbDocument(document.id)
    if (updated.status === 'chunked') {
      ElMessage.success(`重新切片完成，共 ${updated.chunkCount} 个切片，可点「去新建索引」生成向量`)
    } else {
      ElMessage.warning(updated.errorMessage || '重新切片失败')
    }
    await load()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '重新切片失败')
  } finally {
    processingId.value = ''
  }
}

function openIndexDialog(item: KbDocumentItem) {
  indexTarget.value = item
  indexVisible.value = true
}

async function submitIndex() {
  if (!indexTarget.value) {
    return
  }
  indexing.value = true
  try {
    const updated = await buildKbIndex(indexTarget.value.id)
    if (updated.status === 'ready') {
      ElMessage.success(`索引已建立，共 ${updated.chunkCount} 个切片可用于检索`)
    } else {
      ElMessage.warning(updated.errorMessage || '建立索引失败')
    }
    indexVisible.value = false
    await load()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '建立索引失败')
  } finally {
    indexing.value = false
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

/**
 * 把文档按固定模板重新解析成菜谱草稿。
 * 上传时后端已经自动生成过一次；这里用于旧文档补生成，
 * 或运营改过文档内容后重新生成（已发布的菜谱不会被覆盖）。
 */
async function generateRecipeDraft(document: KbDocumentItem) {
  recipeDraftingId.value = document.id
  try {
    const result = await generateKbRecipeDraft(document.id)
    if (result.skipped) {
      ElMessage.warning(result.message)
    } else {
      ElMessage.success(`${result.message}：《${result.title}》`)
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '生成菜谱草稿失败')
  } finally {
    recipeDraftingId.value = ''
  }
}

/**
 * 表格勾选变化时同步选中的文档。
 * 不自己维护“哪些编号被勾中”，直接使用表格给的行对象，
 * 后续拼请求时只取 id，展示标题时也拿得到。
 */
function onSelectionChange(rows: KbDocumentItem[]) {
  selectedDocuments.value = rows
}

async function batchRemove() {
  if (!selectedDocuments.value.length) {
    return
  }
  const count = selectedDocuments.value.length
  try {
    await ElMessageBox.confirm(
      `将删除 ${count} 篇文档，原始文件与全部切片都会移除，且无法恢复。确认继续？`,
      '批量删除文档',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  batchDeleting.value = true
  try {
    const result = await batchDeleteKbDocuments(
      selectedDocuments.value.map((document) => document.id),
    )
    if (result.failed) {
      // 部分失败时把第一篇的原因带出来，运营才知道为什么没删干净。
      const reason = result.results.find((item) => !item.ok)?.message || '请刷新后重试'
      ElMessage.warning(`已删除 ${result.succeeded} 篇，${result.failed} 篇失败：${reason}`)
    } else {
      ElMessage.success(`已删除 ${result.succeeded} 篇文档`)
    }
    await load()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '批量删除失败')
  } finally {
    batchDeleting.value = false
  }
}

/**
 * 批量执行“重新切片 / 生成菜谱 / 建立索引”。
 *
 * 三个操作的交互完全一致：确认数量 → 调接口 → 汇总结果 → 刷新列表。
 * 逐篇执行、逐篇返回，某篇失败不会影响其他篇，所以结果弹窗只列出
 * 失败和跳过的文档，成功数量在提示里说明。
 */
async function runBatchOperation(kind: 'rechunk' | 'recipe' | 'index') {
  if (!selectedDocuments.value.length) {
    return
  }
  const labels = {
    rechunk: { action: '重新切片', confirm: '将对', button: '开始切片' },
    recipe: { action: '生成菜谱草稿', confirm: '将为', button: '开始生成' },
    index: { action: '建立索引', confirm: '将为', button: '开始建立' },
  } as const
  const label = labels[kind]
  const count = selectedDocuments.value.length
  // 与后端上限保持一致：超过 20 篇时提前拦住并说明原因，
  // 而不是提交后收到一条笼统的“格式不正确”。
  if (count > 20) {
    ElMessage.warning(`批量${label.action}一次最多 20 篇，当前勾选 ${count} 篇，请分批处理`)
    return
  }
  try {
    await ElMessageBox.confirm(
      `${label.confirm} ${count} 篇文档执行${label.action}，逐篇处理并返回结果。确认继续？`,
      `批量${label.action}`,
      { type: 'warning', confirmButtonText: label.button, cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  batchOperating.value = kind
  try {
    const ids = selectedDocuments.value.map((document) => document.id)
    const result =
      kind === 'rechunk'
        ? await batchRechunkKbDocuments(ids)
        : kind === 'recipe'
          ? await batchGenerateKbRecipeDrafts(ids)
          : await batchBuildKbIndex(ids)
    const skipped = result.skipped ? `，跳过 ${result.skipped} 篇` : ''
    if (result.failed) {
      ElMessage.warning(
        `${label.action}完成：成功 ${result.succeeded} 篇，失败 ${result.failed} 篇${skipped}`,
      )
    } else {
      ElMessage.success(`${label.action}完成：成功 ${result.succeeded} 篇${skipped}`)
    }
    const abnormal = result.results.filter((item) => !item.ok)
    if (abnormal.length) {
      batchResultTitle.value = `批量${label.action}：${abnormal.length} 篇未完成`
      batchResultItems.value = abnormal
      batchResultVisible.value = true
    }
    await load()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : `批量${label.action}失败`)
  } finally {
    batchOperating.value = ''
  }
}

async function openChunks(document: { id: string; title: string }) {
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
    chunkSource.value = page.source
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

function openBatch() {
  stopBatchPolling()
  batchLabel.value = ''
  batchDocs.value = []
  batchZip.value = null
  batch.value = null
  batchVisible.value = true
}

function pickFolder() {
  folderInput.value?.click()
}

function pickFiles() {
  fileInput.value?.click()
}

/**
 * 文件夹选择：浏览器只给文件，相对目录在 webkitRelativePath 里。
 * 后端按这个路径判断“哪些图片和哪篇文档在同一个目录”，因此必须原样提交。
 */
function onFolderPicked(event: Event) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files || [])
  input.value = ''
  if (!files.length) {
    return
  }
  batchZip.value = null
  batchDocs.value = files.map((file) => ({
    file,
    path: file.webkitRelativePath || file.name,
  }))
}

/**
 * 多选文件：压缩包与普通文件互斥。
 * 压缩包由服务端解压，普通文件直接逐篇处理；混在一起会让失败原因难以解释。
 */
function onFilesPicked(event: Event) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files || [])
  input.value = ''
  if (!files.length) {
    return
  }
  const zip = files.find((file) => /\.zip$/i.test(file.name))
  if (zip) {
    batchZip.value = zip
    batchDocs.value = []
    if (files.length > 1) {
      ElMessage.warning('压缩包不能和其他文件混在同一批，本次只保留压缩包')
    }
    return
  }
  batchZip.value = null
  batchDocs.value = files.map((file) => ({
    file,
    path: file.webkitRelativePath || file.name,
  }))
}

function stopBatchPolling() {
  if (batchTimer !== undefined) {
    window.clearInterval(batchTimer)
    batchTimer = undefined
  }
}

async function pollBatch() {
  if (!batch.value) {
    stopBatchPolling()
    return
  }
  try {
    const current = await getKbImportBatch(batch.value.id)
    batch.value = current
    if (current.status !== 'pending' && current.status !== 'running') {
      stopBatchPolling()
      const stats = current.stats
      if (stats.failed) {
        ElMessage.warning(
          `导入结束：成功 ${stats.succeeded} 篇，失败 ${stats.failed} 篇，可在下方重试失败项`,
        )
      } else {
        ElMessage.success(
          `导入完成：成功 ${stats.succeeded} 篇，跳过 ${stats.skipped} 篇，点文档行的「去新建索引」生成向量`,
        )
      }
      await load()
    }
  } catch (error) {
    stopBatchPolling()
    ElMessage.error(error instanceof Error ? error.message : '查询导入进度失败')
  }
}

function startBatchPolling() {
  stopBatchPolling()
  // 先查一次：文件很少时后端可能在第一次轮询前就处理完了。
  void pollBatch()
  batchTimer = window.setInterval(() => {
    void pollBatch()
  }, 1500)
}

async function submitBatch() {
  if (!batchZip.value && !batchDocCount.value) {
    ElMessage.warning('请选择包含 .md 或 .txt 的文件夹、多个文件，或一个 ZIP 压缩包')
    return
  }
  batchSubmitting.value = true
  try {
    batch.value = await createKbImportBatch({
      files: batchDocs.value.map((item) => item.file),
      paths: batchDocs.value.map((item) => item.path),
      archive: batchZip.value,
      label: batchLabel.value,
    })
    startBatchPolling()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '创建导入批次失败')
  } finally {
    batchSubmitting.value = false
  }
}

async function retryBatch() {
  if (!batch.value) {
    return
  }
  batchSubmitting.value = true
  try {
    batch.value = await retryKbImportBatch(batch.value.id)
    startBatchPolling()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '重试失败')
  } finally {
    batchSubmitting.value = false
  }
}

onBeforeUnmount(stopBatchPolling)
onMounted(load)
</script>

<template>
  <div class="page" v-loading="loading">
    <header class="page-head">
      <div>
        <h1 class="page-title">知识库</h1>
        <p class="page-subtitle">
          上传只做解析与切片；待索引的行出现「去新建索引」，确认后生成向量，再用检索测试验证效果。
        </p>
      </div>
      <div class="head-actions">
        <el-button :icon="Refresh" @click="load">刷新</el-button>
        <el-button :icon="FolderOpened" @click="openBatch">批量导入</el-button>
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
      title="上传只切片，建立索引才调用嵌入模型"
      description="请先在「模型配置」中新增用途为 embedding 的供应商；未配置时切片仍会生成，但建立索引会失败，补好配置后可直接重试，不需要重新上传。"
    />

    <el-card shadow="never" class="section">
      <div class="toolbar">
        <el-input
          v-model="keyword"
          placeholder="按标题搜索"
          clearable
          class="toolbar__search"
          @keyup.enter="query"
        />
        <el-select v-model="statusFilter" placeholder="全部状态" clearable class="toolbar__status">
          <el-option label="待建索引" value="chunked" />
          <el-option label="可用" value="ready" />
          <el-option label="处理中" value="indexing" />
          <el-option label="失败" value="failed" />
        </el-select>
        <el-button @click="query">查询</el-button>
        <el-button
          plain
          :disabled="!selectedDocuments.length || !!batchOperating"
          :loading="batchOperating === 'rechunk'"
          @click="runBatchOperation('rechunk')"
        >
          批量重新切片{{ selectedDocuments.length ? ` (${selectedDocuments.length})` : '' }}
        </el-button>
        <el-button
          plain
          :disabled="!selectedDocuments.length || !!batchOperating"
          :loading="batchOperating === 'recipe'"
          @click="runBatchOperation('recipe')"
        >
          批量生成菜谱{{ selectedDocuments.length ? ` (${selectedDocuments.length})` : '' }}
        </el-button>
        <el-button
          plain
          :disabled="!selectedDocuments.length || !!batchOperating"
          :loading="batchOperating === 'index'"
          @click="runBatchOperation('index')"
        >
          批量建立索引{{ selectedDocuments.length ? ` (${selectedDocuments.length})` : '' }}
        </el-button>
        <el-button
          type="danger"
          plain
          :icon="Delete"
          :disabled="!selectedDocuments.length || !!batchOperating"
          :loading="batchDeleting"
          @click="batchRemove"
        >
          批量删除{{ selectedDocuments.length ? ` (${selectedDocuments.length})` : '' }}
        </el-button>
        <el-tag v-if="pendingChunkCount" type="info" size="small" class="toolbar__tag">
          本页 {{ pendingChunkCount }} 份待建立索引
        </el-tag>
      </div>

      <el-table :data="documents" border stripe @selection-change="onSelectionChange">
        <el-table-column type="selection" width="44" />
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
        <el-table-column label="切片参数" width="150" align="center">
          <template #default="{ row }">
            <span v-if="row.draftChunkCount" class="muted">
              长度 {{ row.chunkSize }} / 重叠 {{ row.chunkOverlap }}
            </span>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
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
        <el-table-column label="操作" width="400">
          <template #default="{ row }">
            <el-button link type="primary" :icon="View" @click="openChunks(row)">
              切片
            </el-button>
            <el-button
              link
              type="primary"
              :loading="processingId === row.id"
              @click="rechunk(row)"
            >
              重新切片
            </el-button>
            <el-button
              v-if="row.draftChunkCount"
              link
              type="primary"
              :icon="SetUp"
              @click="openIndexDialog(row)"
            >
              去新建索引
            </el-button>
            <el-button
              link
              type="primary"
              :loading="recipeDraftingId === row.id"
              @click="generateRecipeDraft(row)"
            >
              生成菜谱
            </el-button>
            <el-button link type="danger" :icon="Delete" @click="remove(row)">
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
      <p class="muted footnote">
        上传只做解析与切片，不会调用嵌入模型；待索引的行会出现「去新建索引」，确认后才生成向量并写入当前启用索引版本。
      </p>
      <div class="pager">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          :total="total"
          :page-sizes="[20, 50, 100]"
          layout="total, sizes, prev, pager, next"
          background
          @current-change="load"
          @size-change="onPageSizeChange"
        />
      </div>
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
            当前启用版本：{{ activeVersion ? activeVersion.name : '无' }}。切换版本后，旧文档需要逐个「重新切片」并「建立索引」才会写入新版本。
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

          <el-alert
            v-if="searchResult?.warning"
            :title="searchResult.warning"
            type="warning"
            :closable="false"
            show-icon
            style="margin-bottom: 12px"
          />

          <el-empty
            v-if="!searchResult || searchResult.items.length === 0"
            :description="searchResult ? '没有达到阈值的结果，试试降低相似度' : '输入问题后查看召回片段'"
          />
          <div v-else class="search-results">
            <div v-for="item in searchResult.items" :key="item.chunkId" class="result">
              <div class="result__head">
                <el-tag type="success" size="small">{{ formatScore(item.score) }}</el-tag>
                <el-tag v-if="searchResult?.mode === 'keyword'" type="warning" size="small">
                  关键词匹配
                </el-tag>
                <span class="result__doc">{{ item.documentTitle }}</span>
                <span class="muted">第 {{ item.ordinal + 1 }} 段</span>
              </div>
              <div class="result__content">
                <template v-for="(segment, segmentIndex) in contentSegments(item.content)" :key="segmentIndex">
                  <span v-if="segment.type === 'text'">{{ segment.text }}</span>
                  <img
                    v-else
                    class="chunk__image"
                    :src="segment.url"
                    :alt="segment.alt"
                    loading="lazy"
                  />
                </template>
              </div>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-dialog
      v-model="batchVisible"
      title="批量导入知识文档"
      width="760px"
      @closed="stopBatchPolling"
    >
      <template v-if="!batch">
        <el-form label-width="90px">
          <el-form-item label="批次名称">
            <el-input
              v-model="batchLabel"
              maxlength="120"
              placeholder="选填；留空则使用压缩包文件名或文件夹名"
            />
          </el-form-item>
          <el-form-item label="选择来源">
            <div class="batch-pickers">
              <el-button :icon="FolderOpened" @click="pickFolder">选择文件夹</el-button>
              <el-button :icon="Plus" @click="pickFiles">选择文件 / 压缩包</el-button>
            </div>
          </el-form-item>
        </el-form>
        <div v-if="batchZip || batchDocs.length" class="batch-summary">
          <el-tag v-if="batchZip" type="warning">压缩包：{{ batchZip.name }}</el-tag>
          <template v-else>
            <el-tag type="success">文档 {{ batchDocCount }}</el-tag>
            <el-tag type="info">图片 {{ batchImageCount }}</el-tag>
            <el-tag v-if="batchOtherCount" type="info">其他 {{ batchOtherCount }}（将被忽略）</el-tag>
          </template>
        </div>
        <el-alert
          type="info"
          show-icon
          :closable="false"
          title="支持文件夹、多选文件与 ZIP 压缩包"
          description="只会解析 .md 与 .txt，并把正文引用到的 JPG / PNG / WebP 图片按同目录优先匹配；PDF、Word 等其他文件会被忽略。上传后自动在后台逐篇切片，失败的单个文件可以单独重试。"
        />
        <!-- 原生 input 才能使用 webkitdirectory：Element Plus 的上传组件不支持选文件夹。 -->
        <input
          ref="folderInput"
          type="file"
          webkitdirectory
          multiple
          class="hidden-input"
          @change="onFolderPicked"
        />
        <input
          ref="fileInput"
          type="file"
          multiple
          accept=".md,.txt,.zip,.jpg,.jpeg,.png,.webp"
          class="hidden-input"
          @change="onFilesPicked"
        />
      </template>

      <template v-else>
        <div class="batch-head">
          <div>
            <div class="batch-label">{{ batch.label }}</div>
            <div class="muted">创建于 {{ formatDateTime(batch.createdAt) }}</div>
          </div>
          <el-tag :type="batchStatusOf(batch.status).type">
            {{ batchStatusOf(batch.status).label }}
          </el-tag>
        </div>
        <el-progress
          :percentage="batchProgress"
          :status="batch.status === 'failed' ? 'exception' : undefined"
        />
        <div class="batch-stats">
          <span>共 {{ batch.stats.total }} 篇</span>
          <span>成功 {{ batch.stats.succeeded }}</span>
          <span>失败 {{ batch.stats.failed }}</span>
          <span>跳过 {{ batch.stats.skipped }}</span>
          <span v-if="batch.stats.ignored">已忽略 {{ batch.stats.ignored }}</span>
          <span v-if="batch.stats.unusedImages">
            未被引用图片 {{ batch.stats.unusedImages }}
          </span>
        </div>
        <el-alert
          v-if="batch.stats.unusedImages"
          class="batch-alert"
          type="info"
          show-icon
          :closable="false"
          title="以下图片没有被任何文档引用，不会进入知识库"
        >
          <ul class="unused-paths">
            <li v-for="path in batch.stats.unusedImagePaths || []" :key="path">
              {{ path }}
            </li>
          </ul>
          <div class="muted">
            常见原因：文档里用的是 HTML &lt;img&gt; 标签或外链地址、图片文件名与正文写法不一致，
            或者图片只是素材而没有写进 .md / .txt 文件。
          </div>
        </el-alert>
        <el-table :data="batch.items" border stripe size="small" max-height="360">
          <el-table-column prop="relativePath" label="文件" min-width="230" show-overflow-tooltip />
          <el-table-column label="状态" width="100" align="center">
            <template #default="{ row }">
              <el-tag :type="jobStatusOf(row.status).type" size="small">
                {{ jobStatusOf(row.status).label }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="结果" min-width="230">
            <template #default="{ row }">
              <span v-if="row.status === 'succeeded'" class="muted">
                切片 {{ row.chunkCount }} 个
                <template v-if="row.imageCount">· 图片 {{ row.imageCount }} 张</template>
                <template v-if="row.unmatchedImageCount">
                  · {{ row.unmatchedImageCount }} 处图片未匹配
                </template>
              </span>
              <span v-else-if="row.errorMessage" class="error-text">{{ row.errorMessage }}</span>
              <span v-else class="muted">等待处理</span>
            </template>
          </el-table-column>
          <el-table-column label="尝试" width="70" align="center">
            <template #default="{ row }">
              <span class="muted">{{ row.attempts }}</span>
            </template>
          </el-table-column>
        </el-table>
        <el-alert
          v-if="batch.stats.failed"
          class="batch-alert"
          type="warning"
          show-icon
          :closable="false"
          title="失败的单个文件可以单独重试"
          description="重试会用暂存的原文件重新处理。如果失败原因是文件内容损坏或编码不对，请修正源文件后只重新上传这一篇。"
        />
      </template>

      <template #footer>
        <el-button @click="batchVisible = false">关闭</el-button>
        <el-button
          v-if="!batch"
          type="primary"
          :loading="batchSubmitting"
          @click="submitBatch"
        >
          开始导入
        </el-button>
        <el-button
          v-else-if="batch.stats.failed"
          type="primary"
          :loading="batchSubmitting"
          @click="retryBatch"
        >
          重试失败项
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="uploadVisible" title="上传知识文档" width="520px">
      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="按菜谱模板编写会自动生成菜谱草稿"
        class="template-hint"
      >
        <p class="muted">
          一级标题写菜名；小节使用「## 必备原料和工具」（列表写原料，厨具会被自动识别）、
          「## 计算」（如“一份正好够 2 个人食用”）、「## 操作」（编号写步骤）、
          「## 附加内容」（小贴士）。不按模板也能上传，只是需要手动在菜谱管理里新建。
        </p>
      </el-alert>
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
        <el-form-item label="图片">
          <el-upload
            multiple
            :auto-upload="false"
            :show-file-list="true"
            :limit="30"
            accept=".jpg,.jpeg,.png,.webp"
            :on-change="handleImagesChange"
            class="uploader"
          >
            <el-button>
              <el-icon><Plus /></el-icon>
              选择图片
            </el-button>
            <template #tip>
              <div class="muted form-hint">
                可选。把 Markdown 里引用的图片一起选中，系统按文件名匹配并改写地址；
                支持 JPG、PNG、WebP，单张不超过 5 MB。
              </div>
            </template>
          </el-upload>
        </el-form-item>
        <el-alert
          v-if="missingImages.length"
          type="warning"
          :closable="false"
          show-icon
          :title="`Markdown 引用了 ${missingImages.length} 张图片，还没有选择：${missingImages.join('、')}`"
          description="请在上方“图片”里选中同名文件；不上传图片时，切片预览只会显示图片地址。"
        />
        <el-alert
          v-else-if="referencedImages.length"
          type="success"
          :closable="false"
          show-icon
          :title="`已匹配 ${referencedImages.length} 张 Markdown 图片`"
        />
      </el-form>
      <template #footer>
        <el-button @click="uploadVisible = false">取消</el-button>
        <el-button type="primary" :loading="uploading" @click="submitUpload">
          上传并切片
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="indexVisible" title="新建索引" width="520px">
      <el-form label-width="120px">
        <el-form-item label="文档">
          <span>{{ indexTarget?.title }}</span>
        </el-form-item>
        <el-form-item label="切片">
          <span>{{ indexTarget?.chunkCount }} 个</span>
        </el-form-item>
        <el-form-item label="切片参数">
          <span class="muted">
            长度 {{ indexTarget?.chunkSize }} 字 / 重叠 {{ indexTarget?.chunkOverlap }} 字
          </span>
        </el-form-item>
        <el-form-item label="目标索引版本">
          <span>{{ activeVersion ? activeVersion.name : '无启用版本（将自动创建默认版本）' }}</span>
        </el-form-item>
      </el-form>
      <el-alert
        type="info"
        show-icon
        :closable="false"
        title="建立索引会调用嵌入模型生成向量"
        description="切片来自刚才的上传或重新切片；建立成功后文档状态变为「可用」，切片进入检索范围。嵌入模型不可用时状态变为「失败」，修好配置后可再次建立索引。"
      />
      <template #footer>
        <el-button @click="indexVisible = false">取消</el-button>
        <el-button type="primary" :loading="indexing" @click="submitIndex">
          建立索引
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="batchResultVisible" :title="batchResultTitle" width="560px">
      <el-table :data="batchResultItems" border max-height="360">
        <el-table-column prop="title" label="文档" min-width="160" />
        <el-table-column label="结果" min-width="240">
          <template #default="{ row }">
            <el-tag :type="row.skipped ? 'info' : 'danger'" size="small">
              {{ row.skipped ? '已跳过' : '失败' }}
            </el-tag>
            <span class="muted"> {{ row.message || '请重试' }}</span>
          </template>
        </el-table-column>
      </el-table>
      <template #footer>
        <el-button type="primary" @click="batchResultVisible = false">知道了</el-button>
      </template>
    </el-dialog>

    <el-drawer
      v-model="chunkVisible"
      :title="chunkDocument ? `切片预览 · ${chunkDocument.title}` : '切片预览'"
      size="620px"
    >
      <div v-loading="chunkLoading">
        <p class="muted">
          共 {{ chunkTotal }} 个切片，当前展示{{ chunkSource === 'draft' ? '待建立索引' : '已建立索引' }}的切片。
          每个切片开头的【文档｜章节】是检索时补的上下文头。
        </p>
        <div v-for="chunk in chunkItems" :key="chunk.id" class="chunk">
          <div class="chunk__head">
            <el-tag size="small" type="info">第 {{ chunk.ordinal + 1 }} 段</el-tag>
            <span class="muted">{{ chunk.tokenCount }} 字/词</span>
            <span v-if="chunk.metadata?.headingPath" class="muted">
              {{ chunk.metadata.headingPath }}
            </span>
          </div>
          <div class="chunk__body">
            <template v-for="(segment, segmentIndex) in contentSegments(chunk.content)" :key="segmentIndex">
              <span v-if="segment.type === 'text'">{{ segment.text }}</span>
              <img
                v-else
                class="chunk__image"
                :src="segment.url"
                :alt="segment.alt"
                loading="lazy"
              />
            </template>
          </div>
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
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
}

.toolbar__search {
  width: 260px;
}

.toolbar__status {
  width: 150px;
}

.toolbar__tag {
  margin-left: auto;
}

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}

.template-hint {
  margin-bottom: 12px;
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

/* 文件夹选择只能用原生 input，隐藏后用普通按钮触发。 */
.hidden-input {
  display: none;
}

.batch-pickers {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.batch-summary {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.batch-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.batch-label {
  font-weight: 600;
}

.batch-stats {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  margin: 12px 0;
  color: #5c6169;
  font-size: 13px;
}

.batch-alert {
  margin-top: 12px;
}

.unused-paths {
  margin: 4px 0 6px;
  padding-left: 18px;
  max-height: 140px;
  overflow-y: auto;
  font-size: 12px;
  word-break: break-all;
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

.chunk__image {
  display: block;
  max-width: 100%;
  margin: 8px 0;
  border-radius: 6px;
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
