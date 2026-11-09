<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, type FormInstance } from 'element-plus'
import { CircleCheck, Refresh, SetUp } from '@element-plus/icons-vue'

import { orgApi } from '@/api/org'
import { useAuthStore } from '@/stores/auth'
import type { SyncPolicy } from '@/types/org'

const auth = useAuthStore()
const canUpdate = computed(() => auth.hasPerm('system:org-sync-policy:update'))

const SOURCE_OPTIONS = [
  { value: 'ldap', label: '域控（AD）' },
  { value: 'dingtalk', label: '钉钉' },
  { value: 'local', label: '本地' },
]

interface PriorityState {
  first: string
  second: string
  third: string
}

const SLOTS = ['first', 'second', 'third'] as const
type Slot = (typeof SLOTS)[number]

const loading = ref(false)
const saving = ref(false)
const formRef = ref<FormInstance>()
const version = ref(1)
const conflictStrategy = ref('fill_empty')
const protectLocal = ref(true)
const disableScope = ref('own')
const priority = reactive<PriorityState>({ first: 'ldap', second: 'dingtalk', third: 'local' })
const previous = reactive<PriorityState>({ ...priority })

function onPriorityChange(slot: Slot, next: string): void {
  for (const other of SLOTS) {
    if (other !== slot && priority[other] === next) {
      priority[other] = previous[slot]
      previous[other] = previous[slot]
      break
    }
  }
  previous[slot] = next
}

function setPriorityValues(raw: string): void {
  const parts = raw.split(',')
  const picked = new Set<string>()
  for (const part of parts) {
    if (part && !picked.has(part)) picked.add(part)
  }
  for (const source of ['ldap', 'dingtalk', 'local']) {
    if (!picked.has(source)) picked.add(source)
  }
  const ordered = [...picked]
  priority.first = ordered[0] ?? 'ldap'
  priority.second = ordered[1] ?? 'dingtalk'
  priority.third = ordered[2] ?? 'local'
  previous.first = priority.first
  previous.second = priority.second
  previous.third = priority.third
}

function applyPolicy(policy: SyncPolicy): void {
  version.value = policy.version
  setPriorityValues(policy.source_priority)
  conflictStrategy.value = policy.conflict_strategy
  protectLocal.value = policy.protect_local
  disableScope.value = policy.disable_scope
}

async function loadPolicy(): Promise<void> {
  loading.value = true
  try {
    applyPolicy(await orgApi.getSyncPolicy())
  } finally {
    loading.value = false
  }
}

const currentPriorityText = computed(() =>
  [priority.first, priority.second, priority.third]
    .map((value) => SOURCE_OPTIONS.find((option) => option.value === value)?.label ?? value)
    .join(' > '),
)

async function savePolicy(): Promise<void> {
  if (!canUpdate.value) return
  const ordered = [priority.first, priority.second, priority.third]
  if (new Set(ordered).size !== 3) {
    ElMessage.warning('三个主源优先级不能重复')
    return
  }
  saving.value = true
  try {
    const policy = await orgApi.updateSyncPolicy({
      source_priority: ordered.join(','),
      conflict_strategy: conflictStrategy.value,
      protect_local: protectLocal.value,
      disable_scope: disableScope.value,
      version: version.value,
    })
    applyPolicy(policy)
    ElMessage.success('组织同步策略已保存，下次同步生效')
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  void loadPolicy()
})
</script>

