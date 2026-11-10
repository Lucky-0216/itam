<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Promotion, Refresh, Search } from '@element-plus/icons-vue'

import { assetFlowApi } from '@/api/assetFlow'
import type {
  AvailableAsset,
  DirectOutboundCategory,
  DirectOutboundUser,
} from '@/types/assetFlow'

const loading = ref(false)
const assets = ref<AvailableAsset[]>([])
const total = ref(0)
const categories = ref<DirectOutboundCategory[]>([])
const tableRef = ref()
const selection = ref<AvailableAsset[]>([])

const query = reactive({
  page: 1,
  page_size: 10,
  keyword: '',
  category_id: undefined as number | undefined,
  include_child: true,
})

const dialogVisible = ref(false)
const submitting = ref(false)
const users = ref<DirectOutboundUser[]>([])
const userLoading = ref(false)

const form = reactive({
  user_id: undefined as number | undefined,
  request_type: 'REQUISITION' as 'REQUISITION' | 'BORROW',
  reason: '',
  location: '',
  expected_return_date: '' as string | null,
  comment: '',
})

const selectedCount = computed(() => selection.value.length)

function disablePastDate(value: Date): boolean {
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  return value.getTime() < today.getTime()
}

function userLabel(user: DirectOutboundUser): string {
  const base = `${user.real_name}（${user.username}）`
  return user.dept_name ? `${base} · ${user.dept_name}` : base
}

async function loadCategories(): Promise<void> {
  categories.value = await assetFlowApi.directOutboundCategories()
}

async function loadAssets(): Promise<void> {
  loading.value = true
  try {
    const page = await assetFlowApi.directOutboundAssets({
      keyword: query.keyword.trim() || undefined,
      category_id: query.category_id,
      include_child: query.include_child,
      page: query.page,
      page_size: query.page_size,
    })
    assets.value = page.items
    total.value = page.total
  } finally {
    loading.value = false
  }
}

function handleSelectionChange(rows: AvailableAsset[]): void {
  selection.value = rows
}

function handleSearch(): void {
  query.page = 1
  void loadAssets()
}

function resetFilters(): void {
  query.keyword = ''
  query.category_id = undefined
  query.include_child = true
  query.page = 1
  void loadAssets()
}

async function refresh(): Promise<void> {
  await loadAssets()
}

async function searchUsers(keyword: string): Promise<void> {
  userLoading.value = true
  try {
    users.value = await assetFlowApi.directOutboundUsers(keyword.trim() || undefined)
  } finally {
    userLoading.value = false
  }
}

function openDialog(): void {
  if (!selection.value.length) {
    ElMessage.warning('请先勾选要出库的资产')
    return
  }
  form.user_id = undefined
  form.request_type = 'REQUISITION'
  form.reason = ''
  form.location = ''
  form.expected_return_date = ''
  form.comment = ''
  dialogVisible.value = true
  if (!users.value.length) {
    void searchUsers('')
  }
}

function resetSelection(): void {
  tableRef.value?.clearSelection()
  selection.value = []
}

async function submit(): Promise<void> {
  if (!form.user_id) {
    ElMessage.warning('请选择目标领用人')
    return
  }
  if (!form.reason.trim()) {
    ElMessage.warning('请填写出库原因')
    return
  }
  if (form.request_type === 'BORROW' && !form.expected_return_date) {
    ElMessage.warning('借用出库请填写预计归还日期')
    return
  }
  submitting.value = true
  try {
    const result = await assetFlowApi.directOutbound({
      user_id: form.user_id,
      request_type: form.request_type,
      reason: form.reason.trim(),
      location: form.location.trim() || null,
      expected_return_date:
        form.request_type === 'BORROW' ? form.expected_return_date : null,
      comment: form.comment.trim() || null,
      items: selection.value.map((item) => ({
        asset_id: item.id,
        version: item.version,
      })),
    })
    ElMessage.success(`已直接出库 ${result.count} 台资产给 ${result.user_name}`)
    dialogVisible.value = false
    resetSelection()
    await loadAssets()
  } catch {
    // 接口已给出具体原因；刷新列表以获取最新状态和版本号后重新选择
    dialogVisible.value = false
    resetSelection()
    await loadAssets()
  } finally {
    submitting.value = false
  }
}

onMounted(async () => {
  await Promise.all([loadCategories(), loadAssets(), searchUsers('')])
})
</script>

