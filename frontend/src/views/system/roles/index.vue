<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { isAxiosError } from 'axios'
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
  Key,
  Lock,
  Plus,
  Refresh,
  Search,
  UserFilled,
} from '@element-plus/icons-vue'

import { orgApi } from '@/api/org'
import { roleApi } from '@/api/roles'
import { useAuthStore } from '@/stores/auth'
import type { DeptNode } from '@/types/org'
import type {
  AdminMenuNode,
  DomainScope,
  FieldPermissionItem,
  ResourceDataPermissionItem,
  RoleDetail,
  RoleItem,
  RoleMeta,
  RoleUserOption,
} from '@/types/rbac'
import { formatDateTime, initials } from '@/utils/format'

const auth = useAuthStore()

const roles = ref<RoleItem[]>([])
const total = ref(0)
const loading = ref(false)
const query = reactive({
  page: 1,
  page_size: 10,
  keyword: '',
  status: undefined as number | undefined,
})
let roleRequestSeq = 0

const roleMeta = ref<RoleMeta | null>(null)
const menuTreeData = ref<AdminMenuNode[]>([])
const deptTreeData = ref<DeptNode[]>([])
const deptTreeLoaded = ref(false)
const deptTreeLoading = ref(false)
const deptTreeError = ref('')
const deptTreeProps = { label: 'name', children: 'children' }

const fallbackScopes = [
  { value: 'ALL', label: '全部数据' },
  { value: 'DEPT_AND_CHILD', label: '本部门及下级部门' },
  { value: 'DEPT', label: '本部门' },
  { value: 'CUSTOM', label: '自定义部门' },
  { value: 'SELF', label: '仅本人' },
]

const scopeOptions = computed(() => roleMeta.value?.data_scopes ?? fallbackScopes)
const fieldCatalog = computed(() => roleMeta.value?.field_catalog ?? {})
const resourceOptions = computed(() => roleMeta.value?.data_resources ?? [])
const assetDomainOptions = computed(() => roleMeta.value?.asset_domains ?? [])

interface ResourceScopeState {
  enabled: boolean
  data_scope: string
  dept_ids: number[]
}

const resourceState = ref<Record<string, ResourceScopeState>>({})

const resourceRows = computed(() =>
  resourceOptions.value.map((option) => ({
    value: option.value,
    label: option.label,
    enabled: resourceState.value[option.value]?.enabled ?? false,
    data_scope: resourceState.value[option.value]?.data_scope ?? selectedScope.value,
    dept_ids: resourceState.value[option.value]?.dept_ids ?? [],
  })),
)

const showDeptTree = computed(() => selectedScope.value === 'CUSTOM')
const deptTreeSelectProps = { label: 'name', children: 'children', value: 'id' }
const noDomainWarning = computed(
  () => selectedDomainScope.value === 'CUSTOM' && !selectedAssetDomains.value.length,
)

function domainLabel(code: string): string {
  return assetDomainOptions.value.find((item) => item.value === code)?.label ?? code
}

function roleDomainText(row: RoleItem): string {
  if (row.domain_scope === 'ALL') return '全部资产域'
  if (!row.asset_domains.length) return '无资产域权限'
  return row.asset_domains.map(domainLabel).join('、')
}

const SCOPE_DESCRIPTIONS: Record<string, string> = {
  ALL: '可查看系统内全部部门数据',
  DEPT_AND_CHILD: '本部门及所有下级部门',
  DEPT: '仅限用户所属部门',
  CUSTOM: '按勾选部门精确组合，不含下级',
  SELF: '仅限本人创建或持有的数据',
}

const canAssignMenus = computed(() => auth.hasPerm('system:role:assign-menu'))
const canAssignData = computed(() => auth.hasPerm('system:role:assign-data'))
const canAssignFields = computed(() => auth.hasPerm('system:role:assign-field'))
const canAssignUsers = computed(() => auth.hasPerm('system:role:assign-user'))

async function loadRoles(): Promise<void> {
  const seq = ++roleRequestSeq
  loading.value = true
  try {
    const data = await roleApi.listRoles({
      page: query.page,
      page_size: query.page_size,
      keyword: query.keyword.trim() || undefined,
      status: query.status,
    })
    if (seq !== roleRequestSeq) return
    roles.value = data.items
    total.value = data.total
  } finally {
    if (seq === roleRequestSeq) loading.value = false
  }
}

function handleSearch(): void {
  query.page = 1
  void loadRoles()
}

function resetFilters(): void {
  query.keyword = ''
  query.status = undefined
  query.page = 1
  void loadRoles()
}

function handleSizeChange(): void {
  query.page = 1
  void loadRoles()
}

async function ensureMeta(): Promise<void> {
  if (roleMeta.value) return
  try {
    roleMeta.value = await roleApi.meta()
  } catch {
    roleMeta.value = null
  }
}

const roleDialogVisible = ref(false)
const roleDialogMode = ref<'create' | 'edit'>('create')
const roleFormRef = ref<FormInstance>()
const roleSubmitting = ref(false)

interface RoleFormState {
  id: number
  code: string
  name: string
  description: string
  data_scope: string
  domain_scope: DomainScope
  asset_domains: string[]
  sort: number
  status: number
  version: number
}

const roleForm = reactive<RoleFormState>({
  id: 0,
  code: '',
  name: '',
  description: '',
  data_scope: 'SELF',
  domain_scope: 'CUSTOM',
  asset_domains: [],
  sort: 0,
  status: 1,
  version: 1,
})

const roleRules: FormRules = {
  code: [
    { required: true, message: '请输入角色编码', trigger: 'blur' },
    {
      pattern: /^[A-Z][A-Z0-9_]{1,49}$/,
      message: '需为 2-50 位大写字母、数字或下划线，且以字母开头',
      trigger: 'blur',
    },
  ],
  name: [
    { required: true, message: '请输入角色名称', trigger: 'blur' },
    { max: 50, message: '角色名称不能超过 50 个字符', trigger: 'blur' },
  ],
}

function resetRoleForm(): void {
  Object.assign(roleForm, {
    id: 0,
    code: '',
    name: '',
    description: '',
    data_scope: 'SELF',
    domain_scope: 'CUSTOM',
    asset_domains: [],
    sort: 0,
    status: 1,
    version: 1,
  })
}

function normalizeRoleCode(): void {
  roleForm.code = roleForm.code.toUpperCase()
}

function openCreateRole(): void {
  resetRoleForm()
  roleDialogMode.value = 'create'
  roleDialogVisible.value = true
  void ensureMeta()
  void nextTick(() => roleFormRef.value?.clearValidate())
}

function openEditRole(row: RoleItem): void {
  roleDialogMode.value = 'edit'
  Object.assign(roleForm, {
    id: row.id,
    code: row.code,
    name: row.name,
    description: row.description ?? '',
    data_scope: row.data_scope,
    domain_scope: row.domain_scope,
    asset_domains: [...row.asset_domains],
    sort: row.sort,
    status: row.status,
    version: row.version,
  })
  roleDialogVisible.value = true
  void nextTick(() => roleFormRef.value?.clearValidate())
}

async function submitRole(): Promise<void> {
  const valid = await roleFormRef.value?.validate().catch(() => false)
  if (!valid || roleSubmitting.value) return
  if (roleDialogMode.value === 'create' && !auth.isSuperAdmin) {
    if (roleForm.data_scope === 'ALL' || roleForm.domain_scope === 'ALL') {
      ElMessage.warning('只有超级管理员可以授予全部数据范围或全部资产域')
      return
    }
  }
  roleSubmitting.value = true
  try {
    if (roleDialogMode.value === 'create') {
      await roleApi.createRole({
        code: roleForm.code.trim(),
        name: roleForm.name.trim(),
        description: roleForm.description.trim() || null,
        data_scope: roleForm.data_scope,
        domain_scope: roleForm.domain_scope,
        asset_domains:
          roleForm.domain_scope === 'ALL' ? [] : [...roleForm.asset_domains],
        sort: roleForm.sort,
        status: roleForm.status,
      })
      ElMessage.success('角色创建成功，请继续配置菜单与数据权限')
    } else {
      await roleApi.updateRole(roleForm.id, {
        name: roleForm.name.trim(),
        description: roleForm.description.trim() || null,
        sort: roleForm.sort,
        status: roleForm.status,
        version: roleForm.version,
      })
      ElMessage.success('角色更新成功')
    }
    roleDialogVisible.value = false
    await loadRoles()
  } finally {
    roleSubmitting.value = false
  }
}

