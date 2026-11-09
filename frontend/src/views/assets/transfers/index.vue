<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh, Search } from '@element-plus/icons-vue'

import { assetOpsApi } from '@/api/assetOps'
import { useAuthStore } from '@/stores/auth'
import type { TagType } from '@/types/assetFlow'
import type {
  DeptOption,
  OpsAsset,
  TransferItem,
  TransferStatus,
  UserOption,
} from '@/types/assetOps'
import {
  TRANSFER_STATUS_LABELS,
  isTransferInterrupted,
  transferActive,
  transferSteps,
} from '@/types/assetOps'
import { formatDateTime } from '@/utils/format'

const DINGTALK_STATUS_META: Record<
  NonNullable<TransferItem['dingtalk_status']>,
  { label: string; type: TagType }
> = {
  RUNNING: { label: '钉钉审批中', type: 'warning' },
  APPROVED: { label: '钉钉已通过', type: 'success' },
  REJECTED: { label: '钉钉已驳回', type: 'danger' },
  TERMINATED: { label: '钉钉已撤销', type: 'info' },
}

function dingtalkMeta(
  status: TransferItem['dingtalk_status'],
): { label: string; type: TagType } {
  return status && DINGTALK_STATUS_META[status]
    ? DINGTALK_STATUS_META[status]
    : { label: '钉钉审批', type: 'info' }
}

type ActionMode = 'approve' | 'reject' | 'confirm'

const auth = useAuthStore()
const route = useRoute()
const focusId = (() => {
  const raw = route.query.focus
  const value = typeof raw === 'string' ? Number(raw) : Number.NaN
  return Number.isInteger(value) && value > 0 ? value : null
})()

const loading = ref(false)
const transfers = ref<TransferItem[]>([])
const total = ref(0)
const query = reactive({
  page: 1,
  page_size: 10,
  keyword: '',
  status: undefined as TransferStatus | undefined,
})
const statusOptions = Object.entries(TRANSFER_STATUS_LABELS) as Array<
  [TransferStatus, string]
>

const createVisible = ref(false)
const createSubmitting = ref(false)
const assetOptions = ref<OpsAsset[]>([])
const assetSearching = ref(false)
const selectedAsset = ref<OpsAsset | null>(null)
const depts = ref<DeptOption[]>([])
const custodianOptions = ref<UserOption[]>([])
const selectedCustodian = ref<UserOption | null>(null)
const form = reactive({
  asset_id: undefined as number | undefined,
  to_dept_id: undefined as number | undefined,
  to_custodian_id: undefined as number | undefined,
  to_location: '',
  reason: '',
})

const detailVisible = ref(false)
const detailItem = ref<TransferItem | null>(null)

const actionVisible = ref(false)
const actionMode = ref<ActionMode>('approve')
const actionItem = ref<TransferItem | null>(null)
const actionComment = ref('')
const actionSubmitting = ref(false)

const actionTitle = computed(() => {
  const titles: Record<ActionMode, string> = {
    approve: '审批调拨',
    reject: '驳回调拨',
    confirm: '确认调拨',
  }
  return titles[actionMode.value]
})

const custodianSelectOptions = computed(() => {
  const options = [...custodianOptions.value]
  if (
    form.to_custodian_id &&
    selectedCustodian.value &&
    !options.some((user) => user.id === form.to_custodian_id)
  ) {
    options.unshift(selectedCustodian.value)
  }
  return options
})

const canCreate = computed(() => auth.hasPerm('asset:transfer:create'))

async function fetchTransfers(): Promise<void> {
  loading.value = true
  try {
    const page = await assetOpsApi.listTransfers({
      page: query.page,
      page_size: query.page_size,
      keyword: query.keyword || undefined,
      status: query.status,
    })
    transfers.value = page.items
    total.value = page.total
  } finally {
    loading.value = false
  }
}

function handleSearch(): void {
  query.page = 1
  void fetchTransfers()
}

function resetFilters(): void {
  query.keyword = ''
  query.status = undefined
  query.page = 1
  void fetchTransfers()
}

async function searchAssets(keyword: string): Promise<void> {
  assetSearching.value = true
  try {
    const page = await assetOpsApi.operableAssets({
      purpose: 'transfer',
      page: 1,
      page_size: 30,
      keyword: keyword || undefined,
    })
    const pinned = selectedAsset.value ? [selectedAsset.value] : []
    assetOptions.value = [
      ...pinned,
      ...page.items.filter((item) => item.id !== selectedAsset.value?.id),
    ]
  } finally {
    assetSearching.value = false
  }
}

