<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Camera, Refresh, Search } from '@element-plus/icons-vue'

import RequestDetailDrawer from '@/components/asset-flow/RequestDetailDrawer.vue'
import ScanDialog from '@/components/ScanDialog.vue'
import { assetFlowApi } from '@/api/assetFlow'
import { useAuthStore } from '@/stores/auth'
import type {
  ApprovalConfig,
  AssetRequestItem,
  AssetRequestStatus,
  AssetRequestSummary,
  AssetRequestType,
  AvailableAsset,
} from '@/types/assetFlow'
import {
  REQUEST_STATUS_LABELS,
  REQUEST_STATUS_TAG_TYPES,
  REQUEST_TYPE_LABELS,
} from '@/types/assetFlow'
import { formatDateTime } from '@/utils/format'

type ActionMode = 'approve' | 'reject' | 'outbound' | 'return'
type PageMode = 'review' | 'outbound' | 'return'

const auth = useAuthStore()
const route = useRoute()

const pageMode = computed<PageMode>(() => {
  if (route.path.startsWith('/assets/outbound')) return 'outbound'
  if (route.path.startsWith('/assets/returns')) return 'return'
  return 'review'
})

const focusId = (() => {
  const raw = route.query.focus
  const value = typeof raw === 'string' ? Number(raw) : Number.NaN
  return Number.isInteger(value) && value > 0 ? value : null
})()

const pageInfo = computed(() => {
  if (pageMode.value === 'outbound') {
    return {
      eyebrow: 'ASSET OUTBOUND',
      title: '资产出库确认',
      subtitle:
        '为已审批通过的领用 / 借用申请分配具体在库资产；确认出库后资产编号、状态、责任人、位置、单据与审计记录在同一事务内同步更新。',
    }
  }
  if (pageMode.value === 'return') {
    return {
      eyebrow: 'ASSET RETURN',
      title: '资产归还确认',
      subtitle:
        '确认已归还资产入库；确认后资产回到在库状态，并同步更新单据、状态历史与审计记录。',
    }
  }
  return {
    eyebrow: 'ASSET WORKFLOW',
    title: '业务审批',
    subtitle:
      '默认仅展示待您处理的单据。领用 / 借用按申请人所属部门自动匹配的审批流程逐级流转，每次审批操作均写入审计日志。',
  }
})

const loading = ref(false)
const requests = ref<AssetRequestItem[]>([])
const total = ref(0)
const summary = ref<AssetRequestSummary | null>(null)
const onlyMine = ref(pageMode.value === 'review')

const query = reactive({
  page: 1,
  page_size: 10,
  keyword: '',
  request_type: undefined as AssetRequestType | undefined,
  status: undefined as AssetRequestStatus | undefined,
})

const initialStatus = route.query.status
if (
  typeof initialStatus === 'string' &&
  initialStatus in REQUEST_STATUS_LABELS
) {
  query.status = initialStatus as AssetRequestStatus
} else if (pageMode.value === 'outbound') {
  query.status = 'PENDING_OUTBOUND'
} else if (pageMode.value === 'return') {
  query.status = 'PENDING_RETURN'
}

const typeOptions = Object.entries(REQUEST_TYPE_LABELS) as Array<
  [AssetRequestType, string]
>
const statusOptions = Object.entries(REQUEST_STATUS_LABELS) as Array<
  [AssetRequestStatus, string]
>

const summaryCards = computed(() => {
  const data = summary.value
  const cards = [
    {
      key: 'PENDING_APPROVAL' as const,
      label: '待审批',
      value: onlyMine.value
        ? data?.my_pending_approval ?? 0
        : data?.pending_approval ?? 0,
    },
    {
      key: 'PENDING_OUTBOUND' as const,
      label: '待出库',
      value: onlyMine.value
        ? data?.my_pending_outbound ?? 0
        : data?.pending_outbound ?? 0,
    },
    {
      key: 'PENDING_RETURN' as const,
      label: '待归还确认',
      value: onlyMine.value
        ? data?.my_pending_return ?? 0
        : data?.pending_return ?? 0,
    },
    {
      key: 'BORROWED' as const,
      label: '借用中',
      value: data?.borrowed ?? 0,
    },
  ]
  if (pageMode.value === 'outbound') {
    return cards.filter((card) => card.key === 'PENDING_OUTBOUND')
  }
  if (pageMode.value === 'return') {
    return cards.filter((card) => card.key === 'PENDING_RETURN')
  }
  return cards
})

