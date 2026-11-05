<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh, Search } from '@element-plus/icons-vue'

import { inboundApi } from '@/api/inbound'
import { useFilterMemory } from '@/composables/useFilterMemory'
import { useAuthStore } from '@/stores/auth'
import type {
  Inbound,
  InboundAsset,
  InboundCategoryOption,
  InboundDeptOption,
  InboundItem,
  InboundItemPayload,
  InboundModelOption,
  InboundStatus,
  InboundType,
} from '@/types/inbound'
import {
  INBOUND_STATUS_LABELS,
  INBOUND_TYPE_LABELS,
  inboundActive,
  inboundSteps,
  isInboundInterrupted,
} from '@/types/inbound'
import { formatDateTime } from '@/utils/format'

interface LineForm {
  key: number
  category_id: number | undefined
  model_id: number | undefined
  name: string
  quantity: number
  base_asset_no: string
  asset_nos: string[]
  codes_edited: boolean
  unit_price: number | undefined
  warranty_end: string
  remark: string
}

const ASSET_NO_RE = /^[A-Za-z0-9][A-Za-z0-9._-]{2,49}$/
const BASE_ASSET_NO_RE = /^[A-Za-z0-9][A-Za-z0-9._-]{0,39}$/

const auth = useAuthStore()
const route = useRoute()
const focusId = (() => {
  const raw = route.query.focus
  const value = typeof raw === 'string' ? Number(raw) : Number.NaN
  return Number.isInteger(value) && value > 0 ? value : null
})()

const loading = ref(false)
const rows = ref<Inbound[]>([])
const total = ref(0)
const query = reactive({
  page: 1,
  page_size: 10,
  keyword: '',
  status: undefined as InboundStatus | undefined,
  inbound_type: undefined as InboundType | undefined,
})

const filterMemory = useFilterMemory('assets-inbounds', query, {
  defaults: {
    page: 1,
    page_size: 10,
    keyword: '',
    status: undefined,
    inbound_type: undefined,
  },
})
filterMemory.restore()
const statusOptions = Object.entries(INBOUND_STATUS_LABELS) as Array<
  [InboundStatus, string]
>
const typeOptions = Object.entries(INBOUND_TYPE_LABELS) as Array<[InboundType, string]>

const canCreate = computed(() => auth.hasPerm('asset:inbound:create'))
const canConfirm = computed(() => auth.hasPerm('asset:inbound:confirm'))

type CreateMode = 'create' | 'edit' | 'supplement'

const createVisible = ref(false)
const createSubmitting = ref(false)
const createMode = ref<CreateMode>('create')
const editingId = ref<number | null>(null)
const editingVersion = ref(0)
const editingNo = ref('')
const sourceInboundId = ref<number | null>(null)
const sourceInboundNo = ref('')
const categories = ref<InboundCategoryOption[]>([])
const depts = ref<InboundDeptOption[]>([])
const modelsByCategory = reactive<Record<number, InboundModelOption[]>>({})
const form = reactive({
  inbound_type: 'PURCHASE' as InboundType,
  supplier: '',
  purchase_date: '',
  location: '',
  dept_id: undefined as number | undefined,
  remark: '',
  items: [] as LineForm[],
})

const detailVisible = ref(false)
const detailItem = ref<Inbound | null>(null)

const confirmVisible = ref(false)
const confirmItem = ref<Inbound | null>(null)
const confirmComment = ref('')
const confirmSubmitting = ref(false)

const reverseVisible = ref(false)
const reverseItem = ref<Inbound | null>(null)
const reverseSubmitting = ref(false)
const reverseReason = ref('')
const reverseSelected = ref<InboundAsset[]>([])

const createTitle = computed(() => {
  if (createMode.value === 'edit') return `编辑入库单 ${editingNo.value}`
  if (createMode.value === 'supplement') return `补录入库单（原单 ${sourceInboundNo.value}）`
  return '新建入库单'
})
const createSubmitText = computed(() => {
  if (createMode.value === 'edit') return '保存修改'
  if (createMode.value === 'supplement') return '创建补录单'
  return '创建入库单'
})

let lineSequence = 0
const previewTimers = new Map<number, ReturnType<typeof setTimeout>>()

function emptyLine(): LineForm {
  lineSequence += 1
  return {
    key: lineSequence,
    category_id: undefined,
    model_id: undefined,
    name: '',
    quantity: 1,
    base_asset_no: '',
    asset_nos: [],
    codes_edited: false,
    unit_price: undefined,
    warranty_end: '',
    remark: '',
  }
}

const totalQuantity = computed(() =>
  form.items.reduce((sum, item) => sum + (item.quantity || 0), 0),
)
const totalAmount = computed(() =>
  form.items.reduce(
    (sum, item) => sum + (item.unit_price || 0) * (item.quantity || 0),
    0,
  ),
)

function categoryLabel(category: InboundCategoryOption): string {
  return `${'　'.repeat(Math.max(category.level - 1, 0))}${category.name}`
}

function deptLabel(dept: InboundDeptOption): string {
  return `${'　'.repeat(Math.max(dept.level - 1, 0))}${dept.name}`
}

function money(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return `¥${Number(value).toLocaleString('zh-CN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`
}

