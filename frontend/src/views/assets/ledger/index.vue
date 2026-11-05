<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import dayjs from 'dayjs'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import {
  Box,
  CircleCheck,
  Delete,
  Document,
  Download,
  Edit,
  Monitor,
  Plus,
  Refresh,
  Search,
  Upload,
  View,
} from '@element-plus/icons-vue'

import { assetApi } from '@/api/assets'
import { assetFlowApi } from '@/api/assetFlow'
import ImportDialog from '@/components/ImportDialog.vue'
import { useColumnWidths } from '@/composables/useColumnWidths'
import { useFilterMemory } from '@/composables/useFilterMemory'
import { useFormDraft } from '@/composables/useFormDraft'
import { useAuthStore } from '@/stores/auth'
import { formatDateTime } from '@/utils/format'
import type {
  AssetAttachment,
  AssetBatchUpdatePayload,
  AssetCategory,
  AssetDeptOption,
  AssetItem,
  AssetQuery,
  AssetStatus,
  AssetTimelineItem,
  CategoryField,
  CustodianOption,
} from '@/types/asset'
import type { AssetHistoryItem } from '@/types/assetFlow'
import {
  ASSET_STATUS_LABELS,
  ASSET_STATUS_TAG_TYPES,
  CATEGORY_TYPE_LABELS,
} from '@/types/asset'

interface TreeOption {
  value: number
  label: string
  disabled?: boolean
  children?: TreeOption[]
}

interface ModelOption {
  id: number
  name: string
  code: string
  brand: string | null
  status: number
}

interface AssetForm {
  asset_no: string
  name: string
  category_id: number | undefined
  model_id: number | null
  serial_no: string
  mac_address: string
  purchase_date: string
  supplier: string
  purchase_price: number | undefined
  warranty_end: string
  location: string
  dept_id: number | undefined
  custodian_id: number | undefined
  remark: string
  custom_fields: Record<string, any>
}

const auth = useAuthStore()
const route = useRoute()
const loading = ref(false)
const assets = ref<AssetItem[]>([])
const total = ref(0)

const categoryTree = ref<AssetCategory[]>([])
const deptOptions = ref<AssetDeptOption[]>([])
const filterCustodians = ref<CustodianOption[]>([])
const filterCustodianLoading = ref(false)

const query = reactive<AssetQuery>({
  page: 1,
  page_size: 20,
  keyword: '',
  category_id: undefined,
  include_child: true,
  status: undefined,
  dept_id: undefined,
  custodian_id: undefined,
  warranty_days: undefined,
})

const filterMemory = useFilterMemory('assets-ledger', query, {
  defaults: {
    page: 1,
    page_size: 20,
    keyword: '',
    category_id: undefined,
    include_child: true,
    status: undefined,
    dept_id: undefined,
    custodian_id: undefined,
    warranty_days: undefined,
  },
})
filterMemory.restore()

const columnWidths = useColumnWidths('assets-ledger')

const initialStatus = typeof route.query.status === 'string' ? route.query.status : ''
if (initialStatus && initialStatus in ASSET_STATUS_LABELS) {
  query.status = initialStatus as AssetStatus
}
const initialWarranty = Number(route.query.warranty)
if (Number.isInteger(initialWarranty) && initialWarranty > 0) {
  query.warranty_days = initialWarranty
}
const initialCategoryId = Number(route.query.category_id)
if (Number.isInteger(initialCategoryId) && initialCategoryId > 0) {
  query.category_id = initialCategoryId
}
const initialDeptId = Number(route.query.dept_id)
if (Number.isInteger(initialDeptId) && initialDeptId > 0) {
  query.dept_id = initialDeptId
}
const initialKeyword = typeof route.query.keyword === 'string' ? route.query.keyword : ''
if (initialKeyword) {
  query.keyword = initialKeyword
}

watch(
  () => route.query.keyword,
  (value) => {
    query.keyword = typeof value === 'string' ? value : ''
    query.page = 1
    void fetchAssets()
  },
)

const canCreate = computed(() => auth.hasPerm('asset:ledger:create'))
const canUpdate = computed(() => auth.hasPerm('asset:ledger:update'))
const canDelete = computed(() => auth.hasPerm('asset:ledger:delete'))
const canStockIn = computed(() => auth.hasPerm('asset:inbound:confirm'))
const canExport = computed(() => auth.hasPerm('asset:report:export'))

const categoryMap = computed(() => {
  const map = new Map<number, AssetCategory>()
  const walk = (nodes: AssetCategory[]): void => {
    nodes.forEach((node) => {
      map.set(node.id, node)
      walk(node.children)
    })
  }
  walk(categoryTree.value)
  return map
})

function toTreeOptions(nodes: AssetCategory[]): TreeOption[] {
  return nodes.map((node) => ({
    value: node.id,
    label: node.name,
    disabled: node.status !== 1,
    children: toTreeOptions(node.children),
  }))
}

const categoryOptions = computed(() => toTreeOptions(categoryTree.value))

const deptSelectOptions = computed(() =>
  deptOptions.value.map((dept) => ({
    value: dept.id,
    label: `${'· '.repeat(Math.max(0, dept.level - 1))}${dept.name}`,
  })),
)

const statusOptions = computed(() =>
  Object.entries(ASSET_STATUS_LABELS) as Array<[AssetStatus, string]>,
)

function statusTagType(status: AssetStatus) {
  return ASSET_STATUS_TAG_TYPES[status] ?? 'info'
}

const pageStatusSummary = computed(() => {
  const counter = new Map<string, number>()
  assets.value.forEach((item) => {
    const label = item.status_label || item.status
    counter.set(label, (counter.get(label) ?? 0) + 1)
  })
  return Array.from(counter.entries())
    .map(([label, count]) => `${label} ${count}`)
    .join(' · ')
})

async function loadCategories(): Promise<void> {
  categoryTree.value = await assetApi.categoryTree()
}

async function loadDepts(): Promise<void> {
  deptOptions.value = await assetApi.deptOptions()
}

async function loadCustodianDefaults(): Promise<void> {
  const options = await assetApi.custodianOptions()
  filterCustodians.value = options
  formCustodians.value = options
}

async function searchFilterCustodians(keyword: string): Promise<void> {
  filterCustodianLoading.value = true
  try {
    filterCustodians.value = await assetApi.custodianOptions(keyword || undefined)
  } finally {
    filterCustodianLoading.value = false
  }
}

async function fetchAssets(): Promise<void> {
  loading.value = true
  try {
    const page = await assetApi.listAssets({ ...query })
    assets.value = page.items
    total.value = page.total
  } finally {
    loading.value = false
  }
}

function handleSearch(): void {
  query.page = 1
  void fetchAssets()
}

function resetFilters(): void {
  filterMemory.clear()
  query.keyword = ''
  query.category_id = undefined
  query.include_child = true
  query.status = undefined
  query.dept_id = undefined
  query.custodian_id = undefined
  query.warranty_days = undefined
  query.page = 1
  void fetchAssets()
}

function clearWarrantyFilter(): void {
  query.warranty_days = undefined
  query.page = 1
  void fetchAssets()
}

function handlePageChange(page: number): void {
  query.page = page
  void fetchAssets()
}

function handleSizeChange(size: number): void {
  query.page_size = size
  query.page = 1
  void fetchAssets()
}

const tableRef = ref<{ clearSelection: () => void; doLayout?: () => void }>()
const selectedRows = ref<AssetItem[]>([])

function resetColumnWidths(): void {
  columnWidths.reset()
  void nextTick(() => tableRef.value?.doLayout?.())
}

function handleSelectionChange(rows: AssetItem[]): void {
  selectedRows.value = rows
}

function clearSelection(): void {
  tableRef.value?.clearSelection()
  selectedRows.value = []
}

interface BatchForm {
  dept_enabled: boolean
  dept_id: number | undefined
  custodian_enabled: boolean
  custodian_id: number | undefined
  location_enabled: boolean
  location: string
}

const batchVisible = ref(false)
const batchSubmitting = ref(false)
const batchForm = reactive<BatchForm>({
  dept_enabled: false,
  dept_id: undefined,
  custodian_enabled: false,
  custodian_id: undefined,
  location_enabled: false,
  location: '',
})