const canConfigure = computed(() =>
  auth.hasAnyPerm(['asset:request:flow:view', 'asset:request:flow:manage']),
)
const approvalConfig = ref<ApprovalConfig | null>(null)
const configSaving = ref(false)

const detailVisible = ref(false)
const detailRequest = ref<AssetRequestItem | null>(null)

const actionVisible = ref(false)
const actionMode = ref<ActionMode>('approve')
const actionRequest = ref<AssetRequestItem | null>(null)
const actionSubmitting = ref(false)
const actionComment = ref('')
const actionLocation = ref('')
const scanVerified = ref(false)
const actionScanVisible = ref(false)

const selectedAssetId = ref<number | null>(null)
const outboundAssetList = ref<AvailableAsset[]>([])
const outboundAssetTotal = ref(0)
const outboundAssetLoading = ref(false)
const outboundAssetQuery = reactive({ page: 1, page_size: 10 })

const toolbarScanVisible = ref(false)

const actionTitle = computed(() => {
  if (actionMode.value === 'approve') {
    if (actionRequest.value?.flow_id) {
      return `${actionRequest.value.current_step_name || '审批'} · 通过`
    }
    return actionRequest.value?.approval_stage === 'DEPT' ? '部门审批通过' : '资产审批通过'
  }
  const titles: Record<Exclude<ActionMode, 'approve'>, string> = {
    reject: '驳回申请',
    outbound: '确认出库',
    return: '确认归还',
  }
  return titles[actionMode.value]
})

const actionSubmitText = computed(() => {
  const labels: Record<ActionMode, string> = {
    approve: actionTitle.value,
    reject: '确认驳回',
    outbound: '确认出库',
    return: '确认归还',
  }
  return labels[actionMode.value]
})

const outboundNeedsSelection = computed(
  () => actionMode.value === 'outbound' && !actionRequest.value?.asset_id,
)
const selectedOutboundAsset = computed(
  () =>
    outboundAssetList.value.find((asset) => asset.id === selectedAssetId.value) ??
    null,
)

function approveActionLabel(row: AssetRequestItem): string {
  if (row.flow_id) return '审批通过'
  return row.approval_stage === 'DEPT' ? '部门审批' : '资产审批'
}

function stageHint(row: AssetRequestItem): string {
  if (row.status !== 'PENDING_APPROVAL') return ''
  if (row.flow_id) return row.current_step_name || ''
  return row.approval_stage_label || ''
}

function canOperate(row: AssetRequestItem, mode: ActionMode): boolean {
  if (mode === 'approve' || mode === 'reject') return row.can_approve
  if (mode === 'outbound') return row.can_outbound
  return row.can_confirm_return
}

function showAction(mode: ActionMode): boolean {
  if (pageMode.value === 'review') return true
  return pageMode.value === mode
}

async function fetchRequests(): Promise<void> {
  loading.value = true
  try {
    const page = await assetFlowApi.reviewRequests({
      page: query.page,
      page_size: query.page_size,
      keyword: query.keyword || undefined,
      request_type: query.request_type,
      status: query.status,
      pending_mine: onlyMine.value,
    })
    requests.value = page.items
    total.value = page.total
  } finally {
    loading.value = false
  }
}

async function fetchSummary(): Promise<void> {
  summary.value = await assetFlowApi.reviewSummary()
}

async function fetchApprovalConfig(): Promise<void> {
  if (!canConfigure.value) return
  approvalConfig.value = await assetFlowApi.approvalConfig()
}