async function fetchRows(): Promise<void> {
  loading.value = true
  try {
    const page = await inboundApi.list({
      page: query.page,
      page_size: query.page_size,
      keyword: query.keyword || undefined,
      status: query.status,
      inbound_type: query.inbound_type,
    })
    rows.value = page.items
    total.value = page.total
  } finally {
    loading.value = false
  }
}

function handleSearch(): void {
  query.page = 1
  void fetchRows()
}

function resetFilters(): void {
  filterMemory.clear()
  query.keyword = ''
  query.status = undefined
  query.inbound_type = undefined
  query.page = 1
  void fetchRows()
}

async function ensureOptions(): Promise<void> {
  const tasks: Promise<unknown>[] = []
  if (!categories.value.length) {
    tasks.push(
      inboundApi.categories().then((data) => {
        categories.value = data
      }),
    )
  }
  if (!depts.value.length) {
    tasks.push(
      inboundApi.departments().then((data) => {
        depts.value = data
      }),
    )
  }
  await Promise.all(tasks)
}

function resetCreationState(): void {
  createMode.value = 'create'
  editingId.value = null
  editingVersion.value = 0
  editingNo.value = ''
  sourceInboundId.value = null
  sourceInboundNo.value = ''
}

async function openCreate(): Promise<void> {
  clearPreviewTimers()
  resetCreationState()
  form.inbound_type = 'PURCHASE'
  form.supplier = ''
  form.purchase_date = ''
  form.location = ''
  form.dept_id = undefined
  form.remark = ''
  form.items = [emptyLine()]
  createVisible.value = true
  await ensureOptions()
}

function lineFromItem(item: InboundItem, quantity = item.quantity): LineForm {
  const line = emptyLine()
  line.category_id = item.category_id
  line.model_id = item.model_id ?? undefined
  line.name = item.name
  line.quantity = quantity
  line.base_asset_no = item.base_asset_no ?? ''
  line.asset_nos = quantity === item.quantity ? [...item.asset_nos] : []
  line.unit_price = item.unit_price ?? undefined
  line.warranty_end = item.warranty_end ?? ''
  line.remark = item.remark ?? ''
  return line
}

async function ensureLineModels(lines: LineForm[]): Promise<void> {
  const missing = [
    ...new Set(
      lines
        .map((line) => line.category_id)
        .filter((id): id is number => typeof id === 'number'),
    ),
  ].filter((id) => !modelsByCategory[id])
  await Promise.all(
    missing.map(async (id) => {
      modelsByCategory[id] = await inboundApi.models(id)
    }),
  )
}

async function openEdit(row: Inbound): Promise<void> {
  clearPreviewTimers()
  const detail = await inboundApi.get(row.id)
  resetCreationState()
  createMode.value = 'edit'
  editingId.value = detail.id
  editingVersion.value = detail.version
  editingNo.value = detail.inbound_no
  form.inbound_type = detail.inbound_type
  form.supplier = detail.supplier ?? ''
  form.purchase_date = detail.purchase_date ?? ''
  form.location = detail.location ?? ''
  form.dept_id = detail.dept_id ?? undefined
  form.remark = detail.remark ?? ''
  form.items = detail.items.map((item) => lineFromItem(item))
  createVisible.value = true
  await ensureOptions()
  await ensureLineModels(form.items)
}

async function openSupplement(row: Inbound): Promise<void> {
  clearPreviewTimers()
  const detail = await inboundApi.get(row.id)
  resetCreationState()
  createMode.value = 'supplement'
  sourceInboundId.value = detail.id
  sourceInboundNo.value = detail.inbound_no
  form.inbound_type = detail.inbound_type
  form.supplier = detail.supplier ?? ''
  form.purchase_date = ''
  form.location = detail.location ?? ''
  form.dept_id = detail.dept_id ?? undefined
  form.remark = `补录入库（原单 ${detail.inbound_no}）`
  form.items = detail.items.map((item) => lineFromItem(item, 1))
  createVisible.value = true
  await ensureOptions()
  await ensureLineModels(form.items)
}

function addLine(): void {
  if (form.items.length >= 50) {
    ElMessage.warning('单张入库单最多 50 行明细')
    return
  }
  form.items.push(emptyLine())
}

function removeLine(line: LineForm): void {
  if (form.items.length === 1) {
    ElMessage.warning('至少保留一行明细')
    return
  }
  const timer = previewTimers.get(line.key)
  if (timer) clearTimeout(timer)
  previewTimers.delete(line.key)
  form.items = form.items.filter((item) => item.key !== line.key)
}

function localCodes(base: string, quantity: number): string[] {
  return Array.from({ length: quantity }, (_, index) => `${base}-${index + 1}`)
}

async function refreshCodePreview(line: LineForm): Promise<void> {
  const base = line.base_asset_no.trim()
  if (!base) {
    line.asset_nos = []
    return
  }
  if (!BASE_ASSET_NO_RE.test(base)) return
  const quantity = Math.max(line.quantity || 1, 1)
  try {
    const preview = await inboundApi.previewCodes(base, quantity)
    if (line.base_asset_no.trim() !== base || line.quantity !== quantity) return
    if (line.codes_edited) return
    line.asset_nos = preview.codes
  } catch {
    if (line.base_asset_no.trim() !== base || line.quantity !== quantity) return
    if (line.codes_edited) return
    line.asset_nos = localCodes(base, quantity)
  }
}