async function deleteRole(row: RoleItem): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `确定删除角色「${row.name}（${row.code}）」吗？删除前必须先解除所有成员关联。`,
      '删除角色',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  await roleApi.deleteRole(row.id)
  ElMessage.success('角色已删除')
  await loadRoles()
}

const drawerVisible = ref(false)
const detailLoading = ref(false)
const currentRole = ref<RoleDetail | null>(null)
const activeTab = ref<'menu' | 'data' | 'field' | 'member'>('menu')
const saving = ref(false)

const menuTreeRef = ref<InstanceType<typeof ElTree>>()
const dataTreeRef = ref<InstanceType<typeof ElTree>>()
const selectedScope = ref('SELF')
// 角色级资产域：ALL=显式全部域（仅超管可授予）；CUSTOM+空数组=无资产域权限。
const selectedDomainScope = ref<DomainScope>('CUSTOM')
const selectedAssetDomains = ref<string[]>([])
const fieldState = ref<Record<string, Record<string, { can_view: boolean; can_edit: boolean }>>>({})
const memberIds = ref<number[]>([])
const memberOptions = ref<RoleUserOption[]>([])
const memberSearchLoading = ref(false)
const memberKeyword = ref('')
const memberResults = ref<RoleUserOption[]>([])
const memberHasSearched = ref(false)
const memberFilter = ref<'all' | 'in' | 'out'>('all')
const memberBaselineIds = ref<number[]>([])
const selectedMemberKeyword = ref('')
const selectedMemberPage = ref(1)
const selectedMemberPageSize = 10
let memberSearchSeq = 0
let memberSearchTimer: number | undefined
const pendingMenuHydration = ref(true)
const pendingDataHydration = ref(true)

const isSuperRole = computed(() => currentRole.value?.code === 'SUPER_ADMIN')
const roleEditable = computed(
  () =>
    Boolean(currentRole.value) &&
    (!currentRole.value?.is_system || auth.isSuperAdmin),
)
const canEditMenus = computed(
  () => canAssignMenus.value && roleEditable.value && !isSuperRole.value,
)
const canEditData = computed(
  () => canAssignData.value && roleEditable.value && !isSuperRole.value,
)
const canEditFields = computed(
  () => canAssignFields.value && roleEditable.value && !isSuperRole.value,
)
const canEditMembers = computed(
  () =>
    canAssignUsers.value &&
    Boolean(currentRole.value) &&
    (!isSuperRole.value || auth.isSuperAdmin),
)

const canSaveCurrent = computed(() => {
  if (!currentRole.value) return false
  if (activeTab.value === 'menu') return canEditMenus.value
  if (activeTab.value === 'data') {
    if (!canEditData.value) return false
    if (!auth.isSuperAdmin) {
      if (selectedScope.value === 'ALL') return false
      if (selectedDomainScope.value === 'ALL') return false
      if (resourceRows.value.some((row) => row.enabled && row.data_scope === 'ALL')) {
        return false
      }
    }
    return true
  }
  if (activeTab.value === 'field') return canEditFields.value
  if (activeTab.value === 'member') {
    return canEditMembers.value && currentRole.value.status === 1
  }
  return false
})

const saveLabel = computed(() => {
  if (activeTab.value === 'menu') return '保存菜单权限'
  if (activeTab.value === 'data') return '保存数据权限'
  if (activeTab.value === 'field') return '保存字段权限'
  return '保存成员'
})

function flattenMenus(nodes: AdminMenuNode[]): AdminMenuNode[] {
  return nodes.flatMap((node) => [node, ...flattenMenus(node.children ?? [])])
}

function menuTypeLabel(type: string): string {
  if (type === 'DIR') return '目录'
  if (type === 'MENU') return '菜单'
  return '操作'
}

function resourceLabel(resource: string): string {
  if (resource === 'asset') return '资产字段'
  return resource
}

async function ensureMenuTree(): Promise<void> {
  if (menuTreeData.value.length) return
  menuTreeData.value = await roleApi.menuTree()
}

async function ensureDeptTree(): Promise<void> {
  if (deptTreeLoaded.value || deptTreeError.value) return
  deptTreeLoading.value = true
  try {
    deptTreeData.value = await orgApi.departmentTree()
    deptTreeLoaded.value = true
  } catch {
    deptTreeError.value = '部门树加载失败，请确认当前账号具备组织架构查看权限'
  } finally {
    deptTreeLoading.value = false
  }
}

function buildFieldState(detail: RoleDetail): Record<
  string,
  Record<string, { can_view: boolean; can_edit: boolean }>
> {
  const result: Record<string, Record<string, { can_view: boolean; can_edit: boolean }>> = {}
  for (const [resource, fields] of Object.entries(fieldCatalog.value)) {
    result[resource] = {}
    for (const field of fields) {
      result[resource][field.field] = { can_view: true, can_edit: true }
    }
  }
  for (const item of detail.field_permissions) {
    if (result[item.resource]?.[item.field]) {
      result[item.resource][item.field] = {
        can_view: item.can_view,
        can_edit: item.can_edit,
      }
    }
  }
  return result
}

function mergeMemberOptions(detail: RoleDetail): void {
  const merged = [...memberOptions.value]
  for (const user of detail.users) {
    if (!merged.some((item) => item.id === user.id)) {
      merged.push(user)
    }
  }
  memberOptions.value = merged
  memberIds.value = detail.users.map((user) => user.id)
  memberBaselineIds.value = [...memberIds.value]
}

function buildResourceState(detail: RoleDetail): Record<string, ResourceScopeState> {
  const result: Record<string, ResourceScopeState> = {}
  for (const option of resourceOptions.value) {
    result[option.value] = {
      enabled: false,
      data_scope: detail.data_scope,
      dept_ids: [],
    }
  }
  for (const item of detail.data_permissions ?? []) {
    result[item.resource] = {
      enabled: true,
      data_scope: item.data_scope,
      dept_ids: [...(item.dept_ids ?? [])],
    }
  }
  return result
}

function setResourceEnabled(
  resource: string,
  value: string | number | boolean,
): void {
  if (!canEditData.value) return
  const state = resourceState.value[resource]
  if (!state) return
  state.enabled = Boolean(value)
  if (state.enabled && !state.data_scope) state.data_scope = selectedScope.value
}

function setResourceScope(resource: string, value: string): void {
  if (!canEditData.value) return
  const state = resourceState.value[resource]
  if (!state) return
  state.data_scope = value
  if (value !== 'CUSTOM') state.dept_ids = []
}

function setResourceDepts(resource: string, value: number[]): void {
  if (!canEditData.value) return
  const state = resourceState.value[resource]
  if (state) state.dept_ids = value.map(Number).filter((id) => Number.isFinite(id))
}

async function hydrateEditor(detail: RoleDetail): Promise<void> {
  selectedScope.value = detail.data_scope
  selectedDomainScope.value = detail.domain_scope
  selectedAssetDomains.value = [...detail.asset_domains]
  fieldState.value = buildFieldState(detail)
  resourceState.value = buildResourceState(detail)
  mergeMemberOptions(detail)
  pendingMenuHydration.value = true
  pendingDataHydration.value = true
  await nextTick()
  applyPendingChecks()
}

function applyPendingChecks(): void {
  if (pendingMenuHydration.value && menuTreeRef.value) {
    menuTreeRef.value.setCheckedKeys(currentRole.value?.menu_ids ?? [])
    pendingMenuHydration.value = false
  }
  if (
    pendingDataHydration.value &&
    dataTreeRef.value &&
    currentRole.value &&
    (deptTreeLoaded.value || !currentRole.value.dept_ids.length)
  ) {
    dataTreeRef.value.setCheckedKeys(currentRole.value.dept_ids)
    pendingDataHydration.value = false
  }
}

