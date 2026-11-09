<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import {
  ElMessage,
  ElMessageBox,
  type FormInstance,
  type FormItemRule,
  type FormRules,
} from 'element-plus'
import {
  ChatDotRound,
  CircleCheck,
  Connection,
  Link,
  Lock,
  Refresh,
  RefreshRight,
  View,
} from '@element-plus/icons-vue'

import { dingtalkApi } from '@/api/dingtalk'
import { useAuthStore } from '@/stores/auth'
import type {
  DingTalkConfig,
  DingTalkConfigPayload,
  DingTalkConfigUpdatePayload,
  DingTalkOptions,
  DingTalkSyncLog,
  DingTalkTestResult,
} from '@/types/dingtalk'
import { formatDateTime } from '@/utils/format'

type TagType = 'primary' | 'success' | 'warning' | 'danger' | 'info'

const STATUS_META: Record<string, { label: string; type: TagType }> = {
  SUCCESS: { label: '成功', type: 'success' },
  PARTIAL: { label: '部分成功', type: 'warning' },
  FAILED: { label: '失败', type: 'danger' },
  RUNNING: { label: '执行中', type: 'primary' },
}

function emptyForm(): DingTalkConfigUpdatePayload {
  return {
    enabled: false,
    corp_id: '',
    app_key: '',
    app_secret: '',
    agent_id: null,
    default_role_id: null,
    root_dept_id: null,
    sync_interval_minutes: 120,
    disable_on_leave: true,
    match_existing: true,
    approval_enabled: false,
    requisition_process_code: '',
    borrow_process_code: '',
    transfer_process_code: '',
    callback_token: '',
    callback_aes_key: '',
    version: undefined,
  }
}

const auth = useAuthStore()
const canUpdate = computed(() => auth.hasPerm('system:dingtalk:update'))
const canSync = computed(() => auth.hasPerm('system:dingtalk:sync'))

const activeTab = ref('config')
const formRef = ref<FormInstance>()
const form = reactive<DingTalkConfigUpdatePayload>(emptyForm())
const config = ref<DingTalkConfig | null>(null)
const options = ref<DingTalkOptions>({
  roles: [],
  depts: [],
  dingtalk_dept_count: 0,
  dingtalk_user_count: 0,
})

const loading = ref(false)
const saving = ref(false)
const testing = ref(false)
const syncing = ref(false)
const testResult = ref<DingTalkTestResult | null>(null)

const logs = ref<DingTalkSyncLog[]>([])
const logsLoading = ref(false)
const logTotal = ref(0)
const logQuery = reactive({
  page: 1,
  page_size: 10,
  status: undefined as string | undefined,
})
const detailVisible = ref(false)
const detailLoading = ref(false)
const activeLog = ref<DingTalkSyncLog | null>(null)

const syncRunning = computed(
  () => syncing.value || config.value?.last_sync_status === 'RUNNING',
)
const roleLabel = computed(() => config.value?.default_role_name || '普通员工（EMPLOYEE）')
const deptLabel = computed(
  () => config.value?.root_dept_name || '钉钉组织直接挂在根部门（无独立挂载点）',
)

const deptOptions = computed(() =>
  options.value.depts.map((dept) => ({
    value: dept.id,
    label: `${'· '.repeat(Math.max(0, dept.level - 1))}${dept.name}`,
  })),
)

function statusMeta(status?: string | null): { label: string; type: TagType } {
  return (status && STATUS_META[status]) || { label: status || '未执行', type: 'info' }
}

function fillForm(cfg: DingTalkConfig): void {
  Object.assign(form, {
    enabled: cfg.enabled,
    corp_id: cfg.corp_id,
    app_key: cfg.app_key,
    app_secret: '',
    agent_id: cfg.agent_id,
    default_role_id: cfg.default_role_id,
    root_dept_id: cfg.root_dept_id,
    sync_interval_minutes: cfg.sync_interval_minutes,
    disable_on_leave: cfg.disable_on_leave,
    match_existing: cfg.match_existing,
    approval_enabled: cfg.approval_enabled,
    requisition_process_code: cfg.requisition_process_code ?? '',
    borrow_process_code: cfg.borrow_process_code ?? '',
    transfer_process_code: cfg.transfer_process_code ?? '',
    callback_token: '',
    callback_aes_key: '',
    version: cfg.version,
  })
}

