<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import dayjs from 'dayjs'
import { useRoute } from 'vue-router'
import {
  ElMessage,
  ElMessageBox,
  type FormInstance,
  type FormRules,
} from 'element-plus'
import { ArrowRight, Camera, Check, Plus, Refresh, Search } from '@element-plus/icons-vue'

import RequestDetailDrawer from '@/components/asset-flow/RequestDetailDrawer.vue'
import ScanDialog from '@/components/ScanDialog.vue'
import { assetFlowApi } from '@/api/assetFlow'
import { useFilterMemory } from '@/composables/useFilterMemory'
import type {
  AssetRequestItem,
  AssetRequestStatus,
  AssetRequestSummary,
  AssetRequestType,
  AvailableAsset,
  AvailableCategory,
} from '@/types/assetFlow'
import {
  REQUEST_STATUS_LABELS,
  REQUEST_STATUS_TAG_TYPES,
  REQUEST_TYPE_LABELS,
  type TagType,
} from '@/types/assetFlow'
import { formatDateTime } from '@/utils/format'

const DINGTALK_STATUS_META: Record<
  NonNullable<AssetRequestItem['dingtalk_status']>,
  { label: string; type: TagType }
> = {
  RUNNING: { label: '钉钉审批中', type: 'warning' },
  APPROVED: { label: '钉钉已通过', type: 'success' },
  REJECTED: { label: '钉钉已驳回', type: 'danger' },
  TERMINATED: { label: '钉钉已撤销', type: 'info' },
}

function dingtalkMeta(
  status: AssetRequestItem['dingtalk_status'],
): { label: string; type: TagType } {
  return status && DINGTALK_STATUS_META[status]
    ? DINGTALK_STATUS_META[status]
    : { label: '钉钉审批', type: 'info' }
}

interface CreateForm {
  request_type: AssetRequestType
  category_id: number | undefined
  reason: string
  expected_return_date: string
}

const loading = ref(false)
const route = useRoute()
const focusId = (() => {
  const raw = route.query.focus
  const value = typeof raw === 'string' ? Number(raw) : Number.NaN
  return Number.isInteger(value) && value > 0 ? value : null
})()
const requests = ref<AssetRequestItem[]>([])
const total = ref(0)
const summary = ref<AssetRequestSummary | null>(null)

const query = reactive({
  page: 1,
  page_size: 10,
  keyword: '',
  request_type: undefined as AssetRequestType | undefined,
  status: undefined as AssetRequestStatus | undefined,
})

const filterMemory = useFilterMemory('assets-requisitions', query, {
  defaults: {
    page: 1,
    page_size: 10,
    keyword: '',
    request_type: undefined,
    status: undefined,
  },
})
filterMemory.restore()

const typeOptions = Object.entries(REQUEST_TYPE_LABELS).filter(
  ([value]) => value !== 'RETURN',
) as Array<[AssetRequestType, string]>
const statusOptions = Object.entries(REQUEST_STATUS_LABELS) as Array<
  [AssetRequestStatus, string]
>

const detailVisible = ref(false)
const detailRequest = ref<AssetRequestItem | null>(null)

const createVisible = ref(false)
const createSubmitting = ref(false)
const createFormRef = ref<FormInstance>()
const createForm = reactive<CreateForm>({
  request_type: 'REQUISITION',
  category_id: undefined,
  reason: '',
  expected_return_date: '',
})

const categoryOptions = ref<AvailableCategory[]>([])
const categoryLoading = ref(false)
const categoryPath = ref<AvailableCategory[]>([])
const selectedCategory = ref<AvailableCategory | null>(null)
const categoryRequestSeq = ref(0)

const isLeafSelected = computed(
  () => selectedCategory.value !== null && !selectedCategory.value.has_children,
)
const selectedLeafHasStock = computed(
  () => isLeafSelected.value && (selectedCategory.value?.available_count ?? 0) > 0,
)
const selectedCategoryPath = computed(() =>
  categoryPath.value.map((node) => node.name).join(' > '),
)

function categoryStockLabel(count: number): string {
  return count > 0 ? `可出库 ${count} 台` : '暂无可出库资产'
}

