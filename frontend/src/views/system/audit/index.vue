<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { Document, Refresh, Search, View } from '@element-plus/icons-vue'

import { auditApi } from '@/api/audit'
import { useColumnWidths } from '@/composables/useColumnWidths'
import { useFilterMemory } from '@/composables/useFilterMemory'
import { useAuthStore } from '@/stores/auth'
import { formatDateTime } from '@/utils/format'
import type {
  AuditFilterOptions,
  AuditLogDetail,
  AuditLogItem,
  AuditQuery,
} from '@/types/audit'

interface ChangedRow {
  field: string
  before: string
  after: string
  beforeRaw: string | null
  afterRaw: string | null
}

const FIELD_LABELS: Record<string, string> = {
  name: '名称',
  code: '编码',
  username: '用户名',
  real_name: '姓名',
  status: '状态',
  sort: '排序',
  remark: '备注',
  version: '版本号',
  parent_id: '上级 ID',
  category_type: '资产类型',
  path: '层级路径',
  level: '层级',
  dept_id: '所属部门',
  custodian_id: '责任人',
  user_id: '用户',
  user_ids: '人员',
  owner_id: '负责人',
  manager_id: '部门负责人',
  applicant_id: '申请人',
  created_by_id: '创建人',
  updated_by_id: '更新人',
  from_custodian_id: '原责任人',
  to_custodian_id: '目标责任人',
  from_dept_id: '原部门',
  to_dept_id: '目标部门',
  category_id: '资产分类',
  model_id: '型号',
  asset_id: '资产',
  asset_ids: '资产列表',
  asset_status: '资产状态',
  location: '存放位置',
  purchase_price: '采购价格',
  purchase_date: '购置日期',
  warranty_end: '保修到期',
  serial_no: '序列号',
  mac_address: 'MAC 地址',
  supplier: '供应商',
  required: '是否必填',
  field_key: '字段标识',
  field_type: '字段类型',
  options: '选项',
  menu_ids: '菜单权限',
  dept_ids: '数据部门',
  role_ids: '角色',
  data_scope: '数据范围',
  permissions: '权限配置',
  old_password: '旧密码',
}

const auth = useAuthStore()
const route = useRoute()
const loading = ref(false)
const logs = ref<AuditLogItem[]>([])
const total = ref(0)
const options = ref<AuditFilterOptions>({ modules: [], actions: [] })
const dateRange = ref<[string, string] | null>(null)

const query = reactive<AuditQuery>({
  page: 1,
  page_size: 20,
  keyword: '',
  module: undefined,
  action: undefined,
  status: undefined,
})

const filterMemory = useFilterMemory('system-audit', query, {
  defaults: {
    page: 1,
    page_size: 20,
    keyword: '',
    module: undefined,
    action: undefined,
    status: undefined,
  },
})
filterMemory.restore()

if (typeof route.query.action === 'string') {
  query.action = route.query.action
}
if (route.query.status === 'SUCCESS' || route.query.status === 'FAILED') {
  query.status = route.query.status
}

const columnWidths = useColumnWidths('system-audit')

const pageFailed = computed(() => logs.value.filter((item) => item.status === 'FAILED').length)

async function fetchLogs(): Promise<void> {
  loading.value = true
  try {
    const params: AuditQuery = { ...query }
    const keyword = params.keyword?.trim()
    if (keyword) {
      params.keyword = keyword
    } else {
      delete params.keyword
    }
    if (dateRange.value) {
      params.start_time = `${dateRange.value[0]}T00:00:00`
      params.end_time = `${dateRange.value[1]}T23:59:59`
    }
    const data = await auditApi.listLogs(params)
    logs.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}

async function fetchOptions(): Promise<void> {
  options.value = await auditApi.options()
}

function handleSearch(): void {
  query.page = 1
  void fetchLogs()
}

function resetFilters(): void {
  filterMemory.clear()
  query.keyword = ''
  query.module = undefined
  query.action = undefined
  query.status = undefined
  query.page = 1
  dateRange.value = null
  void fetchLogs()
}

function handlePageChange(page: number): void {
  query.page = page
  void fetchLogs()
}

function handleSizeChange(size: number): void {
  query.page_size = size
  query.page = 1
  void fetchLogs()
}

function resetColumnWidths(): void {
  columnWidths.reset()
}

function refreshAll(): void {
  void fetchOptions()
  void fetchLogs()
}

function statusLabel(status: string): string {
  return status === 'SUCCESS' ? '成功' : '失败'
}

const detailVisible = ref(false)
const detailLoading = ref(false)
const detailLog = ref<AuditLogDetail | null>(null)

async function openDetail(row: AuditLogItem): Promise<void> {
  detailVisible.value = true
  detailLoading.value = true
  detailLog.value = null
  try {
    detailLog.value = await auditApi.getLog(row.id)
  } finally {
    detailLoading.value = false
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function displayValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'string') return value
  return JSON.stringify(value)
}

function formatJson(value: unknown): string {
  if (value === null || value === undefined) return '—'
  return JSON.stringify(value, null, 2)
}

function formatSnapshot(value: unknown, labels?: Record<string, string> | null): string {
  const text = formatJson(value)
  if (!labels || value === null || value === undefined) return text
  return text
    .split('\n')
    .map((line) => {
      const match = /^  "([^"]+)":/.exec(line)
      const label = match ? labels[match[1]] : undefined
      const trimmed = line.trimEnd()
      if (!label || trimmed.endsWith('{') || trimmed.endsWith('[')) return line
      return `${line}  // ${label}`
    })
    .join('\n')
}

