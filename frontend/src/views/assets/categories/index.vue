<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
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
  Grid,
  MoreFilled,
  Plus,
  Refresh,
  Search,
  Setting,
  Upload,
} from '@element-plus/icons-vue'

import { assetApi } from '@/api/assets'
import ImportDialog from '@/components/ImportDialog.vue'
import { useAuthStore } from '@/stores/auth'
import type {
  AssetCategory,
  AssetCategoryType,
  AssetDomain,
  AssetDomainItem,
  AssetDomainPayload,
  AssetFieldType,
  AssetModel,
  CategoryField,
  CategoryFieldPayload,
  ModelPayload,
} from '@/types/asset'
import {
  CATEGORY_TYPE_LABELS,
  FIELD_TYPE_LABELS,
} from '@/types/asset'

const auth = useAuthStore()
const domains = ref<AssetDomainItem[]>([])

const treeRef = ref<InstanceType<typeof ElTree>>()
const categories = ref<AssetCategory[]>([])
const treeLoading = ref(false)
const treeKeyword = ref('')
const selectedId = ref<number | null>(null)
const treeProps = { label: 'name', children: 'children' }

const models = ref<AssetModel[]>([])
const modelLoading = ref(false)
const modelTotal = ref(0)
const modelQuery = reactive({
  page: 1,
  page_size: 10,
  keyword: '',
  status: undefined as number | undefined,
})
let modelRequestSeq = 0

const canCreateCategory = computed(() => auth.hasPerm('asset:category:create'))
const canUpdateCategory = computed(() => auth.hasPerm('asset:category:update'))
const canDeleteCategory = computed(() => auth.hasPerm('asset:category:delete'))
const canManageModel = computed(
  () =>
    auth.hasPerm('asset:model:create') ||
    auth.hasPerm('asset:model:update') ||
    auth.hasPerm('asset:model:delete'),
)

const domainDialogVisible = ref(false)
const domainFormVisible = ref(false)
const domainFormMode = ref<'create' | 'edit'>('create')
const domainSubmitting = ref(false)
const domainFormRef = ref<FormInstance>()
const domainForm = reactive({
  id: 0,
  code: '',
  name: '',
  sort: 100,
})
const domainRules: FormRules = {
  code: [
    { required: true, message: '请输入资产域编码', trigger: 'blur' },
    {
      pattern: /^[A-Z][A-Z0-9_]{0,19}$/,
      message: '1-20 位大写字母、数字或下划线，且以字母开头',
      trigger: 'blur',
    },
  ],
  name: [{ required: true, message: '请输入资产域名称', trigger: 'blur' }],
}

async function loadDomains(): Promise<void> {
  domains.value = await assetApi.listDomains()
}

function openCreateDomain(): void {
  domainFormMode.value = 'create'
  Object.assign(domainForm, { id: 0, code: '', name: '', sort: 100 })
  domainFormVisible.value = true
  void nextTick(() => domainFormRef.value?.clearValidate())
}

function openEditDomain(domain: AssetDomainItem): void {
  domainFormMode.value = 'edit'
  Object.assign(domainForm, {
    id: domain.id,
    code: domain.code,
    name: domain.name,
    sort: domain.sort,
  })
  domainFormVisible.value = true
  void nextTick(() => domainFormRef.value?.clearValidate())
}

async function submitDomain(): Promise<void> {
  const valid = await domainFormRef.value?.validate().catch(() => false)
  if (!valid || domainSubmitting.value) return
  domainSubmitting.value = true
  try {
    if (domainFormMode.value === 'create') {
      const payload: AssetDomainPayload = {
        code: domainForm.code.trim().toUpperCase(),
        name: domainForm.name.trim(),
        sort: domainForm.sort,
      }
      await assetApi.createDomain(payload)
      ElMessage.success('资产域创建成功')
    } else {
      await assetApi.updateDomain(domainForm.id, {
        name: domainForm.name.trim(),
        sort: domainForm.sort,
      })
      ElMessage.success('资产域已更新')
    }
    domainFormVisible.value = false
    await loadDomains()
  } finally {
    domainSubmitting.value = false
  }
}

async function deleteDomain(domain: AssetDomainItem): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `确定删除资产域「${domain.name}（${domain.code}）」吗？被分类或角色引用的资产域不能删除。`,
      '删除资产域',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  await assetApi.deleteDomain(domain.id)
  ElMessage.success('资产域已删除')
  await loadDomains()
}

function flattenCategories(nodes: AssetCategory[]): AssetCategory[] {
  return nodes.flatMap((node) => [node, ...flattenCategories(node.children ?? [])])
}

function findCategory(nodes: AssetCategory[], id: number): AssetCategory | null {
  for (const node of nodes) {
    if (node.id === id) return node
    const found = findCategory(node.children ?? [], id)
    if (found) return found
  }
  return null
}

const totalCategoryCount = computed(() => flattenCategories(categories.value).length)
const selectedCategory = computed(() =>
  selectedId.value === null ? null : findCategory(categories.value, selectedId.value),
)
const selectedCategoryName = computed(() => selectedCategory.value?.name ?? '全部分类')

function filterTreeNode(value: string, data: Record<string, unknown>): boolean {
  if (!value) return true
  const keyword = value.trim().toLowerCase()
  return (
    String(data.name ?? '').toLowerCase().includes(keyword) ||
    String(data.code ?? '').toLowerCase().includes(keyword)
  )
}

watch(treeKeyword, (value) => {
  treeRef.value?.filter(value)
})

function categoryTypeLabel(type: AssetCategoryType): string {
  return CATEGORY_TYPE_LABELS[type] ?? type
}

function assetDomainLabel(domain: string): string {
  return domains.value.find((item) => item.code === domain)?.name ?? domain
}

function assetDomainTag(domain: string): 'warning' | 'info' {
  return domain === 'ADMIN' ? 'warning' : 'info'
}

function categoryTypeTag(type: AssetCategoryType): 'primary' | 'success' | 'warning' | 'info' {
  if (type === 'HARDWARE') return 'primary'
  if (type === 'SOFTWARE') return 'success'
  if (type === 'ACCESSORY') return 'warning'
  return 'info'
}

async function loadTree(): Promise<void> {
  treeLoading.value = true
  try {
    categories.value = await assetApi.categoryTree()
    await nextTick()
    if (selectedId.value !== null) {
      if (!findCategory(categories.value, selectedId.value)) {
        selectedId.value = null
      } else {
        treeRef.value?.setCurrentKey(selectedId.value)
      }
    }
  } finally {
    treeLoading.value = false
  }
}