const scanVisible = ref(false)

const createRules: FormRules<CreateForm> = {
  request_type: [{ required: true, message: '请选择申请类型', trigger: 'change' }],
  category_id: [{ required: true, message: '请逐级选择到最终一级分类', trigger: 'change' }],
  expected_return_date: [
    {
      validator: (_rule, value, callback) => {
        if (createForm.request_type === 'BORROW' && !value) {
          callback(new Error('借用必须填写预计归还日期'))
          return
        }
        callback()
      },
      trigger: 'change',
    },
  ],
}

const summaryCards = computed(() => [
  { key: 'pending_approval', label: '待审批', value: summary.value?.pending_approval ?? 0 },
  { key: 'pending_outbound', label: '待出库', value: summary.value?.pending_outbound ?? 0 },
  { key: 'pending_return', label: '待归还确认', value: summary.value?.pending_return ?? 0 },
  { key: 'borrowed', label: '借用中', value: summary.value?.borrowed ?? 0 },
])

function disabledDate(value: Date): boolean {
  return dayjs(value).isBefore(dayjs().startOf('day'))
}

function categoryScopeLabel(row: AssetRequestItem): string {
  if (row.request_type === 'RETURN') return '资产分类'
  return row.include_child ? '含下级分类（历史）' : '最终分类'
}

function approvalProgress(row: AssetRequestItem): string {
  if (row.request_type === 'RETURN') return '—'
  if (row.status === 'REJECTED') return '审批未通过'
  if (row.status === 'CANCELLED') return '已撤销'
  if (row.flow_id) {
    const totalSteps = row.total_steps || row.approval_steps.length
    if (row.status === 'PENDING_APPROVAL') {
      const finished = row.approval_steps.filter(
        (step) => step.status === 'APPROVED' || step.status === 'SKIPPED',
      ).length
      return `${row.current_step_name || '审批处理中'}（${finished}/${totalSteps}）`
    }
    return `审批已完成（${totalSteps} 级）`
  }
  const approved = (row.approvals ?? []).filter((item) => item.action === 'APPROVE')
  const totalSteps = row.dept_approval_required ? 2 : 1
  if (row.status === 'PENDING_APPROVAL') {
    return `${row.approval_stage_label || '审批处理中'}（${approved.length}/${totalSteps}）`
  }
  if (approved.length === 0) return '审批已完成'
  return `审批已完成（${approved.length} 级）`
}