async function openBatch(): Promise<void> {
  if (!selectedRows.value.length) {
    ElMessage.warning('请先勾选要批量编辑的资产')
    return
  }
  batchForm.dept_enabled = false
  batchForm.dept_id = undefined
  batchForm.custodian_enabled = false
  batchForm.custodian_id = undefined
  batchForm.location_enabled = false
  batchForm.location = ''
  await loadCustodianDefaults()
  batchVisible.value = true
}

async function submitBatch(): Promise<void> {
  if (!batchForm.dept_enabled && !batchForm.custodian_enabled && !batchForm.location_enabled) {
    ElMessage.warning('请至少勾选一项要修改的字段')
    return
  }
  if (
    batchForm.dept_enabled &&
    !batchForm.dept_id &&
    batchForm.custodian_enabled &&
    batchForm.custodian_id
  ) {
    ElMessage.warning('设置责任人时不能同时清除部门')
    return
  }

  const payload: AssetBatchUpdatePayload = {
    asset_ids: selectedRows.value.map((item) => item.id),
  }
  if (batchForm.dept_enabled) {
    if (batchForm.dept_id) {
      payload.dept_id = batchForm.dept_id
    } else {
      payload.clear_dept = true
    }
  }
  if (batchForm.custodian_enabled) {
    if (batchForm.custodian_id) {
      payload.custodian_id = batchForm.custodian_id
    } else {
      payload.clear_custodian = true
    }
  }
  if (batchForm.location_enabled) {
    const location = batchForm.location.trim()
    if (location) {
      payload.location = location
    } else {
      payload.clear_location = true
    }
  }

  batchSubmitting.value = true
  try {
    const result = await assetApi.batchUpdateAssets(payload)
    ElMessage.success(`已批量更新 ${result.updated} 项资产`)
    batchVisible.value = false
    await fetchAssets()
    clearSelection()
  } finally {
    batchSubmitting.value = false
  }
}

const batchVoidVisible = ref(false)
const batchVoidSubmitting = ref(false)
const batchVoidReason = ref('')

function selectableRow(row: AssetItem): boolean {
  return row.status !== 'VOIDED'
}

function openBatchVoid(): void {
  if (!selectedRows.value.length) {
    ElMessage.warning('请先勾选要作废的资产')
    return
  }
  if (selectedRows.value.some((item) => !selectableRow(item))) {
    ElMessage.warning('已作废资产不能重复作废，请取消勾选')
    return
  }
  batchVoidReason.value = ''
  batchVoidVisible.value = true
}

async function submitBatchVoid(): Promise<void> {
  const reason = batchVoidReason.value.trim()
  if (!reason) {
    ElMessage.warning('请填写作废原因')
    return
  }
  if (reason.length > 500) {
    ElMessage.warning('作废原因不能超过 500 个字符')
    return
  }
  batchVoidSubmitting.value = true
  try {
    const result = await assetApi.batchVoidAssets({
      asset_ids: selectedRows.value.map((item) => item.id),
      reason,
    })
    ElMessage.success(`已作废 ${result.voided} 项资产，编码已释放`)
    batchVoidVisible.value = false
    await fetchAssets()
    clearSelection()
  } finally {
    batchVoidSubmitting.value = false
  }
}

const exporting = ref(false)

async function exportLedger(): Promise<void> {
  exporting.value = true
  try {
    const blob = await assetApi.exportAssets({
      keyword: query.keyword || undefined,
      category_id: query.category_id,
      include_child: query.include_child,
      status: query.status,
      dept_id: query.dept_id,
      custodian_id: query.custodian_id,
      warranty_days: query.warranty_days,
    })
    if (blob.type.includes('application/json')) {
      const body = JSON.parse(await blob.text()) as { message?: string }
      ElMessage.error(body.message || '导出台账失败')
      return
    }
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `资产台账_${dayjs().format('YYYYMMDD_HHmmss')}.xlsx`
    document.body.appendChild(link)
    link.click()
    link.remove()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
    ElMessage.success('台账已导出')
  } finally {
    exporting.value = false
  }
}

const dialogVisible = ref(false)
const dialogMode = ref<'create' | 'edit'>('create')
const dialogSubmitting = ref(false)
const editingId = ref<number | null>(null)
const editingVersion = ref(1)
const editingStatus = ref<AssetStatus>('PENDING_STOCK')
const formRef = ref<FormInstance>()
const modelOptions = ref<ModelOption[]>([])
const formCustodians = ref<CustodianOption[]>([])
const formCustodianLoading = ref(false)

function blankForm(): AssetForm {
  return {
    asset_no: '',
    name: '',
    category_id: undefined,
    model_id: null,
    serial_no: '',
    mac_address: '',
    purchase_date: '',
    supplier: '',
    purchase_price: undefined,
    warranty_end: '',
    location: '',
    dept_id: undefined,
    custodian_id: undefined,
    remark: '',
    custom_fields: {},
  }
}

const form = reactive<AssetForm>(blankForm())

const createDraft = useFormDraft('assets-create', form, {
  isMeaningful: (value) =>
    Boolean(
      value.name.trim() ||
        value.category_id ||
        value.serial_no.trim() ||
        value.supplier.trim() ||
        value.purchase_price,
    ),
})
const dialogRestored = ref(false)
const draftSavedLabel = computed(() => {
  const savedAt = createDraft.savedAt.value
  return savedAt ? dayjs(savedAt).format('MM-DD HH:mm') : ''
})

function discardCreateDraft(): void {
  createDraft.discard()
  Object.assign(form, blankForm())
  modelOptions.value = []
  dialogRestored.value = false
}

const formRules: FormRules = {
  name: [{ required: true, message: '请输入资产名称', trigger: 'blur' }],
  category_id: [{ required: true, message: '请选择资产分类', trigger: 'change' }],
  mac_address: [
    {
      pattern: /^([0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}$/,
      message: 'MAC 地址格式应为 AA:BB:CC:DD:EE:FF',
      trigger: 'blur',
    },
  ],
}

const selectedCategory = computed(() =>
  form.category_id ? categoryMap.value.get(form.category_id) : undefined,
)

const customFieldDefs = computed<CategoryField[]>(() =>
  (selectedCategory.value?.field_defs ?? [])
    .filter((field) => field.status === 1)
    .slice()
    .sort((a, b) => a.sort - b.sort),
)

function editable(field: string): boolean {
  return auth.canEditField('asset', field)
}

function viewable(field: string): boolean {
  return auth.canViewField('asset', field)
}

async function loadModels(): Promise<void> {
  if (!form.category_id) {
    modelOptions.value = []
    return
  }
  const page = await assetApi.listModels({
    page: 1,
    page_size: 200,
    category_id: form.category_id,
    include_child: false,
  })
  modelOptions.value = page.items.map((item) => ({
    id: item.id,
    name: item.name,
    code: item.code,
    brand: item.brand,
    status: item.status,
  }))
}

async function handleCategoryChange(): Promise<void> {
  form.model_id = null
  form.custom_fields = {}
  await loadModels()
}

async function searchFormCustodians(keyword: string): Promise<void> {
  formCustodianLoading.value = true
  try {
    formCustodians.value = await assetApi.custodianOptions(keyword || undefined)
  } finally {
    formCustodianLoading.value = false
  }
}

function ensureFormCustodian(id: number | null, name: string | null): void {
  if (!id || formCustodians.value.some((item) => item.id === id)) return
  formCustodians.value.unshift({
    id,
    username: '',
    real_name: name || `用户 #${id}`,
    dept_id: null,
    dept_name: null,
  })
}

async function openCreate(): Promise<void> {
  dialogMode.value = 'create'
  editingId.value = null
  editingVersion.value = 1
  Object.assign(form, blankForm())
  modelOptions.value = []
  createDraft.start()
  dialogRestored.value = createDraft.restore()
  void loadCustodianDefaults()
  if (dialogRestored.value && form.category_id) {
    await loadModels()
  }
  dialogVisible.value = true
}

async function openEdit(row: AssetItem): Promise<void> {
  createDraft.stop()
  dialogRestored.value = false
  dialogMode.value = 'edit'
  editingId.value = row.id
  editingVersion.value = row.version
  editingStatus.value = row.status
  Object.assign(form, {
    asset_no: row.asset_no,
    name: row.masked_fields.includes('name') ? '' : row.name,
    category_id: row.category_id,
    model_id: row.model_id,
    serial_no: row.serial_no ?? '',
    mac_address: row.mac_address ?? '',
    purchase_date: row.purchase_date ?? '',
    supplier: row.supplier ?? '',
    purchase_price: row.purchase_price ?? undefined,
    warranty_end: row.warranty_end ?? '',
    location: row.location ?? '',
    dept_id: row.dept_id ?? undefined,
    custodian_id: row.custodian_id ?? undefined,
    remark: row.remark ?? '',
    custom_fields: { ...(row.custom_fields ?? {}) },
  })
  ensureFormCustodian(row.custodian_id, row.custodian_name)
  await loadModels()
  if (row.model_id && !modelOptions.value.some((item) => item.id === row.model_id)) {
    modelOptions.value.unshift({
      id: row.model_id,
      name: row.model_name || `型号 #${row.model_id}`,
      code: '',
      brand: row.model_brand,
      status: 1,
    })
  }
  dialogVisible.value = true
}

function cleanedCustomFields(): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(form.custom_fields).filter(
      ([, value]) => value !== '' && value !== null && value !== undefined,
    ),
  )
}

