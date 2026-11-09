<script setup lang="ts">
import { computed } from 'vue'

import FlowSteps from '@/components/asset-flow/FlowSteps.vue'
import type { AssetRequestItem, TagType } from '@/types/assetFlow'
import { APPROVAL_STEP_TAG_TYPES } from '@/types/assetFlow'
import { formatDateTime } from '@/utils/format'

const props = defineProps<{
  modelValue: boolean
  request: AssetRequestItem | null
}>()

const emit = defineEmits<{
  (event: 'update:modelValue', value: boolean): void
}>()

const DINGTALK_STATUS_META: Record<
  NonNullable<AssetRequestItem['dingtalk_status']>,
  { label: string; type: TagType }
> = {
  RUNNING: { label: '钉钉审批中', type: 'warning' },
  APPROVED: { label: '钉钉已通过', type: 'success' },
  REJECTED: { label: '钉钉已驳回', type: 'danger' },
  TERMINATED: { label: '钉钉已撤销', type: 'info' },
}

const hasDingTalk = computed(() => Boolean(props.request?.dingtalk_instance_id))
const dingtalkMeta = computed(() => {
  const status = props.request?.dingtalk_status
  return status ? DINGTALK_STATUS_META[status] : null
})

const dueText = computed(() => {
  const request = props.request
  if (!request?.expected_return_date) return '—'
  if (request.days_to_due === null) return request.expected_return_date
  if (request.days_to_due < 0) return `已逾期 ${Math.abs(request.days_to_due)} 天`
  return `${request.expected_return_date}（剩 ${request.days_to_due} 天）`
})

const approvals = computed(() => props.request?.approvals ?? [])
const hasApprovalFlow = computed(
  () => Boolean(props.request) && props.request?.request_type !== 'RETURN',
)
const isConfiguredFlow = computed(() => Boolean(props.request?.flow_id))
const approvalSteps = computed(() => props.request?.approval_steps ?? [])
const workflowText = computed(() => {
  if (!props.request) return '—'
  if (isConfiguredFlow.value) {
    return `${props.request.flow_name || '审批流程'}（共 ${
      props.request.total_steps || approvalSteps.value.length
    } 级）`
  }
  return props.request.dept_approval_required
    ? '部门管理员审批 → 资产管理员审批'
    : '资产管理员审批'
})
const currentNodeText = computed(() => {
  if (!props.request) return '—'
  if (isConfiguredFlow.value) {
    if (!props.request.current_step_name) return '—'
    const approvers = props.request.current_approvers
    return approvers.length
      ? `${props.request.current_step_name} · 待 ${approvers.join('、')} 处理`
      : props.request.current_step_name
  }
  return props.request.approval_stage_label || '—'
})
const assetPending = computed(
  () => Boolean(props.request) && !props.request?.asset_id,
)
</script>