async function openAuthorization(row: RoleItem): Promise<void> {
  drawerVisible.value = true
  activeTab.value = 'menu'
  currentRole.value = null
  resetMemberPanel()
  detailLoading.value = true
  try {
    const [detail, meta, menus] = await Promise.all([
      roleApi.getRole(row.id),
      roleApi.meta(),
      roleApi.menuTree(),
    ])
    roleMeta.value = meta
    menuTreeData.value = menus
    currentRole.value = detail
    await hydrateEditor(detail)
  } finally {
    detailLoading.value = false
  }
}

watch(activeTab, async (tab) => {
  if (tab === 'data') {
    await ensureDeptTree()
    await nextTick()
    applyPendingChecks()
  }
  if (tab === 'menu') {
    await nextTick()
    applyPendingChecks()
  }
  if (tab === 'member' && canAssignUsers.value && !memberHasSearched.value) {
    void searchMemberOptions(memberKeyword.value)
  }
})

function selectAllMenus(): void {
  if (!canEditMenus.value) return
  menuTreeRef.value?.setCheckedKeys(flattenMenus(menuTreeData.value).map((node) => node.id))
}

function clearMenus(): void {
  if (!canEditMenus.value) return
  menuTreeRef.value?.setCheckedKeys([])
}

function setFieldView(
  resource: string,
  field: string,
  value: string | number | boolean,
): void {
  const state = fieldState.value[resource]?.[field]
  if (!state) return
  state.can_view = Boolean(value)
  if (!state.can_view) state.can_edit = false
}

function setFieldEdit(
  resource: string,
  field: string,
  value: string | number | boolean,
): void {
  const state = fieldState.value[resource]?.[field]
  if (!state) return
  state.can_edit = Boolean(value)
  if (state.can_edit) state.can_view = true
}

async function searchMemberOptions(keyword: string): Promise<void> {
  if (!canAssignUsers.value) return
  const seq = ++memberSearchSeq
  memberSearchLoading.value = true
  try {
    const items = await roleApi.userOptions(keyword.trim())
    if (seq !== memberSearchSeq) return
    const merged = [...memberOptions.value]
    for (const user of items) {
      if (!merged.some((item) => item.id === user.id)) {
        merged.push(user)
      }
    }
    memberOptions.value = merged
    memberResults.value = items
    memberHasSearched.value = true
  } catch {
    // 请求层已提示错误
  } finally {
    if (seq === memberSearchSeq) memberSearchLoading.value = false
  }
}

watch(memberKeyword, (value) => {
  if (activeTab.value !== 'member') return
  if (memberSearchTimer) window.clearTimeout(memberSearchTimer)
  memberSearchTimer = window.setTimeout(() => {
    void searchMemberOptions(value)
  }, 350)
})

onBeforeUnmount(() => {
  if (memberSearchTimer) window.clearTimeout(memberSearchTimer)
})

function resetMemberPanel(): void {
  if (memberSearchTimer) window.clearTimeout(memberSearchTimer)
  memberKeyword.value = ''
  memberResults.value = []
  memberHasSearched.value = false
  memberFilter.value = 'all'
  selectedMemberKeyword.value = ''
  selectedMemberPage.value = 1
}

const memberLookup = computed(() => {
  const map = new Map<number, RoleUserOption>()
  for (const user of currentRole.value?.users ?? []) map.set(user.id, user)
  for (const user of memberOptions.value) {
    if (!map.has(user.id)) map.set(user.id, user)
  }
  return map
})

function userById(id: number): RoleUserOption | undefined {
  return memberLookup.value.get(id)
}

const memberSet = computed(() => new Set(memberIds.value))

const memberPendingText = computed(() => {
  const added = memberIds.value.filter((id) => !memberBaselineIds.value.includes(id)).length
  const removed = memberBaselineIds.value.filter((id) => !memberIds.value.includes(id)).length
  if (!added && !removed) return ''
  const parts: string[] = []
  if (added) parts.push(`新增 ${added} 人`)
  if (removed) parts.push(`移除 ${removed} 人`)
  return parts.join('，')
})

const filteredMemberResults = computed(() => {
  if (memberFilter.value === 'in') {
    return memberResults.value.filter((user) => memberSet.value.has(user.id))
  }
  if (memberFilter.value === 'out') {
    return memberResults.value.filter((user) => !memberSet.value.has(user.id))
  }
  return memberResults.value
})

const selectedMembers = computed<RoleUserOption[]>(() =>
  memberIds.value.map(
    (id) =>
      userById(id) ?? {
        id,
        username: `#${id}`,
        real_name: '未知用户',
        dept_name: null,
        status: 0,
      },
  ),
)

const filteredSelectedMembers = computed(() => {
  const keyword = selectedMemberKeyword.value.trim().toLowerCase()
  if (!keyword) return selectedMembers.value
  return selectedMembers.value.filter((user) =>
    `${user.real_name} ${user.username} ${user.dept_name ?? ''}`
      .toLowerCase()
      .includes(keyword),
  )
})

const pagedSelectedMembers = computed(() => {
  const start = (selectedMemberPage.value - 1) * selectedMemberPageSize
  return filteredSelectedMembers.value.slice(start, start + selectedMemberPageSize)
})

watch(selectedMemberKeyword, () => {
  selectedMemberPage.value = 1
})

watch(
  () => filteredSelectedMembers.value.length,
  (total) => {
    const maxPage = Math.max(1, Math.ceil(total / selectedMemberPageSize))
    if (selectedMemberPage.value > maxPage) selectedMemberPage.value = maxPage
  },
)

function addMember(user: RoleUserOption): void {
  if (!canEditMembers.value) return
  if (!memberOptions.value.some((item) => item.id === user.id)) {
    memberOptions.value = [...memberOptions.value, user]
  }
  if (!memberIds.value.includes(user.id)) {
    memberIds.value = [...memberIds.value, user.id]
  }
}

function removeMember(id: number): void {
  if (!canEditMembers.value) return
  memberIds.value = memberIds.value.filter((item) => item !== id)
}

function bulkAddVisible(): void {
  if (!canEditMembers.value) return
  const targets = filteredMemberResults.value.filter((user) => !memberSet.value.has(user.id))
  if (!targets.length) {
    ElMessage.info('当前搜索结果中没有可加入的人员')
    return
  }
  memberIds.value = [...memberIds.value, ...targets.map((user) => user.id)]
  ElMessage.success(`已加入 ${targets.length} 人，保存后生效`)
}

function checkedDeptIds(): number[] {
  const keys = (dataTreeRef.value?.getCheckedKeys(false) ?? []) as Array<string | number>
  return keys.map(Number).filter((id) => Number.isFinite(id))
}

