<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import {
  ElMessage,
  ElMessageBox,
  ElTree,
  type FormInstance,
  type FormRules,
} from 'element-plus'
import {
  Delete,
  Edit,
  InfoFilled,
  MoreFilled,
  OfficeBuilding,
  Plus,
  Refresh,
  Search,
  Upload,
} from '@element-plus/icons-vue'

import { orgApi } from '@/api/org'
import { roleApi } from '@/api/roles'
import ImportDialog from '@/components/ImportDialog.vue'
import { useAuthStore } from '@/stores/auth'
import type {
  DeptNode,
  OrgUser,
  UserCreatePayload,
  UserUpdatePayload,
} from '@/types/org'
import type { RoleBriefOption } from '@/types/rbac'
import { formatDateTime, initials } from '@/utils/format'

const auth = useAuthStore()
const route = useRoute()

function parseDeptId(value: unknown): number | null {
  const id = Number(value)
  return Number.isInteger(id) && id > 0 ? id : null
}

const deptTreeRef = ref<InstanceType<typeof ElTree>>()
const deptTree = ref<DeptNode[]>([])
const deptLoading = ref(false)
const deptKeyword = ref('')
const selectedDeptId = ref<number | null>(parseDeptId(route.query.dept_id))
const deptTreeProps = { label: 'name', children: 'children' }

const users = ref<OrgUser[]>([])
const userLoading = ref(false)
const userTotal = ref(0)
const statusLoadingId = ref<number | null>(null)
const query = reactive({
  page: 1,
  page_size: 10,
  keyword: typeof route.query.keyword === 'string' ? route.query.keyword : '',
  status: undefined as number | undefined,
  include_child: true,
})
let userRequestSeq = 0

watch(
  () => route.query.keyword,
  (value) => {
    query.keyword = typeof value === 'string' ? value : ''
    query.page = 1
    void loadUsers()
  },
)

watch(
  () => route.query.dept_id,
  (value) => {
    selectedDeptId.value = parseDeptId(value)
    deptTreeRef.value?.setCurrentKey(selectedDeptId.value)
    query.page = 1
    void loadUsers()
  },
)

const roleOptions = ref<RoleBriefOption[]>([])

const canCreateUser = computed(() => auth.hasPerm('system:user:create'))
const canUpdateUser = computed(() => auth.hasPerm('system:user:update'))
const canDeleteUser = computed(() => auth.hasPerm('system:user:delete'))
const canResetPassword = computed(() => auth.hasPerm('system:user:reset-password'))
const canManageDept = computed(
  () =>
    auth.hasPerm('system:dept:create') ||
    auth.hasPerm('system:dept:update') ||
    auth.hasPerm('system:dept:delete'),
)

const selectedDeptName = computed(() => {
  if (selectedDeptId.value === null) return '全部部门'
  return findDeptName(deptTree.value, selectedDeptId.value) || '未知部门'
})

const totalDeptCount = computed(() => flattenDepts(deptTree.value).length)

function flattenDepts(nodes: DeptNode[]): DeptNode[] {
  return nodes.flatMap((node) => [node, ...flattenDepts(node.children ?? [])])
}

function findDeptName(nodes: DeptNode[], id: number): string | null {
  for (const node of nodes) {
    if (node.id === id) return node.name
    const found = findDeptName(node.children ?? [], id)
    if (found) return found
  }
  return null
}

function findDept(nodes: DeptNode[], id: number): DeptNode | null {
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
  const name = String(data.name ?? '').toLowerCase()
  const code = String(data.code ?? '').toLowerCase()
  return name.includes(keyword) || code.includes(keyword)
}

watch(deptKeyword, (value) => {
  deptTreeRef.value?.filter(value)
})

async function loadDeptTree(): Promise<void> {
  deptLoading.value = true
  try {
    deptTree.value = await orgApi.departmentTree()
    if (selectedDeptId.value !== null && !findDept(deptTree.value, selectedDeptId.value)) {
      selectedDeptId.value = null
      query.page = 1
      await loadUsers()
      return
    }
    await nextTick()
    if (selectedDeptId.value !== null) {
      deptTreeRef.value?.setCurrentKey(selectedDeptId.value)
    }
  } finally {
    deptLoading.value = false
  }
}

async function loadUsers(): Promise<void> {
  const seq = ++userRequestSeq
  userLoading.value = true
  try {
    const data = await orgApi.listUsers({
      page: query.page,
      page_size: query.page_size,
      keyword: query.keyword.trim() || undefined,
      dept_id: selectedDeptId.value ?? undefined,
      include_child: query.include_child,
      status: query.status,
    })
    if (seq !== userRequestSeq) return
    users.value = data.items
    userTotal.value = data.total
  } finally {
    if (seq === userRequestSeq) userLoading.value = false
  }
}

function handleSearch(): void {
  query.page = 1
  void loadUsers()
}

function resetFilters(): void {
  query.keyword = ''
  query.status = undefined
  query.include_child = true
  query.page = 1
  void loadUsers()
}

function handleSizeChange(): void {
  query.page = 1
  void loadUsers()
}

function selectAllDepts(): void {
  selectedDeptId.value = null
  deptTreeRef.value?.setCurrentKey(null)
  query.page = 1
  void loadUsers()
}

function handleDeptClick(data: DeptNode): void {
  selectedDeptId.value = data.id
  query.page = 1
  void loadUsers()
}

async function refreshAll(): Promise<void> {
  await Promise.all([loadDeptTree(), loadUsers()])
}

const importVisible = ref(false)

function handleImported(): void {
  void loadUsers()
}