<template>
  <el-drawer
    :model-value="modelValue"
    size="640px"
    class="request-drawer"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <template #header>
      <div class="drawer-head">
        <div>
          <p class="drawer-eyebrow">{{ request?.request_type_label || '业务单据' }}</p>
          <h3>{{ request?.request_no || '单据详情' }}</h3>
        </div>
        <div class="drawer-tags">
          <el-tag
            v-if="hasDingTalk"
            :type="dingtalkMeta?.type ?? 'info'"
            effect="light"
            size="large"
          >
            {{ dingtalkMeta?.label ?? '钉钉审批' }}
          </el-tag>
          <el-tag
            v-if="request"
            :type="request.status_tag_type"
            effect="light"
            size="large"
          >
            {{ request.status_label }}
          </el-tag>
        </div>
      </div>
    </template>

    <template v-if="request">
      <FlowSteps :request-type="request.request_type" :status="request.status" />

      <div class="detail-section">
        <p class="detail-section-title">单据信息</p>
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="单据编号">{{ request.request_no }}</el-descriptions-item>
          <el-descriptions-item label="单据类型">
            {{ request.request_type_label }}
          </el-descriptions-item>
          <el-descriptions-item label="申请人">{{ request.applicant_name }}</el-descriptions-item>
          <el-descriptions-item label="申请部门">
            {{ request.applicant_dept_name || '—' }}
          </el-descriptions-item>
          <el-descriptions-item label="申请时间">
            {{ formatDateTime(request.created_at) }}
          </el-descriptions-item>
          <el-descriptions-item label="预计归还">
            {{ dueText }}
          </el-descriptions-item>
          <el-descriptions-item v-if="hasApprovalFlow" label="审批流程">
            {{ hasDingTalk ? '钉钉审批（替代系统内审批）' : workflowText }}
          </el-descriptions-item>
          <el-descriptions-item v-if="hasApprovalFlow" label="当前节点">
            {{ hasDingTalk ? (dingtalkMeta?.label ?? '钉钉审批') : currentNodeText }}
          </el-descriptions-item>
          <el-descriptions-item v-if="hasDingTalk" label="钉钉实例" :span="2">
            <span class="mono">{{ request.dingtalk_instance_id }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="申请原因" :span="2">
            {{ request.reason || '—' }}
          </el-descriptions-item>
        </el-descriptions>
      </div>

      <div v-if="hasApprovalFlow" class="detail-section">
        <p class="detail-section-title">审批进度</p>
        <div v-if="isConfiguredFlow" class="flow-progress">
          <div
            v-for="step in approvalSteps"
            :key="step.step_no"
            class="flow-progress-item"
            :class="`is-${step.status.toLowerCase()}`"
          >
            <div class="flow-progress-head">
              <span class="flow-step-no">{{ step.step_no }}</span>
              <strong>{{ step.step_name }}</strong>
              <el-tag
                :type="APPROVAL_STEP_TAG_TYPES[step.status] || 'info'"
                size="small"
                effect="light"
              >
                {{ step.status_label }}
              </el-tag>
              <span class="flow-mode">{{ step.approve_mode === 'ALL' ? '会签' : '或签' }}</span>
            </div>
            <div class="flow-progress-meta">
              <span v-if="step.approvers.length">审批人：{{ step.approvers.join('、') }}</span>
              <span v-if="step.pending_approvers.length" class="is-pending-text">
                待处理：{{ step.pending_approvers.join('、') }}
              </span>
              <span v-if="!step.approvers.length && !step.pending_approvers.length">
                未匹配到审批人，按配置跳过
              </span>
              <span v-if="step.acted_at">{{ formatDateTime(step.acted_at) }}</span>
            </div>
            <p v-if="step.comment" class="flow-progress-comment">意见：{{ step.comment }}</p>
          </div>
        </div>
        <div class="approval-timeline">
          <el-timeline>
            <el-timeline-item
              :timestamp="formatDateTime(request.created_at)"
              type="primary"
            >
              <strong>提交申请</strong>
              <span class="timeline-actor">{{ request.applicant_name }}</span>
            </el-timeline-item>
            <el-timeline-item
              v-for="item in approvals"
              :key="item.id"
              :timestamp="formatDateTime(item.operated_at)"
              :type="item.action === 'APPROVE' ? 'success' : 'danger'"
            >
              <strong>{{ item.step_name }}{{ item.action_label }}</strong>
              <span class="timeline-actor">{{ item.approver_name || '—' }}</span>
              <p v-if="item.comment" class="timeline-comment">
                意见：{{ item.comment }}
              </p>
            </el-timeline-item>
            <el-timeline-item
              v-if="request.status === 'PENDING_APPROVAL'"
              timestamp="等待处理"
              type="warning"
              hollow
            >
              <strong>
                {{
                  hasDingTalk
                    ? '钉钉审批中（请在钉钉内处理）'
                    : isConfiguredFlow
                      ? `${request.current_step_name || '审批'}处理中`
                      : `${request.approval_stage_label || '审批'}处理中`
                }}
              </strong>
              <span
                v-if="!hasDingTalk && isConfiguredFlow && request.current_approvers.length"
                class="timeline-actor"
              >
                待 {{ request.current_approvers.join('、') }}
              </span>
            </el-timeline-item>
            <el-timeline-item
              v-else-if="request.status === 'REJECTED'"
              :timestamp="formatDateTime(request.approved_at)"
              type="danger"
            >
              <strong>审批未通过，流程结束</strong>
            </el-timeline-item>
            <el-timeline-item
              v-else-if="request.status === 'CANCELLED'"
              :timestamp="formatDateTime(request.confirmed_at)"
              type="info"
            >
              <strong>申请人撤销，流程结束</strong>
            </el-timeline-item>
            <el-timeline-item
              v-else
              :timestamp="formatDateTime(request.approved_at)"
              type="success"
            >
              <strong>审批完成</strong>
              <span class="timeline-actor">{{ request.approver_name || '—' }}</span>
            </el-timeline-item>
          </el-timeline>
        </div>
      </div>

      <div class="detail-section">
        <p class="detail-section-title">资产信息</p>
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="申请分类" :span="2">
            {{ request.category_name }}
            <span class="muted">
              （{{
                request.request_type === 'RETURN'
                  ? '资产分类'
                  : request.include_child
                    ? '含下级分类（历史）'
                    : '最终分类'
              }}）
            </span>
          </el-descriptions-item>
          <template v-if="request.asset_id">
            <el-descriptions-item label="资产编号">
              <span class="mono">{{ request.asset_no }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="资产名称">{{ request.asset_name }}</el-descriptions-item>
            <el-descriptions-item label="资产型号">
              {{ request.asset_model_name || '—' }}
            </el-descriptions-item>
            <el-descriptions-item label="资产状态">
              {{ request.asset_status_label || '—' }}
            </el-descriptions-item>
            <el-descriptions-item label="当前责任人">
              {{ request.asset_custodian_name || '—' }}
            </el-descriptions-item>
            <el-descriptions-item label="存放位置">
              {{ request.asset_location || '—' }}
            </el-descriptions-item>
          </template>
          <el-descriptions-item v-else label="资产分配" :span="2">
            <div class="asset-pending">
              <el-tag type="warning" effect="light" size="small">待出库分配</el-tag>
              <span v-if="assetPending">
                资产管理员将在确认出库时，从该分类的在库资产中选择并绑定具体资产编号。
              </span>
            </div>
          </el-descriptions-item>
        </el-descriptions>
      </div>

      <div class="detail-section">
        <p class="detail-section-title">出库与归还记录</p>
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="出库人">
            {{ request.outbound_by_name || '—' }}
          </el-descriptions-item>
          <el-descriptions-item label="出库时间">
            {{ formatDateTime(request.outbound_at) }}
          </el-descriptions-item>
          <el-descriptions-item label="出库位置" :span="2">
            {{ request.outbound_location || '—' }}
          </el-descriptions-item>
          <el-descriptions-item label="归还发起时间">
            {{ formatDateTime(request.return_requested_at) }}
          </el-descriptions-item>
          <el-descriptions-item label="归还确认人">
            {{ request.confirm_by_name || '—' }}
          </el-descriptions-item>
          <el-descriptions-item label="确认时间">
            {{ formatDateTime(request.confirmed_at) }}
          </el-descriptions-item>
          <el-descriptions-item label="确认意见">
            {{ request.confirm_comment || '—' }}
          </el-descriptions-item>
        </el-descriptions>
      </div>

      <div class="drawer-actions">
        <slot name="actions" :request="request" />
      </div>
    </template>
  </el-drawer>
</template>

<style scoped>
.drawer-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
}

.drawer-tags {
  display: flex;
  align-items: center;
  gap: 8px;
}

.drawer-head h3 {
  font-size: 18px;
  font-weight: 700;
  color: var(--text-1);
}

.drawer-eyebrow {
  color: var(--brand);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.14em;
}

.detail-section {
  margin-top: 20px;
}

.detail-section-title {
  margin-bottom: 10px;
  color: var(--text-2);
  font-size: 12.5px;
  font-weight: 650;
}

.approval-timeline {
  padding: 14px 16px 2px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--surface-muted);
}