function scheduleCodePreview(line: LineForm): void {
  const timer = previewTimers.get(line.key)
  if (timer) clearTimeout(timer)
  if (!line.base_asset_no.trim()) {
    line.asset_nos = []
    line.codes_edited = false
    return
  }
  previewTimers.set(
    line.key,
    setTimeout(() => {
      previewTimers.delete(line.key)
      void refreshCodePreview(line)
    }, 300),
  )
}

function handleBaseChange(line: LineForm): void {
  line.codes_edited = false
  line.asset_nos = []
  scheduleCodePreview(line)
}

function handleQuantityChange(line: LineForm): void {
  line.codes_edited = false
  line.asset_nos = []
  scheduleCodePreview(line)
}

function markCodesEdited(line: LineForm): void {
  line.codes_edited = true
}

function resetCodes(line: LineForm): void {
  line.codes_edited = false
  void refreshCodePreview(line)
}

function clearPreviewTimers(): void {
  for (const timer of previewTimers.values()) clearTimeout(timer)
  previewTimers.clear()
}

async function handleCategoryChange(line: LineForm): Promise<void> {
  line.model_id = undefined
  if (!line.category_id) return
  if (!modelsByCategory[line.category_id]) {
    modelsByCategory[line.category_id] = await inboundApi.models(line.category_id)
  }
}

function handleModelChange(line: LineForm): void {
  if (!line.category_id || !line.model_id) return
  const model = (modelsByCategory[line.category_id] ?? []).find(
    (item) => item.id === line.model_id,
  )
  if (model && !line.name.trim()) {
    line.name = model.name
  }
}

function modelOptions(line: LineForm): InboundModelOption[] {
  if (!line.category_id) return []
  return modelsByCategory[line.category_id] ?? []
}

async function submitCreate(): Promise<void> {
  for (const [index, line] of form.items.entries()) {
    if (!line.category_id) {
      ElMessage.warning(`第 ${index + 1} 行请选择资产分类`)
      return
    }
    if (!line.name.trim()) {
      ElMessage.warning(`第 ${index + 1} 行请填写资产名称`)
      return
    }
    if (!line.quantity || line.quantity < 1) {
      ElMessage.warning(`第 ${index + 1} 行数量至少为 1`)
      return
    }
    const base = line.base_asset_no.trim()
    if (base && !BASE_ASSET_NO_RE.test(base)) {
      ElMessage.warning(
        `第 ${index + 1} 行基准编码格式不正确，需以字母或数字开头，仅支持字母、数字、点、下划线、中划线`,
      )
      return
    }
    if (base && line.codes_edited) {
      const codes = line.asset_nos.map((code) => code.trim())
      if (codes.length !== line.quantity) {
        ElMessage.warning(`第 ${index + 1} 行最终编码数量必须与入库数量一致`)
        return
      }
      const seen = new Set<string>()
      for (const code of codes) {
        if (!ASSET_NO_RE.test(code)) {
          ElMessage.warning(
            `第 ${index + 1} 行最终编码「${code || '空'}」格式不正确，需以字母或数字开头，长度 3-50 位`,
          )
          return
        }
        const key = code.toLowerCase()
        if (seen.has(key)) {
          ElMessage.warning(`第 ${index + 1} 行最终编码「${code}」重复`)
          return
        }
        seen.add(key)
      }
      line.asset_nos = codes
    }
  }
  if (totalQuantity.value > 500) {
    ElMessage.warning('单张入库单最多支持 500 台/件资产')
    return
  }
  const explicitSeen = new Map<string, number>()
  for (const [index, line] of form.items.entries()) {
    const base = line.base_asset_no.trim()
    if (!base || !line.codes_edited) continue
    for (const code of line.asset_nos) {
      const key = code.toLowerCase()
      const previous = explicitSeen.get(key)
      if (previous !== undefined) {
        ElMessage.warning(
          `第 ${index + 1} 行最终编码「${code}」与第 ${previous} 行重复，请修改后重新提交`,
        )
        return
      }
      explicitSeen.set(key, index + 1)
    }
  }
  createSubmitting.value = true
  try {
    const items: InboundItemPayload[] = form.items.map((line) => {
      const base = line.base_asset_no.trim()
      return {
        category_id: line.category_id as number,
        model_id: line.model_id ?? null,
        name: line.name.trim(),
        quantity: line.quantity,
        base_asset_no: base || null,
        asset_nos:
          base && line.codes_edited
            ? line.asset_nos.map((code) => code.trim())
            : null,
        unit_price: line.unit_price ?? null,
        warranty_end: line.warranty_end || null,
        remark: line.remark.trim() || null,
      }
    })
    const payload = {
      inbound_type: form.inbound_type,
      supplier: form.supplier.trim() || null,
      purchase_date: form.purchase_date || null,
      location: form.location.trim() || null,
      dept_id: form.dept_id ?? null,
      remark: form.remark.trim() || null,
      items,
    }
    let saved: Inbound
    if (createMode.value === 'edit' && editingId.value) {
      saved = await inboundApi.update(editingId.value, {
        ...payload,
        version: editingVersion.value,
      })
      ElMessage.success('入库单已更新，编码已重新预占')
    } else {
      saved = await inboundApi.create({
        ...payload,
        source_inbound_id: sourceInboundId.value,
      })
      ElMessage.success(
        createMode.value === 'supplement'
          ? '补录入库单已创建，确认后生成补录资产'
          : '入库单已创建，资产编码已预占，确认后生成资产台账',
      )
    }
    createVisible.value = false
    clearPreviewTimers()
    detailItem.value = saved
    detailVisible.value = true
    handleSearch()
  } finally {
    createSubmitting.value = false
  }
}