async function handleConfigChange(value: string | number | boolean): Promise<void> {
  if (!approvalConfig.value) return
  configSaving.value = true
  try {
    approvalConfig.value = await assetFlowApi.updateApprovalConfig({
      dept_approval_required: Boolean(value),
      version: approvalConfig.value.version,
    })
    ElMessage.success(
      approvalConfig.value.dept_approval_required
        ? '已开启部门管理员审批，新申请将按两级流程审批'
        : '已关闭部门管理员审批，新申请将直接由资产管理员审批',
    )
  } finally {
    configSaving.value = false
  }
}

function handleSearch(): void {
  query.page = 1
  void fetchRequests()
}

function resetFilters(): void {
  query.keyword = ''
  query.request_type = undefined
  query.status = undefined
  query.page = 1
  void fetchRequests()
}

function filterByStatus(status: AssetRequestStatus): void {
  if (pageMode.value !== 'review') {
    query.status = status
    handleSearch()
    return
  }
  query.status = query.status === status ? undefined : status
  handleSearch()
}

function handleOnlyMineChange(): void {
  query.page = 1
  void fetchRequests()
}

async function refreshAll(): Promise<void> {
  await Promise.all([fetchRequests(), fetchSummary()])
}

async function openDetail(row: AssetRequestItem): Promise<void> {
  detailRequest.value = row
  detailVisible.value = true
  detailRequest.value = await assetFlowApi.getRequest(row.id)
}

async function openFocused(): Promise<void> {
  if (!focusId) return
  const row = requests.value.find((item) => item.id === focusId)
  if (row) {
    await openDetail(row)
    return
  }
  try {
    detailRequest.value = await assetFlowApi.getRequest(focusId)
    detailVisible.value = true
  } catch {
    // 目标单据无权限或已失效时停留在列表页
  }
}

function openAction(row: AssetRequestItem, mode: ActionMode): void {
  actionRequest.value = row
  actionMode.value = mode
  actionComment.value = ''
  actionLocation.value = row.asset_location || ''
  scanVerified.value = false
  selectedAssetId.value = row.asset_id
  outboundAssetList.value = []
  outboundAssetTotal.value = 0
  outboundAssetQuery.page = 1
  actionVisible.value = true
  if (mode === 'outbound' && !row.asset_id) {
    void loadOutboundAssets()
  }
}

async function loadOutboundAssets(): Promise<void> {
  const request = actionRequest.value
  if (!request) return
  outboundAssetLoading.value = true
  try {
    const page = await assetFlowApi.outboundAssets(request.id, {
      page: outboundAssetQuery.page,
      page_size: outboundAssetQuery.page_size,
    })
    outboundAssetList.value = page.items
    outboundAssetTotal.value = page.total
  } finally {
    outboundAssetLoading.value = false
  }
}

function handleOutboundAssetCurrentChange(row: AvailableAsset | null): void {
  selectedAssetId.value = row?.id ?? null
}

function handleOutboundAssetPageChange(): void {
  selectedAssetId.value = null
  void loadOutboundAssets()
}

function handleOutboundAssetSizeChange(): void {
  selectedAssetId.value = null
  outboundAssetQuery.page = 1
  void loadOutboundAssets()
}

async function submitAction(): Promise<void> {
  const request = actionRequest.value
  if (!request) return
  if (actionMode.value === 'reject' && !actionComment.value.trim()) {
    ElMessage.warning('请填写驳回原因')
    return
  }
  if (outboundNeedsSelection.value && !selectedOutboundAsset.value) {
    ElMessage.warning('请选择要出库的具体资产')
    return
  }

  actionSubmitting.value = true
  try {
    let updated: AssetRequestItem
    if (actionMode.value === 'approve') {
      updated = await assetFlowApi.approve(request.id, actionComment.value || null)
      if (updated.status === 'PENDING_APPROVAL') {
        if (updated.flow_id && updated.current_step_name) {
          ElMessage.success(`审批通过，已流转至「${updated.current_step_name}」`)
        } else if (updated.approval_stage) {
          ElMessage.success(`审批通过，已转${updated.approval_stage_label}`)
        } else {
          ElMessage.success('审批通过')
        }
      } else {
        ElMessage.success('审批通过，单据已进入待出库')
      }
    } else if (actionMode.value === 'reject') {
      updated = await assetFlowApi.reject(request.id, actionComment.value)
      ElMessage.success('申请已驳回，流程已结束')
    } else if (actionMode.value === 'outbound') {
      updated = await assetFlowApi.outbound(request.id, {
        version: outboundNeedsSelection.value
          ? (selectedOutboundAsset.value?.version as number)
          : request.asset_version,
        asset_id: outboundNeedsSelection.value ? selectedAssetId.value : undefined,
        location: actionLocation.value || null,
        comment: actionComment.value || null,
      })
      ElMessage.success(
        updated.asset_no
          ? `出库完成，已绑定资产 ${updated.asset_no} 并同步责任人`
          : '出库完成，资产状态与责任人已实时同步',
      )
    } else {
      updated = await assetFlowApi.confirmReturn(request.id, {
        version: request.asset_version,
        location: actionLocation.value || null,
        comment: actionComment.value || null,
      })
      ElMessage.success('归还完成，资产已回到在库状态')
    }
    actionVisible.value = false
    if (detailRequest.value?.id === updated.id) detailRequest.value = updated
    await refreshAll()
  } finally {
    actionSubmitting.value = false
  }
}