.flow-progress {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 12px;
}

.flow-progress-item {
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: 11px;
  background: var(--surface);
}

.flow-progress-item.is-pending {
  border-color: color-mix(in srgb, var(--warning) 40%, var(--border));
  background: color-mix(in srgb, var(--warning) 6%, var(--surface));
}

.flow-progress-item.is-rejected {
  border-color: color-mix(in srgb, var(--danger) 40%, var(--border));
}

.flow-progress-item.is-skipped,
.flow-progress-item.is-waiting {
  opacity: 0.78;
}

.flow-progress-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.flow-progress-head strong {
  color: var(--text-1);
  font-size: 13px;
}

.flow-step-no {
  display: grid;
  place-items: center;
  width: 20px;
  height: 20px;
  border-radius: 7px;
  background: var(--brand-soft);
  color: var(--brand);
  font-family: var(--font-number);
  font-size: 11px;
  font-weight: 600;
}

.flow-mode {
  color: var(--text-3);
  font-size: 11px;
}

.flow-progress-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 14px;
  margin-top: 5px;
  color: var(--text-2);
  font-size: 11.5px;
}

.is-pending-text {
  color: var(--warning-strong, #b45309);
  font-weight: 600;
}

.flow-progress-comment {
  margin-top: 4px;
  color: var(--text-2);
  font-size: 12px;
}

.timeline-actor {
  margin-left: 8px;
  color: var(--text-3);
  font-size: 12px;
}

.timeline-comment {
  margin-top: 4px;
  color: var(--text-2);
  font-size: 12.5px;
}

.muted {
  color: var(--text-3);
  font-size: 12px;
}

.mono {
  font-family: var(--font-number);
  font-weight: 600;
}

.asset-pending {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  color: var(--text-2);
  font-size: 12.5px;
}

.drawer-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 24px;
  padding-top: 16px;
  border-top: 1px solid var(--border);
}
</style>