const deptDialogVisible = ref(false)
const deptDialogMode = ref<'create' | 'edit'>('create')
const deptFormRef = ref<FormInstance>()
const deptSubmitting = ref(false)

interface DeptFormState {
  id: number | null
  parent_id: number | null
  name: string
  code: string
  leader: string
  manager_id: number | undefined
  phone: string
  sort: number
  status: number
  remark: string
  version: number
}

const deptForm = reactive<DeptFormState>({
  id: null,
  parent_id: null,
  name: '',
  code: '',
  leader: '',
  manager_id: undefined,
  phone: '',
  sort: 0,
  status: 1,
  remark: '',
  version: 1,
})

interface ManagerOption {
  id: number
  username: string
  real_name: string
  dept_name: string | null
}

const managerOptions = ref<ManagerOption[]>([])
const managerLoading = ref(false)
let managerRequestSeq = 0
let managerSearchTimer: ReturnType<typeof setTimeout> | null = null

function mergeManagerOption(option: ManagerOption): void {
  managerOptions.value = [
    option,
    ...managerOptions.value.filter((item) => item.id !== option.id),
  ]
}

async function loadManagerOptions(keyword?: string): Promise<void> {
  const seq = ++managerRequestSeq
  managerLoading.value = true
  try {
    const page = await orgApi.listUsers({
      page: 1,
      page_size: 50,
      keyword: keyword?.trim() || undefined,
      status: 1,
      include_child: true,
    })
    if (seq !== managerRequestSeq) return
    const incoming = page.items.map((user) => ({
      id: user.id,
      username: user.username,
      real_name: user.real_name,
      dept_name: user.dept_name,
    }))
    const selectedId = deptForm.manager_id
    const selected = managerOptions.value.find((item) => item.id === selectedId)
    managerOptions.value = selected
      ? [selected, ...incoming.filter((item) => item.id !== selected.id)]
      : incoming
  } finally {
    if (seq === managerRequestSeq) managerLoading.value = false
  }
}

function searchManagers(keyword: string): void {
  if (managerSearchTimer) clearTimeout(managerSearchTimer)
  managerSearchTimer = setTimeout(() => {
    void loadManagerOptions(keyword)
  }, 300)
}

function handleManagerChange(value: number | undefined): void {
  if (!value) return
  const option = managerOptions.value.find((item) => item.id === value)
  if (option) deptForm.leader = option.real_name
}

const deptRules: FormRules = {
  name: [
    { required: true, message: '请输入部门名称', trigger: 'blur' },
    { max: 100, message: '部门名称不能超过 100 个字符', trigger: 'blur' },
  ],
  code: [
    { required: true, message: '请输入部门编码', trigger: 'blur' },
    {
      pattern: /^[A-Z0-9][A-Z0-9_-]{1,49}$/,
      message: '需为 2-50 位大写字母、数字、下划线或短横线',
      trigger: 'blur',
    },
  ],
}

function resetDeptForm(): void {
  Object.assign(deptForm, {
    id: null,
    parent_id: null,
    name: '',
    code: '',
    leader: '',
    manager_id: undefined,
    phone: '',
    sort: 0,
    status: 1,
    remark: '',
    version: 1,
  })
}

function normalizeDeptCode(): void {
  deptForm.code = deptForm.code.toUpperCase()
}

function openCreateDept(parent: DeptNode | null): void {
  resetDeptForm()
  deptDialogMode.value = 'create'
  deptForm.parent_id = parent?.id ?? null
  deptDialogVisible.value = true
  void loadManagerOptions()
  void nextTick(() => deptFormRef.value?.clearValidate())
}

function openEditDept(node: DeptNode): void {
  deptDialogMode.value = 'edit'
  Object.assign(deptForm, {
    id: node.id,
    parent_id: node.parent_id,
    name: node.name,
    code: node.code,
    leader: node.leader ?? '',
    manager_id: node.manager_id ?? undefined,
    phone: node.phone ?? '',
    sort: node.sort,
    status: node.status,
    remark: node.remark ?? '',
    version: node.version,
  })
  if (node.manager_id && node.manager_name) {
    mergeManagerOption({
      id: node.manager_id,
      username: '',
      real_name: node.manager_name,
      dept_name: null,
    })
  }
  deptDialogVisible.value = true
  void loadManagerOptions()
  void nextTick(() => deptFormRef.value?.clearValidate())
}

const deptParentOptions = computed(() => {
  if (deptDialogMode.value !== 'edit' || deptForm.id === null) return deptTree.value
  return excludeDeptSubtree(deptTree.value, deptForm.id)
})

function excludeDeptSubtree(nodes: DeptNode[], excludeId: number): DeptNode[] {
  return nodes
    .filter((node) => node.id !== excludeId)
    .map((node) => ({ ...node, children: excludeDeptSubtree(node.children ?? [], excludeId) }))
}

async function submitDept(): Promise<void> {
  const valid = await deptFormRef.value?.validate().catch(() => false)
  if (!valid || deptSubmitting.value) return
  deptSubmitting.value = true
  try {
    const payload = {
      parent_id: deptForm.parent_id,
      name: deptForm.name.trim(),
      code: deptForm.code.trim(),
      leader: deptForm.leader.trim() || null,
      manager_id: deptForm.manager_id ?? null,
      phone: deptForm.phone.trim() || null,
      sort: deptForm.sort,
      status: deptForm.status,
      remark: deptForm.remark.trim() || null,
    }
    if (deptDialogMode.value === 'create') {
      await orgApi.createDepartment(payload)
      ElMessage.success('部门创建成功')
    } else if (deptForm.id !== null) {
      await orgApi.updateDepartment(deptForm.id, { ...payload, version: deptForm.version })
      ElMessage.success('部门更新成功')
    }
    deptDialogVisible.value = false
    await loadDeptTree()
  } finally {
    deptSubmitting.value = false
  }
}