function formPayload(): DingTalkConfigPayload {
  return {
    enabled: form.enabled,
    corp_id: form.corp_id.trim(),
    app_key: form.app_key.trim(),
    app_secret: form.app_secret?.trim() ? form.app_secret : null,
    agent_id: form.agent_id,
    default_role_id: form.default_role_id,
    root_dept_id: form.root_dept_id,
    sync_interval_minutes: form.sync_interval_minutes,
    disable_on_leave: form.disable_on_leave,
    match_existing: form.match_existing,
    approval_enabled: form.approval_enabled,
    requisition_process_code: form.requisition_process_code?.trim() || null,
    borrow_process_code: form.borrow_process_code?.trim() || null,
    transfer_process_code: form.transfer_process_code?.trim() || null,
    callback_token: form.callback_token?.trim() ? form.callback_token : null,
    callback_aes_key: form.callback_aes_key?.trim() ? form.callback_aes_key : null,
  }
}

const requiredWhenEnabled =
  (label: string): FormItemRule['validator'] =>
  (_rule, value: string, callback) => {
    if (form.enabled && !String(value || '').trim()) {
      callback(new Error(`启用同步时必须填写${label}`))
      return
    }
    callback()
  }

const deptRequiredWhenEnabled: FormItemRule['validator'] = (_rule, value, callback) => {
  if (form.enabled && !value) {
    callback(new Error('启用同步时必须选择钉钉组织挂载的根部门'))
    return
  }
  callback()
}

const processCodeRequiredWhenApproval =
  (label: string): FormItemRule['validator'] =>
  (_rule, value: string, callback) => {
    if (form.approval_enabled && !String(value || '').trim()) {
      callback(new Error(`启用审批对接时必须填写${label}的审批模板编码`))
      return
    }
    callback()
  }

const aesKeyRule: FormItemRule['validator'] = (_rule, value: string, callback) => {
  if (value && value.trim().length !== 43) {
    callback(new Error('回调 AES Key 须为 43 位字符'))
    return
  }
  callback()
}

const rules: FormRules<DingTalkConfigUpdatePayload> = {
  corp_id: [{ validator: requiredWhenEnabled('CorpId'), trigger: 'blur' }],
  app_key: [{ validator: requiredWhenEnabled('AppKey'), trigger: 'blur' }],
  root_dept_id: [{ validator: deptRequiredWhenEnabled, trigger: 'change' }],
  sync_interval_minutes: [
    { type: 'number', min: 5, max: 10080, message: '同步间隔需为 5-10080 分钟', trigger: 'blur' },
  ],
  requisition_process_code: [
    { validator: processCodeRequiredWhenApproval('领用申请'), trigger: 'blur' },
  ],
  borrow_process_code: [
    { validator: processCodeRequiredWhenApproval('借用申请'), trigger: 'blur' },
  ],
  transfer_process_code: [
    { validator: processCodeRequiredWhenApproval('调拨申请'), trigger: 'blur' },
  ],
  callback_aes_key: [{ validator: aesKeyRule, trigger: 'blur' }],
}

async function loadConfig(silent = false): Promise<DingTalkConfig | null> {
  if (!silent) loading.value = true
  try {
    const result = await dingtalkApi.getConfig()
    config.value = result
    fillForm(result)
    return result
  } finally {
    if (!silent) loading.value = false
  }
}

async function loadOptions(): Promise<void> {
  options.value = await dingtalkApi.getOptions()
}

async function loadLogs(silent = false): Promise<void> {
  if (!silent) logsLoading.value = true
  try {
    const result = await dingtalkApi.listLogs({
      page: logQuery.page,
      page_size: logQuery.page_size,
      status: logQuery.status,
    })
    logs.value = result.items
    logTotal.value = result.total
  } finally {
    if (!silent) logsLoading.value = false
  }
}

async function refreshAll(): Promise<void> {
  await Promise.all([loadConfig(), loadOptions(), loadLogs()])
  if (config.value?.last_sync_status === 'RUNNING') {
    startPolling(logs.value[0]?.id ?? 0)
  }
}

async function handleSave(): Promise<void> {
  if (!canUpdate.value || !formRef.value) return
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return
  saving.value = true
  try {
    const result = await dingtalkApi.saveConfig({
      ...formPayload(),
      version: form.version,
    })
    config.value = result
    fillForm(result)
    await loadOptions()
    ElMessage.success('钉钉同步配置已保存')
  } finally {
    saving.value = false
  }
}