<template>
  <div class="page direct-outbound-page">
    <header class="page-header">
      <div>
        <p class="page-eyebrow">DIRECT OUTBOUND</p>
        <h1 class="page-title">资产出库</h1>
        <p class="page-subtitle">
          将在库资产直接分配给指定人员，无需员工先提交申请。出库后资产状态、责任人、位置、状态历史与审计日志在同一事务内同步更新。
        </p>
      </div>
      <div class="page-actions">
        <el-button :icon="Refresh" :loading="loading" @click="refresh">刷新</el-button>
      </div>
    </header>

    <section class="surface-card panel">
      <div class="filter-bar">
        <el-input
          v-model="query.keyword"
          :prefix-icon="Search"
          placeholder="资产编号 / 名称 / 序列号 / 分类 / 型号"
          clearable
          class="filter-keyword"
          @keyup.enter="handleSearch"
          @clear="handleSearch"
        />
        <el-select
          v-model="query.category_id"
          placeholder="资产分类"
          clearable
          filterable
          class="filter-select"
          @change="handleSearch"
        >
          <el-option
            v-for="item in categories"
            :key="item.id"
            :label="item.full_name"
            :value="item.id"
          />
        </el-select>
        <el-checkbox v-model="query.include_child" @change="handleSearch">
          包含子分类
        </el-checkbox>
        <div class="filter-actions">
          <el-button :icon="Search" @click="handleSearch">查询</el-button>
          <el-button text @click="resetFilters">重置</el-button>
        </div>
      </div>

      <div class="selection-bar">
        <span>
          已选择 <strong>{{ selectedCount }}</strong> 台资产
        </span>
        <small>仅显示在库且未被申请、调拨、报废或维修占用的资产</small>
        <el-button
          type="primary"
          :icon="Promotion"
          :disabled="!selectedCount"
          @click="openDialog"
        >
          直接出库
        </el-button>
      </div>

      <el-table
        ref="tableRef"
        v-loading="loading"
        :data="assets"
        row-key="id"
        empty-text="当前没有可出库的在库资产"
        @selection-change="handleSelectionChange"
      >
        <el-table-column type="selection" width="48" reserve-selection />
        <el-table-column label="资产编号" min-width="170">
          <template #default="{ row }">
            <span class="mono">{{ row.asset_no }}</span>
          </template>
        </el-table-column>
        <el-table-column label="资产名称" min-width="160" prop="name" />
        <el-table-column label="分类" min-width="130">
          <template #default="{ row }">{{ row.category_name || '—' }}</template>
        </el-table-column>
        <el-table-column label="型号" min-width="150">
          <template #default="{ row }">{{ row.model_name || '—' }}</template>
        </el-table-column>
        <el-table-column label="序列号" min-width="140">
          <template #default="{ row }">{{ row.serial_no || '—' }}</template>
        </el-table-column>
        <el-table-column label="当前位置" min-width="130">
          <template #default="{ row }">{{ row.location || '—' }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag type="success" effect="light">{{ row.status_label }}</el-tag>
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
          @current-change="loadAssets"
          @size-change="handleSearch"
        />
      </div>
    </section>

    <el-dialog
      v-model="dialogVisible"
      title="资产出库"
      width="720px"
      :close-on-click-modal="false"
    >
      <div class="dialog-summary">
        <span>出库资产 {{ selectedCount }} 台</span>
        <small>出库后将立即变更资产责任人与使用状态</small>
      </div>

      <el-form label-position="top">
        <el-form-item label="目标领用人" required>
          <el-select
            v-model="form.user_id"
            filterable
            remote
            clearable
            :remote-method="searchUsers"
            :loading="userLoading"
            placeholder="输入姓名、账号、工号或手机号搜索"
            class="full-width"
          >
            <el-option
              v-for="user in users"
              :key="user.id"
              :label="userLabel(user)"
              :value="user.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="出库类型" required>
          <el-radio-group v-model="form.request_type">
            <el-radio-button value="REQUISITION">领用（长期使用）</el-radio-button>
            <el-radio-button value="BORROW">借用（需归还）</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="出库原因 / 备注" required>
          <el-input
            v-model="form.reason"
            type="textarea"
            :rows="3"
            maxlength="500"
            show-word-limit
            placeholder="例如：新员工入职配置、项目临时借用"
          />
        </el-form-item>
        <div class="form-grid">
          <el-form-item label="使用位置（选填）">
            <el-input
              v-model="form.location"
              maxlength="120"
              placeholder="不填则保持资产当前位置"
            />
          </el-form-item>
          <el-form-item
            v-if="form.request_type === 'BORROW'"
            label="预计归还日期"
            required
          >
            <el-date-picker
              v-model="form.expected_return_date"
              type="date"
              value-format="YYYY-MM-DD"
              placeholder="选择预计归还日期"
              :disabled-date="disablePastDate"
              class="full-width"
            />
          </el-form-item>
        </div>
        <el-form-item label="补充说明（选填）">
          <el-input
            v-model="form.comment"
            maxlength="500"
            placeholder="可填写交付方式、配件等补充信息"
          />
        </el-form-item>
      </el-form>

      <el-table :data="selection" size="small" max-height="220" class="selected-table">
        <el-table-column label="资产编号" min-width="160">
          <template #default="{ row }">
            <span class="mono">{{ row.asset_no }}</span>
          </template>
        </el-table-column>
        <el-table-column label="资产名称" min-width="160" prop="name" />
        <el-table-column label="当前位置" min-width="120">
          <template #default="{ row }">{{ row.location || '—' }}</template>
        </el-table-column>
      </el-table>

      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="该操作将在同一事务内更新资产状态、责任人、位置、状态历史与审计日志；若资产已被他人占用，将提示刷新后重试"
      />

      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submit">
          确认出库
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
  width: 220px;
}

.filter-actions {
  display: flex;
  gap: 8px;
  margin-left: auto;
}

.selection-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  margin-bottom: 14px;
  border-radius: 12px;
  border: 1px dashed var(--border-strong);
  background: var(--brand-soft);
}

.selection-bar span {
  color: var(--text-2);
  font-size: 13px;
}

.selection-bar strong {
  color: var(--brand);
  font-family: var(--font-number);
  font-size: 18px;
}

.selection-bar small {
  flex: 1;
  min-width: 200px;
  color: var(--text-3);
  font-size: 12px;
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

.dialog-summary {
  padding: 12px 16px;
  margin-bottom: 16px;
  border-radius: 12px;
  background: var(--surface-muted);
  border: 1px solid var(--border);
}

.dialog-summary span {
  display: block;
  font-weight: 650;
  color: var(--text-1);
}

.dialog-summary small {
  display: block;
  margin-top: 2px;
  color: var(--text-3);
  font-size: 12px;
}

.full-width {
  width: 100%;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 16px;
}

.selected-table {
  margin-bottom: 16px;
}

@media (max-width: 900px) {
  .filter-keyword,
  .filter-select {
    width: 100%;
  }

  .filter-actions {
    margin-left: 0;
  }

  .form-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