async function loadModels(): Promise<void> {
  const seq = ++modelRequestSeq
  modelLoading.value = true
  try {
    const data = await assetApi.listModels({
      page: modelQuery.page,
      page_size: modelQuery.page_size,
      category_id: selectedId.value ?? undefined,
      include_child: true,
      keyword: modelQuery.keyword.trim() || undefined,
      status: modelQuery.status,
    })
    if (seq !== modelRequestSeq) return
    models.value = data.items
    modelTotal.value = data.total
  } finally {
    if (seq === modelRequestSeq) modelLoading.value = false
  }
}

async function refreshAll(): Promise<void> {
  await Promise.all([loadDomains(), loadTree(), loadModels()])
}

const importVisible = ref(false)

function handleImported(): void {
  void loadTree()
}

function selectAllCategories(): void {
  selectedId.value = null
  treeRef.value?.setCurrentKey(null)
  modelQuery.page = 1
  void loadModels()
}

function handleCategoryClick(data: AssetCategory): void {
  if (selectedId.value === data.id) return
  selectedId.value = data.id
  modelQuery.page = 1
  void loadModels()
}

function handleModelSearch(): void {
  modelQuery.page = 1
  void loadModels()
}

function resetModelFilters(): void {
  modelQuery.keyword = ''
  modelQuery.status = undefined
  modelQuery.page = 1
  void loadModels()
}

function handleModelSizeChange(): void {
  modelQuery.page = 1
  void loadModels()
}

async function handleModelCommand(command: string, model: AssetModel): Promise<void> {
  if (command === 'edit') {
    openEditModel(model)
    return
  }
  if (command === 'delete') {
    await deleteModel(model)
  }
}

async function deleteModel(model: AssetModel): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `确定删除型号「${model.name}」吗？已被资产引用的型号无法删除。`,
      '删除型号',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  await assetApi.deleteModel(model.id)
  ElMessage.success('型号已删除')
  await Promise.all([loadTree(), loadModels()])
}

/* ---------------- 分类表单 ---------------- */

const categoryDialogVisible = ref(false)
const categoryDialogMode = ref<'create' | 'edit'>('create')
const categorySubmitting = ref(false)
const categoryFormRef = ref<FormInstance>()

interface CategoryFormState {
  id: number | null
  parent_id: number | null
  name: string
  code: string
  category_type: AssetCategoryType
  asset_domain: AssetDomain
  sort: number
  safety_stock: number
  status: number
  remark: string
  version: number
}

const categoryForm = reactive<CategoryFormState>({
  id: null,
  parent_id: null,
  name: '',
  code: '',
  category_type: 'HARDWARE',
  asset_domain: '',
  sort: 0,
  safety_stock: 0,
  status: 1,
  remark: '',
  version: 1,
})

const categoryRules: FormRules = {
  name: [
    { required: true, message: '请输入分类名称', trigger: 'blur' },
    { max: 100, message: '分类名称不能超过 100 个字符', trigger: 'blur' },
  ],
  code: [
    { required: true, message: '请输入分类编码', trigger: 'blur' },
    {
      pattern: /^[A-Za-z0-9][A-Za-z0-9_-]{1,49}$/,
      message: '2-50 位字母、数字、下划线或短横线',
      trigger: 'blur',
    },
  ],
  category_type: [{ required: true, message: '请选择资产类型', trigger: 'change' }],
  asset_domain: [{ required: true, message: '请选择资产域', trigger: 'change' }],
}

const parentTreeData = computed(() => {
  const excludedId = categoryDialogMode.value === 'edit' ? categoryForm.id : null
  function prune(nodes: AssetCategory[]): AssetCategory[] {
    if (excludedId === null) return nodes
    return nodes
      .filter((node) => node.id !== excludedId)
      .map((node) => ({ ...node, children: prune(node.children ?? []) }))
  }
  return prune(categories.value)
})

const categoryTypeLocked = computed(() => categoryForm.parent_id !== null)
const categoryDomainLocked = computed(
  () =>
    categoryForm.parent_id !== null ||
    (categoryDialogMode.value === 'edit' && !auth.isSuperAdmin),
)

watch(
  () => categoryForm.parent_id,
  (parentId) => {
    if (parentId === null) return
    const parent = findCategory(categories.value, parentId)
    if (!parent) return
    categoryForm.category_type = parent.category_type
    categoryForm.asset_domain = parent.asset_domain
  },
)

function resetCategoryForm(): void {
  categoryForm.id = null
  categoryForm.parent_id = null
  categoryForm.name = ''
  categoryForm.code = ''
  categoryForm.category_type = 'HARDWARE'
  categoryForm.asset_domain = domains.value[0]?.code ?? ''
  categoryForm.sort = 0
  categoryForm.safety_stock = 0
  categoryForm.status = 1
  categoryForm.remark = ''
  categoryForm.version = 1
  categoryFormRef.value?.clearValidate()
}

function openCreateCategory(parent: AssetCategory | null = null): void {
  resetCategoryForm()
  categoryDialogMode.value = 'create'
  if (parent) {
    categoryForm.parent_id = parent.id
    categoryForm.category_type = parent.category_type
    categoryForm.asset_domain = parent.asset_domain
  }
  categoryDialogVisible.value = true
}

function openEditCategory(category: AssetCategory): void {
  resetCategoryForm()
  categoryDialogMode.value = 'edit'
  categoryForm.id = category.id
  categoryForm.parent_id = category.parent_id
  categoryForm.name = category.name
  categoryForm.code = category.code
  categoryForm.category_type = category.category_type
  categoryForm.asset_domain = category.asset_domain
  categoryForm.sort = category.sort
  categoryForm.safety_stock = category.safety_stock
  categoryForm.status = category.status
  categoryForm.remark = category.remark ?? ''
  categoryForm.version = category.version
  categoryDialogVisible.value = true
}

function resolveCategoryType(): AssetCategoryType {
  if (categoryForm.parent_id === null) return categoryForm.category_type
  const parent = findCategory(categories.value, categoryForm.parent_id)
  return parent?.category_type ?? categoryForm.category_type
}

