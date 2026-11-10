<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox, ElTree } from 'element-plus'
import {
  Check,
  Close,
  OfficeBuilding,
  Refresh,
  Search,
  UserFilled,
} from '@element-plus/icons-vue'

import { orgApi } from '@/api/org'
import { useAuthStore } from '@/stores/auth'
import type { DeptMember, DeptNode, DeptSource } from '@/types/org'
import { initials } from '@/utils/format'

const auth = useAuthStore()
const canUpdate = computed(() => auth.hasPerm('system:dept-manager:update'))

const sources: Array<{ value: DeptSource; label: string; tag: string }> = [
  { value: 'ldap', label: '域控组织', tag: '域控' },
  { value: 'dingtalk', label: '钉钉组织', tag: '钉钉' },
  { value: 'local', label: '本地组织', tag: '本地' },
]

const activeSource = ref<DeptSource>('ldap')
const trees = reactive<Record<DeptSource, DeptNode[]>>({
  ldap: [],
  dingtalk: [],
  local: [],
})
const loadingSources = reactive<Record<DeptSource, boolean>>({
  ldap: false,
  dingtalk: false,
  local: false,
})
const treeRef = ref<InstanceType<typeof ElTree>>()
const treeKeyword = ref('')
const treeProps = { label: 'name', children: 'children' }
const selectedDeptId = ref<number | null>(null)

const members = ref<DeptMember[]>([])
const manager = ref<DeptMember | null>(null)
const memberLoading = ref(false)
const memberKeyword = ref('')
const page = ref(1)
const pageSize = ref(10)
const total = ref(0)
const saving = ref(false)
let memberSeq = 0

const tree = computed(() => trees[activeSource.value])
const treeLoading = computed(() => loadingSources[activeSource.value])
const sourceMeta = computed(
  () => sources.find((item) => item.value === activeSource.value) ?? sources[0],
)
const flatDepts = computed(() => flatten(tree.value))
const totalDeptCount = computed(() => flatDepts.value.length)
const withManagerCount = computed(
  () => flatDepts.value.filter((item) => item.manager_id !== null).length,
)
const missingManagerCount = computed(
  () => flatDepts.value.filter((item) => !item.manager_id && item.user_count > 0).length,
)
const selectedDept = computed(() => findDept(tree.value, selectedDeptId.value))
const sourceCounts = computed<Record<DeptSource, number>>(() => ({
  ldap: flatten(trees.ldap).length,
  dingtalk: flatten(trees.dingtalk).length,
  local: flatten(trees.local).length,
}))

function flatten(nodes: DeptNode[]): DeptNode[] {
  return nodes.flatMap((node) => [node, ...flatten(node.children ?? [])])
}

function findDept(nodes: DeptNode[], id: number | null): DeptNode | null {
  if (id === null) return null
  for (const node of nodes) {
    if (node.id === id) return node
    const found = findDept(node.children ?? [], id)
    if (found) return found
  }
  return null
}

function filterDeptNode(value: string, data: Record<string, unknown>): boolean {
  if (!value) return true
  const keyword = value.trim().toLowerCase()
  return [data.name, data.code, data.manager_name]
    .map((item) => String(item ?? '').toLowerCase())
    .some((item) => item.includes(keyword))
}

watch(treeKeyword, (value) => {
  treeRef.value?.filter(value)
})

watch(activeSource, () => {
  treeKeyword.value = ''
  memberKeyword.value = ''
  page.value = 1
  selectedDeptId.value = null
  void nextTick(() => {
    autoSelectDept()
    treeRef.value?.setCurrentKey(selectedDeptId.value)
  })
})