async function saveCurrent(): Promise<void> {
  if (!currentRole.value || !canSaveCurrent.value || saving.value) return
  const roleId = currentRole.value.id
  const version = currentRole.value.version
  const deptIds = activeTab.value === 'data' && showDeptTree.value ? checkedDeptIds() : []
  const permissions: ResourceDataPermissionItem[] = []
  if (activeTab.value === 'data') {
    if (showDeptTree.value && !deptIds.length) {
      ElMessage.warning('自定义数据范围至少需要勾选一个部门')
      return
    }
    for (const row of resourceRows.value) {
      if (!row.enabled) continue
      if (row.data_scope === 'CUSTOM' && !row.dept_ids.length) {
        ElMessage.warning(`「${row.label}」使用自定义部门时至少需要选择一个部门`)
        return
      }
      permissions.push({
        resource: row.value,
        data_scope: row.data_scope,
        dept_ids: row.data_scope === 'CUSTOM' ? [...row.dept_ids] : [],
      })
    }
  }
  saving.value = true
  try {
    let detail: RoleDetail
    if (activeTab.value === 'menu') {
      const keys = (menuTreeRef.value?.getCheckedKeys(false) ?? []) as Array<string | number>
      detail = await roleApi.assignMenus(roleId, {
        menu_ids: keys.map(Number).filter((id) => Number.isFinite(id)),
        version,
      })
    } else if (activeTab.value === 'data') {
      detail = await roleApi.assignDataPermissions(roleId, {
        data_scope: selectedScope.value,
        domain_scope: selectedDomainScope.value,
        asset_domains:
          selectedDomainScope.value === 'ALL' ? [] : [...selectedAssetDomains.value],
        permissions,
        dept_ids: deptIds,
        version,
      })
    } else if (activeTab.value === 'field') {
      const fieldItems: FieldPermissionItem[] = []
      for (const [resource, fields] of Object.entries(fieldState.value)) {
        for (const [field, state] of Object.entries(fields)) {
          if (!state.can_view || !state.can_edit) {
            fieldItems.push({
              resource,
              field,
              can_view: state.can_view,
              can_edit: state.can_edit,
            })
          }
        }
      }
      detail = await roleApi.assignFieldPermissions(roleId, {
        permissions: fieldItems,
        version,
      })
    } else {
      detail = await roleApi.assignUsers(roleId, { user_ids: memberIds.value, version })
    }
    currentRole.value = detail
    await hydrateEditor(detail)
    ElMessage.success('权限配置已保存')
    await loadRoles()
  } catch (error) {
    // 版本冲突后必须重新取详情，否则后续保存会一直带着过期 version。
    if (isAxiosError(error) && error.response?.status === 409) {
      const latest = await roleApi.getRole(roleId).catch(() => null)
      if (latest) {
        currentRole.value = latest
        await hydrateEditor(latest)
        ElMessage.info('已加载他人保存的最新配置，请确认后重新保存')
      }
    }
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  void Promise.all([loadRoles(), ensureMeta()])
})
</script>