function handleDeptCommand(command: string | number | object, data: DeptNode): void {
  const action = String(command)
  if (action === 'create') openCreateDept(data)
  if (action === 'edit') openEditDept(data)
  if (action === 'delete') void deleteDept(data)
}

async function deleteDept(node: DeptNode): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `确定删除部门「${node.name}」吗？存在下级部门、用户或角色引用时将无法删除。`,
      '删除部门',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  await orgApi.deleteDepartment(node.id)
  ElMessage.success('部门已删除')
  if (selectedDeptId.value === node.id) {
    selectedDeptId.value = null
    query.page = 1
  }
  await Promise.all([loadDeptTree(), loadUsers()])
}

const userDialogVisible = ref(false)
const userDialogMode = ref<'create' | 'edit'>('create')
const userFormRef = ref<FormInstance>()
const userSubmitting = ref(false)
const userDialogLoading = ref(false)

interface UserFormState {
  id: number
  username: string
  password: string
  real_name: string
  dept_id: number | undefined
  position: string
  employee_no: string
  email: string
  phone: string
  status: number
  role_ids: number[]
  remark: string
  version: number
  source: string
}

const userForm = reactive<UserFormState>({
  id: 0,
  username: '',
  password: '',
  real_name: '',
  dept_id: undefined,
  position: '',
  employee_no: '',
  email: '',
  phone: '',
  status: 1,
  role_ids: [],
  remark: '',
  version: 1,
  source: 'local',
})

function validatePassword(
  _rule: unknown,
  value: string,
  callback: (error?: string | Error) => void,
): void {
  if (userDialogMode.value !== 'create') {
    callback()
    return
  }
  if (!value) {
    callback(new Error('请输入初始密码'))
    return
  }
  if (!/^(?=.*[A-Za-z])(?=.*\d).{8,64}$/.test(value)) {
    callback(new Error('密码需为 8-64 位，且同时包含字母和数字'))
    return
  }
  callback()
}

const userRules: FormRules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    {
      pattern: /^[a-z0-9][a-z0-9._-]{2,49}$/,
      message: '需为 3-50 位小写字母、数字、点、下划线或短横线',
      trigger: 'blur',
    },
  ],
  password: [{ validator: validatePassword, trigger: 'blur' }],
  real_name: [
    { required: true, message: '请输入姓名', trigger: 'blur' },
    { max: 50, message: '姓名不能超过 50 个字符', trigger: 'blur' },
  ],
  dept_id: [{ required: true, message: '请选择所属部门', trigger: 'change' }],
  email: [{ type: 'email', message: '邮箱格式不正确', trigger: 'blur' }],
  role_ids: [
    { type: 'array', required: true, min: 1, message: '至少选择一个角色', trigger: 'change' },
  ],
}

function resetUserForm(): void {
  Object.assign(userForm, {
    id: 0,
    username: '',
    password: '',
    real_name: '',
    dept_id: undefined,
    position: '',
    employee_no: '',
    email: '',
    phone: '',
    status: 1,
    role_ids: [],
    remark: '',
    version: 1,
    source: 'local',
  })
}

function normalizeUsername(): void {
  userForm.username = userForm.username.toLowerCase()
}

async function ensureRoleOptions(): Promise<void> {
  if (roleOptions.value.length) return
  try {
    roleOptions.value = await roleApi.roleOptions()
  } catch {
    roleOptions.value = []
  }
}

function openCreateUser(): void {
  resetUserForm()
  userDialogMode.value = 'create'
  userForm.dept_id = selectedDeptId.value ?? undefined
  userDialogVisible.value = true
  void ensureRoleOptions()
  void nextTick(() => userFormRef.value?.clearValidate())
}

async function openEditUser(row: OrgUser): Promise<void> {
  userDialogLoading.value = true
  try {
    await ensureRoleOptions()
    const detail = await orgApi.getUser(row.id)
    userDialogMode.value = 'edit'
    Object.assign(userForm, {
      id: detail.id,
      username: detail.username,
      password: '',
      real_name: detail.real_name,
      dept_id: detail.dept_id ?? undefined,
      position: detail.position ?? '',
      employee_no: detail.employee_no ?? '',
      email: detail.email ?? '',
      phone: detail.phone ?? '',
      status: detail.status,
      role_ids: detail.roles.map((role) => role.id),
      remark: detail.remark ?? '',
      version: detail.version,
      source: detail.source ?? 'local',
    })
    userDialogVisible.value = true
    void nextTick(() => userFormRef.value?.clearValidate())
  } finally {
    userDialogLoading.value = false
  }
}