async function submitForm(): Promise<void> {
  if (!formRef.value) return
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid || !form.category_id) return

  const text = (value: string): string | null => value.trim() || null
  const payload = {
    name: form.name.trim(),
    category_id: form.category_id,
    model_id: form.model_id ?? null,
    serial_no: text(form.serial_no),
    mac_address: text(form.mac_address),
    purchase_date: form.purchase_date || null,
    supplier: text(form.supplier),
    purchase_price: form.purchase_price ?? null,
    warranty_end: form.warranty_end || null,
    location: text(form.location),
    dept_id: form.dept_id ?? null,
    custodian_id: form.custodian_id ?? null,
    remark: text(form.remark),
    custom_fields: cleanedCustomFields(),
  }

  dialogSubmitting.value = true
  try {
    if (dialogMode.value === 'create') {
      await assetApi.createAsset({
        ...payload,
        asset_no: text(form.asset_no),
      })
      createDraft.clear()
      ElMessage.success('资产已创建，确认入库后可在领用流程中选择')
    } else if (editingId.value) {
      await assetApi.updateAsset(editingId.value, {
        ...payload,
        version: editingVersion.value,
      })
      ElMessage.success('资产信息已更新')
    }
    dialogVisible.value = false
    await fetchAssets()
  } finally {
    dialogSubmitting.value = false
  }
}

const detailVisible = ref(false)
const detailLoading = ref(false)
const detailAsset = ref<AssetItem | null>(null)
const timeline = ref<AssetTimelineItem[]>([])
const statusHistory = ref<AssetHistoryItem[]>([])

const detailCategoryFields = computed<CategoryField[]>(() => {
  if (!detailAsset.value) return []
  const category = categoryMap.value.get(detailAsset.value.category_id)
  return (category?.field_defs ?? [])
    .filter((field) => field.status === 1)
    .slice()
    .sort((a, b) => a.sort - b.sort)
})

function isMasked(field: string): boolean {
  return detailAsset.value?.masked_fields.includes(field) ?? false
}

async function openDetail(row: AssetItem): Promise<void> {
  detailVisible.value = true
  detailLoading.value = true
  detailAsset.value = row
  timeline.value = []
  statusHistory.value = []
  revokeAttachmentPreviews()
  attachments.value = []
  try {
    const [detail, events, history, files] = await Promise.all([
      assetApi.getAsset(row.id),
      assetApi.assetTimeline(row.id),
      assetFlowApi.assetHistory(row.id),
      assetApi.listAssetAttachments(row.id),
    ])
    detailAsset.value = detail
    timeline.value = events
    statusHistory.value = history
    attachments.value = files
    await Promise.all(files.map((item) => loadAttachmentPreview(item)))
  } finally {
    detailLoading.value = false
  }
}

const attachments = ref<AssetAttachment[]>([])
const uploadingAttachment = ref(false)
const attachmentInput = ref<HTMLInputElement>()
const attachmentPreviewUrls = ref<Record<number, string>>({})

const attachmentPreviewList = computed(() =>
  attachments.value
    .filter((item) => item.kind === 'IMAGE')
    .map((item) => attachmentPreviewUrls.value[item.id])
    .filter((url): url is string => Boolean(url)),
)

function revokeAttachmentPreviews(): void {
  Object.values(attachmentPreviewUrls.value).forEach((url) => URL.revokeObjectURL(url))
  attachmentPreviewUrls.value = {}
}

async function loadAttachmentPreview(item: AssetAttachment): Promise<void> {
  if (item.kind !== 'IMAGE' || attachmentPreviewUrls.value[item.id]) return
  try {
    const blob = await assetApi.downloadAssetAttachment(item.asset_id, item.id)
    if (blob.type.includes('application/json')) return
    attachmentPreviewUrls.value = {
      ...attachmentPreviewUrls.value,
      [item.id]: URL.createObjectURL(blob),
    }
  } catch {
    // 预览失败不影响附件上传与下载
  }
}

async function loadAttachments(assetId: number): Promise<void> {
  attachments.value = await assetApi.listAssetAttachments(assetId)
  await Promise.all(attachments.value.map((item) => loadAttachmentPreview(item)))
}

function handleDetailClosed(): void {
  revokeAttachmentPreviews()
  attachments.value = []
}

function triggerAttachmentUpload(): void {
  attachmentInput.value?.click()
}

async function onAttachmentPicked(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file || !detailAsset.value) return
  if (file.size > 10 * 1024 * 1024) {
    ElMessage.warning('单个附件不能超过 10MB')
    return
  }
  uploadingAttachment.value = true
  try {
    await assetApi.uploadAssetAttachment(detailAsset.value.id, file)
    ElMessage.success('附件已上传')
    await loadAttachments(detailAsset.value.id)
  } finally {
    uploadingAttachment.value = false
  }
}