<template>
  <div class="page role-page">
    <header class="page-header">
      <div>
        <p class="page-eyebrow">ROLE BASED ACCESS CONTROL</p>
        <h1 class="page-title">角色与授权</h1>
        <p class="page-subtitle">
          角色按资产域、数据范围、菜单与操作码授权；资产域一次配置后自动作用于全部资产业务。
        </p>
      </div>
      <div class="page-actions">
        <el-button :icon="Refresh" :loading="loading" @click="loadRoles">刷新</el-button>
        <el-button
          v-if="auth.hasPerm('system:role:create')"
          type="primary"
          :icon="Plus"
          @click="openCreateRole"
        >
          新增角色
        </el-button>
      </div>
    </header>

    <section class="surface-card role-panel">
      <div class="role-summary">
        <div class="summary-main">
          <span class="summary-icon"><el-icon><Key /></el-icon></span>
          <div>
            <p class="summary-label">角色总数</p>
            <p class="summary-value">{{ total }}</p>
          </div>
        </div>
        <div class="summary-note">
          <el-icon><InfoFilled /></el-icon>
          <span>超级管理员默认拥有全部权限；系统内置角色仅超级管理员可修改。</span>
        </div>
      </div>

      <div class="role-filters">
        <el-input
          v-model="query.keyword"
          :prefix-icon="Search"
          placeholder="角色名称 / 编码"
          class="filter-keyword"
          clearable
          @keyup.enter="handleSearch"
          @clear="handleSearch"
        />
        <el-select
          v-model="query.status"
          placeholder="角色状态"
          class="filter-status"
          clearable
          @change="handleSearch"
        >
          <el-option label="启用" :value="1" />
          <el-option label="停用" :value="0" />
        </el-select>
        <el-button :icon="Search" @click="handleSearch">查询</el-button>
        <el-button text @click="resetFilters">重置</el-button>
      </div>

      <el-table
        v-loading="loading"
        :data="roles"
        row-key="id"
        empty-text="暂无角色"
        class="role-table"
      >
        <el-table-column label="角色" min-width="210">
          <template #default="{ row }">
            <div class="role-cell">
              <span class="role-mark" :class="{ system: row.is_system }">
                <el-icon><component :is="row.is_system ? Lock : UserFilled" /></el-icon>
              </span>
              <span class="role-identity">
                <span class="role-name">
                  {{ row.name }}
                  <el-tag v-if="row.is_system" size="small" type="info" effect="plain" round>
                    内置
                  </el-tag>
                </span>
                <span class="role-code">{{ row.code }}</span>
              </span>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="数据范围" min-width="150">
          <template #default="{ row }">
            <el-tag
              size="small"
              :type="row.data_scope === 'ALL' ? 'danger' : 'primary'"
              effect="light"
              round
            >
              {{ row.data_scope_label }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column label="资产域" min-width="160" show-overflow-tooltip>
          <template #default="{ row }">
            <span :class="{ muted: row.domain_scope !== 'ALL' && !row.asset_domains.length }">
              {{ roleDomainText(row) }}
            </span>
          </template>
        </el-table-column>

        <el-table-column label="菜单 / 按钮" width="120" align="center">
          <template #default="{ row }">
            <span class="metric-pill">{{ row.menu_count }}</span>
          </template>
        </el-table-column>

        <el-table-column label="成员" width="90" align="center">
          <template #default="{ row }">
            <span class="metric-pill">{{ row.user_count }}</span>
          </template>
        </el-table-column>

        <el-table-column label="排序" width="80" align="center">
          <template #default="{ row }">
            <span class="muted">{{ row.sort }}</span>
          </template>
        </el-table-column>

        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag
              size="small"
              :type="row.status === 1 ? 'success' : 'info'"
              effect="light"
              round
            >
              {{ row.status === 1 ? '启用' : '停用' }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column label="更新时间" width="155">
          <template #default="{ row }">
            <span class="muted">{{ formatDateTime(row.updated_at) }}</span>
          </template>
        </el-table-column>

        <el-table-column label="操作" width="185" fixed="right">
          <template #default="{ row }">
            <div class="row-actions">
              <el-button link type="primary" size="small" @click="openAuthorization(row)">
                授权
              </el-button>
              <el-button
                v-if="auth.hasPerm('system:role:update')"
                link
                type="primary"
                size="small"
                @click="openEditRole(row)"
              >
                编辑
              </el-button>
              <el-button
                v-if="auth.hasPerm('system:role:delete')"
                link
                type="danger"
                size="small"
                :disabled="row.is_system"
                @click="deleteRole(row)"
              >
                删除
              </el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>

      <div class="table-foot">
        <span class="table-hint">共 {{ total }} 个角色；授权变更将通过审计日志留痕</span>
        <el-pagination
          v-model:current-page="query.page"
          v-model:page-size="query.page_size"
          :total="total"
          :page-sizes="[10, 20, 50]"
          layout="sizes, prev, pager, next"
          background
          @current-change="loadRoles"
          @size-change="handleSizeChange"
        />
      </div>
    </section>

    <el-dialog
      v-model="roleDialogVisible"
      :title="roleDialogMode === 'create' ? '新增角色' : '编辑角色'"
      width="580px"
      class="role-dialog"
      :close-on-click-modal="false"
      @closed="resetRoleForm"
    >
      <el-form
        ref="roleFormRef"
        :model="roleForm"
        :rules="roleRules"
        label-position="top"
      >
        <div class="form-grid">
          <el-form-item label="角色编码" prop="code">
            <el-input
              v-model="roleForm.code"
              maxlength="50"
              :disabled="roleDialogMode === 'edit'"
              placeholder="例如：ASSET_MANAGER"
              @input="normalizeRoleCode"
            />
          </el-form-item>
          <el-form-item label="角色名称" prop="name">
            <el-input v-model="roleForm.name" maxlength="50" placeholder="例如：资产管理员" />
          </el-form-item>
          <el-form-item label="排序">
            <el-input-number
              v-model="roleForm.sort"
              :min="0"
              :max="9999"
              controls-position="right"
            />
          </el-form-item>
          <el-form-item label="状态">
            <el-switch
              v-model="roleForm.status"
              :active-value="1"
              :inactive-value="0"
              inline-prompt
              active-text="启用"
              inactive-text="停用"
            />
          </el-form-item>
          <el-form-item v-if="roleDialogMode === 'create'" label="初始数据范围" class="span-2">
            <el-select v-model="roleForm.data_scope" placeholder="选择数据范围">
              <el-option
                v-for="scope in scopeOptions"
                :key="scope.value"
                :label="scope.label"
                :value="scope.value"
                :disabled="scope.value === 'ALL' && !auth.isSuperAdmin"
              />
            </el-select>
          </el-form-item>
          <el-form-item v-else label="数据范围" class="span-2">
            <div class="readonly-field">
              <el-tag effect="light" round>
                {{ scopeOptions.find((item) => item.value === roleForm.data_scope)?.label || roleForm.data_scope }}
              </el-tag>
              <span>数据范围请在「授权 → 数据权限」中调整</span>
            </div>
          </el-form-item>
          <el-form-item v-if="roleDialogMode === 'create'" label="可管理资产域" class="span-2">
            <div class="domain-form-block">
              <el-radio-group v-model="roleForm.domain_scope">
                <el-radio value="ALL" :disabled="!auth.isSuperAdmin">全部资产域</el-radio>
                <el-radio value="CUSTOM">指定资产域</el-radio>
              </el-radio-group>
              <el-select
                v-if="roleForm.domain_scope === 'CUSTOM'"
                v-model="roleForm.asset_domains"
                multiple
                collapse-tags
                collapse-tags-tooltip
                placeholder="未选择表示无资产域权限"
                class="domain-form-select"
              >
                <el-option
                  v-for="domain in assetDomainOptions"
                  :key="domain.value"
                  :label="domain.label"
                  :value="domain.value"
                />
              </el-select>
              <el-alert
                v-if="roleForm.domain_scope === 'CUSTOM' && !roleForm.asset_domains.length"
                title="未选择任何资产域时，该角色不能访问资产数据"
                type="warning"
                :closable="false"
                show-icon
              />
              <p class="tab-hint">一次配置，自动作用于台账、入库、领用、调拨、报废、盘点、维修、合同与报表。</p>
            </div>
          </el-form-item>
          <el-form-item v-else label="可管理资产域" class="span-2">
            <div class="readonly-field">
              <el-tag effect="light" round>
                {{ roleForm.domain_scope === 'ALL'
                  ? '全部资产域'
                  : roleForm.asset_domains.length
                    ? roleForm.asset_domains.map(domainLabel).join('、')
                    : '无资产域权限' }}
              </el-tag>
              <span>资产域请在「授权 → 数据权限」中调整</span>
            </div>
          </el-form-item>
          <el-form-item label="说明" class="span-2">
            <el-input
              v-model="roleForm.description"
              type="textarea"
              :rows="2"
              maxlength="255"
              show-word-limit
              placeholder="描述该角色的职责边界"
            />
          </el-form-item>
        </div>
      </el-form>
      <template #footer>
        <el-button @click="roleDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="roleSubmitting" @click="submitRole">
          {{ roleDialogMode === 'create' ? '创建角色' : '保存修改' }}
        </el-button>
      </template>
    </el-dialog>

    <el-drawer
      v-model="drawerVisible"
      size="820px"
      class="auth-drawer"
      :destroy-on-close="false"
    >
      <template #header>
        <div class="drawer-head">
          <div>
            <p class="drawer-eyebrow">AUTHORIZATION</p>
            <h2 class="drawer-title">
              {{ currentRole?.name || '角色授权' }}
              <code v-if="currentRole">{{ currentRole.code }}</code>
            </h2>
          </div>
          <el-tag
            v-if="currentRole"
            :type="currentRole.status === 1 ? 'success' : 'info'"
            effect="light"
            round
          >
            {{ currentRole.status === 1 ? '启用中' : '已停用' }}
          </el-tag>
        </div>
      </template>

      <div v-loading="detailLoading" class="drawer-body">
        <template v-if="currentRole">
          <el-alert
            v-if="isSuperRole"
            type="success"
            :closable="false"
            show-icon
            title="超级管理员拥有全部权限"
            description="菜单、数据范围与字段权限固定为最大集合，无需授权；成员调整受最后一名启用的超级管理员保护。"
            class="drawer-alert"
          />
          <el-alert
            v-else-if="currentRole.is_system && !auth.isSuperAdmin"
            type="warning"
            :closable="false"
            show-icon
            title="系统内置角色"
            description="系统内置角色只有超级管理员可以修改授权。"
            class="drawer-alert"
          />
          <el-alert
            v-if="currentRole.status !== 1"
            type="warning"
            :closable="false"
            show-icon
            title="角色已停用"
            description="停用角色不能新增成员；已登录用户需刷新权限后才会应用最新授权。"
            class="drawer-alert"
          />

          <el-tabs v-model="activeTab" class="auth-tabs">
            <el-tab-pane name="menu">
              <template #label>
                <span class="tab-label"><el-icon><Key /></el-icon>菜单权限</span>
              </template>
              <div v-if="isSuperRole" class="locked-note">
                超级管理员默认拥有全部菜单与按钮权限。
              </div>
              <template v-else>
                <div class="tab-toolbar">
                  <div class="toolbar-copy">
                    <strong>菜单与按钮权限</strong>
                    <span>勾选精确到按钮；保存时后端会自动补齐上级目录。</span>
                  </div>
                  <div class="toolbar-actions">
                    <el-button size="small" :disabled="!canEditMenus" @click="selectAllMenus">
                      全选
                    </el-button>
                    <el-button size="small" :disabled="!canEditMenus" @click="clearMenus">
                      清空
                    </el-button>
                  </div>
                </div>
                <div class="tree-shell menu-tree-shell">
                  <el-tree
                    ref="menuTreeRef"
                    :data="menuTreeData"
                    node-key="id"
                    :props="{ label: 'name', children: 'children' }"
                    show-checkbox
                    check-strictly
                    default-expand-all
                    :expand-on-click-node="false"
                  >
                    <template #default="{ data }">
                      <span class="menu-node">
                        <span class="menu-type" :class="`type-${data.type.toLowerCase()}`">
                          {{ menuTypeLabel(data.type) }}
                        </span>
                        <span class="menu-node-name">{{ data.name }}</span>
                        <code v-if="data.permission_code" class="menu-perm">
                          {{ data.permission_code }}
                        </code>
                        <span v-if="data.status !== 1" class="menu-off">停用</span>
                      </span>
                    </template>
                  </el-tree>
                </div>
                <p class="tab-hint">
                  勾选父级目录不会自动勾选子级；未勾选任何子级的菜单也可单独授权。
                </p>
              </template>
            </el-tab-pane>

            <el-tab-pane name="data">
              <template #label>
                <span class="tab-label"><el-icon><UserFilled /></el-icon>数据权限</span>
              </template>
              <div v-if="isSuperRole" class="locked-note">
                超级管理员固定为「全部数据」范围。
              </div>
              <template v-else>
                <div class="domain-scope-block">
                  <div class="subhead">
                    <strong>可管理资产域</strong>
                    <span>角色级配置，自动作用于全部资产业务；无需按资源重复勾选。</span>
                  </div>
                  <el-radio-group v-model="selectedDomainScope" :disabled="!canEditData">
                    <el-radio value="ALL" :disabled="!auth.isSuperAdmin">全部资产域</el-radio>
                    <el-radio value="CUSTOM">指定资产域</el-radio>
                  </el-radio-group>
                  <el-select
                    v-if="selectedDomainScope === 'CUSTOM'"
                    v-model="selectedAssetDomains"
                    multiple
                    collapse-tags
                    collapse-tags-tooltip
                    :disabled="!canEditData"
                    class="domain-select"
                    placeholder="未选择表示无资产域权限"
                  >
                    <el-option
                      v-for="domain in assetDomainOptions"
                      :key="domain.value"
                      :label="domain.label"
                      :value="domain.value"
                    />
                  </el-select>
                  <el-alert
                    v-if="noDomainWarning"
                    title="当前未授予任何资产域，该角色不能访问资产数据"
                    type="warning"
                    :closable="false"
                    show-icon
                    class="drawer-alert"
                  />
                  <p class="tab-hint">
                    多个角色的指定资产域取并集；只要任一角色指定了资产域，就按该并集限制，全部资产域不再放宽。
                  </p>
                </div>

                <div class="tab-toolbar">
                  <div class="toolbar-copy">
                    <strong>默认数据范围</strong>
                    <span>后端查询层会按所选范围强制过滤，前端不作为最终保障。</span>
                  </div>
                </div>
                <el-radio-group v-model="selectedScope" class="scope-grid">
                  <el-radio
                    v-for="scope in scopeOptions"
                    :key="scope.value"
                    :value="scope.value"
                    :disabled="!canEditData || (scope.value === 'ALL' && !auth.isSuperAdmin)"
                    border
                    class="scope-radio"
                  >
                    <span class="scope-name">{{ scope.label }}</span>
                    <small>{{ SCOPE_DESCRIPTIONS[scope.value] || '' }}</small>
                  </el-radio>
                </el-radio-group>

                <div v-if="showDeptTree" class="dept-scope-block">
                  <div class="subhead">
                    <strong>自定义部门</strong>
                    <span>仅包含勾选部门，不自动包含下级；需要下级请一并勾选。</span>
                  </div>
                  <el-alert
                    v-if="deptTreeError"
                    :title="deptTreeError"
                    type="error"
                    :closable="false"
                    show-icon
                  />
                  <div v-else v-loading="deptTreeLoading" class="tree-shell dept-scope-tree">
                    <el-tree
                      ref="dataTreeRef"
                      :data="deptTreeData"
                      node-key="id"
                      :props="deptTreeProps"
                      show-checkbox
                      check-strictly
                      default-expand-all
                      :expand-on-click-node="false"
                      empty-text="暂无部门数据"
                    />
                  </div>
                  <p class="tab-hint dept-scope-hint">
                    此处勾选仅作用于角色默认范围；下方资源开启单独配置后可各自选择部门。
                  </p>
                </div>

                <div class="resource-scope-block">
                  <div class="subhead">
                    <strong>资源数据权限</strong>
                    <span>
                      未开启单独配置的资源沿用上方角色默认范围；开启后可为该资源单独指定部门范围。
                    </span>
                  </div>
                  <el-table :data="resourceRows" size="small" border class="resource-table">
                    <el-table-column label="资源" prop="label" width="130" />
                    <el-table-column label="单独配置" width="92" align="center">
                      <template #default="{ row }">
                        <el-switch
                          :model-value="row.enabled"
                          :disabled="!canEditData"
                          @change="setResourceEnabled(row.value, $event)"
                        />
                      </template>
                    </el-table-column>
                    <el-table-column label="数据范围" min-width="150">
                      <template #default="{ row }">
                        <el-select
                          :model-value="row.data_scope"
                          :disabled="!canEditData || !row.enabled"
                          size="small"
                          class="cell-select"
                          @change="setResourceScope(row.value, $event)"
                        >
                          <el-option
                            v-for="scope in scopeOptions"
                            :key="scope.value"
                            :label="scope.label"
                            :value="scope.value"
                            :disabled="scope.value === 'ALL' && !auth.isSuperAdmin"
                          />
                        </el-select>
                      </template>
                    </el-table-column>
                    <el-table-column label="自定义部门" min-width="220">
                      <template #default="{ row }">
                        <el-tree-select
                          v-if="row.enabled && row.data_scope === 'CUSTOM'"
                          :model-value="row.dept_ids"
                          :data="deptTreeData"
                          :props="deptTreeSelectProps"
                          node-key="id"
                          multiple
                          show-checkbox
                          check-strictly
                          collapse-tags
                          collapse-tags-tooltip
                          :render-after-expand="false"
                          :disabled="!canEditData || Boolean(deptTreeError)"
                          size="small"
                          class="cell-select"
                          placeholder="选择部门"
                          @change="setResourceDepts(row.value, $event)"
                        />
                        <span v-else class="muted">
                          {{ row.enabled ? '沿用所选范围' : '未单独配置' }}
                        </span>
                      </template>
                    </el-table-column>
                  </el-table>
                  <p class="tab-hint">
                    多个角色之间数据范围取最宽；「仅本人」在所有资源统一表示只看本人创建、持有或申请的数据。
                  </p>
                </div>
              </template>
            </el-tab-pane>

            <el-tab-pane name="field">
              <template #label>
                <span class="tab-label"><el-icon><Lock /></el-icon>字段权限</span>
              </template>
              <div v-if="isSuperRole" class="locked-note">
                超级管理员默认拥有全部字段的查看与编辑权限。
              </div>
              <template v-else>
                <div class="tab-toolbar">
                  <div class="toolbar-copy">
                    <strong>字段级权限</strong>
                    <span>默认全部可见可编辑；只有被关闭的字段才会作为限制项保存。</span>
                  </div>
                </div>
                <div
                  v-for="(fields, resource) in fieldCatalog"
                  :key="resource"
                  class="field-group"
                >
                  <header class="field-group-head">
                    <h3>{{ resourceLabel(resource) }}</h3>
                    <span>{{ fields.length }} 个字段</span>
                  </header>
                  <div class="field-table-head">
                    <span>字段</span>
                    <span>可查看</span>
                    <span>可编辑</span>
                  </div>
                  <div v-for="field in fields" :key="field.field" class="field-row">
                    <span class="field-name">
                      {{ field.label }}
                      <code>{{ field.field }}</code>
                    </span>
                    <el-switch
                      :model-value="fieldState[resource]?.[field.field]?.can_view ?? true"
                      :disabled="!canEditFields"
                      @change="setFieldView(resource, field.field, $event)"
                    />
                    <el-switch
                      :model-value="fieldState[resource]?.[field.field]?.can_edit ?? true"
                      :disabled="!canEditFields"
                      @change="setFieldEdit(resource, field.field, $event)"
                    />
                  </div>
                </div>
                <p class="tab-hint">
                  关闭「可查看」会同时关闭「可编辑」；多角色之间按并集生效。
                </p>
              </template>
            </el-tab-pane>

            <el-tab-pane name="member">
              <template #label>
                <span class="tab-label"><el-icon><UserFilled /></el-icon>角色成员</span>
              </template>
              <div class="tab-toolbar">
                <div class="toolbar-copy">
                  <strong>成员分配</strong>
                  <span>
                    已选 {{ memberIds.length }} 人<template v-if="memberPendingText">（{{ memberPendingText }}，未保存）</template>；成员变更在保存后立即影响后端鉴权。
                  </span>
                </div>
                <el-tag v-if="memberPendingText" type="warning" effect="light" round>
                  待保存
                </el-tag>
              </div>
              <el-alert
                v-if="isSuperRole"
                type="warning"
                :closable="false"
                show-icon
                title="高权限角色"
                description="只有超级管理员可以调整超级管理员成员，且系统必须保留至少一名启用的超级管理员。"
                class="member-alert"
              />

              <section class="member-panel">
                <div class="panel-head">
                  <div class="panel-title">
                    <strong>查找并添加成员</strong>
                    <span>按姓名、用户名或工号搜索，列表直接标注是否已在角色内</span>
                  </div>
                  <el-radio-group
                    v-model="memberFilter"
                    size="small"
                    :disabled="!memberResults.length"
                  >
                    <el-radio-button value="all">全部</el-radio-button>
                    <el-radio-button value="out">未加入</el-radio-button>
                    <el-radio-button value="in">已加入</el-radio-button>
                  </el-radio-group>
                </div>
                <div class="member-search-row">
                  <el-input
                    v-model="memberKeyword"
                    clearable
                    :prefix-icon="Search"
                    :disabled="!canAssignUsers"
                    placeholder="搜索姓名、用户名或工号，输入后自动检索"
                  />
                  <el-button
                    :loading="memberSearchLoading"
                    :disabled="!canAssignUsers"
                    @click="searchMemberOptions(memberKeyword)"
                  >
                    搜索
                  </el-button>
                  <el-button
                    type="primary"
                    plain
                    :disabled="!canEditMembers || !filteredMemberResults.length"
                    @click="bulkAddVisible"
                  >
                    加入当前结果
                  </el-button>
                </div>
                <el-table
                  v-loading="memberSearchLoading"
                  :data="filteredMemberResults"
                  size="small"
                  height="236"
                  class="member-table"
                  empty-text="没有匹配的人员"
                >
                  <el-table-column label="人员" min-width="180">
                    <template #default="{ row }">
                      <div class="member-cell">
                        <span class="member-avatar">{{
                          initials(row.real_name.slice(0, 2))
                        }}</span>
                        <div>
                          <strong>{{ row.real_name }}</strong>
                          <small>@{{ row.username }}</small>
                        </div>
                      </div>
                    </template>
                  </el-table-column>
                  <el-table-column label="部门" min-width="160" show-overflow-tooltip>
                    <template #default="{ row }">{{ row.dept_name || '未分配部门' }}</template>
                  </el-table-column>
                  <el-table-column label="角色状态" width="96" align="center">
                    <template #default="{ row }">
                      <el-tag
                        v-if="memberSet.has(row.id)"
                        type="success"
                        size="small"
                        effect="light"
                      >
                        已加入
                      </el-tag>
                      <el-tag v-else size="small" type="info" effect="plain">未加入</el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column label="操作" width="78" align="right">
                    <template #default="{ row }">
                      <el-button
                        v-if="memberSet.has(row.id)"
                        link
                        type="danger"
                        :disabled="!canEditMembers"
                        @click="removeMember(row.id)"
                      >
                        移除
                      </el-button>
                      <el-button
                        v-else
                        link
                        type="primary"
                        :disabled="!canEditMembers"
                        @click="addMember(row)"
                      >
                        加入
                      </el-button>
                    </template>
                  </el-table-column>
                </el-table>
                <p class="panel-hint">
                  搜索最多返回 50 名启用用户；「加入当前结果」会批量加入当前筛选下未加入的人员。
                </p>
              </section>

              <section class="member-panel">
                <div class="panel-head">
                  <div class="panel-title">
                    <strong>已选成员</strong>
                    <span>
                      共 {{ memberIds.length }} 人<template v-if="selectedMemberKeyword.trim()"
                        >，筛选出 {{ filteredSelectedMembers.length }} 人</template
                      >
                    </span>
                  </div>
                  <el-input
                    v-model="selectedMemberKeyword"
                    size="small"
                    clearable
                    :prefix-icon="Search"
                    placeholder="在已选成员中筛选"
                    class="selected-filter"
                  />
                </div>
                <el-table
                  :data="pagedSelectedMembers"
                  size="small"
                  height="260"
                  empty-text="尚未选择成员"
                >
                  <el-table-column label="人员" min-width="180">
                    <template #default="{ row }">
                      <div class="member-cell">
                        <span class="member-avatar">{{
                          initials(row.real_name.slice(0, 2))
                        }}</span>
                        <div>
                          <strong>{{ row.real_name }}</strong>
                          <small>@{{ row.username }}</small>
                        </div>
                      </div>
                    </template>
                  </el-table-column>
                  <el-table-column label="部门" min-width="160" show-overflow-tooltip>
                    <template #default="{ row }">{{ row.dept_name || '未分配部门' }}</template>
                  </el-table-column>
                  <el-table-column label="账号" width="80" align="center">
                    <template #default="{ row }">
                      <el-tag
                        v-if="row.status === 1"
                        size="small"
                        type="success"
                        effect="plain"
                      >
                        启用
                      </el-tag>
                      <el-tag v-else size="small" type="danger" effect="plain">停用</el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column label="操作" width="78" align="right">
                    <template #default="{ row }">
                      <el-button
                        link
                        type="danger"
                        :disabled="!canEditMembers"
                        @click="removeMember(row.id)"
                      >
                        移除
                      </el-button>
                    </template>
                  </el-table-column>
                </el-table>
                <div class="member-pager">
                  <span>
                    第 {{ selectedMemberPage }} /
                    {{ Math.max(1, Math.ceil(filteredSelectedMembers.length / selectedMemberPageSize)) }}
                    页
                  </span>
                  <el-pagination
                    v-model:current-page="selectedMemberPage"
                    :page-size="selectedMemberPageSize"
                    :total="filteredSelectedMembers.length"
                    layout="prev, pager, next"
                    small
                    background
                  />
                </div>
              </section>
              <p v-if="!canEditMembers" class="empty-note">
                当前账号没有成员分配权限，仅可查看。
              </p>
            </el-tab-pane>
          </el-tabs>
        </template>
        <div v-else-if="!detailLoading" class="empty-note">请选择角色</div>
      </div>

      <template #footer>
        <div class="drawer-footer">
          <span class="footer-hint">每个页签独立保存，版本冲突会自动拦截</span>
          <div>
            <el-button @click="drawerVisible = false">关闭</el-button>
            <el-button
              type="primary"
              :loading="saving"
              :disabled="!canSaveCurrent"
              @click="saveCurrent"
            >
              {{ saveLabel }}
            </el-button>
          </div>
        </div>
      </template>
    </el-drawer>
  </div>
</template>

<style scoped>
.role-page {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.page-actions {
  display: flex;
  gap: 10px;
}

.role-panel {
  padding: 22px;
}

.role-summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  margin-bottom: 18px;
  padding: 15px 17px;
  border: 1px solid var(--border);
  border-radius: 14px;
  background:
    radial-gradient(320px 120px at 8% 0%, color-mix(in srgb, var(--brand) 8%, transparent), transparent 70%),
    var(--surface-muted);
}

.summary-main {
  display: flex;
  align-items: center;
  gap: 12px;
}

.summary-icon {
  display: grid;
  place-items: center;
  width: 38px;
  height: 38px;
  border-radius: 11px;
  background: var(--gradient-brand);
  color: var(--on-brand);
  box-shadow: 0 10px 22px -14px var(--brand-glow);
}

.summary-label {
  color: var(--text-3);
  font-size: 10.5px;
  letter-spacing: 0.08em;
}

.summary-value {
  color: var(--text-1);
  font-family: var(--font-number);
  font-size: 24px;
  font-weight: 700;
  line-height: 1.15;
}

.summary-note {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  max-width: 440px;
  color: var(--text-3);
  font-size: 11.5px;
  line-height: 1.6;
}

.summary-note .el-icon {
  flex-shrink: 0;
  margin-top: 2px;
  color: var(--brand);
}

.role-filters {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 16px;
}

.filter-keyword {
  width: 230px;
}

.filter-status {
  width: 120px;
}

.role-cell {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.role-mark {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  flex-shrink: 0;
  border-radius: 10px;
  background: var(--brand-soft);
  color: var(--brand);
}

.role-mark.system {
  background: rgba(245, 158, 11, 0.12);
  color: #d97706;
}

.role-identity {
  display: flex;
  flex-direction: column;
  min-width: 0;
  line-height: 1.35;
}

.role-name {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--text-1);
  font-size: 13px;
  font-weight: 600;
}

.role-code {
  color: var(--text-3);
  font-family: var(--font-number);
  font-size: 10px;
  letter-spacing: 0.05em;
}

.metric-pill {
  display: inline-block;
  min-width: 30px;
  padding: 2px 8px;
  border-radius: 999px;
  background: var(--surface-muted);
  color: var(--text-2);
  font-family: var(--font-number);
  font-size: 11.5px;
  text-align: center;
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

.span-2 {
  grid-column: span 2;
}

.form-grid :deep(.el-select),
.form-grid :deep(.el-input-number) {
  width: 100%;
}

.readonly-field {
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--text-3);
  font-size: 11.5px;
}

/* Drawer */
.drawer-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  width: 100%;
  padding-right: 8px;
}

.drawer-eyebrow {
  color: var(--text-3);
  font-size: 9.5px;
  font-weight: 700;
  letter-spacing: 0.2em;
}

.drawer-title {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 3px;
  color: var(--text-1);
  font-size: 18px;
  font-weight: 650;
  letter-spacing: -0.015em;
}

.drawer-title code {
  padding: 2px 7px;
  border-radius: 6px;
  background: var(--surface-muted);
  color: var(--text-3);
  font-family: var(--font-number);
  font-size: 10px;
  font-weight: 500;
}

.drawer-body {
  min-height: 280px;
}

.drawer-alert {
  margin-bottom: 14px;
}

.auth-tabs :deep(.el-tabs__header) {
  margin-bottom: 16px;
}

.tab-label {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.locked-note {
  padding: 30px 20px;
  border: 1px dashed var(--border-strong);
  border-radius: 14px;
  background: var(--surface-muted);
  color: var(--text-3);
  font-size: 12.5px;
  text-align: center;
}

.tab-toolbar {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
  margin-bottom: 12px;
}

.toolbar-copy {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.toolbar-copy strong {
  color: var(--text-1);
  font-size: 13px;
  font-weight: 600;
}

.toolbar-copy span {
  color: var(--text-3);
  font-size: 11.5px;
  line-height: 1.55;
}

.toolbar-actions {
  display: flex;
  gap: 6px;
  flex-shrink: 0;
}

.tree-shell {
  max-height: 380px;
  overflow: auto;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: 13px;
  background: var(--surface-muted);
}

.menu-tree-shell {
  max-height: 430px;
}

.tree-shell :deep(.el-tree) {
  background: transparent;
}

.tree-shell :deep(.el-tree-node__content) {
  height: 34px;
  border-radius: 8px;
}

.menu-node {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  min-width: 0;
  font-size: 12.5px;
}

.menu-type {
  flex-shrink: 0;
  padding: 1px 6px;
  border-radius: 5px;
  font-size: 9.5px;
  line-height: 16px;
}

.type-dir {
  background: rgba(99, 102, 241, 0.12);
  color: #6366f1;
}

.type-menu {
  background: var(--brand-soft);
  color: var(--brand);
}

.type-button {
  background: rgba(16, 185, 129, 0.12);
  color: #059669;
}

.menu-node-name {
  color: var(--text-1);
}

.menu-perm {
  color: var(--text-3);
  font-size: 9.5px;
}

.menu-off {
  color: var(--danger);
  font-size: 9.5px;
}

.tab-hint {
  margin-top: 10px;
  color: var(--text-3);
  font-size: 11px;
  line-height: 1.6;
}

.scope-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  width: 100%;
}

.scope-radio {
  display: flex;
  align-items: flex-start;
  width: 100%;
  height: auto;
  min-height: 58px;
  margin: 0 !important;
  padding: 11px 13px;
  border-radius: 12px;
  background: var(--surface-muted);
}

.scope-radio :deep(.el-radio__label) {
  display: flex;
  flex-direction: column;
  gap: 2px;
  white-space: normal;
}

.scope-name {
  color: var(--text-1);
  font-size: 12.5px;
  font-weight: 600;
}

.scope-radio small {
  color: var(--text-3);
  font-size: 10.5px;
  line-height: 1.5;
}

.domain-scope-block {
  margin-bottom: 16px;
  padding-bottom: 14px;
  border-bottom: 1px dashed var(--border);
}

.dept-scope-block {
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px dashed var(--border);
}

.subhead {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 9px;
}

.subhead strong {
  color: var(--text-1);
  font-size: 12.5px;
  font-weight: 600;
}

.subhead span {
  color: var(--text-3);
  font-size: 10.5px;
}

.dept-scope-tree {
  max-height: 280px;
}

.dept-scope-hint {
  margin-top: 8px;
}

.domain-select {
  width: 100%;
  margin-top: 10px;
}

.domain-form-block {
  display: flex;
  flex-direction: column;
  gap: 4px;
  width: 100%;
}

.domain-form-select {
  width: 100%;
  margin-top: 8px;
}

.resource-scope-block {
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px dashed var(--border);
}

.resource-table {
  width: 100%;
  border-radius: 12px;
}

.resource-table :deep(.el-table__cell) {
  padding: 7px 0;
}

.cell-select {
  width: 100%;
}

.field-group {
  margin-bottom: 16px;
  border: 1px solid var(--border);
  border-radius: 13px;
  overflow: hidden;
}

.field-group-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 11px 14px;
  background: var(--surface-muted);
}

.field-group-head h3 {
  color: var(--text-1);
  font-size: 12.5px;
  font-weight: 600;
}

.field-group-head span {
  color: var(--text-3);
  font-size: 10.5px;
}

.field-table-head,
.field-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 82px 82px;
  align-items: center;
  gap: 8px;
  padding: 9px 14px;
}