async function openDetail(row: Inbound): Promise<void> {
  detailItem.value = row
  detailVisible.value = true
  try {
    detailItem.value = await inboundApi.get(row.id)
  } catch {
    detailVisible.value = false
  }
}

async function openFocused(): Promise<void> {
  if (!focusId) return
  const row = rows.value.find((item) => item.id === focusId)
  if (row) {
    await openDetail(row)
    return
  }
  try {
    detailItem.value = await inboundApi.get(focusId)
    detailVisible.value = true
  } catch {
    // 目标单据无权限或已失效时停留在列表页
  }
}

function openConfirm(row: Inbound): void {
  confirmItem.value = row
  confirmComment.value = ''
  confirmVisible.value = true
}

async function submitConfirm(): Promise<void> {
  const item = confirmItem.value
  if (!item) return
  confirmSubmitting.value = true
  try {
    await inboundApi.confirm(item.id, item.version, confirmComment.value || null)
    ElMessage.success('入库完成，资产已生成并进入在库状态')
    confirmVisible.value = false
    detailVisible.value = false
    await fetchRows()
  } catch {
    confirmVisible.value = false
    detailVisible.value = false
    await fetchRows()
  } finally {
    confirmSubmitting.value = false
  }
}

async function cancelInbound(row: Inbound): Promise<void> {
  let reason: string | null = null
  try {
    const result = await ElMessageBox.prompt(
      `确定取消入库单 ${row.inbound_no} 吗？取消后可重新创建。`,
      '取消入库单',
      {
        confirmButtonText: '取消入库单',
        cancelButtonText: '返回',
        inputType: 'textarea',
        inputPlaceholder: '可填写取消原因（选填）',
        inputValidator: () => true,
      },
    )
    reason = (result.value || '').trim() || null
  } catch {
    return
  }
  await inboundApi.cancel(row.id, reason)
  ElMessage.success('入库单已取消')
  if (detailItem.value?.id === row.id) detailVisible.value = false
  await fetchRows()
}

async function openReverse(row: Inbound): Promise<void> {
  const detail = await inboundApi.get(row.id)
  if (!detail.assets.some((item) => item.can_reverse)) {
    ElMessage.warning('该入库单当前没有可冲销的在库资产')
    return
  }
  reverseItem.value = detail
  reverseReason.value = ''
  reverseSelected.value = []
  reverseVisible.value = true
}

function reverseSelectable(row: InboundAsset): boolean {
  return row.can_reverse
}

function handleReverseSelection(rows: InboundAsset[]): void {
  reverseSelected.value = rows
}

async function submitReverse(): Promise<void> {
  const item = reverseItem.value
  if (!item) return
  if (!reverseSelected.value.length) {
    ElMessage.warning('请勾选要冲销的资产')
    return
  }
  const reason = reverseReason.value.trim()
  if (!reason) {
    ElMessage.warning('请填写冲销原因')
    return
  }
  reverseSubmitting.value = true
  try {
    const updated = await inboundApi.reverseAssets(item.id, {
      asset_nos: reverseSelected.value.map((asset) => asset.asset_no),
      reason,
      version: item.version,
    })
    ElMessage.success('所选资产已冲销作废，编码已释放')
    reverseVisible.value = false
    if (detailItem.value?.id === updated.id) detailItem.value = updated
    await fetchRows()
  } finally {
    reverseSubmitting.value = false
  }
}

onMounted(async () => {
  await fetchRows()
  await openFocused()
})
onBeforeUnmount(clearPreviewTimers)
</script>