async function loadTrees(): Promise<void> {
  await Promise.all(
    sources.map(async (item) => {
      loadingSources[item.value] = true
      try {
        trees[item.value] = await orgApi.deptManagerTree(item.value)
      } catch {
        trees[item.value] = []
      } finally {
        loadingSources[item.value] = false
      }
    }),
  )
  if (!trees[activeSource.value].length) {
    const fallback = sources.find((item) => trees[item.value].length > 0)
    if (fallback && fallback.value !== activeSource.value) {
      activeSource.value = fallback.value
      return
    }
  }
  if (!findDept(tree.value, selectedDeptId.value)) {
    autoSelectDept()
  } else {
    await loadMembers()
  }
}

function autoSelectDept(): void {
  const first =
    flatDepts.value.find((item) => item.user_count > 0) ?? flatDepts.value[0] ?? null
  selectedDeptId.value = first?.id ?? null
  void nextTick(() => treeRef.value?.setCurrentKey(selectedDeptId.value))
  void loadMembers()
}

function handleDeptClick(data: DeptNode): void {
  if (selectedDeptId.value === data.id) return
  selectedDeptId.value = data.id
  memberKeyword.value = ''
  page.value = 1
  void loadMembers()
}

async function loadMembers(): Promise<void> {
  const deptId = selectedDeptId.value
  if (deptId === null) {
    members.value = []
    manager.value = null
    total.value = 0
    return
  }
  const seq = ++memberSeq
  memberLoading.value = true
  try {
    const result = await orgApi.deptManagerMembers(deptId, {
      source: activeSource.value,
      keyword: memberKeyword.value.trim() || undefined,
      page: page.value,
      page_size: pageSize.value,
    })
    if (seq !== memberSeq) return
    members.value = result.items
    manager.value = result.manager
    total.value = result.total
  } catch {
    if (seq === memberSeq) {
      members.value = []
      manager.value = null
      total.value = 0
    }
  } finally {
    if (seq === memberSeq) memberLoading.value = false
  }
}

function handleSearch(): void {
  page.value = 1
  void loadMembers()
}

function handlePageChange(value: number): void {
  page.value = value
  void loadMembers()
}

function handleSizeChange(value: number): void {
  pageSize.value = value
  page.value = 1
  void loadMembers()
}

async function refreshAll(): Promise<void> {
  await loadTrees()
  ElMessage.success('已刷新组织数据')
}