function fieldLabel(field: string): string {
  const label = FIELD_LABELS[field]
  return label ? `${label}（${field}）` : field
}

const changedRows = computed<ChangedRow[]>(() => {
  const log = detailLog.value
  const before = log && isRecord(log.before_data) ? log.before_data : {}
  const after = log && isRecord(log.after_data) ? log.after_data : {}
  const beforeLabels = log?.before_labels ?? {}
  const afterLabels = log?.after_labels ?? {}
  const keys = Array.from(new Set([...Object.keys(before), ...Object.keys(after)])).sort()
  return keys
    .filter((key) => JSON.stringify(before[key]) !== JSON.stringify(after[key]))
    .map((key) => {
      const beforeRaw = displayValue(before[key])
      const afterRaw = displayValue(after[key])
      const beforeLabel = beforeLabels[key]
      const afterLabel = afterLabels[key]
      return {
        field: fieldLabel(key),
        before: beforeLabel ?? beforeRaw,
        after: afterLabel ?? afterRaw,
        beforeRaw: beforeLabel ? beforeRaw : null,
        afterRaw: afterLabel ? afterRaw : null,
      }
    })
})

onMounted(() => {
  void fetchOptions()
  void fetchLogs()
})
</script>

<template>
  <div class="page audit-page">
    <header class="page-header">
      <div>
        <p class="page-eyebrow">AUDIT TRAIL</p>
        <h1 class="page-title">审计日志</h1>
        <p class="page-subtitle">
          记录登录、组织、权限与资产等关键操作；日志仅追加留存，不提供修改与物理删除。
        </p>
      </div>
      <div class="page-actions">
        <el-button :icon="Refresh" :loading="loading" @click="refreshAll">刷新日志</el-button>
      </div>
    </header>

    <section class="surface-card audit-panel">
      <div class="audit-head">
        <div>
          <p class="panel-eyebrow">OPERATIONS</p>
          <h2 class="panel-title">操作记录</h2>
          <p class="audit-hint">
            共 {{ total }} 条记录<span v-if="logs.length"> · 本页失败 {{ pageFailed }} 条</span>
          </p>
        </div>
        <div class="audit-scope">
          <span class="scope-chip">{{ auth.dataScopeLabel || '数据范围' }}</span>
          <span class="scope-note">日志内容按数据范围收敛</span>
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
          placeholder="操作人 / 摘要 / 动作 / 资源 ID"
          class="filter-keyword"
          clearable
          @keyup.enter="handleSearch"
          @clear="handleSearch"
        />
        <el-select
          v-model="query.module"
          placeholder="操作模块"
          class="filter-select"
          clearable
          filterable
          @change="handleSearch"
        >
          <el-option v-for="item in options.modules" :key="item" :label="item" :value="item" />
        </el-select>
        <el-select
          v-model="query.action"
          placeholder="动作编码"
          class="filter-select filter-action"
          clearable
          filterable
          @change="handleSearch"
        >
          <el-option v-for="item in options.actions" :key="item" :label="item" :value="item" />
        </el-select>
        <el-select
          v-model="query.status"
          placeholder="执行结果"
          class="filter-select filter-status"
          clearable
          @change="handleSearch"
        >
          <el-option label="成功" value="SUCCESS" />
          <el-option label="失败" value="FAILED" />
        </el-select>
        <el-date-picker
          v-model="dateRange"
          type="daterange"
          value-format="YYYY-MM-DD"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          class="filter-date"
          @change="handleSearch"
        />
        <div class="filter-actions">
          <el-button :icon="Search" @click="handleSearch">查询</el-button>
          <el-button text @click="resetFilters">重置</el-button>
        </div>
      </div>

      <el-table
        v-loading="loading"
        :data="logs"
        row-key="id"
        border
        class="audit-table"
        empty-text="暂无符合条件的审计记录"
        @header-dragend="columnWidths.onHeaderDragend"
      >
        <el-table-column
          label="操作时间"
          column-key="time"
          :width="columnWidths.widthOf('time') ?? 152"
        >
          <template #default="{ row }">
            <span class="time-cell">{{ formatDateTime(row.created_at) }}</span>
          </template>
        </el-table-column>

        <el-table-column
          label="模块"
          column-key="module"
          :width="columnWidths.widthOf('module') ?? 110"
        >
          <template #default="{ row }">
            <el-tag effect="plain" size="small" round>{{ row.module }}</el-tag>
          </template>
        </el-table-column>

        <el-table-column
          label="操作摘要"
          column-key="summary"
          :width="columnWidths.widthOf('summary')"
          min-width="260"
        >
          <template #default="{ row }">
            <div class="summary-cell">
              <span class="summary-text">{{ row.summary || '—' }}</span>
              <small class="action-code">{{ row.action }}</small>
            </div>
          </template>
        </el-table-column>

        <el-table-column
          label="操作人"
          column-key="user"
          :width="columnWidths.widthOf('user') ?? 140"
        >
          <template #default="{ row }">
            <div class="summary-cell">
              <span>{{ row.username || '匿名' }}</span>
              <small class="action-code">{{ row.ip || '—' }}</small>
            </div>
          </template>
        </el-table-column>

        <el-table-column
          label="资源"
          column-key="resource"
          :width="columnWidths.widthOf('resource') ?? 150"
        >
          <template #default="{ row }">
            <div class="summary-cell">
              <span>{{ row.resource_type || '—' }}</span>
              <small class="action-code">{{ row.resource_id || '—' }}</small>
            </div>
          </template>
        </el-table-column>

        <el-table-column
          label="结果"
          column-key="result"
          :width="columnWidths.widthOf('result') ?? 92"
        >
          <template #default="{ row }">
            <el-tag
              :type="row.status === 'SUCCESS' ? 'success' : 'danger'"
              effect="light"
              size="small"
              round
            >
              {{ statusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column label="操作" width="90" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" :icon="View" @click="openDetail(row)">详情</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="audit-pager">
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

    <el-drawer v-model="detailVisible" title="日志详情" size="620px" destroy-on-close>
      <div v-loading="detailLoading" class="audit-detail">
        <template v-if="detailLog">
          <div class="detail-hero">
            <div class="detail-hero-main">
              <span class="detail-module">{{ detailLog.module }}</span>
              <h3>{{ detailLog.summary || detailLog.action }}</h3>
              <p class="detail-action">{{ detailLog.action }}</p>
            </div>
            <el-tag
              :type="detailLog.status === 'SUCCESS' ? 'success' : 'danger'"
              effect="light"
              round
            >
              {{ statusLabel(detailLog.status) }}
            </el-tag>
          </div>

          <el-descriptions :column="2" border class="detail-meta">
            <el-descriptions-item label="操作时间">
              {{ formatDateTime(detailLog.created_at) }}
            </el-descriptions-item>
            <el-descriptions-item label="操作人">
              {{ detailLog.username || '匿名' }}
            </el-descriptions-item>
            <el-descriptions-item label="请求方式">
              {{ detailLog.method || '—' }}
            </el-descriptions-item>
            <el-descriptions-item label="来源 IP">
              {{ detailLog.ip || '—' }}
            </el-descriptions-item>
            <el-descriptions-item label="请求路径" :span="2">
              <span class="mono-value">{{ detailLog.path || '—' }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="资源对象">
              {{ detailLog.resource_type || '—' }}
              <span v-if="detailLog.resource_id" class="mono-value">
                #{{ detailLog.resource_id }}
              </span>
            </el-descriptions-item>
            <el-descriptions-item label="请求编号">
              <span class="mono-value">{{ detailLog.request_id || '—' }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="User-Agent" :span="2">
              <span class="mono-value">{{ detailLog.user_agent || '—' }}</span>
            </el-descriptions-item>
          </el-descriptions>

          <div class="detail-section">
            <h4><el-icon><Document /></el-icon>变更对比</h4>
            <el-table
              v-if="changedRows.length"
              :data="changedRows"
              size="small"
              border
              class="diff-table"
            >
              <el-table-column prop="field" label="字段" width="180" />
              <el-table-column label="变更前">
                <template #default="{ row }">
                  <div class="diff-cell">
                    <span class="diff-before">{{ row.before }}</span>
                    <small v-if="row.beforeRaw" class="diff-raw">{{ row.beforeRaw }}</small>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="变更后">
                <template #default="{ row }">
                  <div class="diff-cell">
                    <span class="diff-after">{{ row.after }}</span>
                    <small v-if="row.afterRaw" class="diff-raw">{{ row.afterRaw }}</small>
                  </div>
                </template>
              </el-table-column>
            </el-table>
            <p v-else class="detail-empty">该操作没有字段级变更数据。</p>
          </div>

          <div
            v-if="detailLog.before_data !== null || detailLog.after_data !== null"
            class="detail-section"
          >
            <h4>原始快照</h4>
            <p class="snapshot-hint">ID 字段已用注释标注名称，数值仍保持原始记录。</p>
            <el-collapse>
              <el-collapse-item title="变更前 (before)" name="before">
                <pre class="json-block">{{
                  formatSnapshot(detailLog.before_data, detailLog.before_labels)
                }}</pre>
              </el-collapse-item>
              <el-collapse-item title="变更后 (after)" name="after">
                <pre class="json-block">{{
                  formatSnapshot(detailLog.after_data, detailLog.after_labels)
                }}</pre>
              </el-collapse-item>
            </el-collapse>
          </div>
        </template>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.audit-panel {
  padding: 20px;
}

.audit-head {
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

.audit-hint {
  margin: 6px 0 0;
  font-size: 12.5px;
  color: var(--text-3);
}

.audit-scope {
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
  width: 240px;
}

.filter-select {
  width: 150px;
}

.filter-action {
  width: 200px;
}

.filter-date {
  width: 250px;
}

.filter-actions {
  display: flex;
  gap: 6px;
  margin-left: auto;
}

.time-cell {
  font-family: var(--font-number);
  font-size: 12.5px;
  color: var(--text-2);
}

:deep(.audit-table.el-table--border .el-table__cell) {
  border-right-color: color-mix(in srgb, var(--border) 55%, transparent);
}

.summary-cell {
  display: flex;
  flex-direction: column;
  min-width: 0;
  line-height: 1.4;
}

.summary-text {
  font-weight: 500;
  color: var(--text-1);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.action-code {
  font-family: var(--font-number);
  font-size: 11px;
  color: var(--text-3);
  letter-spacing: 0.01em;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.audit-pager {
  display: flex;
  justify-content: flex-end;
  padding-top: 16px;
}

.audit-detail {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.detail-hero {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 16px 18px;
  border-radius: var(--radius-md);
  background: var(--gradient-brand-soft);
}

.detail-hero-main h3 {
  margin: 6px 0 4px;
  font-size: 17px;
  color: var(--text-1);
  line-height: 1.4;
}

.detail-module {
  display: inline-block;
  padding: 2px 9px;
  border-radius: 999px;
  background: var(--brand-soft);
  color: var(--brand);
  font-size: 11px;
  font-weight: 600;
}

.detail-action {
  margin: 0;
  font-family: var(--font-number);
  font-size: 11.5px;
  color: var(--text-3);
}

.detail-meta {
  margin-top: 2px;
}

.mono-value {
  font-family: var(--font-number);
  font-size: 12px;
  word-break: break-all;
}

.detail-section h4 {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 0 0 10px;
  font-size: 13.5px;
  color: var(--text-1);
}

.snapshot-hint {
  margin: -4px 0 10px;
  font-size: 11.5px;
  color: var(--text-3);
}

.diff-table {
  width: 100%;
}

.diff-before {
  color: var(--text-3);
  text-decoration: line-through;
  text-decoration-color: color-mix(in srgb, var(--text-3) 60%, transparent);
}

.diff-after {
  color: var(--text-1);
  font-weight: 600;
}

.diff-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.diff-raw {
  font-family: var(--font-number);
  font-size: 11px;
  color: var(--text-3);
  text-decoration: none;
}

.detail-empty {
  margin: 0;
  padding: 14px;
  border: 1px dashed var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-3);
  font-size: 12.5px;
}

.json-block {
  margin: 0;
  max-height: 280px;
  overflow: auto;
  padding: 12px;
  border-radius: var(--radius-sm);
  background: var(--surface-muted);
  color: var(--text-2);
  font-family: var(--font-number);
  font-size: 11.5px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
}

@media (max-width: 1180px) {
  .filter-keyword,
  .filter-action {
    width: 100%;
  }

  .filter-select,
  .filter-date {
    width: calc(50% - 5px);
  }

  .filter-actions {
    margin-left: 0;
  }
}

@media (max-width: 820px) {
  .audit-head {
    flex-direction: column;
  }

  .audit-scope {
    align-items: flex-start;
  }

  .filter-select,
  .filter-date {
    width: 100%;
  }

  .audit-pager {
    justify-content: center;
  }
}
</style>