async function submitUser(): Promise<void> {
  const valid = await userFormRef.value?.validate().catch(() => false)
  if (!valid || userSubmitting.value) return
  if (!userForm.dept_id) return
  userSubmitting.value = true
  try {
    if (userDialogMode.value === 'create') {
      const payload: UserCreatePayload = {
        username: userForm.username.trim(),
        password: userForm.password,
        real_name: userForm.real_name.trim(),
        dept_id: userForm.dept_id,
        position: userForm.position.trim() || null,
        employee_no: userForm.employee_no.trim() || null,
        email: userForm.email.trim() || null,
        phone: userForm.phone.trim() || null,
        status: userForm.status,
        role_ids: userForm.role_ids,
        remark: userForm.remark.trim() || null,
      }
      await orgApi.createUser(payload)
      ElMessage.success('用户创建成功，首次登录需修改密码')
    } else {
      const payload: UserUpdatePayload = {
        real_name: userForm.real_name.trim(),
        dept_id: userForm.dept_id,
        position: userForm.position.trim() || null,
        employee_no: userForm.employee_no.trim() || null,
        email: userForm.email.trim() || null,
        phone: userForm.phone.trim() || null,
        role_ids: userForm.role_ids,
        remark: userForm.remark.trim() || null,
        version: userForm.version,
      }
      await orgApi.updateUser(userForm.id, payload)
      ElMessage.success('用户更新成功')
    }
    userDialogVisible.value = false
    await Promise.all([loadUsers(), loadDeptTree()])
  } finally {
    userSubmitting.value = false
  }
}

async function handleStatusChange(row: OrgUser, enabled: boolean): Promise<void> {
  if (statusLoadingId.value !== null) return
  statusLoadingId.value = row.id
  try {
    await orgApi.setUserStatus(row.id, {
      status: enabled ? 1 : 0,
      version: row.version,
    })
    ElMessage.success(enabled ? '用户已启用' : '用户已停用，登录会话已失效')
    await loadUsers()
  } catch {
    await loadUsers()
  } finally {
    statusLoadingId.value = null
  }
}

function handleSwitchChange(row: OrgUser, value: string | number | boolean): void {
  void handleStatusChange(row, Boolean(value))
}

const resetDialogVisible = ref(false)
const resetFormRef = ref<FormInstance>()
const resetSubmitting = ref(false)
const resetForm = reactive({
  userId: 0,
  username: '',
  realName: '',
  version: 1,
  new_password: '',
  confirm_password: '',
})

function validateConfirmPassword(
  _rule: unknown,
  value: string,
  callback: (error?: string | Error) => void,
): void {
  if (!value) {
    callback(new Error('请再次输入新密码'))
    return
  }
  if (value !== resetForm.new_password) {
    callback(new Error('两次输入的密码不一致'))
    return
  }
  callback()
}

const resetRules: FormRules = {
  new_password: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    {
      pattern: /^(?=.*[A-Za-z])(?=.*\d).{8,64}$/,
      message: '密码需为 8-64 位，且同时包含字母和数字',
      trigger: 'blur',
    },
  ],
  confirm_password: [{ validator: validateConfirmPassword, trigger: 'blur' }],
}

function openResetPassword(row: OrgUser): void {
  Object.assign(resetForm, {
    userId: row.id,
    username: row.username,
    realName: row.real_name,
    version: row.version,
    new_password: '',
    confirm_password: '',
  })
  resetDialogVisible.value = true
  void nextTick(() => resetFormRef.value?.clearValidate())
}

async function submitResetPassword(): Promise<void> {
  const valid = await resetFormRef.value?.validate().catch(() => false)
  if (!valid || resetSubmitting.value) return
  resetSubmitting.value = true
  try {
    await orgApi.resetPassword(resetForm.userId, {
      new_password: resetForm.new_password,
      version: resetForm.version,
    })
    ElMessage.success('密码已重置，该用户所有登录状态已失效')
    resetDialogVisible.value = false
    await loadUsers()
  } finally {
    resetSubmitting.value = false
  }
}

async function deleteUser(row: OrgUser): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `确定删除用户「${row.real_name}（${row.username}）」吗？删除采用软删除，历史记录与审计日志保留。`,
      '删除用户',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  await orgApi.deleteUser(row.id)
  ElMessage.success('用户已删除（历史记录保留）')
  await Promise.all([loadUsers(), loadDeptTree()])
}

onMounted(() => {
  void Promise.all([loadDeptTree(), loadUsers()])
})
</script>