<template>
  <div class="page inbound-page">
    <header class="page-header">
      <div>
        <p class="page-eyebrow">INBOUND MANAGEMENT</p>
        <h1 class="page-title">资产入库</h1>
        <p class="page-subtitle">
          按采购批次登记入库明细，确认验收入库后在同一事务内批量生成资产台账、写入状态历史与审计日志。
        </p>
      </div>
      <div class="page-actions">
        <el-button :icon="Refresh" :loading="loading" @click="fetchRows">刷新</el-button>
        <el-button v-if="canCreate" type="primary" :icon="Plus" @click="openCreate">
          新建入库单
        </el-button>
      </div>
    </header>

    <section class="surface-card panel">
      <div class="filter-bar">
        <el-input
          v-model="query.keyword"
          :prefix-icon="Search"
          placeholder="入库单号 / 供应商 / 创建人"
          clearable
          class="filter-keyword"
          @keyup.enter="handleSearch"
          @clear="handleSearch"
        />
        <el-select
          v-model="query.status"
          placeholder="单据状态"
          clearable
          class="filter-select"
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
          v-model="query.inbound_type"
          placeholder="入库类型"
          clearable
          class="filter-select"
          @change="handleSearch"
        >
          <el-option
            v-for="[value, label] in typeOptions"
            :key="value"
            :label="label"
            :value="value"
          />
        </el-select>
        <div class="filter-actions">
          <el-button :icon="Search" @click="handleSearch">查询</el-button>
          <el-button text @click="resetFilters">重置</el-button>
        </div>
      </div>

      <el-table
        v-loading="loading"
        :data="rows"
        row-key="id"
        empty-text="当前没有入库单"
      >
        <el-table-column label="入库单" min-width="190">
          <template #default="{ row }">
            <div class="stack-cell">
              <span class="mono">{{ row.inbound_no }}</span>
              <small>{{ formatDateTime(row.created_at) }}</small>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="类型" width="110">
          <template #default="{ row }">
            <el-tag effect="plain" type="info">{{ row.inbound_type_label }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="供应商 / 部门" min-width="180">
          <template #default="{ row }">
            <div class="stack-cell">
              <span>{{ row.supplier || '未填写供应商' }}</span>
              <small>{{ row.dept_name || '未指定部门' }}</small>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="入库数量 / 金额" min-width="170">
          <template #default="{ row }">
            <div class="stack-cell">
              <span>{{ row.total_quantity }} 台/件</span>
              <small>{{ money(row.total_amount) }}</small>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="存放位置" min-width="150">
          <template #default="{ row }">{{ row.location || '未指定位置' }}</template>
        </el-table-column>
        <el-table-column label="状态" width="130">
          <template #default="{ row }">
            <el-tag :type="row.status_tag_type" effect="light">{{ row.status_label }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="创建人" min-width="120">
          <template #default="{ row }">{{ row.created_by_name || '—' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="340" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openDetail(row)">详情</el-button>
            <el-button v-if="row.can_edit" link type="primary" @click="openEdit(row)">
              编辑
            </el-button>
            <el-button
              v-if="row.can_confirm"
              link
              type="success"
              @click="openConfirm(row)"
            >
              确认入库
            </el-button>
            <el-button
              v-if="row.can_reverse || (row.status === 'COMPLETED' && canConfirm)"
              link
              type="danger"
              @click="openReverse(row)"
            >
              冲销资产
            </el-button>
            <el-button
              v-if="row.can_supplement"
              link
              type="warning"
              @click="openSupplement(row)"
            >
              补录
            </el-button>
            <el-button v-if="row.can_cancel" link type="warning" @click="cancelInbound(row)">
              取消
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="table-footer">
        <el-pagination
          v-model:current-page="query.page"
          v-model:page-size="query.page_size"
          :total="total"
          :page-sizes="[10, 20, 50]"
          layout="total, sizes, prev, pager, next"
          background
          @current-change="fetchRows"
          @size-change="handleSearch"
        />
      </div>
    </section>

    <el-dialog
      v-model="createVisible"
      :title="createTitle"
      width="1200px"
      destroy-on-close
      @closed="clearPreviewTimers"
    >
      <el-alert
        v-if="createMode === 'edit'"
        type="info"
        :closable="false"
        show-icon
        class="mode-alert"
        title="仅待确认入库单可编辑；保存后原编码预占将被释放并按最新规则重新预占，确认入库时才生成资产台账。"
      />
      <el-alert
        v-else-if="createMode === 'supplement'"
        type="warning"
        :closable="false"
        show-icon
        class="mode-alert"
        title="补录单关联原入库单，用于补足数量缺口；编码按规则顺延或手工指定，原单据与历史记录不会被修改。"
      />
      <el-form label-position="top">
        <div class="form-grid">
          <el-form-item label="入库类型">
            <el-select v-model="form.inbound_type" class="full-width">
              <el-option
                v-for="[value, label] in typeOptions"
                :key="value"
                :label="label"
                :value="value"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="所属部门">
            <el-select
              v-model="form.dept_id"
              clearable
              filterable
              placeholder="选择资产归属部门"
              class="full-width"
            >
              <el-option
                v-for="dept in depts"
                :key="dept.id"
                :label="deptLabel(dept)"
                :value="dept.id"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="供应商">
            <el-input v-model="form.supplier" maxlength="120" placeholder="选填" />
          </el-form-item>
          <el-form-item label="采购日期">
            <el-date-picker
              v-model="form.purchase_date"
              type="date"
              value-format="YYYY-MM-DD"
              placeholder="不填写则默认为今天"
              class="full-width"
            />
          </el-form-item>
          <el-form-item label="存放位置">
            <el-input
              v-model="form.location"
              maxlength="120"
              placeholder="例如 总部机房 A 区"
            />
          </el-form-item>
          <el-form-item label="备注">
            <el-input v-model="form.remark" maxlength="500" placeholder="选填" />
          </el-form-item>
        </div>

        <div class="line-header">
          <div>
            <span class="line-title">入库明细</span>
            <small>
              填写基准编码后自动生成 1001-1、1001-2…，可展开逐台修改；未填写时沿用系统全局编号规则
            </small>
          </div>
          <el-button text type="primary" :icon="Plus" @click="addLine">添加明细行</el-button>
        </div>

        <el-table :data="form.items" row-key="key" size="small" class="line-table">
          <el-table-column type="expand" width="42">
            <template #default="{ row }">
              <div class="code-editor">
                <div class="code-editor-head">
                  <div>
                    <span v-if="row.base_asset_no.trim()">
                      基准编码
                      <strong class="mono">{{ row.base_asset_no.trim() }}</strong>
                      · 已生成 {{ row.asset_nos.length }} / {{ row.quantity }} 个最终编码
                    </span>
                    <span v-else>未填写基准编码，确认入库时将使用系统全局编号规则</span>
                    <small>
                      未修改时提交后由系统按当前最大序号顺延分配，避免并发重复；修改后以填写的编码为准。
                    </small>
                  </div>
                  <el-button
                    v-if="row.base_asset_no.trim()"
                    link
                    type="primary"
                    @click="resetCodes(row)"
                  >
                    按最新序号重置
                  </el-button>
                </div>
                <div v-if="row.asset_nos.length" class="code-grid">
                  <el-input
                    v-for="(_, index) in row.asset_nos"
                    :key="`${row.key}-${index}`"
                    v-model="row.asset_nos[index]"
                    size="small"
                    maxlength="50"
                    class="code-input"
                    @input="markCodesEdited(row)"
                  >
                    <template #prepend>{{ index + 1 }}</template>
                  </el-input>
                </div>
                <small v-else-if="row.base_asset_no.trim()" class="code-hint">
                  正在按最新序号生成最终编码…
                </small>
                <small v-else class="code-hint">
                  填写基准编码后自动生成，例如 1001 → 1001-1、1001-2、1001-3
                </small>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="资产分类" min-width="170">
            <template #default="{ row }">
              <el-select
                v-model="row.category_id"
                filterable
                placeholder="选择分类"
                class="full-width"
                @change="handleCategoryChange(row)"
              >
                <el-option
                  v-for="category in categories"
                  :key="category.id"
                  :label="categoryLabel(category)"
                  :value="category.id"
                />
              </el-select>
            </template>
          </el-table-column>
          <el-table-column label="型号" min-width="160">
            <template #default="{ row }">
              <el-select
                v-model="row.model_id"
                filterable
                clearable
                :disabled="!row.category_id"
                placeholder="选填"
                class="full-width"
                @change="handleModelChange(row)"
              >
                <el-option
                  v-for="model in modelOptions(row)"
                  :key="model.id"
                  :label="`${model.name}（${model.code}）`"
                  :value="model.id"
                />
              </el-select>
            </template>
          </el-table-column>
          <el-table-column label="资产名称" min-width="145">
            <template #default="{ row }">
              <el-input v-model="row.name" maxlength="120" placeholder="例如 笔记本电脑" />
            </template>
          </el-table-column>
          <el-table-column label="基准编码" width="130">
            <template #default="{ row }">
              <el-input
                v-model="row.base_asset_no"
                size="small"
                maxlength="40"
                placeholder="如 1001"
                @input="handleBaseChange(row)"
              />
            </template>
          </el-table-column>
          <el-table-column label="数量" width="115">
            <template #default="{ row }">
              <el-input-number
                v-model="row.quantity"
                :min="1"
                :max="200"
                size="small"
                controls-position="right"
                class="full-width"
                @change="handleQuantityChange(row)"
              />
            </template>
          </el-table-column>
          <el-table-column label="单价（元）" width="140">
            <template #default="{ row }">
              <el-input-number
                v-model="row.unit_price"
                :min="0"
                :max="99999999"
                :precision="2"
                size="small"
                controls-position="right"
                class="full-width"
              />
            </template>
          </el-table-column>
          <el-table-column label="保修截止" width="155">
            <template #default="{ row }">
              <el-date-picker
                v-model="row.warranty_end"
                type="date"
                value-format="YYYY-MM-DD"
                size="small"
                placeholder="选填"
                class="full-width"
              />
            </template>
          </el-table-column>
          <el-table-column label="操作" width="70" fixed="right">
            <template #default="{ row }">
              <el-button link type="danger" @click="removeLine(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>

        <div class="line-summary">
          <span>共 {{ form.items.length }} 行</span>
          <span>合计数量 <strong>{{ totalQuantity }}</strong> 台/件</span>
          <span>合计金额 <strong>{{ money(totalAmount) }}</strong></span>
        </div>
      </el-form>
      <el-alert
        type="info"
        :closable="false"
        show-icon
        :title="
          createMode === 'edit'
            ? '保存后仍为待确认状态；确认入库时会在事务内生成全部资产并写入历史记录，任一步失败则整体回滚'
            : '创建后为待确认状态；确认入库时会在事务内生成全部资产并写入历史记录，任一步失败则整体回滚'
        "
      />
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="createSubmitting" @click="submitCreate">
          {{ createSubmitText }}
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="detailVisible" title="入库单详情" width="980px">
      <template v-if="detailItem">
        <el-steps
          :active="inboundActive(detailItem.status)"
          :process-status="isInboundInterrupted(detailItem.status) ? 'error' : 'process'"
          finish-status="success"
          align-center
          class="flow-steps"
        >
          <el-step v-for="step in inboundSteps()" :key="step" :title="step" />
        </el-steps>

        <el-descriptions :column="2" border>
          <el-descriptions-item label="入库单号">{{ detailItem.inbound_no }}</el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="detailItem.status_tag_type" effect="light">
              {{ detailItem.status_label }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="入库类型">
            {{ detailItem.inbound_type_label }}
          </el-descriptions-item>
          <el-descriptions-item label="所属部门">
            {{ detailItem.dept_name || '未指定部门' }}
          </el-descriptions-item>
          <el-descriptions-item label="供应商">
            {{ detailItem.supplier || '—' }}
          </el-descriptions-item>
          <el-descriptions-item label="采购日期">
            {{ detailItem.purchase_date || '—' }}
          </el-descriptions-item>
          <el-descriptions-item label="存放位置">
            {{ detailItem.location || '未指定位置' }}
          </el-descriptions-item>
          <el-descriptions-item label="创建人">
            {{ detailItem.created_by_name || '—' }}
          </el-descriptions-item>
          <el-descriptions-item label="创建时间">
            {{ formatDateTime(detailItem.created_at) }}
          </el-descriptions-item>
          <el-descriptions-item label="确认人">
            {{ detailItem.confirmed_by_name || '—' }}
          </el-descriptions-item>
          <el-descriptions-item label="确认时间">
            {{ formatDateTime(detailItem.confirmed_at) }}
          </el-descriptions-item>
          <el-descriptions-item label="备注" :span="2">
            {{ detailItem.remark || '—' }}
          </el-descriptions-item>
          <el-descriptions-item label="确认备注" :span="2">
            {{ detailItem.completion_comment || '—' }}
          </el-descriptions-item>
          <el-descriptions-item
            v-if="detailItem.status === 'CANCELLED'"
            label="取消原因"
            :span="2"
          >
            {{ detailItem.cancel_reason || '—' }}
          </el-descriptions-item>
        </el-descriptions>

        <div class="detail-subtitle">入库明细</div>
        <el-table :data="detailItem.items" size="small" border>
          <el-table-column prop="name" label="资产名称" min-width="140" />
          <el-table-column label="基准 / 最终编码" min-width="230">
            <template #default="{ row }">
              <div class="stack-cell">
                <span class="mono">{{ row.base_asset_no || '系统全局规则' }}</span>
                <small v-if="row.asset_nos.length" class="code-list">
                  {{ row.asset_nos.join('、') }}
                </small>
                <small v-else>确认入库时生成</small>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="分类 / 型号" min-width="160">
            <template #default="{ row }">
              <div class="stack-cell">
                <span>{{ row.category_name }}</span>
                <small>{{ row.model_name || '未指定型号' }}</small>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="quantity" label="数量" width="80" />
          <el-table-column label="单价" width="120">
            <template #default="{ row }">{{ money(row.unit_price) }}</template>
          </el-table-column>
          <el-table-column label="金额" width="130">
            <template #default="{ row }">{{ money(row.amount) }}</template>
          </el-table-column>
          <el-table-column label="保修截止" width="110">
            <template #default="{ row }">{{ row.warranty_end || '—' }}</template>
          </el-table-column>
        </el-table>

        <div v-if="detailItem.status === 'COMPLETED' && detailItem.assets.length" class="detail-subtitle">
          已生成资产
        </div>
        <el-table
          v-if="detailItem.status === 'COMPLETED' && detailItem.assets.length"
          :data="detailItem.assets"
          size="small"
          border
        >
          <el-table-column label="资产编码" min-width="160">
            <template #default="{ row }">
              <span class="mono">{{ row.asset_no }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="name" label="资产名称" min-width="160" />
          <el-table-column label="状态" width="110">
            <template #default="{ row }">
              <el-tag
                :type="row.can_reverse ? 'success' : 'info'"
                size="small"
                effect="light"
              >
                {{ row.status_label }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="可冲销" width="90">
            <template #default="{ row }">
              {{ row.can_reverse ? '是' : '否' }}
            </template>
          </el-table-column>
        </el-table>

        <div class="detail-total">
          合计 <strong>{{ detailItem.total_quantity }}</strong> 台/件 ·
          <strong>{{ money(detailItem.total_amount) }}</strong>
        </div>
      </template>
      <template #footer>
        <el-button @click="detailVisible = false">关闭</el-button>
        <el-button
          v-if="detailItem?.can_edit"
          type="primary"
          plain
          @click="detailItem && openEdit(detailItem)"
        >
          编辑入库单
        </el-button>
        <el-button
          v-if="detailItem?.can_supplement"
          type="warning"
          plain
          @click="detailItem && openSupplement(detailItem)"
        >
          补录入库
        </el-button>
        <el-button
          v-if="detailItem?.can_reverse"
          type="danger"
          plain
          @click="detailItem && openReverse(detailItem)"
        >
          冲销资产
        </el-button>
        <el-button
          v-if="detailItem?.can_cancel"
          type="warning"
          plain
          @click="detailItem && cancelInbound(detailItem)"
        >
          取消入库单
        </el-button>
        <el-button
          v-if="detailItem?.can_confirm"
          type="primary"
          @click="detailItem && openConfirm(detailItem)"
        >
          确认入库
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="confirmVisible" title="确认验收入库" width="540px">
      <div v-if="confirmItem" class="action-summary">
        <div>
          <span>{{ confirmItem.inbound_no }}</span>
          <small>
            {{ confirmItem.total_quantity }} 台/件 · {{ money(confirmItem.total_amount) }} ·
            {{ confirmItem.location || '未指定位置' }}
          </small>
        </div>
        <el-tag :type="confirmItem.status_tag_type" effect="light">
          {{ confirmItem.status_label }}
        </el-tag>
      </div>

      <el-form label-position="top">
        <el-form-item label="确认备注（选填）">
          <el-input
            v-model="confirmComment"
            type="textarea"
            :rows="3"
            maxlength="500"
            show-word-limit
            placeholder="如验收情况、到货说明等"
          />
        </el-form-item>
      </el-form>

      <el-alert
        type="warning"
        :closable="false"
        show-icon
        title="确认后将批量生成资产台账并进入在库状态，同时写入状态历史与审计日志；任一步失败将整体回滚"
      />
      <template #footer>
        <el-button @click="confirmVisible = false">取消</el-button>
        <el-button type="primary" :loading="confirmSubmitting" @click="submitConfirm">
          确认入库
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="reverseVisible" title="冲销入库资产" width="760px">
      <template v-if="reverseItem">
        <div class="action-summary">
          <div>
            <span>{{ reverseItem.inbound_no }}</span>
            <small>
              仅「在库」且无处理中业务的资产可冲销；冲销后资产作废、编码释放，原入库单与历史保留。
            </small>
          </div>
          <el-tag :type="reverseItem.status_tag_type" effect="light">
            {{ reverseItem.status_label }}
          </el-tag>
        </div>

        <el-table
          :data="reverseItem.assets"
          size="small"
          border
          max-height="320"
          @selection-change="handleReverseSelection"
        >
          <el-table-column type="selection" width="46" :selectable="reverseSelectable" />
          <el-table-column label="资产编码" min-width="160">
            <template #default="{ row }">
              <span class="mono">{{ row.asset_no }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="name" label="资产名称" min-width="160" />
          <el-table-column label="状态" width="110">
            <template #default="{ row }">
              <el-tag
                :type="row.can_reverse ? 'success' : 'info'"
                size="small"
                effect="light"
              >
                {{ row.status_label }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="可冲销" width="90">
            <template #default="{ row }">
              {{ row.can_reverse ? '是' : '否' }}
            </template>
          </el-table-column>
        </el-table>

        <el-form label-position="top" class="reverse-form">
          <el-form-item label="冲销原因（必填）">
            <el-input
              v-model="reverseReason"
              type="textarea"
              :rows="3"
              maxlength="500"
              show-word-limit
              placeholder="如：入库数量多录 1 台，冲销多余资产"
            />
          </el-form-item>
        </el-form>

        <el-alert
          type="warning"
          :closable="false"
          show-icon
          title="冲销会将该资产置为已作废并写入状态快照与审计日志；已领用、借用或维修中的资产需先归还或处理至在库状态。"
        />
      </template>
      <template #footer>
        <el-button @click="reverseVisible = false">取消</el-button>
        <el-button
          type="danger"
          :loading="reverseSubmitting"
          :disabled="!reverseSelected.length"
          @click="submitReverse"
        >
          确认冲销（{{ reverseSelected.length }}）
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page-actions {
  display: flex;
  gap: 10px;
}

.inbound-page :deep(.el-dialog) {
  max-width: 96vw;
}

.panel {
  padding: 20px;
}

.filter-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}

.filter-keyword {
  width: 300px;
}

.filter-select {
  width: 150px;
}

.filter-actions {
  display: flex;
  gap: 8px;
  margin-left: auto;
}

.stack-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.stack-cell small {
  color: var(--text-3);
  font-size: 11.5px;
}

.mono {
  font-family: var(--font-number);
  font-weight: 600;
}

.table-footer {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}

.full-width {
  width: 100%;
}

.mode-alert {
  margin-bottom: 14px;
}

.reverse-form {
  margin-top: 16px;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0 16px;
}

.line-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 12px;
  margin: 4px 0 10px;
}

.line-title {
  font-weight: 650;
  color: var(--text-1);
}

.line-header small {
  display: block;
  margin-top: 2px;
  color: var(--text-3);
  font-size: 12px;
}

.line-table {
  width: 100%;
}

.code-editor {
  margin: 4px 8px 8px 48px;
  padding: 12px 16px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--surface-muted);
}

.code-editor-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 10px;
}

.code-editor-head span {
  display: block;
  color: var(--text-1);
  font-weight: 600;
}

.code-editor-head small {
  display: block;
  margin-top: 3px;
  color: var(--text-3);
  font-size: 12px;
}

.code-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 8px;
  max-height: 220px;
  overflow-y: auto;
}

.code-input {
  width: 100%;
}

.code-hint {
  color: var(--text-3);
  font-size: 12px;
}

.code-list {
  display: block;
  max-height: 76px;
  overflow-y: auto;
  word-break: break-all;
}

.line-summary {
  display: flex;
  justify-content: flex-end;
  gap: 20px;
  margin: 12px 0;
  color: var(--text-2);
  font-size: 13px;
}

.line-summary strong {
  color: var(--text-1);
  font-family: var(--font-number);
}

.flow-steps {
  margin-bottom: 22px;
}

.detail-subtitle {
  margin: 20px 0 10px;
  font-weight: 650;
  color: var(--text-1);
}

.detail-total {
  margin-top: 12px;
  text-align: right;
  color: var(--text-2);
}

.detail-total strong {
  color: var(--text-1);
  font-family: var(--font-number);
}

.action-summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 16px;
  border-radius: 12px;
  background: var(--surface-muted);
  border: 1px solid var(--border);
  margin-bottom: 16px;
}

.action-summary span {
  display: block;
  font-weight: 650;
  color: var(--text-1);
}

.action-summary small {
  display: block;
  margin-top: 2px;
  color: var(--text-3);
  font-size: 12px;
}

@media (max-width: 1180px) {
  .filter-keyword {
    width: 100%;
  }

  .form-grid {
    grid-template-columns: 1fr;
  }
}
</style>