async function downloadAttachmentFile(item: AssetAttachment): Promise<void> {
  const blob = await assetApi.downloadAssetAttachment(item.asset_id, item.id)
  if (blob.type.includes('application/json')) {
    const body = JSON.parse(await blob.text()) as { message?: string }
    ElMessage.error(body.message || '附件下载失败')
    return
  }
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = item.file_name
  document.body.appendChild(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

async function removeAttachment(item: AssetAttachment): Promise<void> {
  try {
    await ElMessageBox.confirm(`确定删除附件「${item.file_name}」吗？`, '删除附件', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  await assetApi.deleteAssetAttachment(item.asset_id, item.id)
  ElMessage.success('附件已删除')
  const url = attachmentPreviewUrls.value[item.id]
  if (url) {
    URL.revokeObjectURL(url)
    const next = { ...attachmentPreviewUrls.value }
    delete next[item.id]
    attachmentPreviewUrls.value = next
  }
  attachments.value = attachments.value.filter((row) => row.id !== item.id)
}

function formatFileSize(size: number): string {
  if (size >= 1024 * 1024) return `${(size / (1024 * 1024)).toFixed(1)} MB`
  if (size >= 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${size} B`
}

async function handleStockIn(row: AssetItem): Promise<void> {
  if (row.custodian_id) {
    ElMessage.warning('该资产已指定责任人，请先在编辑中清除责任人后再确认入库')
    return
  }
  try {
    await ElMessageBox.confirm(
      `确认将资产「${row.name}（${row.asset_no}）」入库？入库后可在领用流程中选择该资产。`,
      '确认入库',
      { type: 'warning', confirmButtonText: '确认入库', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  await assetApi.stockInAsset(row.id, { version: row.version })
  ElMessage.success('资产已入库')
  await fetchAssets()
}

async function handleVoid(row: AssetItem): Promise<void> {
  let reason = ''
  try {
    const result = await ElMessageBox.prompt(
      `作废资产「${row.name}（${row.asset_no}）」后，编码将被释放并可重新使用，资产记录、状态变更与审计日志全部保留。仅待入库或在库资产可直接作废。`,
      '作废资产',
      {
        type: 'warning',
        confirmButtonText: '确认作废',
        cancelButtonText: '取消',
        inputType: 'textarea',
        inputPlaceholder: '请填写作废原因（必填）',
        inputValidator: (value: string) => {
          const text = (value || '').trim()
          if (!text) return '请填写作废原因'
          if (text.length > 500) return '作废原因不能超过 500 个字符'
          return true
        },
      },
    )
    reason = result.value.trim()
  } catch {
    return
  }
  await assetApi.voidAsset(row.id, { reason, version: row.version })
  ElMessage.success('资产已作废，编码已释放')
  if (assets.value.length === 1 && query.page > 1) {
    query.page -= 1
  }
  await fetchAssets()
}

const ACTION_LABELS: Record<string, string> = {
  'asset.ledger.create': '创建资产',
  'asset.ledger.update': '编辑资产',
  'asset.ledger.stock_in': '确认入库',
  'asset.ledger.delete': '删除资产',
  'asset.ledger.void': '作废资产',
  'asset.inbound.update': '更新入库单',
  'asset.inbound.reverse': '入库冲销',
  'asset.request.create': '发起业务申请',
  'asset.request.approve': '审批通过',
  'asset.request.reject': '驳回申请',
  'asset.request.cancel': '撤销申请',
  'asset.request.outbound': '确认出库',
  'asset.request.return.create': '发起归还',
  'asset.request.return.confirm': '确认归还',
  'asset.request.due_reminder': '借用到期提醒',
  'asset.transfer.create': '发起调拨',
  'asset.transfer.approve': '审批调拨',
  'asset.transfer.reject': '驳回调拨',
  'asset.transfer.cancel': '撤销调拨',
  'asset.transfer.complete': '完成调拨',
  'asset.scrap.create': '发起报废',
  'asset.scrap.approve': '审批报废',
  'asset.scrap.reject': '驳回报废',
  'asset.scrap.cancel': '撤销报废',
  'asset.scrap.complete': '确认报废',
}

function actionLabel(action: string): string {
  return ACTION_LABELS[action] ?? action
}

function timelineType(action: string): 'success' | 'primary' | 'danger' | 'info' {
  if (
    action.endsWith('.delete') ||
    action.endsWith('.void') ||
    action.endsWith('.reject')
  ) {
    return 'danger'
  }
  if (
    action.endsWith('.return.confirm') ||
    action.endsWith('.outbound') ||
    action.endsWith('.stock_in') ||
    action.endsWith('.complete')
  ) {
    return 'success'
  }
  if (action.endsWith('.create') || action.endsWith('.update')) return 'primary'
  return 'info'
}

function formatDate(value?: string | null): string {
  return value ? dayjs(value).format('YYYY-MM-DD') : '—'
}

function formatMoney(value?: number | null): string {
  if (value === null || value === undefined) return '—'
  return `¥ ${Number(value).toLocaleString('zh-CN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`
}

function warrantyInfo(value?: string | null): {
  text: string
  type: 'success' | 'warning' | 'danger' | 'info'
} {
  if (!value) return { text: '—', type: 'info' }
  const days = dayjs(value).startOf('day').diff(dayjs().startOf('day'), 'day')
  if (days < 0) return { text: `${formatDate(value)} · 已过保`, type: 'danger' }
  if (days <= 30) return { text: `${formatDate(value)} · ${days} 天后到期`, type: 'warning' }
  return { text: formatDate(value), type: 'success' }
}

onMounted(async () => {
  await Promise.all([loadCategories(), loadDepts(), loadCustodianDefaults()])
  await fetchAssets()
})

function refreshAll(): void {
  void Promise.all([loadCategories(), loadDepts(), loadCustodianDefaults()])
  void fetchAssets()
}

const importVisible = ref(false)

function handleImported(): void {
  void fetchAssets()
}
</script>

<template>
  <div class="page ledger-page">
    <header class="page-header">
      <div>
        <p class="page-eyebrow">ASSET LEDGER</p>
        <h1 class="page-title">资产台账</h1>
        <p class="page-subtitle">
          统一维护资产编号、分类型号、购置与保管信息；状态由业务流程驱动，待入库资产可在行内确认入库。
        </p>
      </div>
      <div class="page-actions">
        <el-button :icon="Refresh" :loading="loading" @click="refreshAll">刷新数据</el-button>
        <el-button
          v-if="canExport"
          :icon="Download"
          :loading="exporting"
          @click="exportLedger"
        >
          导出台账
        </el-button>
        <el-button v-if="canCreate" :icon="Upload" @click="importVisible = true">
          导入资产
        </el-button>
        <el-button v-if="canCreate" type="primary" :icon="Plus" @click="openCreate">
          新增资产
        </el-button>
      </div>
    </header>

    <section class="surface-card ledger-panel">
      <div class="ledger-head">
        <div>
          <p class="panel-eyebrow">INVENTORY</p>
          <h2 class="panel-title">资产列表</h2>
          <p class="ledger-hint">
            共 {{ total }} 项资产<span v-if="pageStatusSummary"> · 本页 {{ pageStatusSummary }}</span>
          </p>
        </div>
        <div class="ledger-scope">
          <span class="scope-chip">{{ auth.dataScopeLabel || '数据范围' }}</span>
          <span class="scope-note">后端按数据范围收敛结果</span>
          <el-button
            v-if="columnWidths.hasSaved()"
            link
            size="small"
            class="scope-reset"
            @click="resetColumnWidths"
          >
            重置列宽
          </el-button>
        </div>
      </div>

      <div class="filter-bar">
        <el-input
          v-model="query.keyword"
          :prefix-icon="Search"
          placeholder="资产编号 / 名称 / 序列号 / MAC / 供应商"
          class="filter-keyword"
          clearable
          @keyup.enter="handleSearch"
          @clear="handleSearch"
        />
        <el-tree-select
          v-model="query.category_id"
          :data="categoryOptions"
          :props="{ label: 'label', children: 'children' }"
          node-key="value"
          placeholder="资产分类"
          class="filter-select"
          check-strictly
          clearable
          filterable
          @change="handleSearch"
        />
        <el-select
          v-model="query.status"
          placeholder="资产状态"
          class="filter-select filter-status"
          clearable
          @change="handleSearch"
        >
          <el-option
            v-for="[value, label] in statusOptions"
            :key="value"
            :label="label"
            :value="value"
          />
        </el-select>
        <el-select
          v-model="query.dept_id"
          placeholder="所属部门"
          class="filter-select"
          clearable
          filterable
          @change="handleSearch"
        >
          <el-option
            v-for="dept in deptSelectOptions"
            :key="dept.value"
            :label="dept.label"
            :value="dept.value"
          />
        </el-select>
        <el-select
          v-model="query.custodian_id"
          placeholder="责任人"
          class="filter-select"
          clearable
          filterable
          remote
          :remote-method="searchFilterCustodians"
          :loading="filterCustodianLoading"
          @change="handleSearch"
        >
          <el-option
            v-for="person in filterCustodians"
            :key="person.id"
            :label="person.real_name"
            :value="person.id"
          >
            <span>{{ person.real_name }}</span>
            <span class="option-sub">{{ person.dept_name || person.username }}</span>
          </el-option>
        </el-select>
        <el-checkbox v-model="query.include_child" @change="handleSearch">
          含下级分类
        </el-checkbox>
        <div class="filter-actions">
          <el-button :icon="Search" @click="handleSearch">查询</el-button>
          <el-button text @click="resetFilters">重置</el-button>
        </div>
      </div>

      <div v-if="query.warranty_days" class="quick-filter">
        <el-tag type="warning" closable effect="light" @close="clearWarrantyFilter">
          {{ query.warranty_days }} 天内保修到期
        </el-tag>
        <span>仅显示未报废且保修即将到期的资产</span>
      </div>

      <div v-if="canUpdate && selectedRows.length" class="batch-bar">
        <span class="batch-count">已选择 {{ selectedRows.length }} 项资产</span>
        <el-button type="primary" plain :icon="Edit" @click="openBatch">批量编辑</el-button>
        <el-button
          v-if="canDelete"
          type="danger"
          plain
          :icon="Delete"
          @click="openBatchVoid"
        >
          批量作废
        </el-button>
        <el-button text @click="clearSelection">清空选择</el-button>
      </div>

      <el-table
        ref="tableRef"
        v-loading="loading"
        :data="assets"
        row-key="id"
        border
        class="asset-table"
        empty-text="暂无符合条件的资产"
        @selection-change="handleSelectionChange"
        @header-dragend="columnWidths.onHeaderDragend"
      >
        <el-table-column
          v-if="canUpdate"
          type="selection"
          width="46"
          fixed="left"
          :selectable="selectableRow"
        />
        <el-table-column
          label="资产"
          column-key="asset"
          :width="columnWidths.widthOf('asset')"
          min-width="230"
        >
          <template #default="{ row }">
            <div class="asset-cell">
              <span class="asset-icon"><el-icon><Monitor /></el-icon></span>
              <span class="asset-identity">
                <span class="asset-name">{{ row.name }}</span>
                <span class="asset-no">{{ row.asset_no }}</span>
              </span>
            </div>
          </template>
        </el-table-column>

        <el-table-column
          label="分类 / 型号"
          column-key="category"
          :width="columnWidths.widthOf('category')"
          min-width="180"
        >
          <template #default="{ row }">
            <div class="stack-cell">
              <span>{{ row.category_name || '未分类' }}</span>
              <small>{{ row.model_name || '未指定型号' }}</small>
            </div>
          </template>
        </el-table-column>

        <el-table-column
          label="责任人 / 部门"
          column-key="dept"
          :width="columnWidths.widthOf('dept')"
          min-width="170"
        >
          <template #default="{ row }">
            <div class="stack-cell">
              <span>{{ row.custodian_name || '未指定责任人' }}</span>
              <small>{{ row.dept_name || '未分配部门' }}</small>
            </div>
          </template>
        </el-table-column>

        <el-table-column
          label="存放位置"
          column-key="location"
          :width="columnWidths.widthOf('location')"
          min-width="120"
        >
          <template #default="{ row }">
            <span class="muted-value">{{ row.location || '—' }}</span>
          </template>
        </el-table-column>

        <el-table-column
          label="购置 / 价格"
          column-key="purchase"
          :width="columnWidths.widthOf('purchase')"
          min-width="150"
        >
          <template #default="{ row }">
            <div class="stack-cell">
              <span>{{ formatMoney(row.purchase_price) }}</span>
              <small>{{ formatDate(row.purchase_date) }}</small>
            </div>
          </template>
        </el-table-column>

        <el-table-column
          label="保修到期"
          column-key="warranty"
          :width="columnWidths.widthOf('warranty') ?? 150"
        >
          <template #default="{ row }">
            <el-tag
              v-if="row.warranty_end"
              :type="warrantyInfo(row.warranty_end).type"
              effect="plain"
              size="small"
              round
            >
              {{ warrantyInfo(row.warranty_end).text }}
            </el-tag>
            <span v-else class="muted-value">—</span>
          </template>
        </el-table-column>

        <el-table-column
          label="状态"
          column-key="status"
          :width="columnWidths.widthOf('status') ?? 100"
        >
          <template #default="{ row }">
            <el-tag :type="statusTagType(row.status)" effect="light" round>
              {{ row.status_label }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column label="操作" width="252" fixed="right">
          <template #default="{ row }">
            <div class="row-actions">
              <el-button link type="primary" :icon="View" @click="openDetail(row)">详情</el-button>
              <el-button
                v-if="canStockIn && row.status === 'PENDING_STOCK'"
                link
                type="success"
                :icon="CircleCheck"
                @click="handleStockIn(row)"
              >
                入库
              </el-button>
              <el-button
                v-if="canUpdate && row.status !== 'VOIDED'"
                link
                type="primary"
                :icon="Edit"
                @click="openEdit(row)"
              >
                编辑
              </el-button>
              <el-button
                v-if="canDelete && row.status !== 'VOIDED'"
                link
                type="danger"
                :icon="Delete"
                @click="handleVoid(row)"
              >
                作废
              </el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>

      <div class="table-footer">
        <el-pagination
          :current-page="query.page"
          :page-size="query.page_size"
          :page-sizes="[10, 20, 50, 100]"
          :total="total"
          layout="total, sizes, prev, pager, next, jumper"
          background
          @current-change="handlePageChange"
          @size-change="handleSizeChange"
        />
      </div>
    </section>

    <el-dialog
      v-model="dialogVisible"
      :title="dialogMode === 'create' ? '新增资产' : '编辑资产'"
      width="880px"
      class="asset-dialog"
      destroy-on-close
      :close-on-click-modal="false"
      @closed="createDraft.stop()"
    >
      <el-alert
        v-if="dialogRestored"
        type="info"
        :closable="false"
        show-icon
        class="draft-alert"
      >
        <template #title>
          已恢复 {{ draftSavedLabel }} 保存的草稿
          <el-button link type="primary" size="small" @click="discardCreateDraft">
            放弃草稿
          </el-button>
        </template>
      </el-alert>
      <el-form ref="formRef" :model="form" :rules="formRules" label-position="top">
        <div class="form-section">
          <div class="form-section-head">
            <span class="form-section-title">基础信息</span>
            <el-tag
              v-if="dialogMode === 'edit'"
              :type="ASSET_STATUS_TAG_TYPES[editingStatus]"
              size="small"
              round
            >
              {{ ASSET_STATUS_LABELS[editingStatus] }}
            </el-tag>
            <span v-else class="form-section-note">创建后状态为「待入库」，点击行内「入库」后可在领用流程中选择</span>
          </div>
          <div class="form-grid">
            <el-form-item label="资产名称" prop="name">
              <el-input
                v-model="form.name"
                maxlength="120"
                placeholder="如：研发部 MacBook Pro"
                :disabled="dialogMode === 'edit' && !editable('name')"
              />
            </el-form-item>
            <el-form-item label="资产编号">
              <el-input
                v-if="dialogMode === 'create'"
                v-model="form.asset_no"
                maxlength="50"
                placeholder="留空则按规则自动生成"
              />
              <el-input v-else v-model="form.asset_no" disabled />
            </el-form-item>
            <el-form-item label="资产分类" prop="category_id">
              <el-tree-select
                v-model="form.category_id"
                :data="categoryOptions"
                :props="{ label: 'label', children: 'children' }"
                node-key="value"
                placeholder="选择资产分类"
                check-strictly
                filterable
                default-expand-all
                @change="handleCategoryChange"
              />
            </el-form-item>
            <el-form-item label="资产型号">
              <el-select
                v-model="form.model_id"
                placeholder="可选，先选择分类"
                clearable
                filterable
                :disabled="!form.category_id"
              >
                <el-option
                  v-for="model in modelOptions"
                  :key="model.id"
                  :label="model.brand ? `${model.name} · ${model.brand}` : model.name"
                  :value="model.id"
                  :disabled="model.status !== 1"
                >
                  <span>{{ model.name }}</span>
                  <span class="option-sub">{{ model.code }}</span>
                </el-option>
              </el-select>
            </el-form-item>
            <el-form-item v-if="viewable('serial_no')" label="序列号">
              <el-input
                v-model="form.serial_no"
                maxlength="120"
                placeholder="设备序列号 / SN"
                :disabled="!editable('serial_no')"
              />
            </el-form-item>
            <el-form-item v-if="viewable('mac_address')" label="MAC 地址">
              <el-input
                v-model="form.mac_address"
                maxlength="64"
                placeholder="AA:BB:CC:DD:EE:FF"
                :disabled="!editable('mac_address')"
              />
            </el-form-item>
          </div>
        </div>

        <div class="form-section">
          <div class="form-section-head">
            <span class="form-section-title">购置与保修</span>
          </div>
          <div class="form-grid">
            <el-form-item v-if="viewable('purchase_date')" label="购置日期">
              <el-date-picker
                v-model="form.purchase_date"
                type="date"
                value-format="YYYY-MM-DD"
                placeholder="选择日期"
                :disabled="!editable('purchase_date')"
              />
            </el-form-item>
            <el-form-item v-if="viewable('purchase_price')" label="采购价格（元）">
              <el-input-number
                v-model="form.purchase_price"
                :min="0"
                :max="9999999999"
                :precision="2"
                :controls="false"
                placeholder="0.00"
                :disabled="!editable('purchase_price')"
              />
            </el-form-item>
            <el-form-item v-if="viewable('supplier')" label="供应商">
              <el-input
                v-model="form.supplier"
                maxlength="120"
                placeholder="供应商名称"
                :disabled="!editable('supplier')"
              />
            </el-form-item>
            <el-form-item v-if="viewable('warranty_end')" label="保修到期">
              <el-date-picker
                v-model="form.warranty_end"
                type="date"
                value-format="YYYY-MM-DD"
                placeholder="选择日期"
                :disabled="!editable('warranty_end')"
              />
            </el-form-item>
          </div>
        </div>

        <div class="form-section">
          <div class="form-section-head">
            <span class="form-section-title">保管信息</span>
          </div>
          <div class="form-grid">
            <el-form-item label="所属部门">
              <el-select
                v-model="form.dept_id"
                placeholder="选择部门"
                clearable
                filterable
              >
                <el-option
                  v-for="dept in deptSelectOptions"
                  :key="dept.value"
                  :label="dept.label"
                  :value="dept.value"
                />
              </el-select>
            </el-form-item>
            <el-form-item v-if="viewable('custodian_id')" label="责任人">
              <el-select
                v-model="form.custodian_id"
                placeholder="搜索姓名 / 用户名 / 工号"
                clearable
                filterable
                remote
                :remote-method="searchFormCustodians"
                :loading="formCustodianLoading"
                :disabled="!editable('custodian_id')"
              >
                <el-option
                  v-for="person in formCustodians"
                  :key="person.id"
                  :label="person.real_name"
                  :value="person.id"
                >
                  <span>{{ person.real_name }}</span>
                  <span class="option-sub">{{ person.dept_name || person.username }}</span>
                </el-option>
              </el-select>
            </el-form-item>
            <el-form-item v-if="viewable('location')" label="存放位置">
              <el-input
                v-model="form.location"
                maxlength="120"
                placeholder="如：A 座 3 层机房"
                :disabled="!editable('location')"
              />
            </el-form-item>
          </div>
        </div>

        <div v-if="customFieldDefs.length" class="form-section">
          <div class="form-section-head">
            <span class="form-section-title">扩展字段</span>
            <span class="form-section-note">
              {{ selectedCategory?.name }} · {{ customFieldDefs.length }} 个字段
            </span>
          </div>
          <div class="form-grid">
            <el-form-item
              v-for="field in customFieldDefs"
              :key="field.id"
              :label="field.name"
              :required="field.required"
            >
              <el-select
                v-if="field.field_type === 'SELECT'"
                v-model="form.custom_fields[field.field_key]"
                :placeholder="`选择${field.name}`"
                clearable
              >
                <el-option
                  v-for="option in field.options ?? []"
                  :key="option"
                  :label="option"
                  :value="option"
                />
              </el-select>
              <el-input-number
                v-else-if="field.field_type === 'NUMBER'"
                v-model="form.custom_fields[field.field_key]"
                :controls="false"
                :placeholder="`输入${field.name}`"
              />
              <el-date-picker
                v-else-if="field.field_type === 'DATE'"
                v-model="form.custom_fields[field.field_key]"
                type="date"
                value-format="YYYY-MM-DD"
                :placeholder="`选择${field.name}`"
              />
              <el-input
                v-else
                v-model="form.custom_fields[field.field_key]"
                maxlength="500"
                :placeholder="`输入${field.name}`"
              />
            </el-form-item>
          </div>
        </div>

        <div v-if="viewable('remark')" class="form-section last">
          <el-form-item label="备注">
            <el-input
              v-model="form.remark"
              type="textarea"
              :rows="3"
              maxlength="255"
              show-word-limit
              placeholder="补充说明"
              :disabled="!editable('remark')"
            />
          </el-form-item>
        </div>
      </el-form>

      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="dialogSubmitting" @click="submitForm">
          {{ dialogMode === 'create' ? '创建资产' : '保存修改' }}
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="batchVisible"
      title="批量编辑资产"
      width="560px"
      destroy-on-close
      :close-on-click-modal="false"
    >
      <el-alert
        type="warning"
        :closable="false"
        show-icon
        :title="`将同时更新 ${selectedRows.length} 项资产，每项资产都会写入审计日志，操作不可撤销。`"
      />
      <el-form label-position="top" class="batch-form">
        <el-form-item>
          <template #label>
            <el-checkbox v-model="batchForm.dept_enabled">调整所属部门</el-checkbox>
          </template>
          <el-select
            v-model="batchForm.dept_id"
            :disabled="!batchForm.dept_enabled"
            placeholder="选择部门；留空表示清除部门"
            clearable
            filterable
          >
            <el-option
              v-for="dept in deptSelectOptions"
              :key="dept.value"
              :label="dept.label"
              :value="dept.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item>
          <template #label>
            <el-checkbox v-model="batchForm.custodian_enabled">调整责任人</el-checkbox>
          </template>
          <el-select
            v-model="batchForm.custodian_id"
            :disabled="!batchForm.custodian_enabled"
            placeholder="搜索姓名 / 用户名 / 工号；留空表示清除责任人"
            clearable
            filterable
            remote
            :remote-method="searchFormCustodians"
            :loading="formCustodianLoading"
          >
            <el-option
              v-for="person in formCustodians"
              :key="person.id"
              :label="person.real_name"
              :value="person.id"
            >
              <span>{{ person.real_name }}</span>
              <span class="option-sub">{{ person.dept_name || person.username }}</span>
            </el-option>
          </el-select>
        </el-form-item>
        <el-form-item>
          <template #label>
            <el-checkbox v-model="batchForm.location_enabled">调整存放位置</el-checkbox>
          </template>
          <el-input
            v-model="batchForm.location"
            :disabled="!batchForm.location_enabled"
            maxlength="120"
            placeholder="如：A 座 3 层机房；留空表示清除位置"
          />
        </el-form-item>
      </el-form>
      <p class="batch-note">同时设置责任人时，未指定部门将自动跟随责任人所在部门。</p>
      <template #footer>
        <el-button @click="batchVisible = false">取消</el-button>
        <el-button type="primary" :loading="batchSubmitting" @click="submitBatch">
          确认批量更新
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="batchVoidVisible"
      title="批量作废资产"
      width="520px"
      :close-on-click-modal="false"
    >
      <el-alert
        type="warning"
        :closable="false"
        show-icon
        :title="`将作废 ${selectedRows.length} 项资产，编码会释放并可重新使用，记录与审计日志保留。仅待入库或在库资产可作废，存在处理中业务的资产会被拦截。`"
      />
      <el-input
        v-model="batchVoidReason"
        type="textarea"
        :rows="3"
        maxlength="500"
        show-word-limit
        placeholder="请填写作废原因（必填）"
        class="batch-void-reason"
      />
      <template #footer>
        <el-button @click="batchVoidVisible = false">取消</el-button>
        <el-button
          type="danger"
          :loading="batchVoidSubmitting"
          @click="submitBatchVoid"
        >
          确认作废
        </el-button>
      </template>
    </el-dialog>

    <el-drawer
      v-model="detailVisible"
      size="540px"
      class="asset-drawer"
      :with-header="false"
      destroy-on-close
      @closed="handleDetailClosed"
    >
      <div v-loading="detailLoading" class="detail-body">
        <div class="detail-hero">
          <span class="detail-icon"><el-icon><Box /></el-icon></span>
          <div class="detail-heading">
            <h3>{{ detailAsset?.name || '资产详情' }}</h3>
            <p>{{ detailAsset?.asset_no || '—' }}</p>
          </div>
          <el-tag
            v-if="detailAsset"
            :type="ASSET_STATUS_TAG_TYPES[detailAsset.status]"
            effect="light"
            round
          >
            {{ detailAsset.status_label }}
          </el-tag>
          <el-button text class="detail-close" @click="detailVisible = false">关闭</el-button>
        </div>

        <template v-if="detailAsset">
          <div v-if="detailAsset.masked_fields.length" class="masked-banner">
            部分字段受角色字段权限限制，已隐藏不可见内容。
          </div>

          <div class="detail-section">
            <p class="detail-section-title">基础信息</p>
            <el-descriptions :column="2" border size="small">
              <el-descriptions-item label="资产编号">{{ detailAsset.asset_no }}</el-descriptions-item>
              <el-descriptions-item label="资产分类">
                {{ detailAsset.category_name || '—' }}
                <span v-if="detailAsset.category_type" class="type-note">
                  {{ CATEGORY_TYPE_LABELS[detailAsset.category_type] }}
                </span>
              </el-descriptions-item>
              <el-descriptions-item label="型号">
                {{ detailAsset.model_name || '—' }}
              </el-descriptions-item>
              <el-descriptions-item label="序列号">
                <span v-if="isMasked('serial_no')" class="masked">无权查看</span>
                <template v-else>{{ detailAsset.serial_no || '—' }}</template>
              </el-descriptions-item>
              <el-descriptions-item label="MAC 地址">
                <span v-if="isMasked('mac_address')" class="masked">无权查看</span>
                <template v-else>{{ detailAsset.mac_address || '—' }}</template>
              </el-descriptions-item>
              <el-descriptions-item label="存放位置">
                <span v-if="isMasked('location')" class="masked">无权查看</span>
                <template v-else>{{ detailAsset.location || '—' }}</template>
              </el-descriptions-item>
            </el-descriptions>
          </div>

          <div class="detail-section">
            <p class="detail-section-title">购置与保修</p>
            <el-descriptions :column="2" border size="small">
              <el-descriptions-item label="购置日期">
                {{ formatDate(detailAsset.purchase_date) }}
              </el-descriptions-item>
              <el-descriptions-item label="采购价格">
                <span v-if="isMasked('purchase_price')" class="masked">无权查看</span>
                <template v-else>{{ formatMoney(detailAsset.purchase_price) }}</template>
              </el-descriptions-item>
              <el-descriptions-item label="供应商">
                <span v-if="isMasked('supplier')" class="masked">无权查看</span>
                <template v-else>{{ detailAsset.supplier || '—' }}</template>
              </el-descriptions-item>
              <el-descriptions-item label="保修到期">
                {{ formatDate(detailAsset.warranty_end) }}
              </el-descriptions-item>
            </el-descriptions>
          </div>

          <div class="detail-section">
            <p class="detail-section-title">保管信息</p>
            <el-descriptions :column="2" border size="small">
              <el-descriptions-item label="所属部门">
                {{ detailAsset.dept_name || '未分配部门' }}
              </el-descriptions-item>
              <el-descriptions-item label="责任人">
                <span v-if="isMasked('custodian_id')" class="masked">无权查看</span>
                <template v-else>{{ detailAsset.custodian_name || '未指定' }}</template>
              </el-descriptions-item>
              <el-descriptions-item label="创建时间">
                {{ formatDateTime(detailAsset.created_at) }}
              </el-descriptions-item>
              <el-descriptions-item label="最近更新">
                {{ formatDateTime(detailAsset.updated_at) }}
              </el-descriptions-item>
              <el-descriptions-item label="备注" :span="2">
                <span v-if="isMasked('remark')" class="masked">无权查看</span>
                <template v-else>{{ detailAsset.remark || '—' }}</template>
              </el-descriptions-item>
            </el-descriptions>
          </div>

          <div v-if="detailAsset.status === 'VOIDED'" class="detail-section">
            <p class="detail-section-title">作废信息</p>
            <el-descriptions :column="2" border size="small">
              <el-descriptions-item label="作废时间">
                {{ detailAsset.voided_at ? formatDateTime(detailAsset.voided_at) : '—' }}
              </el-descriptions-item>
              <el-descriptions-item label="作废人">
                {{ detailAsset.voided_by_name || '系统' }}
              </el-descriptions-item>
              <el-descriptions-item label="作废原因" :span="2">
                {{ detailAsset.void_reason || '—' }}
              </el-descriptions-item>
            </el-descriptions>
            <p class="batch-note">该资产编码已释放，可重新登记使用；历史记录与审计日志保留。</p>
          </div>

          <div v-if="detailCategoryFields.length" class="detail-section">
            <p class="detail-section-title">扩展字段</p>
            <el-descriptions :column="2" border size="small">
              <el-descriptions-item
                v-for="field in detailCategoryFields"
                :key="field.id"
                :label="field.name"
              >
                {{ detailAsset.custom_fields[field.field_key] ?? '—' }}
              </el-descriptions-item>
            </el-descriptions>
          </div>

          <div class="detail-section">
            <div class="attachment-head">
              <p class="detail-section-title">图片与附件</p>
              <div class="attachment-head-actions">
                <span class="attachment-count">{{ attachments.length }} 个文件</span>
                <el-button
                  v-if="canUpdate"
                  size="small"
                  :icon="Upload"
                  :loading="uploadingAttachment"
                  @click="triggerAttachmentUpload"
                >
                  上传附件
                </el-button>
              </div>
            </div>
            <input
              ref="attachmentInput"
              type="file"
              class="attachment-input"
              accept=".jpg,.jpeg,.png,.gif,.webp,.bmp,.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.csv,.zip,.rar,.7z"
              @change="onAttachmentPicked"
            />
            <div v-if="attachments.length" class="attachment-grid">
              <div v-for="item in attachments" :key="item.id" class="attachment-card">
                <el-image
                  v-if="item.kind === 'IMAGE' && attachmentPreviewUrls[item.id]"
                  :src="attachmentPreviewUrls[item.id]"
                  :preview-src-list="attachmentPreviewList"
                  :initial-index="
                    Math.max(0, attachmentPreviewList.indexOf(attachmentPreviewUrls[item.id]))
                  "
                  fit="cover"
                  preview-teleported
                  class="attachment-thumb"
                />
                <span v-else class="attachment-file-icon">
                  <el-icon><Document /></el-icon>
                </span>
                <div class="attachment-meta">
                  <span>{{ item.file_name }}</span>
                  <small>
                    {{ formatFileSize(item.file_size) }} ·
                    {{ item.uploaded_by_name || '系统' }}
                  </small>
                </div>
                <div class="attachment-actions">
                  <el-button link type="primary" @click="downloadAttachmentFile(item)">
                    下载
                  </el-button>
                  <el-button
                    v-if="canUpdate"
                    link
                    type="danger"
                    @click="removeAttachment(item)"
                  >
                    删除
                  </el-button>
                </div>
              </div>
            </div>
            <p v-else class="timeline-empty">
              暂无图片或附件，支持图片与常见文档，单个文件不超过 10MB。
            </p>
          </div>

          <div class="detail-section">
            <p class="detail-section-title">状态变更记录</p>
            <el-timeline v-if="statusHistory.length" class="asset-timeline">
              <el-timeline-item
                v-for="record in statusHistory"
                :key="record.id"
                :timestamp="formatDateTime(record.created_at)"
                :type="record.to_status === 'IN_STOCK' ? 'success' : 'primary'"
                placement="top"
              >
                <div class="timeline-title">{{ record.action_label }}</div>
                <div class="status-shift">
                  <el-tag size="small" effect="plain">{{ record.from_status_label }}</el-tag>
                  <span>→</span>
                  <el-tag size="small" type="success" effect="light">
                    {{ record.to_status_label }}
                  </el-tag>
                </div>
                <div class="timeline-summary">{{ record.summary || '—' }}</div>
                <div class="timeline-user">
                  责任人：{{ record.before_snapshot.custodian_name || '无' }} →
                  {{ record.after_snapshot.custodian_name || '无' }}
                </div>
                <div class="timeline-user">操作人：{{ record.operator_name || '系统' }}</div>
              </el-timeline-item>
            </el-timeline>
            <p v-else class="timeline-empty">暂无状态变更记录，资产状态由业务流程驱动</p>
          </div>

          <div class="detail-section">
            <p class="detail-section-title">操作时间线</p>
            <el-timeline v-if="timeline.length" class="asset-timeline">
              <el-timeline-item
                v-for="item in timeline"
                :key="item.id"
                :timestamp="formatDateTime(item.created_at)"
                :type="timelineType(item.action)"
                placement="top"
              >
                <div class="timeline-title">{{ actionLabel(item.action) }}</div>
                <div class="timeline-summary">{{ item.summary || '—' }}</div>
                <div class="timeline-user">操作人：{{ item.username || '系统' }}</div>
              </el-timeline-item>
            </el-timeline>
            <p v-else class="timeline-empty">暂无操作记录</p>
          </div>
        </template>
      </div>
    </el-drawer>

    <ImportDialog v-model="importVisible" kind="assets" @imported="handleImported" />
  </div>
</template>

<style scoped>
.ledger-panel {
  padding: 20px;
}

.ledger-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 18px;
  margin-bottom: 16px;
}

.panel-eyebrow {
  margin: 0 0 4px;
  font-size: 10.5px;
  font-weight: 700;
  letter-spacing: 0.16em;
  color: var(--brand);
}

.panel-title {
  margin: 0;
  font-size: 17px;
  font-weight: 700;
  letter-spacing: -0.01em;
  color: var(--text-1);
}

.ledger-hint {
  margin: 6px 0 0;
  font-size: 12.5px;
  color: var(--text-3);
}

.ledger-scope {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 4px;
}

.scope-chip {
  padding: 3px 10px;
  border-radius: 999px;
  background: var(--brand-soft);
  color: var(--brand);
  font-size: 11.5px;
  font-weight: 600;
}

.scope-note {
  font-size: 11.5px;
  color: var(--text-3);
}

.scope-reset {
  padding: 0;
  height: auto;
}

.draft-alert {
  margin-bottom: 14px;
}

.draft-alert :deep(.el-alert__title) {
  display: flex;
  align-items: center;
  gap: 6px;
}

.filter-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  padding: 14px;
  margin-bottom: 16px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--surface-muted);
}

.filter-keyword {
  width: 250px;
}

.filter-select {
  width: 168px;
}

.filter-actions {
  display: flex;
  gap: 6px;
  margin-left: auto;
}

.quick-filter {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: -6px 0 14px;
  color: var(--text-3);
  font-size: 11.5px;
}

.batch-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  margin-bottom: 14px;
  border: 1px solid color-mix(in srgb, var(--brand) 28%, transparent);
  border-radius: var(--radius-md);
  background: var(--brand-soft);
}

.batch-count {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--brand);
}

.batch-form {
  margin-top: 16px;
}

.batch-form :deep(.el-form-item) {
  margin-bottom: 14px;
}

.batch-form :deep(.el-select) {
  width: 100%;
}

.batch-note {
  margin: 0;
  font-size: 11.5px;
  color: var(--text-3);
}

.batch-void-reason {
  margin-top: 14px;
}

.asset-cell {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.asset-icon {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  flex-shrink: 0;
  border-radius: 10px;
  background: var(--brand-soft);
  color: var(--brand);
}

.asset-identity {
  display: flex;
  flex-direction: column;
  min-width: 0;
  line-height: 1.35;
}

.asset-name {
  font-weight: 600;
  color: var(--text-1);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.asset-no {
  font-family: var(--font-number);
  font-size: 11.5px;
  color: var(--text-3);
  letter-spacing: 0.02em;
}

.stack-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
  line-height: 1.4;
  min-width: 0;
}

.stack-cell span {
  color: var(--text-1);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.stack-cell small {
  font-size: 11.5px;
  color: var(--text-3);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.muted-value {
  color: var(--text-3);
}

.option-sub {
  margin-left: 10px;
  color: var(--text-3);
  font-size: 11.5px;
}

.row-actions {
  display: flex;
  align-items: center;
  gap: 2px;
  flex-wrap: nowrap;
}

.row-actions :deep(.el-button + .el-button) {
  margin-left: 4px;
}

.table-footer {
  display: flex;
  justify-content: flex-end;
  padding-top: 16px;
}

.form-section {
  padding-bottom: 6px;
  margin-bottom: 14px;
  border-bottom: 1px dashed var(--border);
}

.form-section.last {
  border-bottom: none;
  margin-bottom: 0;
}

.form-section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.form-section-title {
  font-size: 13px;
  font-weight: 700;
  color: var(--text-1);
  letter-spacing: 0.01em;
}

.form-section-note {
  font-size: 11.5px;
  color: var(--text-3);
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 16px;
}

.form-grid :deep(.el-date-editor.el-input),
.form-grid :deep(.el-input-number) {
  width: 100%;
}

.detail-body {
  min-height: 200px;
}

.detail-hero {
  display: flex;
  align-items: center;
  gap: 12px;
  padding-bottom: 16px;
  margin-bottom: 16px;
  border-bottom: 1px solid var(--border);
}

.detail-icon {
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  border-radius: 13px;
  background: var(--gradient-brand-soft);
  color: var(--brand);
  font-size: 20px;
}

.detail-heading {
  flex: 1;
  min-width: 0;
}

.detail-heading h3 {
  margin: 0;
  font-size: 18px;
  font-weight: 700;
  color: var(--text-1);
}

.detail-heading p {
  margin: 2px 0 0;
  font-family: var(--font-number);
  font-size: 12px;
  color: var(--text-3);
  letter-spacing: 0.04em;
}

.detail-close {
  align-self: flex-start;
}

.masked-banner {
  padding: 9px 12px;
  margin-bottom: 16px;
  border: 1px solid color-mix(in srgb, var(--warning) 30%, transparent);
  border-radius: 10px;
  background: color-mix(in srgb, var(--warning) 10%, transparent);
  color: color-mix(in srgb, var(--warning) 78%, var(--text-1));
  font-size: 12px;
}

.detail-section {
  margin-bottom: 18px;
}

.detail-section-title {
  margin: 0 0 8px;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.08em;
  color: var(--text-2);
  text-transform: uppercase;
}

.type-note {
  margin-left: 6px;
  font-size: 11px;
  color: var(--text-3);
}

.masked {
  color: var(--text-3);
  font-style: italic;
}

.attachment-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}

.attachment-head .detail-section-title {
  margin-bottom: 0;
}

.attachment-head-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.attachment-count {
  font-size: 11.5px;
  color: var(--text-3);
}

.attachment-input {
  display: none;
}

.attachment-grid {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.attachment-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--surface-muted);
}

.attachment-thumb {
  width: 48px;
  height: 48px;
  flex-shrink: 0;
  border-radius: 8px;
  cursor: zoom-in;
}

.attachment-file-icon {
  display: grid;
  place-items: center;
  width: 48px;
  height: 48px;
  flex-shrink: 0;
  border-radius: 8px;
  background: var(--brand-soft);
  color: var(--brand);
  font-size: 20px;
}

.attachment-meta {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.attachment-meta span {
  font-size: 12.5px;
  color: var(--text-1);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.attachment-meta small {
  font-size: 11px;
  color: var(--text-3);
}

.attachment-actions {
  display: flex;
  flex-shrink: 0;
  align-items: center;
}

.asset-timeline {
  padding: 4px 0 0 2px;
}

.timeline-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-1);
}

.timeline-summary {
  margin-top: 2px;
  font-size: 12.5px;
  color: var(--text-2);
}

.timeline-user {
  margin-top: 2px;
  font-size: 11.5px;
  color: var(--text-3);
}

.status-shift {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 6px;
  color: var(--text-3);
  font-size: 12px;
}

.timeline-empty {
  padding: 10px 0;
  font-size: 12.5px;
  color: var(--text-3);
}

:deep(.asset-table .el-table__cell) {
  padding: 11px 0;
}

:deep(.asset-table.el-table--border .el-table__cell) {
  border-right-color: color-mix(in srgb, var(--border) 55%, transparent);
}

@media (max-width: 1180px) {
  .filter-keyword {
    width: 100%;
  }

  .filter-select {
    width: calc(50% - 5px);
  }

  .filter-actions {
    width: 100%;
    margin-left: 0;
  }
}

@media (max-width: 820px) {
  .ledger-head {
    flex-direction: column;
  }

  .ledger-scope {
    align-items: flex-start;
  }

  .form-grid {
    grid-template-columns: 1fr;
  }

  .form-grid :deep(.el-form-item) {
    grid-column: span 1;
  }

  .filter-select {
    width: 100%;
  }
}
</style>