<template>
  <div class="page org-page">
    <header class="page-header">
      <div>
        <p class="page-eyebrow">ORGANIZATION & PEOPLE</p>
        <h1 class="page-title">组织架构与人员</h1>
        <p class="page-subtitle">
          维护部门层级、用户账号与角色归属；数据范围由后端查询层强制收敛。
        </p>
      </div>
      <div class="page-actions">
        <el-button
          :icon="Refresh"
          :loading="deptLoading || userLoading"
          @click="refreshAll"
        >
          刷新数据
        </el-button>
        <el-button
          v-if="canCreateUser"
          :icon="Upload"
          @click="importVisible = true"
        >
          导入用户
        </el-button>
      </div>
    </header>

    <div class="org-layout">
      <section class="surface-card dept-panel">
        <div class="panel-head">
          <div>
            <p class="panel-eyebrow">DEPARTMENTS</p>
            <h2 class="panel-title">部门树</h2>
          </div>
          <el-button
            v-if="auth.hasPerm('system:dept:create')"
            type="primary"
            plain
            size="small"
            :icon="Plus"
            @click="openCreateDept(null)"
          >
            新增
          </el-button>
        </div>

        <div class="dept-search">
          <el-input
            v-model="deptKeyword"
            :prefix-icon="Search"
            placeholder="搜索部门名称 / 编码"
            clearable
          />
        </div>

        <button
          type="button"
          class="dept-all"
          :class="{ active: selectedDeptId === null }"
          @click="selectAllDepts"
        >
          <span class="dept-all-icon"><el-icon><OfficeBuilding /></el-icon></span>
          <span class="dept-all-label">全部部门</span>
          <span class="dept-all-count">{{ totalDeptCount }}</span>
        </button>

        <div v-loading="deptLoading" class="dept-tree-scroll">
          <el-tree
            ref="deptTreeRef"
            :data="deptTree"
            node-key="id"
            :props="deptTreeProps"
            :indent="14"
            highlight-current
            default-expand-all
            :expand-on-click-node="false"
            :filter-node-method="filterDeptNode"
            empty-text="暂无部门，请先新增"
            @node-click="handleDeptClick"
          >
            <template #default="{ data }">
              <div class="dept-node">
                <span class="dept-node-main">
                  <span class="dept-name" :title="data.name">{{ data.name }}</span>
                  <span class="dept-meta">
                    <span class="dept-code" :title="data.code">{{ data.code }}</span>
                    <el-tag v-if="data.source === 'ldap'" size="small" type="info" effect="plain">
                      域控
                    </el-tag>
                  </span>
                </span>
                <span class="dept-node-side" @click.stop>
                  <span class="dept-user-count" :title="`${data.user_count} 位直属用户`">
                    {{ data.user_count }}
                  </span>
                  <el-dropdown
                    v-if="canManageDept"
                    trigger="click"
                    @command="handleDeptCommand($event, data)"
                  >
                    <button class="dept-more" type="button" aria-label="部门操作" @click.stop>
                      <el-icon><MoreFilled /></el-icon>
                    </button>
                    <template #dropdown>
                      <el-dropdown-menu>
                        <el-dropdown-item
                          v-if="auth.hasPerm('system:dept:create')"
                          command="create"
                          :icon="Plus"
                        >
                          新增下级
                        </el-dropdown-item>
                        <el-dropdown-item
                          v-if="auth.hasPerm('system:dept:update')"
                          command="edit"
                          :icon="Edit"
                        >
                          编辑部门
                        </el-dropdown-item>
                        <el-dropdown-item
                          v-if="auth.hasPerm('system:dept:delete')"
                          command="delete"
                          :icon="Delete"
                          divided
                        >
                          删除部门
                        </el-dropdown-item>
                      </el-dropdown-menu>
                    </template>
                  </el-dropdown>
                </span>
              </div>
            </template>
          </el-tree>
        </div>

        <div class="dept-foot">
          <span>共 {{ totalDeptCount }} 个部门</span>
          <span class="dept-foot-note">编码全局唯一</span>
        </div>
      </section>

      <section class="surface-card user-panel">
        <div class="panel-head user-head">
          <div>
            <p class="panel-eyebrow">MEMBERS</p>
            <h2 class="panel-title">
              用户列表
              <span class="dept-context">{{ selectedDeptName }}</span>
            </h2>
          </div>
          <el-button
            v-if="canCreateUser"
            type="primary"
            :icon="Plus"
            @click="openCreateUser"
          >
            新增用户
          </el-button>
        </div>

        <div class="user-filters">
          <el-input
            v-model="query.keyword"
            :prefix-icon="Search"
            placeholder="用户名 / 姓名 / 工号 / 手机"
            class="filter-keyword"
            clearable
            @keyup.enter="handleSearch"
            @clear="handleSearch"
          />
          <el-select
            v-model="query.status"
            placeholder="账号状态"
            class="filter-status"
            clearable
            @change="handleSearch"
          >
            <el-option label="启用" :value="1" />
            <el-option label="停用" :value="0" />
          </el-select>
          <el-checkbox v-model="query.include_child" @change="handleSearch">
            包含下级部门
          </el-checkbox>
          <el-button :icon="Search" @click="handleSearch">查询</el-button>
          <el-button text @click="resetFilters">重置</el-button>
        </div>

        <el-table
          v-loading="userLoading"
          :data="users"
          row-key="id"
          class="user-table"
          empty-text="当前范围内暂无用户"
        >
          <el-table-column label="用户" min-width="190">
            <template #default="{ row }">
              <div class="user-cell">
                <span class="user-avatar-sm">{{ initials(row.real_name) }}</span>
                <span class="user-identity">
                  <span class="user-realname">
                    {{ row.real_name }}
                    <el-tag
                      v-if="row.source === 'ldap'"
                      size="small"
                      type="info"
                      effect="plain"
                      round
                    >
                      域控
                    </el-tag>
                    <el-tag
                      v-if="row.id === auth.profile?.id"
                      size="small"
                      type="primary"
                      effect="light"
                      round
                    >
                      我
                    </el-tag>
                  </span>
                  <span class="user-username">
                    @{{ row.username }}
                    <template v-if="row.employee_no"> · {{ row.employee_no }}</template>
                  </span>
                </span>
              </div>
            </template>
          </el-table-column>

          <el-table-column label="部门 / 岗位" min-width="150">
            <template #default="{ row }">
              <div class="stack-cell">
                <span :title="row.dept_path || row.dept_name || '未分配部门'">
                  {{ row.dept_path || row.dept_name || '未分配部门' }}
                </span>
                <small>{{ row.position || '未设置岗位' }}</small>
              </div>
            </template>
          </el-table-column>

          <el-table-column label="角色" min-width="170">
            <template #default="{ row }">
              <div class="role-tags">
                <el-tag
                  v-for="role in row.roles"
                  :key="role.id"
                  size="small"
                  effect="plain"
                  round
                >
                  {{ role.name }}
                </el-tag>
                <span v-if="!row.roles.length" class="muted">未分配角色</span>
              </div>
            </template>
          </el-table-column>

          <el-table-column label="联系方式" min-width="180">
            <template #default="{ row }">
              <div class="stack-cell">
                <span>{{ row.email || '—' }}</span>
                <small>{{ row.phone || '未填写手机号' }}</small>
              </div>
            </template>
          </el-table-column>

          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-switch
                :model-value="row.status === 1"
                :loading="statusLoadingId === row.id"
                :disabled="!canUpdateUser || row.id === auth.profile?.id"
                inline-prompt
                active-text="启用"
                inactive-text="停用"
                @change="handleSwitchChange(row, $event)"
              />
            </template>
          </el-table-column>

          <el-table-column label="最近登录" width="155">
            <template #default="{ row }">
              <span class="muted">{{ formatDateTime(row.last_login_at) }}</span>
            </template>
          </el-table-column>

          <el-table-column label="操作" width="190" fixed="right">
            <template #default="{ row }">
              <div class="row-actions">
                <el-button
                  v-if="canUpdateUser"
                  link
                  type="primary"
                  size="small"
                  :loading="userDialogLoading"
                  @click="openEditUser(row)"
                >
                  编辑
                </el-button>
                <el-button
                  v-if="canResetPassword"
                  link
                  type="warning"
                  size="small"
                  :disabled="row.id === auth.profile?.id || row.source === 'ldap'"
                  :title="row.source === 'ldap' ? '域控账号密码由 AD 域管理' : ''"
                  @click="openResetPassword(row)"
                >
                  重置密码
                </el-button>
                <el-button
                  v-if="canDeleteUser"
                  link
                  type="danger"
                  size="small"
                  :disabled="row.id === auth.profile?.id"
                  @click="deleteUser(row)"
                >
                  删除
                </el-button>
              </div>
            </template>
          </el-table-column>
        </el-table>

        <div class="table-foot">
          <span class="table-hint">共 {{ userTotal }} 位用户，结果已按数据范围过滤</span>
          <el-pagination
            v-model:current-page="query.page"
            v-model:page-size="query.page_size"
            :total="userTotal"
            :page-sizes="[10, 20, 50]"
            layout="sizes, prev, pager, next"
            background
            @current-change="loadUsers"
            @size-change="handleSizeChange"
          />
        </div>
      </section>
    </div>

    <el-dialog
      v-model="deptDialogVisible"
      :title="deptDialogMode === 'create' ? '新增部门' : '编辑部门'"
      width="580px"
      class="org-dialog"
      :close-on-click-modal="false"
      @closed="resetDeptForm"
    >
      <el-form
        ref="deptFormRef"
        :model="deptForm"
        :rules="deptRules"
        label-position="top"
      >
        <div class="form-grid">
          <el-form-item label="上级部门" prop="parent_id" class="span-2">
            <el-tree-select
              v-model="deptForm.parent_id"
              :data="deptParentOptions"
              node-key="id"
              :props="deptTreeProps"
              check-strictly
              :render-after-expand="false"
              default-expand-all
              clearable
              placeholder="不选择则作为根部门"
            />
          </el-form-item>
          <el-form-item label="部门名称" prop="name">
            <el-input v-model="deptForm.name" maxlength="100" placeholder="例如：信息技术部" />
          </el-form-item>
          <el-form-item label="部门编码" prop="code">
            <el-input
              v-model="deptForm.code"
              maxlength="50"
              placeholder="例如：IT"
              @input="normalizeDeptCode"
            />
          </el-form-item>
          <el-form-item label="部门负责人">
            <el-select
              v-model="deptForm.manager_id"
              filterable
              remote
              clearable
              :remote-method="searchManagers"
              :loading="managerLoading"
              placeholder="搜索姓名 / 用户名"
              @change="handleManagerChange"
            >
              <el-option
                v-for="user in managerOptions"
                :key="user.id"
                :label="
                  user.username
                    ? `${user.real_name}（${user.username}）`
                    : user.real_name
                "
                :value="user.id"
              >
                <div class="manager-option">
                  <span>
                    {{ user.real_name }}<template v-if="user.username">（{{ user.username }}）</template>
                  </span>
                  <small>{{ user.dept_name || '' }}</small>
                </div>
              </el-option>
            </el-select>
            <p class="field-hint">
              审批流程中的「部门负责人」节点将自动取该用户；域控同步仅在此字段为空时回填。
            </p>
          </el-form-item>
          <el-form-item label="联系电话">
            <el-input v-model="deptForm.phone" maxlength="30" placeholder="办公电话或手机号" />
          </el-form-item>
          <el-form-item label="排序">
            <el-input-number v-model="deptForm.sort" :min="0" :max="9999" controls-position="right" />
          </el-form-item>
          <el-form-item label="状态">
            <el-switch
              v-model="deptForm.status"
              :active-value="1"
              :inactive-value="0"
              inline-prompt
              active-text="启用"
              inactive-text="停用"
            />
          </el-form-item>
          <el-form-item label="备注" class="span-2">
            <el-input
              v-model="deptForm.remark"
              type="textarea"
              :rows="2"
              maxlength="255"
              show-word-limit
            />
          </el-form-item>
        </div>
      </el-form>
      <template #footer>
        <el-button @click="deptDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="deptSubmitting" @click="submitDept">
          {{ deptDialogMode === 'create' ? '创建部门' : '保存修改' }}
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="userDialogVisible"
      :title="userDialogMode === 'create' ? '新增用户' : '编辑用户'"
      width="680px"
      class="org-dialog"
      :close-on-click-modal="false"
      @closed="resetUserForm"
    >
      <el-form
        ref="userFormRef"
        :model="userForm"
        :rules="userRules"
        label-position="top"
      >
        <el-alert
          v-if="userForm.source === 'ldap'"
          type="warning"
          :closable="false"
          show-icon
          class="ldap-edit-alert"
          title="该账号来自域控同步"
          description="姓名、工号、邮箱、电话、部门与状态将在下次同步时以域控数据为准；域控账号密码由 AD 域管理。"
        />
        <div class="form-grid">
          <el-form-item label="用户名" prop="username">
            <el-input
              v-model="userForm.username"
              maxlength="50"
              :disabled="userDialogMode === 'edit'"
              placeholder="小写字母、数字、点、下划线"
              @input="normalizeUsername"
            />
          </el-form-item>
          <el-form-item v-if="userDialogMode === 'create'" label="初始密码" prop="password">
            <el-input
              v-model="userForm.password"
              type="password"
              show-password
              maxlength="64"
              autocomplete="new-password"
              placeholder="8-64 位，字母 + 数字"
            />
          </el-form-item>
          <el-form-item label="姓名" prop="real_name">
            <el-input v-model="userForm.real_name" maxlength="50" placeholder="真实姓名" />
          </el-form-item>
          <el-form-item label="所属部门" prop="dept_id">
            <el-tree-select
              v-model="userForm.dept_id"
              :data="deptTree"
              node-key="id"
              :props="deptTreeProps"
              check-strictly
              :render-after-expand="false"
              default-expand-all
              filterable
              placeholder="请选择部门"
            />
          </el-form-item>
          <el-form-item label="岗位">
            <el-input v-model="userForm.position" maxlength="64" placeholder="例如：系统管理员" />
          </el-form-item>
          <el-form-item label="工号">
            <el-input v-model="userForm.employee_no" maxlength="50" placeholder="选填" />
          </el-form-item>
          <el-form-item label="邮箱" prop="email">
            <el-input v-model="userForm.email" maxlength="120" placeholder="name@company.com" />
          </el-form-item>
          <el-form-item label="手机号">
            <el-input v-model="userForm.phone" maxlength="30" placeholder="选填" />
          </el-form-item>
          <el-form-item label="角色" prop="role_ids" class="span-2">
            <el-select
              v-model="userForm.role_ids"
              multiple
              filterable
              collapse-tags
              collapse-tags-tooltip
              placeholder="至少选择一个角色"
            >
              <el-option
                v-for="role in roleOptions"
                :key="role.id"
                :label="`${role.name}（${role.code}）`"
                :value="role.id"
              />
            </el-select>
          </el-form-item>
          <el-form-item v-if="userDialogMode === 'create'" label="账号状态">
            <el-switch
              v-model="userForm.status"
              :active-value="1"
              :inactive-value="0"
              inline-prompt
              active-text="启用"
              inactive-text="停用"
            />
          </el-form-item>
          <el-form-item label="备注" class="span-2">
            <el-input
              v-model="userForm.remark"
              type="textarea"
              :rows="2"
              maxlength="255"
              show-word-limit
            />
          </el-form-item>
        </div>
        <div v-if="userDialogMode === 'create'" class="form-note">
          <el-icon><InfoFilled /></el-icon>
          <span>新用户首次登录必须修改初始密码；停用或重置密码会立即失效其全部登录会话。</span>
        </div>
      </el-form>
      <template #footer>
        <el-button @click="userDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="userSubmitting" @click="submitUser">
          {{ userDialogMode === 'create' ? '创建用户' : '保存修改' }}
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="resetDialogVisible"
      title="重置密码"
      width="500px"
      class="org-dialog"
      :close-on-click-modal="false"
    >
      <div class="reset-target">
        <span class="reset-avatar">{{ initials(resetForm.realName) }}</span>
        <div>
          <strong>{{ resetForm.realName }}</strong>
          <p>@{{ resetForm.username }}</p>
        </div>
      </div>
      <el-form
        ref="resetFormRef"
        :model="resetForm"
        :rules="resetRules"
        label-position="top"
      >
        <el-form-item label="新密码" prop="new_password">
          <el-input
            v-model="resetForm.new_password"
            type="password"
            show-password
            maxlength="64"
            autocomplete="new-password"
            placeholder="8-64 位，字母 + 数字"
          />
        </el-form-item>
        <el-form-item label="确认新密码" prop="confirm_password">
          <el-input
            v-model="resetForm.confirm_password"
            type="password"
            show-password
            maxlength="64"
            autocomplete="new-password"
            placeholder="再次输入新密码"
          />
        </el-form-item>
      </el-form>
      <div class="form-note warning">
        <el-icon><InfoFilled /></el-icon>
        <span>重置后该用户下次登录必须再次修改密码，所有现有令牌立即失效。</span>
      </div>
      <template #footer>
        <el-button @click="resetDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="resetSubmitting" @click="submitResetPassword">
          确认重置
        </el-button>
      </template>
    </el-dialog>

    <ImportDialog v-model="importVisible" kind="users" @imported="handleImported" />
  </div>