async function assignManager(row: DeptMember | null): Promise<void> {
  const dept = selectedDept.value
  if (!dept || saving.value) return
  const current = manager.value
  if (row && current && row.id === current.id) return

  let prompt: string
  if (row === null) {
    prompt = current
      ? `确认取消「${dept.name}」负责人（${current.real_name}）？`
      : `「${dept.name}」当前没有负责人`
    if (!current) return
  } else if (current) {
    prompt = `确认将「${dept.name}」负责人由 ${current.real_name} 更换为 ${row.real_name}？`
  } else {
    prompt = `确认指定 ${row.real_name} 为「${dept.name}」负责人？`
  }

  try {
    await ElMessageBox.confirm(prompt, row === null ? '取消负责人' : '指定负责人', {
      confirmButtonText: '确认',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return
  }

  saving.value = true
  try {
    const result = await orgApi.assignDeptManager(dept.id, {
      source: activeSource.value,
      manager_id: row?.id ?? null,
      version: dept.version,
    })
    ElMessage.success(
      result.manager_id
        ? `已指定 ${result.manager_name} 为「${result.dept_name}」负责人`
        : `已取消「${result.dept_name}」负责人`,
    )
    await loadTrees()
  } catch {
    // 冲突或校验失败时刷新最新版本，便于重试
    await loadTrees()
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  await loadTrees()
})
</script>

<template>
  <div class="page dept-manager-page">
    <header class="page-header">
      <div>
        <p class="page-eyebrow">DEPARTMENT MANAGERS</p>
        <h1 class="page-title">部门负责人</h1>
        <p class="page-subtitle">
          按组织来源分别维护部门负责人；指定结果直接用于审批流程的「部门负责人」节点。
        </p>
      </div>
      <div class="page-actions">
        <el-button :icon="Refresh" :loading="treeLoading || memberLoading" @click="refreshAll">
          刷新
        </el-button>
      </div>
    </header>

    <el-alert type="info" :closable="false" show-icon class="source-alert">
      <template #title>
        域控、钉钉与本地组织完全分开，不能跨来源选人。负责人以 ITAM 本地维护为准：同步任务仅在负责人为空时自动填充，不会覆盖此处指定结果，也不会回写钉钉或域控。
      </template>
    </el-alert>

    <el-tabs v-model="activeSource" class="source-tabs">
      <el-tab-pane
        v-for="item in sources"
        :key="item.value"
        :name="item.value"
        :label="`${item.label} (${sourceCounts[item.value]})`"
      />
    </el-tabs>

    <div class="manager-layout">
      <section class="surface-card dept-panel">
        <div class="panel-head">
          <div>
            <p class="panel-eyebrow">{{ sourceMeta.tag.toUpperCase() }} DEPARTMENTS</p>
            <h2 class="panel-title">{{ sourceMeta.label }}</h2>
          </div>
          <span class="source-chip">{{ sourceMeta.tag }}</span>
        </div>

        <div class="dept-search">
          <el-input
            v-model="treeKeyword"
            :prefix-icon="Search"
            placeholder="搜索部门名称 / 编码 / 负责人"
            clearable
          />
        </div>

        <div class="dept-stats">
          <span>部门 <strong>{{ totalDeptCount }}</strong></span>
          <span>已指定 <strong>{{ withManagerCount }}</strong></span>
          <span :class="{ warning: missingManagerCount > 0 }">
            待指定 <strong>{{ missingManagerCount }}</strong>
          </span>
        </div>

        <div v-loading="treeLoading" class="dept-tree-scroll">
          <el-tree
            ref="treeRef"
            :data="tree"
            node-key="id"
            :props="treeProps"
            :indent="14"
            highlight-current
            default-expand-all
            :expand-on-click-node="false"
            :filter-node-method="filterDeptNode"
            :empty-text="`当前来源暂无部门数据`"
            @node-click="handleDeptClick"
          >
            <template #default="{ data }">
              <div class="dept-node">
                <span class="dept-node-main">
                  <span class="dept-name" :title="data.name">{{ data.name }}</span>
                  <span class="dept-meta">
                    <span class="dept-code" :title="data.code">{{ data.code }}</span>
                    <el-tag
                      v-if="data.manager_name"
                      size="small"
                      type="success"
                      effect="plain"
                    >
                      {{ data.manager_name }}
                    </el-tag>
                    <el-tag
                      v-else-if="data.user_count > 0"
                      size="small"
                      type="warning"
                      effect="plain"
                    >
                      未指定
                    </el-tag>
                  </span>
                </span>
                <span class="dept-user-count" :title="`${data.user_count} 位直属成员`">
                  {{ data.user_count }}
                </span>
              </div>
            </template>
          </el-tree>
        </div>

        <div class="dept-foot">
          <span>共 {{ totalDeptCount }} 个部门</span>
          <span class="dept-foot-note">负责人按来源独立维护</span>
        </div>
      </section>

      <section class="surface-card member-panel">
        <div class="panel-head member-head">
          <div>
            <p class="panel-eyebrow">DEPARTMENT MEMBERS</p>
            <h2 class="panel-title">
              {{ selectedDept?.name || '部门成员' }}
              <el-tag
                v-if="selectedDept"
                size="small"
                effect="plain"
                class="dept-code-tag"
              >
                {{ selectedDept.code }}
              </el-tag>
            </h2>
          </div>
          <span v-if="selectedDept" class="member-count">
            {{ selectedDept.user_count }} 位直属成员
          </span>
        </div>

        <template v-if="selectedDept">
          <div class="manager-summary">
            <div class="manager-main">
              <span class="manager-label">当前负责人</span>
              <template v-if="manager">
                <span class="manager-avatar">{{ initials(manager.real_name) }}</span>
                <span class="manager-identity">
                  <strong>{{ manager.real_name }}</strong>
                  <small>
                    {{ manager.username }}
                    <template v-if="manager.employee_no"> · {{ manager.employee_no }}</template>
                  </small>
                </span>
              </template>
              <span v-else class="manager-empty">
                <el-icon><UserFilled /></el-icon>
                暂未指定负责人
              </span>
            </div>
            <el-button
              v-if="canUpdate && manager"
              plain
              type="danger"
              size="small"
              :icon="Close"
              :loading="saving"
              @click="assignManager(null)"
            >
              取消负责人
            </el-button>
          </div>

          <div class="member-filters">
            <el-input
              v-model="memberKeyword"
              :prefix-icon="Search"
              placeholder="搜索姓名 / 账号 / 工号"
              clearable
              class="member-keyword"
              @keyup.enter="handleSearch"
              @clear="handleSearch"
            />
            <el-button :icon="Search" @click="handleSearch">查询</el-button>
          </div>

          <el-table
            v-loading="memberLoading"
            :data="members"
            row-key="id"
            class="member-table"
            empty-text="该部门暂无直属成员，无法指定负责人"
          >
            <el-table-column label="成员" min-width="200">
              <template #default="{ row }">
                <div class="member-cell">
                  <span class="member-avatar">{{ initials(row.real_name) }}</span>
                  <span class="member-identity">
                    <span class="member-name">
                      {{ row.real_name }}
                      <el-tag v-if="row.is_manager" size="small" type="success" effect="light">
                        负责人
                      </el-tag>
                    </span>
                    <small class="member-account">{{ row.username }}</small>
                  </span>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="工号" min-width="110">
              <template #default="{ row }">
                <span class="mono">{{ row.employee_no || '—' }}</span>
              </template>
            </el-table-column>
            <el-table-column label="职位" min-width="120">
              <template #default="{ row }">{{ row.position || '—' }}</template>
            </el-table-column>
            <el-table-column label="状态" width="90">
              <template #default="{ row }">
                <el-tag :type="row.status === 1 ? 'success' : 'info'" effect="plain" size="small">
                  {{ row.status === 1 ? '启用' : '停用' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column v-if="canUpdate" label="操作" width="130" align="right">
              <template #default="{ row }">
                <el-button
                  v-if="row.is_manager"
                  text
                  type="danger"
                  size="small"
                  :icon="Close"
                  :loading="saving"
                  @click="assignManager(null)"
                >
                  取消负责人
                </el-button>
                <el-button
                  v-else
                  text
                  type="primary"
                  size="small"
                  :icon="Check"
                  :disabled="row.status !== 1"
                  :loading="saving"
                  @click="assignManager(row)"
                >
                  {{ manager ? '更换负责人' : '设为负责人' }}
                </el-button>
              </template>
            </el-table-column>
          </el-table>

          <div class="table-footer">
            <el-pagination
              :current-page="page"
              :page-size="pageSize"
              :total="total"
              :page-sizes="[10, 20, 50]"
              layout="total, sizes, prev, pager, next"
              background
              @current-change="handlePageChange"
              @size-change="handleSizeChange"
            />
          </div>
        </template>

        <el-empty
          v-else
          :image-size="90"
          description="请选择左侧部门查看成员并指定负责人"
        />
      </section>
    </div>
  </div>
</template>

<style scoped>
.source-alert {
  margin-bottom: 14px;
}

.source-tabs {
  margin-bottom: 4px;
}

.manager-layout {
  display: grid;
  grid-template-columns: minmax(300px, 360px) minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}

.dept-panel,
.member-panel {
  padding: 16px 18px;
  min-height: 420px;
}

.panel-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.panel-eyebrow {
  margin: 0 0 2px;
  color: var(--text-3);
  font-family: var(--font-number);
  font-size: 10px;
  letter-spacing: 0.12em;
}

.panel-title {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  color: var(--text-1);
  font-size: 16px;
  font-weight: 600;
}

.source-chip {
  padding: 2px 9px;
  border-radius: 999px;
  background: var(--brand-soft);
  color: var(--brand);
  font-size: 11px;
  font-weight: 500;
}

.dept-search {
  margin-bottom: 10px;
}

.dept-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  margin-bottom: 8px;
  color: var(--text-3);
  font-size: 11px;
}

.dept-stats strong {
  color: var(--text-1);
  font-family: var(--font-number);
  font-size: 12px;
}

.dept-stats .warning strong {
  color: var(--el-color-warning);
}

.dept-tree-scroll {
  min-height: 200px;
  max-height: 520px;
  overflow: auto;
  padding-right: 2px;
}

.dept-tree-scroll :deep(.el-tree) {
  background: transparent;
  --el-tree-node-hover-bg-color: var(--surface-muted);
}

.dept-tree-scroll :deep(.el-tree-node__content) {
  height: auto;
  min-height: 46px;
  padding: 4px 0;
  border-radius: 9px;
  margin-bottom: 2px;
}

.dept-tree-scroll :deep(.el-tree-node.is-current > .el-tree-node__content) {
  background: var(--brand-soft);
  color: var(--brand);
}

.dept-node {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  min-width: 0;
  padding-right: 4px;
}

.dept-node-main {
  display: flex;
  flex: 1;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  min-width: 0;
}

.dept-name {
  max-width: 100%;
  overflow: hidden;
  color: inherit;
  font-size: 13px;
  font-weight: 500;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dept-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  max-width: 100%;
  min-width: 0;
}

.dept-code {
  overflow: hidden;
  color: var(--text-3);
  font-family: var(--font-number);
  font-size: 9.5px;
  letter-spacing: 0.04em;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dept-user-count {
  min-width: 20px;
  padding: 0 5px;
  border-radius: 999px;
  background: var(--surface-muted);
  color: var(--text-3);
  font-family: var(--font-number);
  font-size: 10px;
  line-height: 18px;
  text-align: center;
  flex-shrink: 0;
}

.dept-foot {
  display: flex;
  justify-content: space-between;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed var(--border);
  color: var(--text-3);
  font-size: 11px;
}

.member-head {
  align-items: center;
}

.member-count {
  color: var(--text-3);
  font-family: var(--font-number);
  font-size: 11px;
}

.dept-code-tag {
  font-family: var(--font-number);
}

.manager-summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  margin-bottom: 12px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--surface-muted);
}

.manager-main {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.manager-label {
  color: var(--text-3);
  font-size: 11px;
}

.manager-avatar,
.member-avatar {
  display: grid;
  place-items: center;
  flex-shrink: 0;
  border-radius: 50%;
  background: var(--brand-soft);
  color: var(--brand);
  font-size: 11px;
  font-weight: 600;
}

.manager-avatar {
  width: 26px;
  height: 26px;
}

.manager-identity {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}

.manager-identity strong {
  color: var(--text-1);
  font-size: 13px;
}

.manager-identity small {
  color: var(--text-3);
  font-size: 10.5px;
}

.manager-empty {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: var(--text-3);
  font-size: 12px;
}

.member-filters {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}

.member-keyword {
  max-width: 320px;
}

.member-table {
  width: 100%;
}

.member-cell {
  display: flex;
  align-items: center;
  gap: 9px;
  min-width: 0;
}

.member-avatar {
  width: 30px;
  height: 30px;
}

.member-identity {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}

.member-name {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--text-1);
  font-size: 13px;
  font-weight: 500;
}

.member-account {
  color: var(--text-3);
  font-family: var(--font-number);
  font-size: 10.5px;
}

.mono {
  font-family: var(--font-number);
  font-size: 12px;
}

.table-footer {
  display: flex;
  justify-content: flex-end;
  margin-top: 10px;
}

@media (max-width: 1100px) {
  .manager-layout {
    grid-template-columns: 1fr;
  }

  .dept-tree-scroll {
    max-height: 320px;
  }
}
</style>