.field-table-head {
  color: var(--text-3);
  font-size: 10.5px;
  letter-spacing: 0.04em;
  border-bottom: 1px solid var(--border);
}

.field-table-head span:not(:first-child) {
  text-align: center;
}

.field-row {
  border-bottom: 1px dashed var(--border);
}

.field-row:last-child {
  border-bottom: none;
}

.field-row :deep(.el-switch) {
  justify-self: center;
}

.field-name {
  display: flex;
  align-items: baseline;
  gap: 8px;
  min-width: 0;
  color: var(--text-1);
  font-size: 12.5px;
}

.field-name code {
  color: var(--text-3);
  font-size: 9.5px;
}

.member-alert {
  margin-bottom: 10px;
}

.member-panel {
  margin-top: 14px;
  padding: 14px;
  border: 1px solid var(--border);
  border-radius: 14px;
  background: var(--surface-muted);
}

.member-panel + .member-panel {
  margin-top: 12px;
}

.panel-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
  margin-bottom: 10px;
}

.panel-title {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.panel-title strong {
  color: var(--text-1);
  font-size: 13px;
  font-weight: 600;
}

.panel-title span {
  color: var(--text-3);
  font-size: 11.5px;
  line-height: 1.5;
}

.member-search-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}

.member-search-row :deep(.el-input) {
  flex: 1;
  min-width: 0;
}