</template>

<style scoped>
.org-page {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.page-actions {
  display: flex;
  gap: 10px;
}

.org-layout {
  display: grid;
  grid-template-columns: clamp(340px, 25vw, 400px) minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}

.dept-panel,
.user-panel {
  padding: 22px;
}

.panel-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
  margin-bottom: 16px;
}

.panel-eyebrow {
  color: var(--text-3);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.18em;
}

.panel-title {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 9px;
  margin-top: 4px;
  color: var(--text-1);
  font-size: 17px;
  font-weight: 650;
  letter-spacing: -0.015em;
}

.dept-context {
  padding: 3px 9px;
  border-radius: 999px;
  background: var(--brand-soft);
  color: var(--brand);
  font-size: 11px;
  font-weight: 600;
}

.dept-search {
  margin-bottom: 10px;
}

.dept-all {
  display: flex;
  align-items: center;
  gap: 9px;
  width: 100%;
  margin-bottom: 8px;
  padding: 9px 11px;
  border: 1px solid transparent;
  border-radius: 11px;
  background: var(--surface-muted);
  color: var(--text-1);
  font-size: 13px;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.2s ease, background-color 0.2s ease, color 0.2s ease;
}

.dept-all:hover {
  border-color: color-mix(in srgb, var(--brand) 24%, var(--border));
}