async function fetchRequests(): Promise<void> {
  loading.value = true
  try {
    const page = await assetFlowApi.myRequests({
      page: query.page,
      page_size: query.page_size,
      keyword: query.keyword || undefined,
      request_type: query.request_type,
      status: query.status,
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

function handleSearch(): void {
  query.page = 1
  void fetchRequests()
}

function resetFilters(): void {
  filterMemory.clear()
  query.keyword = ''
  query.request_type = undefined
  query.status = undefined
  query.page = 1
  void fetchRequests()
}

async function refreshAll(): Promise<void> {
  await Promise.all([fetchRequests(), fetchSummary()])
}

async function loadCategoryOptions(parentId?: number): Promise<void> {
  const seq = ++categoryRequestSeq.value
  categoryLoading.value = true
  try {
    const items = await assetFlowApi.categoryOptions(parentId)
    if (seq === categoryRequestSeq.value) {
      categoryOptions.value = items
    }
  } finally {
    if (seq === categoryRequestSeq.value) {
      categoryLoading.value = false
    }
  }
}

function currentBasePath(): AvailableCategory[] {
  const last = categoryPath.value[categoryPath.value.length - 1]
  if (last && !last.has_children) return categoryPath.value.slice(0, -1)
  return categoryPath.value.slice()
}

async function handleCategoryClick(option: AvailableCategory): Promise<void> {
  if (categoryLoading.value) return
  const basePath = currentBasePath()
  if (option.has_children) {
    categoryPath.value = [...basePath, option]
    selectedCategory.value = null
    createForm.category_id = undefined
    await loadCategoryOptions(option.id)
    return
  }
  categoryPath.value = [...basePath, option]
  selectedCategory.value = option
  createForm.category_id = option.id
  createFormRef.value?.clearValidate('category_id')
}

async function handleCategoryCrumb(index: number): Promise<void> {
  if (categoryLoading.value) return
  const node = categoryPath.value[index]
  if (!node || !node.has_children) return
  categoryPath.value = categoryPath.value.slice(0, index + 1)
  selectedCategory.value = null
  createForm.category_id = undefined
  await loadCategoryOptions(node.id)
}

async function resetCategorySelection(): Promise<void> {
  categoryRequestSeq.value += 1
  categoryPath.value = []
  selectedCategory.value = null
  createForm.category_id = undefined
  categoryOptions.value = []
  createFormRef.value?.clearValidate('category_id')
  await loadCategoryOptions()
}

async function openCreate(): Promise<void> {
  createForm.request_type = 'REQUISITION'
  createForm.category_id = undefined
  createForm.reason = ''
  createForm.expected_return_date = ''
  categoryPath.value = []
  selectedCategory.value = null
  categoryOptions.value = []
  createVisible.value = true
  await loadCategoryOptions()
}

async function submitCreate(): Promise<void> {
  const form = createFormRef.value
  if (!form) return
  if (!selectedCategory.value || selectedCategory.value.has_children) {
    ElMessage.warning('请逐级选择到最终一级分类后再提交')
    return
  }
  if (!selectedLeafHasStock.value) {
    ElMessage.warning('该分类当前暂无可出库资产，请选择其他分类')
    return
  }
  const valid = await form.validate().catch(() => false)
  if (!valid) return

  createSubmitting.value = true
  try {
    const created = await assetFlowApi.createRequest({
      request_type: createForm.request_type as 'REQUISITION' | 'BORROW',
      category_id: selectedCategory.value.id,
      reason: createForm.reason || null,
      expected_return_date:
        createForm.request_type === 'BORROW'
          ? createForm.expected_return_date
          : null,
    })
    ElMessage.success(`申请 ${created.request_no} 已提交，等待审批`)
    createVisible.value = false
    await refreshAll()
  } finally {
    createSubmitting.value = false
  }
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

async function cancelRequest(row: AssetRequestItem): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `确定撤销单据「${row.request_no}」吗？撤销后需重新发起申请。`,
      '撤销申请',
      { type: 'warning', confirmButtonText: '撤销', cancelButtonText: '保留' },
    )
  } catch {
    return
  }
  const updated = await assetFlowApi.cancel(row.id)
  ElMessage.success('申请已撤销')
  if (detailRequest.value?.id === row.id) detailRequest.value = updated
  await refreshAll()
}

function handleScanSelect(asset: AvailableAsset, result: { requests: AssetRequestItem[] }): void {
  if (result.requests.length) {
    void openDetail(result.requests[0])
    return
  }
  ElMessage.info(`资产 ${asset.asset_no} 当前没有进行中的业务单据`)
}

onMounted(async () => {
  await refreshAll()
  await openFocused()
})
</script>

<template>
  <div class="page requisition-page">
    <header class="page-header">
      <div>
        <p class="page-eyebrow">ASSET REQUISITION</p>
        <h1 class="page-title">我的申请</h1>
        <p class="page-subtitle">
          按资产分类发起领用或借用申请；系统按申请人所属部门自动匹配审批流程，审批通过后由资产管理员分配具体资产并确认出库。
        </p>
      </div>
      <div class="page-actions">
        <el-button :icon="Camera" @click="scanVisible = true">扫码查询</el-button>
        <el-button :icon="Refresh" :loading="loading" @click="refreshAll">刷新</el-button>
        <el-button type="primary" :icon="Plus" @click="openCreate">发起申请</el-button>
      </div>
    </header>

    <section class="summary-strip">
      <div v-for="card in summaryCards" :key="card.key" class="summary-card surface-card">
        <span>{{ card.label }}</span>
        <strong>{{ card.value }}</strong>
      </div>
      <div class="summary-note">
        <span>我的处理中</span>
        <strong>{{ summary?.mine_pending ?? 0 }}</strong>
        <small>提交后可在“审批进度”查看当前审批节点</small>
      </div>
    </section>

    <section class="surface-card panel">
      <div class="filter-bar">
        <el-input
          v-model="query.keyword"
          :prefix-icon="Search"
          placeholder="单据号 / 资产编号 / 申请人"
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
        <div class="filter-actions">
          <el-button :icon="Search" @click="handleSearch">查询</el-button>
          <el-button text @click="resetFilters">重置</el-button>
        </div>
      </div>

      <el-table
        v-loading="loading"
        :data="requests"
        row-key="id"
        empty-text="暂无业务申请，点击右上角发起领用"
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
        <el-table-column label="申请分类" min-width="160">
          <template #default="{ row }">
            <div class="stack-cell">
              <span>{{ row.category_name }}</span>
              <small>{{ categoryScopeLabel(row) }}</small>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="分配资产" min-width="190">
          <template #default="{ row }">
            <div v-if="row.asset_no" class="stack-cell">
              <span>{{ row.asset_name }}</span>
              <small class="mono">{{ row.asset_no }}</small>
            </div>
            <div v-else class="stack-cell">
              <span class="pending-text">待出库分配</span>
              <small>审批通过后由资产管理员选择</small>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="审批进度" min-width="180">
          <template #default="{ row }">
            <div class="stack-cell">
              <span>{{ approvalProgress(row) }}</span>
              <small v-if="row.dingtalk_instance_id" class="dingtalk-line">
                <el-tag size="small" :type="dingtalkMeta(row.dingtalk_status).type" effect="plain">
                  {{ dingtalkMeta(row.dingtalk_status).label }}
                </el-tag>
              </small>
              <small
                v-else-if="
                  row.status === 'PENDING_APPROVAL' &&
                  row.flow_id &&
                  row.current_approvers.length
                "
              >
                待处理：{{ row.current_approvers.join('、') }}
              </small>
              <small v-else-if="row.flow_id">{{ row.flow_name }}</small>
              <small v-else-if="row.approver_name">
                最近处理：{{ row.approver_name }}
              </small>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="130">
          <template #default="{ row }">
            <el-tag :type="REQUEST_STATUS_TAG_TYPES[row.status as AssetRequestStatus]" effect="light">
              {{ row.status_label }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="预计归还" width="130">
          <template #default="{ row }">
            <span v-if="row.expected_return_date" :class="{ overdue: row.is_overdue }">
              {{ row.expected_return_date }}
              <em v-if="row.is_overdue">逾期</em>
            </span>
            <span v-else>—</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="140" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openDetail(row)">详情</el-button>
            <el-button
              v-if="row.can_cancel"
              link
              type="danger"
              @click="cancelRequest(row)"
            >
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
          @current-change="fetchRequests"
          @size-change="handleSearch"
        />
      </div>
    </section>

    <el-dialog
      v-model="createVisible"
      title="发起领用 / 借用申请"
      width="620px"
      destroy-on-close
      @closed="createFormRef?.resetFields()"
    >
      <el-form
        ref="createFormRef"
        :model="createForm"
        :rules="createRules"
        label-width="100px"
        label-position="top"
      >
        <el-form-item label="申请类型" prop="request_type">
          <el-radio-group v-model="createForm.request_type">
            <el-radio-button value="REQUISITION">资产领用（长期使用）</el-radio-button>
            <el-radio-button value="BORROW">资产借用（到期归还）</el-radio-button>
          </el-radio-group>
        </el-form-item>

        <el-form-item label="资产分类" prop="category_id">
          <div class="category-picker">
            <div class="category-breadcrumb">
              <el-button
                link
                :type="categoryPath.length ? 'primary' : 'default'"
                @click="resetCategorySelection"
              >
                全部分类
              </el-button>
              <template v-for="(node, index) in categoryPath" :key="node.id">
                <el-icon class="crumb-separator"><ArrowRight /></el-icon>
                <el-button
                  link
                  :type="node.has_children ? 'primary' : 'default'"
                  :class="{ 'is-current': !node.has_children }"
                  :disabled="!node.has_children"
                  @click="handleCategoryCrumb(index)"
                >
                  {{ node.name }}
                </el-button>
              </template>
            </div>

            <div v-loading="categoryLoading" class="category-options">
              <button
                v-for="option in categoryOptions"
                :key="option.id"
                type="button"
                class="category-option"
                :class="{
                  'is-branch': option.has_children,
                  'is-selected': selectedCategory?.id === option.id,
                }"
                :disabled="categoryLoading"
                @click="handleCategoryClick(option)"
              >
                <span class="category-option-text">
                  <strong>{{ option.name }}</strong>
                  <small>
                    {{
                      option.has_children
                        ? '继续选择下级分类'
                        : '选择为该申请的最终分类'
                    }}
                    · {{ categoryStockLabel(option.available_count) }}
                  </small>
                </span>
                <el-icon class="category-option-icon">
                  <ArrowRight v-if="option.has_children" />
                  <Check v-else-if="selectedCategory?.id === option.id" />
                </el-icon>
              </button>
              <p
                v-if="!categoryLoading && categoryOptions.length === 0"
                class="category-empty"
              >
                当前层级暂无分类，请返回上一层查看其他分类。
              </p>
            </div>

            <div
              v-if="isLeafSelected"
              class="category-selected"
              :class="{ 'is-empty': !selectedLeafHasStock }"
            >
              <el-tag
                :type="selectedLeafHasStock ? 'success' : 'warning'"
                effect="light"
                size="small"
              >
                最终分类
              </el-tag>
              <span class="category-selected-path">{{ selectedCategoryPath }}</span>
              <span class="category-selected-count">
                {{ categoryStockLabel(selectedCategory?.available_count ?? 0) }}
              </span>
              <el-button link type="primary" @click="resetCategorySelection">
                重新选择
              </el-button>
            </div>
            <p v-else class="category-hint">
              请从顶级分类开始逐级选择；只有选中没有子分类的最终一级后，才能填写申请信息并提交。
            </p>
            <p
              v-if="isLeafSelected && !selectedLeafHasStock"
              class="category-stock-warning"
            >
              该分类当前暂无可出库资产，暂不能提交；请选择其他分类或等待入库后再申请。
            </p>
          </div>
        </el-form-item>

        <template v-if="isLeafSelected">
          <el-form-item
            v-if="createForm.request_type === 'BORROW'"
            label="预计归还日期"
            prop="expected_return_date"
          >
            <el-date-picker
              v-model="createForm.expected_return_date"
              type="date"
              value-format="YYYY-MM-DD"
              placeholder="借用到期前 3 天系统会提醒归还"
              :disabled-date="disabledDate"
              class="full-width"
            />
          </el-form-item>

          <el-form-item label="申请原因" prop="reason">
            <el-input
              v-model="createForm.reason"
              type="textarea"
              :rows="3"
              maxlength="500"
              show-word-limit
              placeholder="简要说明用途，便于审批人判断"
            />
          </el-form-item>
        </template>
        <div v-else class="category-locked-tip">
          选定最终一级分类后，即可填写申请原因{{
            createForm.request_type === 'BORROW' ? '与预计归还日期' : ''
          }}。
        </div>

        <el-alert
          type="info"
          :closable="false"
          show-icon
          title="逐级选择最终分类，申请阶段无需选择具体资产"
          description="提交后系统按申请人所属部门匹配审批流程并逐级流转，审批通过后进入待出库；由资产管理员在该最终分类下分配具体资产编号并确认出库。"
        />
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button
          type="primary"
          :loading="createSubmitting"
          :disabled="!selectedLeafHasStock"
          @click="submitCreate"
        >
          提交申请
        </el-button>
      </template>
    </el-dialog>

    <RequestDetailDrawer v-model="detailVisible" :request="detailRequest">
      <template #actions="{ request }">
        <el-button
          v-if="request.can_cancel"
          type="danger"
          plain
          @click="cancelRequest(request)"
        >
          撤销申请
        </el-button>
      </template>
    </RequestDetailDrawer>

    <ScanDialog v-model="scanVisible" @select="handleScanSelect" />
  </div>
</template>

<style scoped>
.page-actions {
  display: flex;
  gap: 10px;
}

.summary-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr)) 1.4fr;
  gap: 14px;
  margin-bottom: 18px;
}