.member-search-row :deep(.el-button) {
  flex-shrink: 0;
  margin-left: 0;
}

.member-table :deep(.el-table__inner-wrapper) {
  border-radius: 10px;
}

.member-cell {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.member-cell div {
  display: flex;
  flex-direction: column;
  min-width: 0;
  line-height: 1.35;
}

.member-cell strong {
  overflow: hidden;
  color: var(--text-1);
  font-size: 12.5px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.member-cell small {
  color: var(--text-3);
  font-size: 10.5px;
}

.member-avatar {
  flex-shrink: 0;
  display: grid;
  place-items: center;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: var(--gradient-brand);
  color: var(--on-brand);
  font-size: 9.5px;
  font-weight: 700;
}

.panel-hint {
  margin: 8px 0 0;
  color: var(--text-3);
  font-size: 10.5px;
  line-height: 1.5;
}

.selected-filter {
  flex-shrink: 0;
  width: 200px;
}

.member-pager {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 10px;
  color: var(--text-3);
  font-size: 11px;
}

.member-pager :deep(.el-pagination) {
  padding: 0;
}

.empty-note {
  padding: 20px;
  color: var(--text-3);
  font-size: 12px;
  text-align: center;
}

.drawer-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  width: 100%;
  padding: 0 4px;
}

.footer-hint {
  color: var(--text-3);
  font-size: 10.5px;
}

:deep(.auth-drawer) {
  max-width: 96vw;
}

:deep(.role-dialog) {
  max-width: 94vw;
}

@media (max-width: 860px) {
  .role-summary {
    align-items: flex-start;
    flex-direction: column;
  }

  .scope-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 640px) {
  .role-panel {
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

  .drawer-footer {
    align-items: flex-start;
    flex-direction: column;
  }

  .field-table-head,
  .field-row {
    grid-template-columns: minmax(0, 1fr) 64px 64px;
  }
}
</style>