.dept-all.active {
  border-color: color-mix(in srgb, var(--brand) 30%, var(--border));
  background: var(--brand-soft);
  color: var(--brand);
}

.dept-all-icon {
  display: grid;
  place-items: center;
  width: 26px;
  height: 26px;
  border-radius: 8px;
  background: var(--surface);
  color: var(--brand);
}

.dept-all-label {
  flex: 1;
  font-weight: 500;
}

.dept-all-count {
  min-width: 24px;
  padding: 1px 7px;
  border-radius: 999px;
  background: var(--surface);
  color: var(--text-2);
  font-family: var(--font-number);
  font-size: 11px;
  text-align: center;
}

.dept-tree-scroll {
  min-height: 180px;
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

.dept-node-side {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
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
}

.dept-more {
  display: grid;
  place-items: center;
  width: 22px;
  height: 22px;
  padding: 0;
  border: none;
  border-radius: 7px;
  background: transparent;
  color: var(--text-3);
  cursor: pointer;
}

.dept-more:hover {
  background: var(--surface);
  color: var(--brand);
}

.dept-foot {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px dashed var(--border);
  color: var(--text-3);
  font-size: 11px;
}

.dept-foot-note {
  color: var(--text-3);
}

.user-head {
  align-items: center;
}

.user-filters {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 16px;
}

.filter-keyword {
  width: 240px;
}

.filter-status {
  width: 120px;
}

.user-table {
  width: 100%;
}

.user-cell {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.user-avatar-sm {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  flex-shrink: 0;
  border-radius: 10px;
  background: var(--gradient-brand);
  color: #fff;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: -0.02em;
}

.user-identity {
  display: flex;
  flex-direction: column;
  min-width: 0;
  line-height: 1.35;
}

.user-realname {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--text-1);
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
}

.user-username {
  overflow: hidden;
  color: var(--text-3);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.stack-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  font-size: 12.5px;
}

.stack-cell span {
  overflow: hidden;
  color: var(--text-1);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.stack-cell small {
  overflow: hidden;
  color: var(--text-3);
  font-size: 10.5px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.role-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}

.muted {
  color: var(--text-3);
  font-size: 12px;
}

.row-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 2px;
}

.row-actions :deep(.el-button + .el-button) {
  margin-left: 6px;
}

.table-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  margin-top: 16px;
  padding-top: 15px;
  border-top: 1px dashed var(--border);
  flex-wrap: wrap;
}