async function submitCategory(): Promise<void> {
  const valid = await categoryFormRef.value?.validate().catch(() => false)
  if (!valid) return
  categorySubmitting.value = true
  try {
    const payload = {
      parent_id: categoryForm.parent_id,
      name: categoryForm.name.trim(),
      code: categoryForm.code.trim().toUpperCase(),
      category_type: resolveCategoryType(),
      asset_domain: categoryForm.parent_id === null ? categoryForm.asset_domain : null,
      sort: categoryForm.sort,
      safety_stock: categoryForm.safety_stock,
      status: categoryForm.status,
      remark: categoryForm.remark.trim() || null,
    }
    let targetId = categoryForm.id
    if (categoryDialogMode.value === 'create') {
      const created = await assetApi.createCategory(payload)
      targetId = created.id
      ElMessage.success('分类创建成功')
    } else if (categoryForm.id !== null) {
      const original = findCategory(categories.value, categoryForm.id)
      const parent =
        categoryForm.parent_id === null
          ? null
          : findCategory(categories.value, categoryForm.parent_id)
      const targetDomain = parent?.asset_domain ?? categoryForm.asset_domain
      let confirmDomainChange = false
      if (original && targetDomain !== original.asset_domain) {
        if (!auth.isSuperAdmin) {
          ElMessage.warning('仅超级管理员可跨域调整分类')
          return
        }
        try {
          await ElMessageBox.confirm(
            `分类「${original.name}」将从「${assetDomainLabel(original.asset_domain)}」调整到「${assetDomainLabel(targetDomain)}」，全部子分类同步变更并写入专项审计。确定继续吗？`,
            '跨域调整分类',
            { type: 'warning', confirmButtonText: '确认调整', cancelButtonText: '取消' },
          )
          confirmDomainChange = true
        } catch {
          return
        }
      }
      await assetApi.updateCategory(categoryForm.id, {
        ...payload,
        version: categoryForm.version,
        confirm_domain_change: confirmDomainChange,
      })
      ElMessage.success('分类更新成功')
    }
    categoryDialogVisible.value = false
    selectedId.value = targetId
    await Promise.all([loadTree(), loadModels()])
  } finally {
    categorySubmitting.value = false
  }
}