async function searchCustodians(keyword: string): Promise<void> {
  custodianOptions.value = await assetOpsApi.users(keyword || undefined)
}

function handleAssetChange(id: number): void {
  selectedAsset.value = assetOptions.value.find((item) => item.id === id) ?? null
}

function handleCustodianChange(id: number): void {
  selectedCustodian.value =
    custodianSelectOptions.value.find((item) => item.id === id) ?? null
  if (selectedCustodian.value && !form.to_dept_id) {
    form.to_dept_id = selectedCustodian.value.dept_id ?? undefined
  }
}

async function openCreate(): Promise<void> {
  form.asset_id = undefined
  form.to_dept_id = undefined
  form.to_custodian_id = undefined
  form.to_location = ''
  form.reason = ''
  selectedAsset.value = null
  selectedCustodian.value = null
  assetOptions.value = []
  custodianOptions.value = []
  createVisible.value = true
  await Promise.all([searchAssets(''), searchCustodians(''), loadDepartments()])
}

async function loadDepartments(): Promise<void> {
  if (depts.value.length) return
  depts.value = await assetOpsApi.departments()
}

async function submitCreate(): Promise<void> {
  if (!form.asset_id) {
    ElMessage.warning('请选择要调拨的资产')
    return
  }
  if (!form.to_dept_id && !form.to_custodian_id && !form.to_location.trim()) {
    ElMessage.warning('请至少填写调入部门、责任人或存放位置之一')
    return
  }
  createSubmitting.value = true
  try {
    await assetOpsApi.createTransfer({
      asset_id: form.asset_id,
      to_dept_id: form.to_dept_id ?? null,
      to_custodian_id: form.to_custodian_id ?? null,
      to_location: form.to_location.trim() || null,
      reason: form.reason.trim() || null,
    })
    ElMessage.success('调拨申请已提交，等待审批')
    createVisible.value = false
    handleSearch()
  } finally {
    createSubmitting.value = false
  }
}

function openDetail(row: TransferItem): void {
  detailItem.value = row
  detailVisible.value = true
}

async function openFocused(): Promise<void> {
  if (!focusId) return
  const row = transfers.value.find((item) => item.id === focusId)
  if (row) {
    openDetail(row)
    return
  }
  try {
    detailItem.value = await assetOpsApi.getTransfer(focusId)
    detailVisible.value = true
  } catch {
    // 目标单据无权限或已失效时停留在列表页
  }
}

function openAction(row: TransferItem, mode: ActionMode): void {
  actionItem.value = row
  actionMode.value = mode
  actionComment.value = ''
  actionVisible.value = true
}

async function submitAction(): Promise<void> {
  const item = actionItem.value
  if (!item) return
  if (actionMode.value === 'reject' && !actionComment.value.trim()) {
    ElMessage.warning('请填写驳回原因')
    return
  }
  actionSubmitting.value = true
  try {
    if (actionMode.value === 'approve') {
      await assetOpsApi.approveTransfer(item.id, actionComment.value || null)
      ElMessage.success('审批通过，等待确认调拨')
    } else if (actionMode.value === 'reject') {
      await assetOpsApi.rejectTransfer(item.id, actionComment.value)
      ElMessage.success('调拨单已驳回')
    } else {
      await assetOpsApi.confirmTransfer(item.id, {
        version: item.asset_version,
        comment: actionComment.value || null,
      })
      ElMessage.success('调拨完成，资产部门、责任人与位置已实时同步')
    }
    actionVisible.value = false
    if (detailItem.value?.id === item.id) detailItem.value = null
    detailVisible.value = false
    await fetchTransfers()
  } finally {
    actionSubmitting.value = false
  }
}

async function cancelTransfer(row: TransferItem): Promise<void> {
  await ElMessageBox.confirm(
    `确定撤销调拨单 ${row.transfer_no} 吗？撤销后需重新发起。`,
    '撤销调拨',
    { type: 'warning', confirmButtonText: '撤销', cancelButtonText: '返回' },
  )
  await assetOpsApi.cancelTransfer(row.id)
  ElMessage.success('调拨单已撤销')
  await fetchTransfers()
}