.table-hint {
  color: var(--text-3);
  font-size: 11.5px;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 16px;
}

.ldap-edit-alert {
  margin-bottom: 16px;
}

.dept-node-main :deep(.el-tag) {
  margin-left: 6px;
}

.span-2 {
  grid-column: span 2;
}

.form-grid :deep(.el-select),
.form-grid :deep(.el-tree-select),
.form-grid :deep(.el-input-number) {
  width: 100%;
}

.manager-option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.manager-option small {
  color: var(--text-3);
  font-size: 11px;
}

.field-hint {
  margin: 4px 0 0;
  color: var(--text-3);
  font-size: 11.5px;
  line-height: 1.6;
}

.form-note {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin-top: 2px;
  padding: 11px 13px;
  border: 1px solid color-mix(in srgb, var(--brand) 16%, var(--border));
  border-radius: 11px;
  background: var(--brand-soft);
  color: var(--text-2);
  font-size: 11.5px;
  line-height: 1.6;
}

.form-note .el-icon {
  flex-shrink: 0;
  margin-top: 2px;
  color: var(--brand);
}

.form-note.warning {
  border-color: rgba(245, 158, 11, 0.22);
  background: rgba(245, 158, 11, 0.08);
}

.form-note.warning .el-icon {
  color: var(--warning);
}

.reset-target {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 18px;
  padding: 13px 14px;
  border: 1px solid var(--border);
  border-radius: 13px;
  background: var(--surface-muted);
}

.reset-avatar {
  display: grid;
  place-items: center;
  width: 38px;
  height: 38px;
  border-radius: 11px;
  background: var(--gradient-brand);
  color: #fff;
  font-size: 12px;
  font-weight: 700;
}

.reset-target strong {
  color: var(--text-1);
  font-size: 13.5px;
}

.reset-target p {
  margin-top: 1px;
  color: var(--text-3);
  font-size: 11.5px;
}

:deep(.org-dialog) {
  max-width: 94vw;
}

@media (max-width: 1180px) {
  .org-layout {
    grid-template-columns: 300px minmax(0, 1fr);
  }
}

@media (max-width: 1024px) {
  .org-layout {
    grid-template-columns: 1fr;
  }

  .dept-tree-scroll {
    max-height: 320px;
  }
}

@media (max-width: 640px) {
  .dept-panel,
  .user-panel {
    padding: 17px 15px;
  }

  .filter-keyword,
  .filter-status {
    width: 100%;
  }

  .form-grid {
    grid-template-columns: 1fr;
  }

  .span-2 {
    grid-column: span 1;
  }

  .table-foot {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