function handleActionScan(asset: AvailableAsset): void {
  const request = actionRequest.value
  if (!request?.asset_id) {
    ElMessage.info('请先在列表中选择要出库的具体资产')
    return
  }
  if (asset.id !== request.asset_id) {
    scanVerified.value = false
    ElMessage.error(`扫码资产与单据不一致：${asset.asset_no}`)
    return
  }
  scanVerified.value = true
  ElMessage.success(`扫码核对通过：${asset.asset_no} ${asset.name}`)
}

function handleToolbarScan(
  asset: AvailableAsset,
  result: { requests: AssetRequestItem[] },
): void {
  if (result.requests.length) {
    void openDetail(result.requests[0])
    return
  }
  ElMessage.info(`资产 ${asset.asset_no} 当前没有进行中的业务单据`)
}

onMounted(async () => {
  await refreshAll()
  await openFocused()
  void fetchApprovalConfig()
})
</script>

<template>
  <div class="page review-page">
    <header class="page-header">
      <div>
        <p class="page-eyebrow">{{ pageInfo.eyebrow }}</p>
        <h1 class="page-title">{{ pageInfo.title }}</h1>
        <p class="page-subtitle">{{ pageInfo.subtitle }}</p>
      </div>
      <div class="page-actions">
        <el-button :icon="Camera" @click="toolbarScanVisible = true">扫码定位</el-button>
        <el-button :icon="Refresh" :loading="loading" @click="refreshAll">刷新</el-button>
      </div>
    </header>

    <section
      v-if="canConfigure && pageMode === 'review' && approvalConfig"
      class="surface-card config-bar"
    >
      <div class="config-copy">
        <span>传统两级审批（兜底）</span>
        <small>
          仅对未匹配到审批流程的部门生效：开启后按“部门管理员 → 资产管理员”两级审批；已配置专属或默认流程的部门以流程配置为准。
        </small>
      </div>
      <el-switch
        :model-value="approvalConfig.dept_approval_required"
        :loading="configSaving"
        :disabled="configSaving"
        active-text="开启"
        inactive-text="关闭"
        inline-prompt
        @change="handleConfigChange"
      />
    </section>

    <section class="summary-strip" :class="{ single: pageMode !== 'review' }">
      <button
        v-for="card in summaryCards"
        :key="card.key"
        type="button"
        class="summary-card surface-card"
        :class="{ active: query.status === card.key }"
        @click="filterByStatus(card.key)"
      >
        <span>{{ card.label }}</span>
        <strong>{{ card.value }}</strong>
      </button>
      <div class="summary-scope">
        <span>数据范围</span>
        <strong>{{ auth.dataScopeLabel || '按角色收敛' }}</strong>
        <small>可配置流程审批人仅能看到分配给自己的待办；部门管理员可见本部门及下级部门单据</small>
      </div>
    </section>

    <section class="surface-card panel">
      <div class="filter-bar">
        <el-input
          v-model="query.keyword"
          :prefix-icon="Search"
          placeholder="单据号 / 申请人 / 分类"
          clearable
          class="filter-keyword"
          @keyup.enter="handleSearch"
          @clear="handleSearch"
        />
        <el-select
          v-model="query.request_type"
          placeholder="单据类型"
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
        <el-checkbox
          v-if="pageMode === 'review'"
          v-model="onlyMine"
          class="mine-toggle"
          @change="handleOnlyMineChange"
        >
          仅看我的待办
        </el-checkbox>
        <div class="filter-actions">
          <el-button :icon="Search" @click="handleSearch">查询</el-button>
          <el-button text @click="resetFilters">重置</el-button>
        </div>
      </div>

      <el-table
        v-loading="loading"
        :data="requests"
        row-key="id"
        :empty-text="
          onlyMine ? '当前没有待您处理的业务单据' : '当前没有业务单据'
        "
      >
        <el-table-column label="单据" min-width="190">
          <template #default="{ row }">
            <div class="stack-cell">
              <span class="mono">{{ row.request_no }}</span>
              <small>
                {{ REQUEST_TYPE_LABELS[row.request_type as AssetRequestType] }} ·
                {{ formatDateTime(row.created_at) }}
              </small>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="申请分类 / 资产" min-width="210">
          <template #default="{ row }">
            <div class="stack-cell">
              <span>{{ row.category_name }}</span>
              <small v-if="row.asset_no" class="mono">
                已分配：{{ row.asset_no }} · {{ row.asset_name }}
              </small>
              <small v-else class="pending-text">待出库分配具体资产</small>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="申请人" min-width="130">
          <template #default="{ row }">
            <div class="stack-cell">
              <span>{{ row.applicant_name }}</span>
              <small>{{ row.applicant_dept_name || '未分配部门' }}</small>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="150">
          <template #default="{ row }">
            <div class="status-cell">
              <el-tag
                :type="REQUEST_STATUS_TAG_TYPES[row.status as AssetRequestStatus]"
                effect="light"
              >
                {{ row.status_label }}
              </el-tag>
              <small v-if="stageHint(row)">{{ stageHint(row) }}</small>
              <small
                v-if="
                  row.status === 'PENDING_APPROVAL' &&
                  row.flow_id &&
                  row.current_approvers.length
                "
              >
                待 {{ row.current_approvers.join('、') }}
              </small>
              <el-tag
                v-if="row.is_overdue"
                type="danger"
                size="small"
                effect="plain"
                class="overdue-tag"
              >
                逾期
              </el-tag>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="预计归还" width="120">
          <template #default="{ row }">
            {{ row.expected_return_date || '—' }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="260" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openDetail(row)">详情</el-button>
            <el-button
              v-if="showAction('approve') && canOperate(row, 'approve')"
              link
              type="success"
              @click="openAction(row, 'approve')"
            >
              {{ approveActionLabel(row) }}
            </el-button>
            <el-button
              v-if="showAction('reject') && canOperate(row, 'reject')"
              link
              type="danger"
              @click="openAction(row, 'reject')"
            >
              驳回
            </el-button>
            <el-button
              v-if="showAction('outbound') && canOperate(row, 'outbound')"
              link
              type="primary"
              @click="openAction(row, 'outbound')"
            >
              确认出库
            </el-button>
            <el-button
              v-if="showAction('return') && canOperate(row, 'return')"
              link
              type="warning"
              @click="openAction(row, 'return')"
            >
              确认归还
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
          @current-change="fetchRequests"
          @size-change="handleSearch"
        />
      </div>
    </section>

    <el-dialog v-model="actionVisible" :title="actionTitle" width="680px">
      <div v-if="actionRequest" class="action-summary">
        <div>
          <span>{{ actionRequest.category_name }}</span>
          <small>
            {{ actionRequest.request_no }} · {{ actionRequest.applicant_name }}
            <template v-if="actionRequest.asset_no">
              · 已绑定 {{ actionRequest.asset_no }}
            </template>
          </small>
        </div>
        <el-tag :type="actionRequest.status_tag_type" effect="light">
          {{ actionRequest.status_label }}
        </el-tag>
      </div>

      <div v-if="outboundNeedsSelection" class="outbound-picker">
        <div class="outbound-picker-head">
          <div>
            <strong>选择要出库的具体资产</strong>
            <small>
              仅展示“{{ actionRequest?.category_name }}”分类下的在库资产，已排除被其他单据占用的资产
            </small>
          </div>
          <span>共 {{ outboundAssetTotal }} 台可选</span>
        </div>
        <el-table
          v-loading="outboundAssetLoading"
          :data="outboundAssetList"
          row-key="id"
          max-height="280"
          highlight-current-row
          empty-text="该分类下暂无可出库的在库资产"
          @current-change="handleOutboundAssetCurrentChange"
          @row-click="handleOutboundAssetCurrentChange"
        >
          <el-table-column width="48">
            <template #default="{ row }">
              <el-radio v-model="selectedAssetId" :value="row.id">
                <span class="sr-only">选择</span>
              </el-radio>
            </template>
          </el-table-column>
          <el-table-column label="资产编号" min-width="150">
            <template #default="{ row }">
              <span class="mono">{{ row.asset_no }}</span>
            </template>
          </el-table-column>
          <el-table-column label="资产名称" min-width="150" prop="name" />
          <el-table-column label="型号" min-width="140">
            <template #default="{ row }">{{ row.model_name || '—' }}</template>
          </el-table-column>
          <el-table-column label="当前位置" min-width="130">
            <template #default="{ row }">{{ row.location || '—' }}</template>
          </el-table-column>
        </el-table>
        <div class="outbound-picker-footer">
          <span v-if="selectedOutboundAsset">
            已选择：{{ selectedOutboundAsset.asset_no }} · {{ selectedOutboundAsset.name }}
          </span>
          <span v-else>请选择一台资产</span>
          <el-pagination
            v-model:current-page="outboundAssetQuery.page"
            v-model:page-size="outboundAssetQuery.page_size"
            :total="outboundAssetTotal"
            :page-sizes="[10, 20, 50]"
            layout="total, sizes, prev, pager, next"
            small
            background
            @current-change="handleOutboundAssetPageChange"
            @size-change="handleOutboundAssetSizeChange"
          />
        </div>
      </div>

      <div
        v-if="
          (actionMode === 'outbound' && !outboundNeedsSelection) ||
          actionMode === 'return'
        "
        class="scan-verify"
      >
        <el-button :icon="Camera" @click="actionScanVisible = true">
          扫码核对资产
        </el-button>
        <el-tag v-if="scanVerified" type="success" effect="light">扫码核对通过</el-tag>
        <span v-else>建议使用扫码枪核对实物编号，避免错发、错还</span>
      </div>

      <el-form label-position="top">
        <el-form-item
          v-if="actionMode === 'outbound' || actionMode === 'return'"
          label="存放位置"
        >
          <el-input
            v-model="actionLocation"
            maxlength="120"
            placeholder="出库后的使用位置 / 归还后的入库位置"
          />
        </el-form-item>
        <el-form-item
          :label="
            actionMode === 'approve'
              ? '审批意见（选填）'
              : actionMode === 'reject'
                ? '驳回原因（必填）'
                : '备注（选填）'
          "
        >
          <el-input
            v-model="actionComment"
            type="textarea"
            :rows="3"
            maxlength="500"
            show-word-limit
            :placeholder="
              actionMode === 'reject'
                ? '请说明驳回原因，便于申请人调整后重新提交'
                : '可填写补充说明'
            "
          />
        </el-form-item>
      </el-form>

      <el-alert
        v-if="actionMode === 'outbound' || actionMode === 'return'"
        type="info"
        :closable="false"
        show-icon
        title="该操作将同时更新资产状态、责任人、单据、状态历史与审计日志"
      />

      <template #footer>
        <el-button @click="actionVisible = false">取消</el-button>
        <el-button
          :type="
            actionMode === 'reject'
              ? 'danger'
              : actionMode === 'return'
                ? 'warning'
                : 'primary'
          "
          :loading="actionSubmitting"
          @click="submitAction"
        >
          {{ actionSubmitText }}
        </el-button>
      </template>
    </el-dialog>

    <RequestDetailDrawer v-model="detailVisible" :request="detailRequest">
      <template #actions="{ request }">
        <el-button
          v-if="showAction('approve') && request.can_approve"
          type="success"
          plain
          @click="openAction(request, 'approve')"
        >
          {{ approveActionLabel(request) }}
        </el-button>
        <el-button
          v-if="showAction('reject') && request.can_reject"
          type="danger"
          plain
          @click="openAction(request, 'reject')"
        >
          驳回
        </el-button>
        <el-button
          v-if="showAction('outbound') && request.can_outbound"
          type="primary"
          @click="openAction(request, 'outbound')"
        >
          确认出库
        </el-button>
        <el-button
          v-if="showAction('return') && request.can_confirm_return"
          type="warning"
          @click="openAction(request, 'return')"
        >
          确认归还
        </el-button>
      </template>
    </RequestDetailDrawer>

    <ScanDialog
      v-model="actionScanVisible"
      title="扫码核对资产"
      hint="扫描或输入实物资产编号，系统会校验是否与当前单据一致。"
      @select="handleActionScan"
    />
    <ScanDialog v-model="toolbarScanVisible" @select="handleToolbarScan" />
  </div>
</template>

<style scoped>
.page-actions {
  display: flex;
  gap: 10px;
}

.config-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 14px 18px;
  margin-bottom: 16px;
}