async function deleteCategory(category: AssetCategory): Promise<void> {
  const notes: string[] = []
  if (category.children.length) notes.push(`${category.children.length} 个下级分类`)
  if (category.model_count) notes.push(`${category.model_count} 个型号`)
  if (category.asset_count) notes.push(`${category.asset_count} 台资产`)
  const suffix = notes.length ? `该分类下仍有 ${notes.join('、')}，需先处理。` : '删除后不可恢复。'
  try {
    await ElMessageBox.confirm(`确定删除分类「${category.name}」吗？${suffix}`, '删除分类', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  await assetApi.deleteCategory(category.id)
  ElMessage.success('分类已删除')
  if (selectedId.value === category.id) selectedId.value = null
  await Promise.all([loadTree(), loadModels()])
}

async function handleCategoryCommand(
  command: string,
  category: AssetCategory,
): Promise<void> {
  if (command === 'create') openCreateCategory(category)
  else if (command === 'edit') openEditCategory(category)
  else if (command === 'fields') openFields(category)
  else if (command === 'delete') await deleteCategory(category)
}

/* ---------------- 自定义字段 ---------------- */

const fieldsDrawerVisible = ref(false)
const fieldCategoryId = ref<number | null>(null)
const fieldCategory = computed(() =>
  fieldCategoryId.value === null ? null : findCategory(categories.value, fieldCategoryId.value),
)
const fieldDefs = computed<CategoryField[]>(() => fieldCategory.value?.field_defs ?? [])
const fieldAssetsLocked = computed(() => (fieldCategory.value?.asset_count ?? 0) > 0)

function openFields(category: AssetCategory): void {
  fieldCategoryId.value = category.id
  fieldsDrawerVisible.value = true
}

const fieldDialogVisible = ref(false)
const fieldDialogMode = ref<'create' | 'edit'>('create')
const fieldSubmitting = ref(false)
const fieldFormRef = ref<FormInstance>()

interface FieldFormState {
  id: number | null
  name: string
  field_key: string
  field_type: AssetFieldType
  required: boolean
  optionsText: string
  sort: number
  status: number
  remark: string
  version: number
}

const fieldForm = reactive<FieldFormState>({
  id: null,
  name: '',
  field_key: '',
  field_type: 'TEXT',
  required: false,
  optionsText: '',
  sort: 0,
  status: 1,
  remark: '',
  version: 1,
})

const fieldRules: FormRules = {
  name: [{ required: true, message: '请输入字段名称', trigger: 'blur' }],
  field_key: [
    { required: true, message: '请输入字段标识', trigger: 'blur' },
    {
      pattern: /^[a-z][a-z0-9_]{1,49}$/,
      message: '小写字母开头的 2-50 位小写字母、数字或下划线',
      trigger: 'blur',
    },
  ],
}

function resetFieldForm(): void {
  fieldForm.id = null
  fieldForm.name = ''
  fieldForm.field_key = ''
  fieldForm.field_type = 'TEXT'
  fieldForm.required = false
  fieldForm.optionsText = ''
  fieldForm.sort = 0
  fieldForm.status = 1
  fieldForm.remark = ''
  fieldForm.version = 1
  fieldFormRef.value?.clearValidate()
}

function openCreateField(): void {
  resetFieldForm()
  fieldDialogMode.value = 'create'
  fieldForm.sort = fieldDefs.value.length * 10 + 10
  fieldDialogVisible.value = true
}

function openEditField(field: CategoryField): void {
  resetFieldForm()
  fieldDialogMode.value = 'edit'
  fieldForm.id = field.id
  fieldForm.name = field.name
  fieldForm.field_key = field.field_key
  fieldForm.field_type = field.field_type
  fieldForm.required = field.required
  fieldForm.optionsText = (field.options ?? []).join('\n')
  fieldForm.sort = field.sort
  fieldForm.status = field.status
  fieldForm.remark = field.remark ?? ''
  fieldForm.version = field.version
  fieldDialogVisible.value = true
}

function parseFieldOptions(): string[] | null {
  const result = fieldForm.optionsText
    .split(/[\n,，]/)
    .map((item) => item.trim())
    .filter(Boolean)
  return result.length ? result : null
}

async function submitField(): Promise<void> {
  const valid = await fieldFormRef.value?.validate().catch(() => false)
  if (!valid) return
  if (fieldForm.field_type === 'SELECT' && !parseFieldOptions()) {
    ElMessage.warning('下拉选项字段至少需要一个选项')
    return
  }
  if (fieldCategoryId.value === null) return
  fieldSubmitting.value = true
  try {
    const payload: CategoryFieldPayload = {
      name: fieldForm.name.trim(),
      field_key: fieldForm.field_key.trim().toLowerCase(),
      field_type: fieldForm.field_type,
      required: fieldForm.required,
      options: fieldForm.field_type === 'SELECT' ? parseFieldOptions() : null,
      sort: fieldForm.sort,
      status: fieldForm.status,
      remark: fieldForm.remark.trim() || null,
    }
    if (fieldDialogMode.value === 'create') {
      await assetApi.createCategoryField(fieldCategoryId.value, payload)
      ElMessage.success('自定义字段已创建')
    } else if (fieldForm.id !== null) {
      await assetApi.updateCategoryField(fieldCategoryId.value, fieldForm.id, {
        ...payload,
        version: fieldForm.version,
      })
      ElMessage.success('自定义字段已更新')
    }
    fieldDialogVisible.value = false
    await loadTree()
  } finally {
    fieldSubmitting.value = false
  }
}

async function deleteField(field: CategoryField): Promise<void> {
  if (fieldCategoryId.value === null) return
  try {
    await ElMessageBox.confirm(
      `确定删除字段「${field.name}」吗？分类下已有资产时不允许删除。`,
      '删除字段',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  await assetApi.deleteCategoryField(fieldCategoryId.value, field.id)
  ElMessage.success('字段已删除')
  await loadTree()
}

/* ---------------- 型号表单 ---------------- */

const modelDialogVisible = ref(false)
const modelDialogMode = ref<'create' | 'edit'>('create')
const modelSubmitting = ref(false)
const modelFormRef = ref<FormInstance>()
const originalModelDomain = ref<AssetDomain | null>(null)

interface ModelFormState {
  id: number | null
  category_id: number | null
  name: string
  code: string
  brand: string
  spec: string
  unit: string
  depreciation_months: number | null
  residual_rate_percent: number
  status: number
  remark: string
  version: number
}

const modelForm = reactive<ModelFormState>({
  id: null,
  category_id: null,
  name: '',
  code: '',
  brand: '',
  spec: '',
  unit: '台',
  depreciation_months: 60,
  residual_rate_percent: 5,
  status: 1,
  remark: '',
  version: 1,
})

const modelRules: FormRules = {
  category_id: [{ required: true, message: '请选择所属分类', trigger: 'change' }],
  name: [{ required: true, message: '请输入型号名称', trigger: 'blur' }],
  code: [
    { required: true, message: '请输入型号编码', trigger: 'blur' },
    {
      pattern: /^[A-Za-z0-9][A-Za-z0-9._-]{1,49}$/,
      message: '2-50 位字母、数字、点、下划线或短横线',
      trigger: 'blur',
    },
  ],
  unit: [{ required: true, message: '请输入计量单位', trigger: 'blur' }],
}

const modelCategoryTree = computed(() => {
  if (
    modelDialogMode.value !== 'edit' ||
    auth.isSuperAdmin ||
    originalModelDomain.value === null
  ) {
    return categories.value
  }
  return categories.value.filter((node) => node.asset_domain === originalModelDomain.value)
})

function resetModelForm(): void {
  modelForm.id = null
  modelForm.category_id = selectedId.value
  originalModelDomain.value = null
  modelForm.name = ''
  modelForm.code = ''
  modelForm.brand = ''
  modelForm.spec = ''
  modelForm.unit = '台'
  modelForm.depreciation_months = 60
  modelForm.residual_rate_percent = 5
  modelForm.status = 1
  modelForm.remark = ''
  modelForm.version = 1
  modelFormRef.value?.clearValidate()
}

function openCreateModel(): void {
  resetModelForm()
  modelDialogMode.value = 'create'
  modelDialogVisible.value = true
}

function openEditModel(model: AssetModel): void {
  resetModelForm()
  modelDialogMode.value = 'edit'
  modelForm.id = model.id
  modelForm.category_id = model.category_id
  originalModelDomain.value =
    findCategory(categories.value, model.category_id)?.asset_domain ?? null
  modelForm.name = model.name
  modelForm.code = model.code
  modelForm.brand = model.brand ?? ''
  modelForm.spec = model.spec ?? ''
  modelForm.unit = model.unit
  modelForm.depreciation_months = model.depreciation_months
  modelForm.residual_rate_percent = Math.round(model.residual_rate * 10000) / 100
  modelForm.status = model.status
  modelForm.remark = model.remark ?? ''
  modelForm.version = model.version
  modelDialogVisible.value = true
}

async function submitModel(): Promise<void> {
  const valid = await modelFormRef.value?.validate().catch(() => false)
  if (!valid || modelForm.category_id === null) return
  modelSubmitting.value = true
  try {
    const payload: ModelPayload = {
      category_id: modelForm.category_id,
      name: modelForm.name.trim(),
      code: modelForm.code.trim().toUpperCase(),
      brand: modelForm.brand.trim() || null,
      spec: modelForm.spec.trim() || null,
      unit: modelForm.unit.trim() || '台',
      depreciation_months: modelForm.depreciation_months,
      residual_rate: Number((modelForm.residual_rate_percent / 100).toFixed(4)),
      status: modelForm.status,
      remark: modelForm.remark.trim() || null,
    }
    if (modelDialogMode.value === 'create') {
      await assetApi.createModel(payload)
      ElMessage.success('型号创建成功')
    } else if (modelForm.id !== null) {
      const targetDomain = findCategory(categories.value, modelForm.category_id)?.asset_domain
      let confirmDomainChange = false
      if (
        originalModelDomain.value !== null &&
        targetDomain !== undefined &&
        targetDomain !== originalModelDomain.value
      ) {
        if (!auth.isSuperAdmin) {
          ElMessage.warning('仅超级管理员可跨域调整型号所属分类')
          return
        }
        try {
          await ElMessageBox.confirm(
            `型号「${modelForm.name}」将从「${assetDomainLabel(originalModelDomain.value)}」调整到「${assetDomainLabel(targetDomain)}」，并写入专项审计。确定继续吗？`,
            '跨域调整型号',
            { type: 'warning', confirmButtonText: '确认调整', cancelButtonText: '取消' },
          )
          confirmDomainChange = true
        } catch {
          return
        }
      }
      await assetApi.updateModel(modelForm.id, {
        ...payload,
        version: modelForm.version,
        confirm_domain_change: confirmDomainChange,
      })
      ElMessage.success('型号更新成功')
    }
    modelDialogVisible.value = false
    await Promise.all([loadModels(), loadTree()])
  } finally {
    modelSubmitting.value = false
  }
}

onMounted(() => {
  void refreshAll()
})
</script>

<template>
  <div class="page category-page">
    <header class="page-header">
      <div>
        <p class="page-eyebrow">ASSET CATALOG</p>
        <h1 class="page-title">资产分类与型号</h1>
        <p class="page-subtitle">
          维护多级资产分类、分类自定义字段与设备型号；型号是台账录入的基础数据。
        </p>
      </div>
      <div class="page-actions">
        <el-button :icon="Refresh" :loading="treeLoading || modelLoading" @click="refreshAll">
          刷新数据
        </el-button>
        <el-button v-if="auth.isSuperAdmin" :icon="Setting" @click="domainDialogVisible = true">
          资产域管理
        </el-button>
        <el-button v-if="canCreateCategory" :icon="Upload" @click="importVisible = true">
          导入分类
        </el-button>
      </div>
    </header>

    <div class="category-layout">
      <section class="surface-card category-panel">
        <div class="panel-head">
          <div>
            <p class="panel-eyebrow">CATEGORIES</p>
            <h2 class="panel-title">分类树</h2>
          </div>
          <el-button
            v-if="canCreateCategory"
            type="primary"
            plain
            size="small"
            :icon="Plus"
            @click="openCreateCategory(null)"
          >
            新增根分类
          </el-button>
        </div>

        <div class="category-search">
          <el-input
            v-model="treeKeyword"
            :prefix-icon="Search"
            placeholder="搜索分类名称 / 编码"
            clearable
          />
        </div>

        <button
          type="button"
          class="category-all"
          :class="{ active: selectedId === null }"
          @click="selectAllCategories"
        >
          <span class="category-all-icon"><el-icon><Grid /></el-icon></span>
          <span class="category-all-label">全部分类</span>
          <span class="category-all-count">{{ totalCategoryCount }}</span>
        </button>

        <div v-loading="treeLoading" class="category-tree-scroll">
          <el-tree
            ref="treeRef"
            :data="categories"
            node-key="id"
            :props="treeProps"
            highlight-current
            default-expand-all
            :expand-on-click-node="false"
            :filter-node-method="filterTreeNode"
            empty-text="暂无分类，请先新增"
            @node-click="handleCategoryClick"
          >
            <template #default="{ data }">
              <div class="category-node">
                <span class="category-node-main">
                  <span class="category-name" :title="data.name">{{ data.name }}</span>
                  <span class="category-meta">
                    <el-tag
                      size="small"
                      effect="plain"
                      :type="categoryTypeTag(data.category_type)"
                    >
                      {{ categoryTypeLabel(data.category_type) }}
                    </el-tag>
                    <el-tag
                      size="small"
                      effect="plain"
                      :type="assetDomainTag(data.asset_domain)"
                    >
                      {{ assetDomainLabel(data.asset_domain) }}
                    </el-tag>
                    <span class="category-code">{{ data.code }}</span>
                    <span class="category-stats">
                      {{ data.model_count }} 型号 · {{ data.asset_count }} 资产
                    </span>
                  </span>
                </span>
                <span class="category-node-side" @click.stop>
                  <el-dropdown
                    trigger="click"
                    @command="handleCategoryCommand($event, data)"
                  >
                    <button class="category-more" type="button" aria-label="分类操作" @click.stop>
                      <el-icon><MoreFilled /></el-icon>
                    </button>
                    <template #dropdown>
                      <el-dropdown-menu>
                        <el-dropdown-item
                          v-if="canCreateCategory"
                          command="create"
                          :icon="Plus"
                        >
                          新增下级
                        </el-dropdown-item>
                        <el-dropdown-item
                          v-if="canUpdateCategory"
                          command="edit"
                          :icon="Edit"
                        >
                          编辑分类
                        </el-dropdown-item>
                        <el-dropdown-item
                          v-if="canUpdateCategory"
                          command="fields"
                          :icon="Setting"
                        >
                          自定义字段
                        </el-dropdown-item>
                        <el-dropdown-item
                          v-if="canDeleteCategory"
                          command="delete"
                          :icon="Delete"
                          divided
                        >
                          删除分类
                        </el-dropdown-item>
                      </el-dropdown-menu>
                    </template>
                  </el-dropdown>
                </span>
              </div>
            </template>
          </el-tree>
        </div>

        <div class="category-foot">
          <span>共 {{ totalCategoryCount }} 个分类</span>
          <span class="category-foot-note">子分类继承父级资产类型</span>
        </div>
      </section>

      <section class="surface-card model-panel">
        <div class="panel-head model-head">
          <div>
            <p class="panel-eyebrow">MODELS</p>
            <h2 class="panel-title">
              型号管理
              <span class="category-context">{{ selectedCategoryName }}</span>
            </h2>
            <p class="panel-hint">
              当前范围：{{ selectedCategory ? '含下级分类' : '全部分类' }}
              <template v-if="selectedCategory">
                · {{ selectedCategory.field_defs.length }} 个扩展字段
              </template>
            </p>
          </div>
          <div class="model-head-actions">
            <el-button
              v-if="canUpdateCategory && selectedCategory"
              :icon="Setting"
              plain
              @click="openFields(selectedCategory)"
            >
              自定义字段
            </el-button>
            <el-button
              v-if="auth.hasPerm('asset:model:create')"
              type="primary"
              :icon="Plus"
              @click="openCreateModel"
            >
              新增型号
            </el-button>
          </div>
        </div>

        <div class="model-filters">
          <el-input
            v-model="modelQuery.keyword"
            :prefix-icon="Search"
            placeholder="型号名称 / 编码 / 品牌"
            class="filter-keyword"
            clearable
            @keyup.enter="handleModelSearch"
            @clear="handleModelSearch"
          />
          <el-select
            v-model="modelQuery.status"
            placeholder="启用状态"
            class="filter-status"
            clearable
            @change="handleModelSearch"
          >
            <el-option label="启用" :value="1" />
            <el-option label="停用" :value="0" />
          </el-select>
          <el-button :icon="Search" @click="handleModelSearch">查询</el-button>
          <el-button text @click="resetModelFilters">重置</el-button>
        </div>

        <el-table
          v-loading="modelLoading"
          :data="models"
          row-key="id"
          class="model-table"
          empty-text="当前分类下暂无型号"
        >
          <el-table-column label="型号" min-width="200">
            <template #default="{ row }">
              <div class="model-cell">
                <span class="model-name">{{ row.name }}</span>
                <span class="model-code">{{ row.code }}</span>
                <span class="model-sub">
                  {{ row.brand || '未填写品牌' }}
                  <template v-if="row.spec"> · {{ row.spec }}</template>
                </span>
              </div>
            </template>
          </el-table-column>

          <el-table-column label="所属分类" width="100">
            <template #default="{ row }">
              <el-tag size="small" effect="plain" round>
                {{ row.category_name || '未分类' }}
              </el-tag>
            </template>
          </el-table-column>

          <el-table-column label="折旧 / 残值" width="110">
            <template #default="{ row }">
              <div class="stack-cell">
                <span>
                  {{ row.depreciation_months ? `${row.depreciation_months} 个月` : '不计折旧' }}
                </span>
                <small>残值 {{ (row.residual_rate * 100).toFixed(1) }}% · {{ row.unit }}</small>
              </div>
            </template>
          </el-table-column>

          <el-table-column label="资产数" width="72" align="center">
            <template #default="{ row }">
              <span class="asset-count">{{ row.asset_count }}</span>
            </template>
          </el-table-column>

          <el-table-column label="状态" width="78" align="center">
            <template #default="{ row }">
              <el-tag :type="row.status === 1 ? 'success' : 'info'" size="small" effect="light">
                {{ row.status === 1 ? '启用' : '停用' }}
              </el-tag>
            </template>
          </el-table-column>

          <el-table-column
            v-if="canManageModel"
            label="操作"
            width="76"
            align="center"
          >
            <template #default="{ row }">
              <el-dropdown trigger="click" @command="handleModelCommand($event, row)">
                <el-button text :icon="MoreFilled" aria-label="型号操作" />
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item
                      v-if="auth.hasPerm('asset:model:update')"
                      command="edit"
                      :icon="Edit"
                    >
                      编辑型号
                    </el-dropdown-item>
                    <el-dropdown-item
                      v-if="auth.hasPerm('asset:model:delete')"
                      command="delete"
                      :icon="Delete"
                      divided
                    >
                      删除型号
                    </el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </template>
          </el-table-column>
        </el-table>

        <div class="table-foot">
          <span class="table-total">共 {{ modelTotal }} 个型号</span>
          <el-pagination
            v-model:current-page="modelQuery.page"
            v-model:page-size="modelQuery.page_size"
            :total="modelTotal"
            :page-sizes="[10, 20, 50, 100]"
            layout="sizes, prev, pager, next"
            background
            @current-change="loadModels"
            @size-change="handleModelSizeChange"
          />
        </div>
      </section>
    </div>

    <el-dialog
      v-model="categoryDialogVisible"
      :title="categoryDialogMode === 'create' ? '新增资产分类' : '编辑资产分类'"
      width="560px"
      destroy-on-close
    >
      <el-form
        ref="categoryFormRef"
        :model="categoryForm"
        :rules="categoryRules"
        label-width="96px"
        class="dialog-form"
      >
        <el-form-item label="上级分类">
          <el-tree-select
            v-model="categoryForm.parent_id"
            :data="parentTreeData"
            :props="{ label: 'name', children: 'children' }"
            node-key="id"
            check-strictly
            clearable
            placeholder="不选择则创建为根分类"
            class="full-width"
          />
        </el-form-item>
        <el-form-item label="分类名称" prop="name">
          <el-input v-model="categoryForm.name" maxlength="100" show-word-limit />
        </el-form-item>
        <el-form-item label="分类编码" prop="code">
          <el-input
            v-model="categoryForm.code"
            maxlength="50"
            placeholder="例如 HW-LAPTOP"
            @input="categoryForm.code = String($event).toUpperCase()"
          />
        </el-form-item>
        <el-form-item label="资产类型" prop="category_type">
          <el-select
            v-model="categoryForm.category_type"
            :disabled="categoryTypeLocked"
            class="full-width"
          >
            <el-option
              v-for="(label, value) in CATEGORY_TYPE_LABELS"
              :key="value"
              :label="label"
              :value="value"
            />
          </el-select>
          <p v-if="categoryTypeLocked" class="form-tip">
            子分类自动继承父级资产类型
          </p>
        </el-form-item>
        <el-form-item label="资产域" prop="asset_domain">
          <el-select
            v-model="categoryForm.asset_domain"
            :disabled="categoryDomainLocked"
            class="full-width"
          >
            <el-option
              v-for="domain in domains"
              :key="domain.code"
              :label="domain.name"
              :value="domain.code"
            />
          </el-select>
          <p v-if="categoryForm.parent_id !== null" class="form-tip">
            子分类自动继承根分类的资产域
          </p>
          <p v-else-if="categoryDomainLocked" class="form-tip">
            仅超级管理员可调整已有分类的资产域
          </p>
          <p v-else class="form-tip">
            根分类决定整棵分类树的业务域，跨域修改需二次确认并同步全部子分类
          </p>
        </el-form-item>
        <div class="form-row">
          <el-form-item label="排序">
            <el-input-number v-model="categoryForm.sort" :min="0" :max="9999" controls-position="right" />
          </el-form-item>
          <el-form-item label="安全库存">
            <el-input-number
              v-model="categoryForm.safety_stock"
              :min="0"
              :max="99999"
              controls-position="right"
            />
          </el-form-item>
          <el-form-item label="状态">
            <el-switch
              v-model="categoryForm.status"
              :active-value="1"
              :inactive-value="0"
              inline-prompt
              active-text="启用"
              inactive-text="停用"
            />
          </el-form-item>
        </div>
        <el-form-item label="备注">
          <el-input
            v-model="categoryForm.remark"
            type="textarea"
            :rows="2"
            maxlength="255"
            show-word-limit
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="categoryDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="categorySubmitting" @click="submitCategory">
          {{ categoryDialogMode === 'create' ? '创建分类' : '保存修改' }}
        </el-button>
      </template>
    </el-dialog>

    <el-drawer
      v-model="fieldsDrawerVisible"
      :title="`自定义字段 · ${fieldCategory?.name ?? ''}`"
      size="620px"
      destroy-on-close
    >
      <div class="field-drawer">
        <div class="field-drawer-head">
          <div>
            <p class="panel-eyebrow">CUSTOM FIELDS</p>
            <p class="field-drawer-desc">
              扩展字段随资产录入动态生成，值以 JSON 形式保存在台账中。
              <span v-if="fieldAssetsLocked" class="field-locked">
                当前分类已有资产，字段标识与类型不可再修改。
              </span>
            </p>
          </div>
          <el-button
            v-if="canUpdateCategory"
            type="primary"
            :icon="Plus"
            @click="openCreateField"
          >
            新增字段
          </el-button>
        </div>

        <el-table :data="fieldDefs" row-key="id" empty-text="暂无自定义字段">
          <el-table-column label="字段" min-width="130">
            <template #default="{ row }">
              <div class="stack-cell">
                <span>{{ row.name }}</span>
                <small>{{ row.field_key }}</small>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="类型" width="86">
            <template #default="{ row }">
              <el-tag size="small" effect="plain">
                {{ FIELD_TYPE_LABELS[row.field_type as AssetFieldType] }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="必填" width="60" align="center">
            <template #default="{ row }">
              <span :class="row.required ? 'required-yes' : 'muted'">
                {{ row.required ? '是' : '否' }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="选项 / 排序" min-width="130">
            <template #default="{ row }">
              <div class="stack-cell">
                <span v-if="row.options?.length">{{ row.options.join(' / ') }}</span>
                <span v-else class="muted">—</span>
                <small>排序 {{ row.sort }}</small>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="72" align="center">
            <template #default="{ row }">
              <el-tag :type="row.status === 1 ? 'success' : 'info'" size="small" effect="light">
                {{ row.status === 1 ? '启用' : '停用' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column v-if="canUpdateCategory" label="操作" width="84" align="center">
            <template #default="{ row }">
              <el-button text :icon="Edit" @click="openEditField(row)" />
              <el-button
                text
                type="danger"
                :icon="Delete"
                :disabled="fieldAssetsLocked"
                @click="deleteField(row)"
              />
            </template>
          </el-table-column>
        </el-table>
      </div>
    </el-drawer>

    <el-dialog
      v-model="fieldDialogVisible"
      :title="fieldDialogMode === 'create' ? '新增自定义字段' : '编辑自定义字段'"
      width="520px"
      destroy-on-close
    >
      <el-form
        ref="fieldFormRef"
        :model="fieldForm"
        :rules="fieldRules"
        label-width="92px"
        class="dialog-form"
      >
        <el-form-item label="字段名称" prop="name">
          <el-input v-model="fieldForm.name" maxlength="50" />
        </el-form-item>
        <el-form-item label="字段标识" prop="field_key">
          <el-input
            v-model="fieldForm.field_key"
            maxlength="50"
            :disabled="fieldDialogMode === 'edit' && fieldAssetsLocked"
            placeholder="例如 cpu_model"
            @input="fieldForm.field_key = String($event).toLowerCase()"
          />
        </el-form-item>
        <el-form-item label="字段类型">
          <el-select
            v-model="fieldForm.field_type"
            :disabled="fieldDialogMode === 'edit' && fieldAssetsLocked"
            class="full-width"
          >
            <el-option
              v-for="(label, value) in FIELD_TYPE_LABELS"
              :key="value"
              :label="label"
              :value="value"
            />
          </el-select>
        </el-form-item>
        <el-form-item v-if="fieldForm.field_type === 'SELECT'" label="下拉选项">
          <el-input
            v-model="fieldForm.optionsText"
            type="textarea"
            :rows="4"
            placeholder="每行一个选项，也支持用逗号分隔"
          />
        </el-form-item>
        <div class="form-row">
          <el-form-item label="是否必填">
            <el-switch
              v-model="fieldForm.required"
              inline-prompt
              active-text="必填"
              inactive-text="选填"
            />
          </el-form-item>
          <el-form-item label="排序">
            <el-input-number v-model="fieldForm.sort" :min="0" :max="9999" controls-position="right" />
          </el-form-item>
          <el-form-item label="状态">
            <el-switch
              v-model="fieldForm.status"
              :active-value="1"
              :inactive-value="0"
              inline-prompt
              active-text="启用"
              inactive-text="停用"
            />
          </el-form-item>
        </div>
        <el-form-item label="备注">
          <el-input v-model="fieldForm.remark" maxlength="255" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="fieldDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="fieldSubmitting" @click="submitField">
          {{ fieldDialogMode === 'create' ? '创建字段' : '保存修改' }}
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="modelDialogVisible"
      :title="modelDialogMode === 'create' ? '新增资产型号' : '编辑资产型号'"
      width="600px"
      destroy-on-close
    >
      <el-form
        ref="modelFormRef"
        :model="modelForm"
        :rules="modelRules"
        label-width="96px"
        class="dialog-form"
      >
        <el-form-item label="所属分类" prop="category_id">
          <el-tree-select
            v-model="modelForm.category_id"
            :data="modelCategoryTree"
            :props="{ label: 'name', children: 'children' }"
            node-key="id"
            check-strictly
            placeholder="请选择资产分类"
            class="full-width"
          />
        </el-form-item>
        <div class="form-row">
          <el-form-item label="型号名称" prop="name" class="grow">
            <el-input v-model="modelForm.name" maxlength="100" />
          </el-form-item>
          <el-form-item label="型号编码" prop="code" class="grow">
            <el-input
              v-model="modelForm.code"
              maxlength="50"
              placeholder="例如 DELL-OPTIPLEX-7010"
              @input="modelForm.code = String($event).toUpperCase()"
            />
          </el-form-item>
        </div>
        <div class="form-row">
          <el-form-item label="品牌" class="grow">
            <el-input v-model="modelForm.brand" maxlength="80" />
          </el-form-item>
          <el-form-item label="计量单位" prop="unit" class="grow">
            <el-input v-model="modelForm.unit" maxlength="20" />
          </el-form-item>
        </div>
        <el-form-item label="规格参数">
          <el-input v-model="modelForm.spec" maxlength="255" placeholder="例如 i7 / 32GB / 1TB SSD" />
        </el-form-item>
        <div class="form-row">
          <el-form-item label="折旧月数" class="grow">
            <el-input-number
              v-model="modelForm.depreciation_months"
              :min="1"
              :max="600"
              controls-position="right"
              class="full-width"
            />
            <p class="form-tip">留空表示不计折旧</p>
          </el-form-item>
          <el-form-item label="残值率" class="grow">
            <el-input-number
              v-model="modelForm.residual_rate_percent"
              :min="0"
              :max="100"
              :precision="2"
              :step="1"
              controls-position="right"
              class="full-width"
            />
            <p class="form-tip">按百分比填写，例如 5 表示 5%</p>
          </el-form-item>
        </div>
        <el-form-item label="状态">
          <el-switch
            v-model="modelForm.status"
            :active-value="1"
            :inactive-value="0"
            inline-prompt
            active-text="启用"
            inactive-text="停用"
          />
        </el-form-item>
        <el-form-item label="备注">
          <el-input
            v-model="modelForm.remark"
            type="textarea"
            :rows="2"
            maxlength="255"
            show-word-limit
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="modelDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="modelSubmitting" @click="submitModel">
          {{ modelDialogMode === 'create' ? '创建型号' : '保存修改' }}
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="domainDialogVisible" title="资产域管理" width="680px">
      <div class="panel-head">
        <p class="form-tip">
          资产域在角色级一次授权后作用于全部资产业务；内置域不可删除，被分类或角色引用的域不可删除。
        </p>
        <el-button type="primary" plain size="small" :icon="Plus" @click="openCreateDomain">
          新增资产域
        </el-button>
      </div>
      <el-table :data="domains" row-key="id" size="small" border>
        <el-table-column label="编码" prop="code" width="130" />
        <el-table-column label="名称" prop="name" min-width="150" />
        <el-table-column label="排序" prop="sort" width="80" align="center" />
        <el-table-column label="类型" width="90" align="center">
          <template #default="{ row }">
            <el-tag :type="row.is_builtin ? 'info' : 'success'" size="small" effect="plain">
              {{ row.is_builtin ? '内置' : '自定义' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="110" align="center">
          <template #default="{ row }">
            <el-button text :icon="Edit" @click="openEditDomain(row)" />
            <el-button
              text
              type="danger"
              :icon="Delete"
              :disabled="row.is_builtin"
              @click="deleteDomain(row)"
            />
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>

    <el-dialog
      v-model="domainFormVisible"
      :title="domainFormMode === 'create' ? '新增资产域' : '编辑资产域'"
      width="460px"
      destroy-on-close
    >
      <el-form
        ref="domainFormRef"
        :model="domainForm"
        :rules="domainRules"
        label-width="92px"
        class="dialog-form"
      >
        <el-form-item label="域编码" prop="code">
          <el-input
            v-model="domainForm.code"
            maxlength="20"
            :disabled="domainFormMode === 'edit'"
            placeholder="例如 FACILITY"
            @input="domainForm.code = String($event).toUpperCase()"
          />
        </el-form-item>
        <el-form-item label="域名称" prop="name">
          <el-input v-model="domainForm.name" maxlength="50" placeholder="例如 设施资产" />
        </el-form-item>
        <el-form-item label="排序">
          <el-input-number v-model="domainForm.sort" :min="0" :max="9999" controls-position="right" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="domainFormVisible = false">取消</el-button>
        <el-button type="primary" :loading="domainSubmitting" @click="submitDomain">
          {{ domainFormMode === 'create' ? '创建资产域' : '保存修改' }}
        </el-button>
      </template>
    </el-dialog>

    <ImportDialog v-model="importVisible" kind="categories" @imported="handleImported" />
  </div>
</template>

<style scoped>
.category-layout {
  display: grid;
  grid-template-columns: 340px minmax(0, 1fr);
  gap: 18px;
  align-items: start;
}

.category-panel,
.model-panel {
  padding: 20px;
  min-width: 0;
}

.panel-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
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

.panel-hint {
  margin: 6px 0 0;
  font-size: 12px;
  color: var(--text-3);
}

.category-context {
  margin-left: 8px;
  padding: 2px 9px;
  border-radius: 999px;
  background: var(--brand-soft);
  color: var(--brand);
  font-size: 11.5px;
  font-weight: 600;
  vertical-align: 2px;
}

.category-search {
  margin-bottom: 10px;
}

.category-all {
  display: flex;
  align-items: center;
  gap: 9px;
  width: 100%;
  padding: 9px 11px;
  border: 1px solid transparent;
  border-radius: 11px;
  background: transparent;
  color: var(--text-2);
  cursor: pointer;
  transition: background-color 0.2s ease, color 0.2s ease, border-color 0.2s ease;
}

.category-all:hover {
  background: var(--surface-muted);
}

.category-all.active {
  background: var(--brand-soft);
  border-color: color-mix(in srgb, var(--brand) 22%, transparent);
  color: var(--brand);
}

.category-all-icon {
  display: grid;
  place-items: center;
  width: 26px;
  height: 26px;
  border-radius: 8px;
  background: var(--surface-muted);
  color: var(--brand);
}

.category-all.active .category-all-icon {
  background: var(--surface);
}

.category-all-label {
  flex: 1;
  text-align: left;
  font-size: 13px;
  font-weight: 600;
}

.category-all-count {
  font-family: var(--font-number);
  font-size: 12px;
  opacity: 0.7;
}

.category-tree-scroll {
  max-height: calc(100vh - 360px);
  min-height: 280px;
  overflow-y: auto;
  padding: 4px 2px 4px 0;
}

.category-node {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  width: 100%;
  min-width: 0;
  padding-right: 6px;
}

.category-node-main {
  display: flex;
  flex-direction: column;
  min-width: 0;
  line-height: 1.3;
}

.category-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-1);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.category-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  row-gap: 2px;
  margin-top: 3px;
  min-width: 0;
}

.category-code {
  font-size: 10.5px;
  color: var(--text-3);
  font-family: var(--font-number);
}

.category-stats {
  font-size: 10.5px;
  color: var(--text-3);
  white-space: nowrap;
}

.category-node-side {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
  opacity: 0;
  transition: opacity 0.2s ease;
}

.category-node:hover .category-node-side,
.el-tree-node.is-current .category-node-side {
  opacity: 1;
}

.category-more {
  display: grid;
  place-items: center;
  width: 24px;
  height: 24px;
  border: none;
  border-radius: 7px;
  background: transparent;
  color: var(--text-2);
  cursor: pointer;
}

.category-more:hover {
  background: var(--brand-soft);
  color: var(--brand);
}

.category-foot {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  padding-top: 12px;
  margin-top: 8px;
  border-top: 1px solid var(--border);
  color: var(--text-3);
  font-size: 11.5px;
}

.category-foot-note {
  opacity: 0.8;
}

.model-head-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.model-filters {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px;
  margin-bottom: 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--surface-muted);
  flex-wrap: wrap;
}

.filter-keyword {
  width: 280px;
  max-width: 100%;
}

.filter-status {
  width: 130px;
}

.model-cell {
  display: flex;
  flex-direction: column;
  line-height: 1.35;
}

.model-name {
  font-weight: 600;
  color: var(--text-1);
}

.model-code {
  margin-top: 2px;
  font-size: 10.5px;
  color: var(--text-3);
  font-family: var(--font-number);
}

.model-sub {
  margin-top: 3px;
  font-size: 11px;
  color: var(--text-3);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.stack-cell {
  display: flex;
  flex-direction: column;
  line-height: 1.35;
  min-width: 0;
}

.stack-cell small {
  color: var(--text-3);
  font-size: 11px;
  margin-top: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.asset-count {
  font-family: var(--font-number);
  font-weight: 700;
  color: var(--brand);
}

.muted {
  color: var(--text-3);
}

.required-yes {
  color: var(--danger);
  font-weight: 600;
}

.table-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding-top: 16px;
  flex-wrap: wrap;
}

.table-total {
  font-size: 12px;
  color: var(--text-3);
}

.dialog-form {
  padding-right: 6px;
}

.full-width {
  width: 100%;
}

.form-row {
  display: flex;
  gap: 14px;
}

.form-row .grow {
  flex: 1;
  min-width: 0;
}

.form-tip {
  margin: 4px 0 0;
  font-size: 11px;
  color: var(--text-3);
  line-height: 1.4;
}

.field-drawer {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.field-drawer-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
}

.field-drawer-desc {
  margin: 0;
  font-size: 12.5px;
  line-height: 1.55;
  color: var(--text-2);
}

.field-locked {
  color: var(--warning);
}

:deep(.el-tree-node__content) {
  height: auto;
  min-height: 46px;
  padding: 4px 0;
  border-radius: 10px;
  margin-bottom: 2px;
}

:deep(.el-tree-node.is-current > .el-tree-node__content) {
  background: var(--brand-soft);
}

:deep(.el-drawer__body) {
  padding-top: 8px;
}

@media (max-width: 1180px) {
  .category-layout {
    grid-template-columns: 1fr;
  }

  .category-tree-scroll {
    max-height: 360px;
  }

  .category-node-side {
    opacity: 1;
  }
}

@media (max-width: 640px) {
  .category-panel,
  .model-panel {
    padding: 16px;
  }

  .panel-head,
  .field-drawer-head {
    flex-direction: column;
  }

  .model-head-actions {
    width: 100%;
    justify-content: flex-start;
  }

  .model-filters {
    align-items: stretch;
  }

  .filter-keyword,
  .filter-status {
    width: 100%;
  }

  .form-row {
    flex-direction: column;
    gap: 0;
  }
}
</style>