function checkTestable(): boolean {
  if (!form.corp_id.trim() || !form.app_key.trim()) {
    ElMessage.warning('请填写 CorpId 与 AppKey')
    return false
  }
  if (!form.app_secret?.trim() && !config.value?.has_secret) {
    ElMessage.warning('请填写 AppSecret 后再测试')
    return false
  }
  return true
}

async function handleTest(): Promise<void> {
  if (!canUpdate.value || testing.value || !checkTestable()) return
  testing.value = true
  testResult.value = null
  try {
    testResult.value = await dingtalkApi.testConfig(formPayload())
    if (testResult.value.success) {
      ElMessage.success(testResult.value.message)
    } else {
      ElMessage.error(testResult.value.message)
    }
  } finally {
    testing.value = false
  }
}

let pollTimer: ReturnType<typeof setInterval> | undefined
let pollAttempts = 0
let pollBaselineId = 0
let sawRunning = false

function stopPolling(): void {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = undefined
  }
}

function finishPolling(): void {
  stopPolling()
  syncing.value = false
  sawRunning = false
  const status = config.value?.last_sync_status
  if (status === 'SUCCESS') {
    ElMessage.success('钉钉人员同步完成')
  } else if (status === 'PARTIAL') {
    ElMessage.warning('同步完成，但存在部分异常，请查看同步日志')
  } else if (status === 'FAILED') {
    ElMessage.error('钉钉人员同步失败，请查看同步日志')
  }
  void loadOptions()
}

async function pollOnce(): Promise<void> {
  pollAttempts += 1
  const [cfg] = await Promise.all([loadConfig(true), loadLogs(true)])
  if (cfg?.last_sync_status === 'RUNNING') {
    sawRunning = true
  }
  const newest = logs.value[0]
  const completedNew = Boolean(
    newest && newest.id > pollBaselineId && newest.status !== 'RUNNING',
  )
  if (completedNew || (sawRunning && cfg?.last_sync_status !== 'RUNNING')) {
    finishPolling()
    return
  }
  if (pollAttempts >= 200) {
    stopPolling()
    syncing.value = false
    ElMessage.warning('同步仍在后台执行，请稍后刷新日志查看结果')
  }
}

function startPolling(baselineId: number): void {
  stopPolling()
  pollAttempts = 0
  sawRunning = false
  pollBaselineId = baselineId
  syncing.value = true
  pollTimer = setInterval(() => {
    void pollOnce()
  }, 3000)
}

async function handleSync(): Promise<void> {
  if (!canSync.value || syncRunning.value) return
  try {
    await ElMessageBox.confirm(
      '将立即从钉钉读取部门与人员数据，并同步部门层级、账号信息与在职状态。离职人员仅停用账号，不物理删除。同步期间请勿重复触发。',
      '手动触发钉钉同步',
      {
        confirmButtonText: '开始同步',
        cancelButtonText: '取消',
        type: 'warning',
      },
    )
  } catch {
    return
  }
  const baseline = logs.value[0]?.id ?? 0
  syncing.value = true
  try {
    await dingtalkApi.triggerSync()
    ElMessage.info('同步任务已提交，正在执行...')
    startPolling(baseline)
    void loadLogs(true)
  } catch {
    syncing.value = false
  }
}

async function openDetail(row: DingTalkSyncLog): Promise<void> {
  detailVisible.value = true
  detailLoading.value = true
  activeLog.value = row
  try {
    activeLog.value = await dingtalkApi.getLog(row.id)
  } finally {
    detailLoading.value = false
  }
}

function handleLogSearch(): void {
  logQuery.page = 1
  void loadLogs()
}

function handleLogPageChange(page: number): void {
  logQuery.page = page
  void loadLogs()
}

function handleLogSizeChange(size: number): void {
  logQuery.page_size = size
  logQuery.page = 1
  void loadLogs()
}

function durationText(value: number): string {
  if (!value) return '—'
  if (value < 1000) return `${value} ms`
  return `${(value / 1000).toFixed(1)} s`
}

onMounted(async () => {
  await Promise.all([loadConfig(), loadOptions(), loadLogs()])
  if (config.value?.last_sync_status === 'RUNNING') {
    startPolling(logs.value[0]?.id ?? 0)
  }
})

onBeforeUnmount(() => {
  stopPolling()
})
</script>