.summary-card,
.summary-note {
  padding: 16px 18px;
}

.summary-card span,
.summary-note span {
  color: var(--text-3);
  font-size: 12px;
}

.summary-card strong,
.summary-note strong {
  display: block;
  margin-top: 6px;
  font-family: var(--font-number);
  font-size: 24px;
  color: var(--text-1);
}

.summary-note {
  border-radius: var(--radius-lg);
  border: 1px dashed var(--border-strong);
  background: var(--brand-soft);
}

.summary-note small {
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

.dingtalk-line {
  display: inline-flex;
  align-items: center;
}

.pending-text {
  color: var(--warning-strong, #b45309);
  font-weight: 600;
}

.mono {
  font-family: var(--font-number);
  font-weight: 600;
}

.overdue {
  color: var(--danger);
  font-weight: 600;
}

.overdue em {
  font-style: normal;
  font-size: 11px;
  margin-left: 4px;
}

.table-footer {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}

.category-picker {
  display: flex;
  flex-direction: column;
  gap: 10px;
  width: 100%;
}

.category-breadcrumb {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 2px;
  padding: 6px 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface-muted);
}

.category-breadcrumb :deep(.el-button.is-disabled) {
  color: var(--text-1);
  opacity: 1;
  cursor: default;
}

.category-breadcrumb :deep(.el-button.is-current) {
  font-weight: 600;
}

.crumb-separator {
  color: var(--text-3);
  font-size: 12px;
}

.category-options {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  min-height: 68px;
}

.category-option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface);
  color: var(--text-1);
  text-align: left;
  cursor: pointer;
  transition: border-color 0.18s ease, background-color 0.18s ease, transform 0.18s ease;
}