.config-copy span {
  display: block;
  font-weight: 650;
  color: var(--text-1);
}

.config-copy small {
  display: block;
  margin-top: 3px;
  color: var(--text-3);
  font-size: 12px;
}

.summary-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr)) 1.4fr;
  gap: 14px;
  margin-bottom: 18px;
}

.summary-strip.single {
  grid-template-columns: minmax(0, 1fr) 1.4fr;
}

.summary-card {
  text-align: left;
  padding: 16px 18px;
  cursor: pointer;
  border: 1px solid var(--border);
  transition: transform 0.2s ease, border-color 0.2s ease, box-shadow 0.2s ease;
}

.summary-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-md);
}

.summary-card.active {
  border-color: var(--brand);
  box-shadow: 0 0 0 3px var(--brand-soft);
}

.summary-card span,
.summary-scope span {
  color: var(--text-3);
  font-size: 12px;
}

.summary-card strong,
.summary-scope strong {
  display: block;
  margin-top: 6px;
  font-family: var(--font-number);
  font-size: 24px;
  color: var(--text-1);
}

.summary-scope {
  padding: 16px 18px;
  border-radius: var(--radius-lg);
  border: 1px dashed var(--border-strong);
  background: var(--brand-soft);
}

.summary-scope small {
  display: block;
  margin-top: 4px;
  color: var(--text-2);
  font-size: 11.5px;
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
  width: 280px;
}

.filter-select {
  width: 150px;
}

.mine-toggle {
  margin-left: 2px;
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

.pending-text {
  color: var(--warning-strong, #b45309);
  font-weight: 600;
}

.status-cell {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
}

.status-cell small {
  color: var(--warning-strong, #b45309);
  font-size: 11.5px;
}

.mono {
  font-family: var(--font-number);
  font-weight: 600;
}

.overdue-tag {
  margin-left: 0;
}

.table-footer {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
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

.outbound-picker {
  padding: 12px;
  margin-bottom: 16px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--surface-muted);
}

.outbound-picker-head {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 10px;
}

.outbound-picker-head strong {
  display: block;
  color: var(--text-1);
}

.outbound-picker-head small {
  display: block;
  margin-top: 2px;
  color: var(--text-3);
  font-size: 12px;
}

.outbound-picker-head > span {
  color: var(--text-2);
  font-size: 12px;
}

.outbound-picker-footer {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-top: 10px;
  color: var(--text-3);
  font-size: 12px;
}

.scan-verify {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
  color: var(--text-3);
  font-size: 12px;
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

@media (max-width: 1100px) {
  .summary-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .summary-strip.single {
    grid-template-columns: minmax(0, 1fr) 1.4fr;
  }
}
</style>