<template>
  <div class="page dingtalk-page">
    <header class="page-header">
      <div>
        <p class="page-eyebrow">DINGTALK DIRECTORY SYNC</p>
        <h1 class="page-title">钉钉同步</h1>
        <p class="page-subtitle">
          对接钉钉通讯录与审批流：部门自动映射到独立根部门下，人员按手机号/邮箱匹配或自动创建；钉钉离职仅停用账号，不物理删除。领用/借用/调拨申请可提交钉钉审批，与 AD 域控同步相互独立、互不覆盖。
        </p>
      </div>
      <div class="page-actions">
        <el-button :icon="Refresh" :loading="loading" @click="refreshAll">刷新数据</el-button>
        <el-button
          v-if="canSync"
          type="primary"
          :icon="RefreshRight"
          :loading="syncRunning"
          :disabled="!config?.enabled || config.id === 0"
          @click="handleSync"
        >
          {{ syncRunning ? '同步执行中' : '手动同步' }}
        </el-button>
      </div>
    </header>

    <section class="status-grid">
      <article class="surface-card status-card">
        <div class="status-icon" :class="config?.enabled ? 'is-on' : 'is-off'">
          <el-icon><ChatDotRound /></el-icon>
        </div>
        <div class="status-body">
          <p class="status-label">连接状态</p>
          <p class="status-value">
            <el-tag :type="config?.enabled ? 'success' : 'info'" effect="light" round>
              {{ config?.enabled ? '已启用' : '未启用' }}
            </el-tag>
          </p>
          <p class="status-note">
            {{ config?.corp_id ? `CorpId ${config.corp_id}` : '尚未配置钉钉应用' }}
          </p>
        </div>
      </article>

      <article class="surface-card status-card">
        <div class="status-icon" :class="config?.last_sync_status === 'FAILED' ? 'is-alert' : 'is-on'">
          <el-icon><RefreshRight /></el-icon>
        </div>
        <div class="status-body">
          <p class="status-label">上次同步</p>
          <p class="status-value">
            <el-tag :type="statusMeta(config?.last_sync_status).type" effect="light" round>
              {{ statusMeta(config?.last_sync_status).label }}
            </el-tag>
          </p>
          <p class="status-note">{{ formatDateTime(config?.last_sync_at) }}</p>
        </div>
      </article>

      <article class="surface-card status-card">
        <div class="status-icon is-on">
          <el-icon><Link /></el-icon>
        </div>
        <div class="status-body">
          <p class="status-label">同步范围</p>
          <p class="status-value">
            {{ options.dingtalk_dept_count }} 个部门 / {{ options.dingtalk_user_count }} 名钉钉用户
          </p>
          <p class="status-note">与 AD 域账号按手机号/邮箱匹配，不覆盖其部门与状态</p>
        </div>
      </article>

      <article class="surface-card status-card">
        <div class="status-icon is-on">
          <el-icon><Lock /></el-icon>
        </div>
        <div class="status-body">
          <p class="status-label">定时策略</p>
          <p class="status-value">每 {{ config?.sync_interval_minutes || 120 }} 分钟</p>
          <p class="status-note">Celery 每 5 分钟检查一次到期任务</p>
        </div>
      </article>
    </section>

    <el-alert
      v-if="config?.last_sync_status === 'FAILED' && config.last_sync_message"
      type="error"
      :closable="false"
      show-icon
      class="sync-alert"
      title="最近一次同步失败"
      :description="config.last_sync_message"
    />
    <el-alert
      v-else-if="config?.last_sync_status === 'PARTIAL' && config.last_sync_message"
      type="warning"
      :closable="false"
      show-icon
      class="sync-alert"
      title="最近一次同步部分成功"
      :description="config.last_sync_message"
    />
    <el-alert
      v-if="testResult"
      :type="testResult.success ? 'success' : 'error'"
      :closable="true"
      show-icon
      class="sync-alert"
      :title="testResult.success ? '钉钉连接测试成功' : '钉钉连接测试失败'"
      @close="testResult = null"
    >
      <template #default>
        {{ testResult.message }}
        <span v-if="testResult.success">
          （通讯录 {{ testResult.dept_sample }} 个部门，抽查 {{ testResult.user_sample }} 名成员，耗时
          {{ testResult.elapsed_ms }} ms）
        </span>
      </template>
    </el-alert>

    <section v-loading="loading" class="surface-card dingtalk-panel">
      <el-tabs v-model="activeTab">
        <el-tab-pane label="连接配置" name="config">
          <el-form
            ref="formRef"
            :model="form"
            :rules="rules"
            :disabled="!canUpdate"
            label-position="top"
            class="dingtalk-form"
          >
            <div class="form-section">
              <div class="section-head">
                <h3>基础连接</h3>
                <p>填写钉钉自建应用的凭证，AppSecret 使用服务端密钥加密存储，不落明文。</p>
              </div>
              <div class="form-grid">
                <el-form-item label="启用钉钉同步" class="span-2">
                  <el-switch v-model="form.enabled" active-text="启用" inactive-text="停用" />
                  <span class="field-hint">停用后不会自动同步，已同步的钉钉用户不受影响。</span>
                </el-form-item>
                <el-form-item label="CorpId（企业 ID）" prop="corp_id">
                  <el-input v-model="form.corp_id" placeholder="例如 dingxxxxxxxxxxxxxxxx" />
                </el-form-item>
                <el-form-item label="AppKey" prop="app_key">
                  <el-input v-model="form.app_key" placeholder="自建应用 AppKey" />
                </el-form-item>
                <el-form-item label="AppSecret">
                  <el-input
                    v-model="form.app_secret"
                    type="password"
                    show-password
                    autocomplete="new-password"
                    :placeholder="config?.has_secret ? '已保存，留空表示保持不变' : '请输入自建应用 AppSecret'"
                  />
                </el-form-item>
                <el-form-item label="AgentId">
                  <el-input-number
                    v-model="form.agent_id"
                    :min="1"
                    controls-position="right"
                    placeholder="应用 AgentId"
                    class="full-width"
                  />
                </el-form-item>
                <el-form-item label="同步间隔（分钟）" prop="sync_interval_minutes">
                  <el-input-number
                    v-model="form.sync_interval_minutes"
                    :min="5"
                    :max="10080"
                    controls-position="right"
                    class="full-width"
                  />
                </el-form-item>
              </div>
            </div>

            <div class="form-section">
              <div class="section-head">
                <h3>同步策略</h3>
                <p>钉钉部门挂载到所选根部门下，与 AD 同步的部门树完全隔离；新员工自动创建为系统账号。</p>
              </div>
              <div class="form-grid">
                <el-form-item label="默认角色">
                  <el-select
                    v-model="form.default_role_id"
                    clearable
                    placeholder="未配置时使用普通员工"
                    class="full-width"
                  >
                    <el-option
                      v-for="role in options.roles"
                      :key="role.id"
                      :label="`${role.name}（${role.code}）`"
                      :value="role.id"
                    />
                  </el-select>
                </el-form-item>
                <el-form-item label="钉钉组织根部门" prop="root_dept_id">
                  <el-select
                    v-model="form.root_dept_id"
                    clearable
                    placeholder="选择钉钉组织树的挂载部门"
                    class="full-width"
                  >
                    <el-option
                      v-for="dept in deptOptions"
                      :key="dept.value"
                      :label="dept.label"
                      :value="dept.value"
                    />
                  </el-select>
                  <p class="field-hint">
                    启用同步前必须选择挂载部门；如无合适的本地部门，请先在「组织架构」页面创建（例如「钉钉组织」）。
                  </p>
                </el-form-item>
                <el-form-item label="离职自动停用" class="span-2">
                  <el-switch v-model="form.disable_on_leave" active-text="启用" inactive-text="停用" />
                  <span class="field-hint">
                    钉钉通讯录中已不存在（离职/移除）的钉钉用户将被停用，不物理删除。
                  </span>
                </el-form-item>
                <el-form-item label="按手机号/邮箱匹配已有账号" class="span-2">
                  <el-switch v-model="form.match_existing" active-text="启用" inactive-text="停用" />
                  <span class="field-hint">
                    优先按钉钉 UserId 匹配；未命中时按手机号/邮箱匹配已有账号，仅补齐绑定关系，不改动其部门与状态。
                  </span>
                </el-form-item>
                <el-form-item label="当前策略" class="span-2">
                  <div class="policy-summary">
                    <span><strong>默认角色：</strong>{{ roleLabel }}</span>
                    <span><strong>根部门：</strong>{{ deptLabel }}</span>
                    <span><strong>离职策略：</strong>{{ form.disable_on_leave ? '自动停用（保留历史）' : '仅记录提醒' }}</span>
                    <span><strong>与 AD 关系：</strong>独立部门树，匹配到的 AD 用户仅补绑定，不覆盖</span>
                  </div>
                </el-form-item>
              </div>
            </div>

            <div class="form-section">
              <div class="section-head">
                <h3>审批对接</h3>
                <p>
                  领用、借用、调拨申请可提交到钉钉审批（完全替代系统内审批）；申请人未绑定钉钉账号时自动回退系统内审批。
                </p>
              </div>
              <div class="form-grid">
                <el-form-item label="启用钉钉审批对接" class="span-2">
                  <el-switch v-model="form.approval_enabled" active-text="启用" inactive-text="停用" />
                  <span class="field-hint">停用后新单据继续走系统内审批，已在钉钉中的单据不受影响。</span>
                </el-form-item>
                <el-form-item label="领用申请审批模板编码" prop="requisition_process_code">
                  <el-input
                    v-model="form.requisition_process_code"
                    placeholder="钉钉 OA 审批模板 processCode"
                  />
                </el-form-item>
                <el-form-item label="借用申请审批模板编码" prop="borrow_process_code">
                  <el-input
                    v-model="form.borrow_process_code"
                    placeholder="钉钉 OA 审批模板 processCode"
                  />
                </el-form-item>
                <el-form-item label="调拨申请审批模板编码" prop="transfer_process_code">
                  <el-input
                    v-model="form.transfer_process_code"
                    placeholder="钉钉 OA 审批模板 processCode"
                  />
                </el-form-item>
                <el-form-item
                  label="回调 Token"
                  class="span-2"
                >
                  <el-input
                    v-model="form.callback_token"
                    autocomplete="new-password"
                    :placeholder="config?.has_callback_token ? '已保存，留空表示保持不变' : '钉钉事件订阅的加密 token'"
                  />
                  <span class="field-hint">与钉钉「事件订阅」中填写的加密 token 保持一致。</span>
                </el-form-item>
                <el-form-item label="回调 AES Key" prop="callback_aes_key" class="span-2">
                  <el-input
                    v-model="form.callback_aes_key"
                    autocomplete="new-password"
                    :placeholder="config?.has_callback_aes_key ? '已保存，留空表示保持不变' : '43 位随机字符串（EncodingAESKey）'"
                  />
                  <span class="field-hint">
                    与钉钉「事件订阅」中填写的 EncodingAESKey 保持一致；回调地址为当前服务地址的
                    <code>/api/v1/system/dingtalk/callback</code>。
                  </span>
                </el-form-item>
              </div>
            </div>

            <div v-if="canUpdate" class="form-actions">
              <el-button :icon="Connection" :loading="testing" @click="handleTest">测试连接</el-button>
              <el-button type="primary" :icon="CircleCheck" :loading="saving" @click="handleSave">
                保存配置
              </el-button>
            </div>
            <el-alert
              v-else
              type="info"
              :closable="false"
              show-icon
              title="当前账号仅可查看钉钉配置，修改需 system:dingtalk:update 权限。"
            />
          </el-form>
        </el-tab-pane>

        <el-tab-pane label="同步日志" name="logs">
          <div class="log-toolbar">
            <el-select
              v-model="logQuery.status"
              clearable
              placeholder="全部状态"
              class="log-status"
              @change="handleLogSearch"
            >
              <el-option label="成功" value="SUCCESS" />
              <el-option label="部分成功" value="PARTIAL" />
              <el-option label="失败" value="FAILED" />
              <el-option label="执行中" value="RUNNING" />
            </el-select>
            <el-button :icon="Refresh" :loading="logsLoading" @click="loadLogs()">刷新日志</el-button>
          </div>

          <el-table
            v-loading="logsLoading"
            :data="logs"
            row-key="id"
            empty-text="暂无同步记录，保存配置后可手动触发同步"
          >
            <el-table-column label="开始时间" width="170">
              <template #default="{ row }">
                <span class="mono">{{ formatDateTime(row.started_at) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="触发方式" width="100">
              <template #default="{ row }">
                <el-tag size="small" effect="plain" :type="row.trigger_type === 'MANUAL' ? 'primary' : 'info'">
                  {{ row.trigger_type === 'MANUAL' ? '手动' : '定时' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-tag size="small" :type="statusMeta(row.status).type">{{ statusMeta(row.status).label }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="部门变化" width="130">
              <template #default="{ row }">
                新增 {{ row.dept_created }} / 更新 {{ row.dept_updated }}
                <span class="muted">（共 {{ row.dept_total }}）</span>
              </template>
            </el-table-column>
            <el-table-column label="用户变化" width="210">
              <template #default="{ row }">
                新增 {{ row.user_created }} / 更新 {{ row.user_updated }} / 匹配 {{ row.user_matched }}
                <span class="muted">（共 {{ row.user_total }}）</span>
              </template>
            </el-table-column>
            <el-table-column label="停用" width="80">
              <template #default="{ row }">{{ row.user_disabled }}</template>
            </el-table-column>
            <el-table-column label="耗时" width="90">
              <template #default="{ row }">{{ durationText(row.duration_ms) }}</template>
            </el-table-column>
            <el-table-column label="操作人" width="110">
              <template #default="{ row }">{{ row.operator_name || '系统' }}</template>
            </el-table-column>
            <el-table-column label="结果" min-width="220" show-overflow-tooltip>
              <template #default="{ row }">
                <span :class="{ 'text-danger': row.status === 'FAILED' }">{{ row.message || '—' }}</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="80" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" size="small" :icon="View" @click="openDetail(row)">
                  详情
                </el-button>
              </template>
            </el-table-column>
          </el-table>

          <div class="log-pagination">
            <el-pagination
              :current-page="logQuery.page"
              :page-size="logQuery.page_size"
              :page-sizes="[10, 20, 50]"
              :total="logTotal"
              layout="total, sizes, prev, pager, next"
              background
              @current-change="handleLogPageChange"
              @size-change="handleLogSizeChange"
            />
          </div>
        </el-tab-pane>
      </el-tabs>
    </section>

    <el-dialog v-model="detailVisible" title="同步日志详情" width="680px" destroy-on-close>
      <div v-loading="detailLoading">
        <template v-if="activeLog">
          <div class="detail-head">
            <el-tag :type="statusMeta(activeLog.status).type" round>
              {{ statusMeta(activeLog.status).label }}
            </el-tag>
            <span class="muted">{{ formatDateTime(activeLog.started_at) }}</span>
            <span class="muted">耗时 {{ durationText(activeLog.duration_ms) }}</span>
            <span class="muted">{{ activeLog.operator_name || '系统' }}</span>
          </div>

          <div class="detail-grid">
            <div><span>部门总数</span><strong>{{ activeLog.dept_total }}</strong></div>
            <div><span>新增部门</span><strong>{{ activeLog.dept_created }}</strong></div>
            <div><span>更新部门</span><strong>{{ activeLog.dept_updated }}</strong></div>
            <div><span>用户总数</span><strong>{{ activeLog.user_total }}</strong></div>
            <div><span>新增用户</span><strong>{{ activeLog.user_created }}</strong></div>
            <div><span>更新用户</span><strong>{{ activeLog.user_updated }}</strong></div>
            <div><span>匹配用户</span><strong>{{ activeLog.user_matched }}</strong></div>
            <div><span>停用用户</span><strong>{{ activeLog.user_disabled }}</strong></div>
            <div><span>跳过用户</span><strong>{{ activeLog.user_skipped }}</strong></div>
            <div><span>异常数量</span><strong>{{ activeLog.error_count }}</strong></div>
          </div>

          <el-alert
            v-if="activeLog.error_message"
            type="error"
            :closable="false"
            show-icon
            title="错误信息"
            :description="activeLog.error_message"
            class="detail-alert"
          />

          <div class="detail-section">
            <h4>执行摘要</h4>
            <p class="detail-message">{{ activeLog.message || '—' }}</p>
          </div>

          <div class="detail-section">
            <h4>处理明细</h4>
            <el-empty v-if="!activeLog.details?.length" description="无明细记录" :image-size="64" />
            <ul v-else class="detail-list">
              <li v-for="(item, index) in activeLog.details" :key="index" :class="`level-${item.level}`">
                <el-tag
                  size="small"
                  :type="item.level === 'error' ? 'danger' : item.level === 'warning' ? 'warning' : 'info'"
                >
                  {{ item.level }}
                </el-tag>
                <span>{{ item.message }}</span>
              </li>
            </ul>
          </div>
        </template>
      </div>
    </el-dialog>
  </div>
</template>

<style scoped>
.dingtalk-page {
  --dingtalk-border: var(--border);
}

.status-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
  margin-bottom: 16px;
}

.status-card {
  display: flex;
  align-items: flex-start;
  gap: 13px;
  padding: 18px 18px 16px;
}

.status-icon {
  display: grid;
  place-items: center;
  width: 42px;
  height: 42px;
  flex-shrink: 0;
  border-radius: 13px;
  background: var(--surface-muted);
  color: var(--text-3);
}

.status-icon.is-on {
  background: var(--gradient-brand-soft);
  color: var(--brand);
}

.status-icon.is-off {
  background: rgba(148, 163, 184, 0.14);
  color: var(--text-3);
}

.status-icon.is-alert {
  background: rgba(239, 68, 68, 0.1);
  color: #ef4444;
}

.status-icon svg {
  width: 19px;
  height: 19px;
}

.status-body {
  min-width: 0;
}

.status-label {
  margin: 0;
  color: var(--text-3);
  font-size: 11.5px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.status-value {
  margin: 5px 0 4px;
  color: var(--text-1);
  font-size: 15px;
  font-weight: 650;
}

.status-note {
  margin: 0;
  color: var(--text-3);
  font-size: 11.5px;
  line-height: 1.5;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sync-alert {
  margin-bottom: 14px;
}

.dingtalk-panel {
  padding: 6px 22px 22px;
}

.dingtalk-form {
  max-width: 1080px;
}

.form-section {
  padding: 20px 0 4px;
  border-bottom: 1px dashed var(--dingtalk-border);
}

.form-section:last-of-type {
  border-bottom: none;
}

.section-head {
  margin-bottom: 16px;
}

.section-head h3 {
  margin: 0;
  color: var(--text-1);
  font-size: 15px;
  font-weight: 650;
}

.section-head p {
  margin: 4px 0 0;
  color: var(--text-3);
  font-size: 12px;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  column-gap: 20px;
}

.form-grid .span-2 {
  grid-column: span 2;
}

.full-width {
  width: 100%;
}

.field-hint {
  margin-left: 12px;
  color: var(--text-3);
  font-size: 11.5px;
}

.policy-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 22px;
  padding: 10px 14px;
  border: 1px solid var(--dingtalk-border);
  border-radius: 10px;
  background: var(--surface-muted);
  color: var(--text-2);
  font-size: 12px;
}

.policy-summary strong {
  color: var(--text-1);
  font-weight: 600;
}

.form-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding-top: 18px;
}

.log-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 4px 0 16px;
}

.log-status {
  width: 170px;
}

.mono {
  font-variant-numeric: tabular-nums;
  color: var(--text-2);
  font-size: 12px;
}

.muted {
  color: var(--text-3);
  font-size: 11.5px;
}

.text-danger {
  color: #ef4444;
}

.log-pagination {
  display: flex;
  justify-content: flex-end;
  padding-top: 16px;
}

.detail-head {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}

.detail-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 16px;
}

.detail-grid > div {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px 12px;
  border: 1px solid var(--dingtalk-border);
  border-radius: 10px;
  background: var(--surface-muted);
}

.detail-grid span {
  color: var(--text-3);
  font-size: 11.5px;
}

.detail-grid strong {
  color: var(--text-1);
  font-size: 16px;
  font-weight: 650;
}

.detail-alert {
  margin-bottom: 16px;
}

.detail-section {
  margin-bottom: 16px;
}

.detail-section h4 {
  margin: 0 0 8px;
  color: var(--text-1);
  font-size: 13px;
  font-weight: 650;
}

.detail-message {
  margin: 0;
  color: var(--text-2);
  font-size: 12.5px;
  line-height: 1.7;
}

.detail-list {
  display: flex;
  flex-direction: column;
  gap: 7px;
  max-height: 300px;
  margin: 0;
  padding: 0;
  overflow-y: auto;
  list-style: none;
}

.detail-list li {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  color: var(--text-2);
  font-size: 12px;
  line-height: 1.6;
}

.detail-list li.level-error span {
  color: #ef4444;
}

.detail-list li.level-warning span {
  color: #b45309;
}

@media (max-width: 1200px) {
  .status-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 720px) {
  .status-grid,
  .form-grid,
  .detail-grid {
    grid-template-columns: 1fr;
  }

  .form-grid .span-2 {
    grid-column: span 1;
  }
}
</style>