.category-option:hover:not(:disabled) {
  border-color: var(--brand);
  background: var(--brand-soft);
  transform: translateY(-1px);
}

.category-option.is-branch {
  border-style: dashed;
}

.category-option.is-selected {
  border-color: var(--brand);
  background: var(--brand-soft);
  box-shadow: inset 0 0 0 1px var(--brand);
}

.category-option:disabled {
  cursor: progress;
  opacity: 0.7;
}

.category-option-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.category-option-text strong {
  overflow: hidden;
  font-size: 13.5px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.category-option-text small {
  color: var(--text-3);
  font-size: 11.5px;
}

.category-option-icon {
  flex: none;
  color: var(--text-3);
  font-size: 14px;
}

.category-option.is-branch .category-option-icon {
  color: var(--brand);
}

.category-option.is-selected .category-option-icon {
  color: var(--success);
}

.category-empty {
  grid-column: 1 / -1;
  margin: 0;
  padding: 14px;
  border: 1px dashed var(--border-strong);
  border-radius: var(--radius-sm);
  color: var(--text-3);
  font-size: 12.5px;
  text-align: center;
}

.category-selected {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border: 1px solid var(--success);
  border-radius: var(--radius-sm);
  background: rgba(16, 185, 129, 0.08);
}

.category-selected-path {
  font-weight: 600;
}

.category-selected.is-empty {
  border-color: var(--warning);
  background: rgba(245, 158, 11, 0.08);
}

.category-selected-count {
  color: var(--text-2);
  font-size: 12px;
}

.category-stock-warning {
  margin: 0;
  color: var(--warning);
  font-size: 12px;
}

.category-locked-tip {
  padding: 12px 14px;
  border: 1px dashed var(--border-strong);
  border-radius: var(--radius-sm);
  color: var(--text-3);
  font-size: 12.5px;
  text-align: center;
}

.category-hint {
  margin: 0;
  color: var(--text-3);
  font-size: 12px;
}

.full-width {
  width: 100%;
}

@media (max-width: 640px) {
  .category-options {
    grid-template-columns: minmax(0, 1fr);
  }
}

@media (max-width: 1100px) {
  .summary-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