function deptLabel(dept: DeptOption): string {
  return `${'　'.repeat(Math.max(dept.level - 1, 0))}${dept.name}`
}

function targetText(item: TransferItem): string {
  return [item.to_dept_name, item.to_custodian_name, item.to_location]
    .filter(Boolean)
    .join(' · ')
}

onMounted(async () => {
  await fetchTransfers()
  await openFocused()
})
</script>

<template>
  <div class="page transfer-page">
    <header class="page-header">
      <div>
        <p class="page-eyebrow">ASSET OPERATION</p>
        <h1 class="page-title">资产调拨</h1>
        <p class="page-subtitle">
          跨部门或跨责任人调拨资产。审批通过后由资产管理员确认，确认时在事务内同步资产、单据、状态历史与审计记录。
        </p>
      </div>
      <div class="page-actions">
        <el-button :icon="Refresh" :loading="loading" @click="fetchTransfers">刷新</el-button>
        <el-button v-if="canCreate" type="primary" :icon="Plus" @click="openCreate">
          发起调拨
        </el-button>
      </div>
    </header>

    <section class="surface-card panel">
      <div class="filter-bar">
        <el-input
          v-model="query.keyword"
          :prefix-icon="Search"
          placeholder="调拨单号 / 资产编号 / 资产名称 / 申请人"
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
        <div class="filter-actions">
          <el-button :icon="Search" @click="handleSearch">查询</el-button>
          <el-button text @click="resetFilters">重置</el-button>
        </div>
      </div>

      <el-table
        v-loading="loading"
        :data="transfers"
        row-key="id"
        empty-text="当前没有调拨单"
      >
        <el-table-column label="调拨单" min-width="190">
          <template #default="{ row }">
            <div class="stack-cell">
              <span class="mono">{{ row.transfer_no }}</span>
              <small>{{ formatDateTime(row.created_at) }}</small>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="资产" min-width="210">
          <template #default="{ row }">
            <div class="stack-cell">
              <span>{{ row.asset_name }}</span>
              <small>{{ row.asset_no }} · {{ row.asset_status_label }}</small>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="调出 → 调入" min-width="260">
          <template #default="{ row }">
            <div class="stack-cell">
              <span>
                {{ row.from_dept_name || '未分配部门' }} /
                {{ row.from_custodian_name || '无责任人' }}
                <span class="arrow">→</span>
                {{ row.to_dept_name || row.from_dept_name || '原部门' }} /
                {{ row.to_custodian_name || '无责任人' }}
              </span>
              <small>{{ row.to_location || '沿用原位置' }}</small>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="申请人" min-width="140">
          <template #default="{ row }">
            <div class="stack-cell">
              <span>{{ row.applicant_name }}</span>
              <small>{{ row.applicant_dept_name || '未分配部门' }}</small>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="150">
          <template #default="{ row }">
            <div class="stack-cell">
              <el-tag :type="row.status_tag_type" effect="light">{{ row.status_label }}</el-tag>
              <el-tag
                v-if="row.dingtalk_instance_id"
                size="small"
                :type="dingtalkMeta(row.dingtalk_status).type"
                effect="plain"
              >
                {{ dingtalkMeta(row.dingtalk_status).label }}
              </el-tag>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="260" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openDetail(row)">详情</el-button>
            <el-button
              v-if="row.can_approve"
              link
              type="success"
              @click="openAction(row, 'approve')"
            >
              审批
            </el-button>
            <el-button
              v-if="row.can_reject"
              link
              type="danger"
              @click="openAction(row, 'reject')"
            >
              驳回
            </el-button>
            <el-button
              v-if="row.can_confirm"
              link
              type="primary"
              @click="openAction(row, 'confirm')"
            >
              确认调拨
            </el-button>
            <el-button v-if="row.can_cancel" link type="warning" @click="cancelTransfer(row)">
              撤销
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
          @current-change="fetchTransfers"
          @size-change="handleSearch"
        />
      </div>
    </section>

    <el-dialog v-model="createVisible" title="发起资产调拨" width="620px">
      <el-form label-position="top">
        <el-form-item label="调拨资产" required>
          <el-select
            v-model="form.asset_id"
            filterable
            remote
            clearable
            reserve-keyword
            :remote-method="searchAssets"
            :loading="assetSearching"
            placeholder="输入资产编号或名称搜索"
            class="full-width"
            @change="handleAssetChange"
          >
            <el-option
              v-for="asset in assetOptions"
              :key="asset.id"
              :label="`${asset.asset_no} · ${asset.name}`"
              :value="asset.id"
            >
              <div class="option-cell">
                <span>{{ asset.asset_no }} · {{ asset.name }}</span>
                <small>
                  {{ asset.status_label }} · {{ asset.dept_name || '未分配部门' }} ·
                  {{ asset.custodian_name || '无责任人' }}
                </small>
              </div>
            </el-option>
          </el-select>
        </el-form-item>

        <div v-if="selectedAsset" class="asset-preview">
          <div>
            <span>{{ selectedAsset.name }}</span>
            <small>
              {{ selectedAsset.asset_no }} · {{ selectedAsset.category_name || '未分类' }} ·
              {{ selectedAsset.location || '未登记位置' }}
            </small>
          </div>
          <el-tag type="primary" effect="light">{{ selectedAsset.status_label }}</el-tag>
        </div>

        <div class="form-grid">
          <el-form-item label="调入部门">
            <el-select
              v-model="form.to_dept_id"
              clearable
              filterable
              placeholder="选择调入部门"
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
          <el-form-item label="新责任人">
            <el-select
              v-model="form.to_custodian_id"
              clearable
              filterable
              remote
              reserve-keyword
              :remote-method="searchCustodians"
              placeholder="输入姓名搜索"
              class="full-width"
              @change="handleCustodianChange"
            >
              <el-option
                v-for="user in custodianSelectOptions"
                :key="user.id"
                :label="`${user.name}（${user.dept_name || '未分配部门'}）`"
                :value="user.id"
              />
            </el-select>
          </el-form-item>
        </div>

        <el-form-item label="调入位置">
          <el-input
            v-model="form.to_location"
            maxlength="120"
            :placeholder="selectedAsset?.location || '不填写则沿用原存放位置'"
          />
        </el-form-item>
        <el-form-item label="调拨原因">
          <el-input
            v-model="form.reason"
            type="textarea"
            :rows="3"
            maxlength="500"
            show-word-limit
            placeholder="说明调拨原因，便于审批人判断"
          />
        </el-form-item>
      </el-form>
      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="调入部门、责任人与位置至少填写一项；确认调拨时会校验资产版本号"
      />
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="createSubmitting" @click="submitCreate">
          提交调拨申请
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="detailVisible" title="调拨单详情" width="680px">
      <template v-if="detailItem">
        <el-steps
          :active="transferActive(detailItem.status)"
          :process-status="isTransferInterrupted(detailItem.status) ? 'error' : 'process'"
          finish-status="success"
          align-center
          class="flow-steps"
        >
          <el-step v-for="step in transferSteps()" :key="step" :title="step" />
        </el-steps>

        <el-descriptions :column="2" border>
          <el-descriptions-item label="调拨单号">{{ detailItem.transfer_no }}</el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="detailItem.status_tag_type" effect="light">
              {{ detailItem.status_label }}
            </el-tag>
            <el-tag
              v-if="detailItem.dingtalk_instance_id"
              :type="dingtalkMeta(detailItem.dingtalk_status).type"
              effect="plain"
              style="margin-left: 8px"
            >
              {{ dingtalkMeta(detailItem.dingtalk_status).label }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item
            v-if="detailItem.dingtalk_instance_id"
            label="钉钉审批"
            :span="2"
          >
            <span class="mono">{{ detailItem.dingtalk_instance_id }}</span>
            <span class="muted">（钉钉审批替代系统内审批，结果自动同步）</span>
          </el-descriptions-item>
          <el-descriptions-item label="资产">
            {{ detailItem.asset_name }}（{{ detailItem.asset_no }}）
          </el-descriptions-item>
          <el-descriptions-item label="资产当前状态">
            {{ detailItem.asset_status_label }}
          </el-descriptions-item>
          <el-descriptions-item label="调出">
            {{ detailItem.from_dept_name || '未分配部门' }} /
            {{ detailItem.from_custodian_name || '无责任人' }} /
            {{ detailItem.from_location || '未登记位置' }}
          </el-descriptions-item>
          <el-descriptions-item label="调入">
            {{ detailItem.to_dept_name || '沿用原部门' }} /
            {{ detailItem.to_custodian_name || '无责任人' }} /
            {{ detailItem.to_location || '沿用原位置' }}
          </el-descriptions-item>
          <el-descriptions-item label="申请人">
            {{ detailItem.applicant_name }}（{{ detailItem.applicant_dept_name || '未分配部门' }}）
          </el-descriptions-item>
          <el-descriptions-item label="申请时间">
            {{ formatDateTime(detailItem.created_at) }}
          </el-descriptions-item>
          <el-descriptions-item label="审批人">
            {{ detailItem.approver_name || '—' }}
          </el-descriptions-item>
          <el-descriptions-item label="审批时间">
            {{ formatDateTime(detailItem.approved_at) }}
          </el-descriptions-item>
          <el-descriptions-item label="确认人">
            {{ detailItem.completed_by_name || '—' }}
          </el-descriptions-item>
          <el-descriptions-item label="确认时间">
            {{ formatDateTime(detailItem.completed_at) }}
          </el-descriptions-item>
          <el-descriptions-item label="调拨原因" :span="2">
            {{ detailItem.reason || '—' }}
          </el-descriptions-item>
          <el-descriptions-item label="审批意见" :span="2">
            {{ detailItem.approval_comment || '—' }}
          </el-descriptions-item>
          <el-descriptions-item label="确认备注" :span="2">
            {{ detailItem.completion_comment || '—' }}
          </el-descriptions-item>
        </el-descriptions>
      </template>
      <template #footer>
        <el-button @click="detailVisible = false">关闭</el-button>
        <el-button
          v-if="detailItem?.can_approve"
          type="success"
          @click="detailItem && openAction(detailItem, 'approve')"
        >
          审批
        </el-button>
        <el-button
          v-if="detailItem?.can_confirm"
          type="primary"
          @click="detailItem && openAction(detailItem, 'confirm')"
        >
          确认调拨
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="actionVisible" :title="actionTitle" width="520px">
      <div v-if="actionItem" class="action-summary">
        <div>
          <span>{{ actionItem.asset_name }}</span>
          <small>{{ actionItem.asset_no }} · {{ actionItem.transfer_no }}</small>
        </div>
        <el-tag :type="actionItem.status_tag_type" effect="light">
          {{ actionItem.status_label }}
        </el-tag>
      </div>

      <div v-if="actionMode === 'confirm'" class="transfer-target">
        <span>调往</span>
        <strong>{{ (actionItem && targetText(actionItem)) || '沿用原信息' }}</strong>
      </div>

      <el-form label-position="top">
        <el-form-item
          :label="
            actionMode === 'approve'
              ? '审批意见（选填）'
              : actionMode === 'reject'
                ? '驳回原因（必填）'
                : '确认备注（选填）'
          "
        >
          <el-input
            v-model="actionComment"
            type="textarea"
            :rows="3"
            maxlength="500"
            show-word-limit
            :placeholder="actionMode === 'reject' ? '请说明驳回原因' : '可填写补充说明'"
          />
        </el-form-item>
      </el-form>

      <el-alert
        v-if="actionMode === 'confirm'"
        type="warning"
        :closable="false"
        show-icon
        title="确认后将同步更新资产的部门、责任人、存放位置，并写入状态历史与审计日志"
      />
      <template #footer>
        <el-button @click="actionVisible = false">取消</el-button>
        <el-button
          :type="actionMode === 'reject' ? 'danger' : 'primary'"
          :loading="actionSubmitting"
          @click="submitAction"
        >
          确认{{ actionTitle }}
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
  width: 320px;
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

.arrow {
  margin: 0 4px;
  color: var(--brand);
}

.table-footer {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}

.full-width {
  width: 100%;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 16px;
}

.option-cell {
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.option-cell small {
  color: var(--text-3);
  font-size: 11px;
}

.asset-preview {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
  padding: 12px 14px;
  border-radius: 12px;
  border: 1px solid var(--border);
  background: var(--surface-muted);
}

.asset-preview span {
  font-weight: 650;
  color: var(--text-1);
}

.asset-preview small {
  display: block;
  margin-top: 2px;
  color: var(--text-3);
  font-size: 12px;
}

.flow-steps {
  margin-bottom: 22px;
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

.transfer-target {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 16px;
  padding: 12px 14px;
  border-radius: 10px;
  background: var(--brand-soft);
  color: var(--text-2);
}

.transfer-target strong {
  color: var(--text-1);
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