<template>
  <div class="page policy-page" v-loading="loading">
    <header class="page-header">
      <div>
        <p class="page-eyebrow">ORGANIZATION SYNC POLICY</p>
        <h1 class="page-title">组织同步策略</h1>
        <p class="page-subtitle">
          组织架构同时接入域控、钉钉与本地三个来源；这里定义来源优先级、字段冲突策略与停用联动规则。
        </p>
      </div>
      <div class="page-actions">
        <el-button :icon="Refresh" @click="loadPolicy">刷新</el-button>
      </div>
    </header>

    <section class="surface-card">
      <div class="panel-head">
        <div>
          <p class="panel-eyebrow">MATRIX</p>
          <h2 class="panel-title">生效规则说明</h2>
        </div>
      </div>
      <div class="rule-grid">
        <div class="rule-item">
          <span class="rule-icon"><el-icon><SetUp /></el-icon></span>
          <div>
            <strong>同源全量刷新</strong>
            <p>
              来源相同的部门 / 用户每次同步都以数据源为准完整刷新；来源不同时才按下方优先级与冲突策略处理。
            </p>
          </div>
        </div>
        <div class="rule-item">
          <span class="rule-icon"><el-icon><SetUp /></el-icon></span>
          <div>
            <strong>高优先级来源只补空</strong>
            <p>
              当目标数据来自更高优先级来源时，低优先级同步只会补充空字段（fill_empty），绝不覆盖已有内容。
            </p>
          </div>
        </div>
        <div class="rule-item">
          <span class="rule-icon"><el-icon><CircleCheck /></el-icon></span>
          <div>
            <strong>外部标识始终绑定</strong>
            <p>
              无论冲突等级如何，域控 DN / 钉钉 UserID 与同步时间都会记录到匹配的账号上，用于后续识别与审批人匹配。
            </p>
          </div>
        </div>
        <div class="rule-item">
          <span class="rule-icon"><el-icon><CircleCheck /></el-icon></span>
          <div>
            <strong>停用不删除</strong>
            <p>
              数据源中离职或禁用的成员，其系统账号只会被停用（保留历史记录），不会物理删除；最后一名超级管理员始终受保护。
            </p>
          </div>
        </div>
      </div>
    </section>

    <section class="surface-card">
      <div class="panel-head">
        <div>
          <p class="panel-eyebrow">CONFIGURATION</p>
          <h2 class="panel-title">策略配置</h2>
        </div>
      </div>

      <el-form ref="formRef" label-position="top" class="policy-form" :disabled="!canUpdate">
        <el-form-item label="主源优先级">
          <div class="priority-row">
            <template v-for="(slot, index) in (['first', 'second', 'third'] as const)" :key="slot">
              <el-select
                v-model="priority[slot]"
                class="priority-select"
                :placeholder="`第 ${index + 1} 主源`"
                @change="(value: string) => onPriorityChange(slot, value)"
              >
                <el-option
                  v-for="option in SOURCE_OPTIONS"
                  :key="option.value"
                  :label="option.label"
                  :value="option.value"
                />
              </el-select>
              <span v-if="index < 2" class="priority-arrow">›</span>
            </template>
          </div>
          <p class="field-hint">
            当前顺序：{{ currentPriorityText }}。低优先级来源同步时，不会覆盖来自更高优先级来源的数据。
          </p>
        </el-form-item>

        <el-form-item label="跨来源冲突策略">
          <el-radio-group v-model="conflictStrategy" class="strategy-group">
            <el-radio value="skip" border>
              <div class="strategy-option">
                <strong>跳过（skip）</strong>
                <p>只绑定外部标识与同步时间，不改动任何字段。</p>
              </div>
            </el-radio>
            <el-radio value="fill_empty" border>
              <div class="strategy-option">
                <strong>补空（fill_empty）</strong>
                <p>仅补充姓名、邮箱、工号、电话等空字段，不修改部门、状态与来源。</p>
              </div>
            </el-radio>
            <el-radio value="overwrite" border>
              <div class="strategy-option">
                <strong>覆盖（overwrite）</strong>
                <p>以同步数据为准全量覆盖，来源标记也会切换（谨慎使用）。</p>
              </div>
            </el-radio>
          </el-radio-group>
        </el-form-item>

        <el-form-item label="保护本地数据">
          <el-switch
            v-model="protectLocal"
            inline-prompt
            active-text="开启"
            inactive-text="关闭"
          />
          <p class="field-hint">
            开启后，本地手工维护的部门 / 用户永远只被补空，不会被域控或钉钉同步覆盖。
          </p>
        </el-form-item>

        <el-form-item label="停用联动范围">
          <el-radio-group v-model="disableScope" class="scope-group">
            <el-radio value="own" border>
              <div class="strategy-option">
                <strong>仅本源用户</strong>
                <p>只停用由该来源创建的账号；被匹配绑定的其他来源账号不受影响。</p>
              </div>
            </el-radio>
            <el-radio value="any" border>
              <div class="strategy-option">
                <strong>含绑定用户</strong>
                <p>绑定了该来源标识的账号（含其他来源）在名册缺失时也会被停用。</p>
              </div>
            </el-radio>
          </el-radio-group>
        </el-form-item>

        <div class="policy-actions">
          <el-button type="primary" :loading="saving" :disabled="!canUpdate" @click="savePolicy">
            保存策略
          </el-button>
          <span v-if="!canUpdate" class="muted">当前账号无编辑权限，仅可查看</span>
        </div>
      </el-form>
    </section>
  </div>
</template>

<style scoped>
.policy-page {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.page-actions {
  display: flex;
  gap: 10px;
}

.surface-card {
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
  margin-top: 4px;
  color: var(--text-1);
  font-size: 17px;
  font-weight: 650;
  letter-spacing: -0.015em;
}

.rule-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.rule-item {
  display: flex;
  gap: 12px;
  padding: 14px 15px;
  border: 1px solid var(--border);
  border-radius: 13px;
  background: var(--surface-muted);
}

.rule-icon {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  flex-shrink: 0;
  border-radius: 9px;
  background: var(--brand-soft);
  color: var(--brand);
}

.rule-item strong {
  display: block;
  color: var(--text-1);
  font-size: 13px;
}

.rule-item p {
  margin: 4px 0 0;
  color: var(--text-2);
  font-size: 11.5px;
  line-height: 1.65;
}

.policy-form {
  max-width: 860px;
}

.priority-row {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
}

.priority-select {
  flex: 1;
  min-width: 0;
}

.priority-arrow {
  color: var(--text-3);
  font-size: 18px;
  font-weight: 700;
}

.strategy-group,
.scope-group {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  width: 100%;
}

.strategy-group :deep(.el-radio),
.scope-group :deep(.el-radio) {
  flex: 1;
  min-width: 220px;
  height: auto;
  margin-right: 0;
  padding: 13px 15px;
  white-space: normal;
}

.strategy-option strong {
  display: block;
  color: var(--text-1);
  font-size: 13px;
}

.strategy-option p {
  margin: 4px 0 0;
  color: var(--text-3);
  font-size: 11px;
  line-height: 1.6;
  white-space: normal;
}

.field-hint {
  width: 100%;
  margin: 6px 0 0;
  color: var(--text-3);
  font-size: 11.5px;
  line-height: 1.6;
}

.policy-actions {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-top: 6px;
}

.muted {
  color: var(--text-3);
  font-size: 12px;
}

@media (max-width: 900px) {
  .rule-grid {
    grid-template-columns: 1fr;
  }

  .strategy-group :deep(.el-radio),
  .scope-group :deep(.el-radio) {
    min-width: 100%;
  }
}
</style>
