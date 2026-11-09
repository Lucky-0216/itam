import type { AssetStatus } from '@/types/asset'

export type AssetRequestType = 'REQUISITION' | 'BORROW' | 'RETURN'
export type AssetRequestStatus =
  | 'PENDING_APPROVAL'
  | 'PENDING_OUTBOUND'
  | 'BORROWED'
  | 'PENDING_RETURN'
  | 'COMPLETED'
  | 'REJECTED'
  | 'CANCELLED'

export type TagType = 'primary' | 'success' | 'info' | 'warning' | 'danger'

export interface AvailableCategory {
  id: number
  parent_id: number | null
  name: string
  available_count: number
  has_children: boolean
}

export interface AvailableAsset {
  id: number
  asset_no: string
  name: string
  category_name: string | null
  model_id: number | null
  model_name: string | null
  serial_no: string | null
  location: string | null
  dept_id: number | null
  dept_name: string | null
  status: AssetStatus
  status_label: string
  version: number
}

export type ApprovalStage = 'DEPT' | 'ASSET'

export type ApprovalTaskStatus = 'PENDING' | 'WAITING' | 'APPROVED' | 'REJECTED' | 'SKIPPED'

export interface ApprovalStep {
  step_no: number
  step_code: string
  step_name: string
  approve_mode: 'OR' | 'ALL'
  status: ApprovalTaskStatus
  status_label: string
  approvers: string[]
  pending_approvers: string[]
  acted_at: string | null
  comment: string | null
}

export interface ApprovalRecordItem {
  id: number
  task_id: number | null
  step_no: number
  step_code: string
  step_name: string
  action: 'APPROVE' | 'REJECT'
  action_label: string
  approver_id: number | null
  approver_name: string | null
  comment: string | null
  operated_at: string
}

export interface ApprovalConfig {
  dept_approval_required: boolean
  version: number
  updated_by_name: string | null
  updated_at: string
}

export interface AssetRequestItem {
  id: number
  request_no: string
  request_type: AssetRequestType
  request_type_label: string
  status: AssetRequestStatus
  status_label: string
  status_tag_type: TagType
  category_id: number
  category_name: string
  include_child: boolean
  approval_stage: ApprovalStage | null
  approval_stage_label: string | null
  dept_approval_required: boolean
  flow_id: number | null
  flow_name: string | null
  current_step_no: number | null
  current_step_name: string | null
  current_approvers: string[]
  total_steps: number
  approval_steps: ApprovalStep[]
  asset_id: number | null
  asset_no: string | null
  asset_name: string | null
  asset_version: number
  asset_model_name: string | null
  asset_status: AssetStatus | null
  asset_status_label: string | null
  asset_location: string | null
  asset_custodian_id: number | null
  asset_custodian_name: string | null
  applicant_id: number
  applicant_name: string
  applicant_dept_id: number | null
  applicant_dept_name: string | null
  reason: string | null
  expected_return_date: string | null
  days_to_due: number | null
  is_overdue: boolean
  source_request_id: number | null
  approver_name: string | null
  approved_at: string | null
  approval_comment: string | null
  approvals: ApprovalRecordItem[]
  dingtalk_instance_id: string | null
  dingtalk_status: 'RUNNING' | 'APPROVED' | 'REJECTED' | 'TERMINATED' | null
  dingtalk_result: string | null
  outbound_by_name: string | null
  outbound_at: string | null
  outbound_location: string | null
  return_requested_at: string | null
  confirm_by_name: string | null
  confirmed_at: string | null
  confirm_comment: string | null
  can_approve: boolean
  can_reject: boolean
  can_outbound: boolean
  can_configure: boolean
  can_cancel: boolean
  can_confirm_return: boolean
  version: number
  created_at: string
  updated_at: string
}

export interface AssetRequestPage {
  items: AssetRequestItem[]
  total: number
  page: number
  page_size: number
}

export interface AssetRequestSummary {
  pending_approval: number
  pending_outbound: number
  pending_return: number
  borrowed: number
  mine_pending: number
  my_pending_approval: number
  my_pending_outbound: number
  my_pending_return: number
}

export interface MyAssetItem {
  asset_id: number
  asset_no: string
  name: string
  category_name: string | null
  model_name: string | null
  serial_no: string | null
  location: string | null
  dept_name: string | null
  status: AssetStatus
  status_label: string
  status_tag_type: TagType
  request_id: number | null
  request_type: AssetRequestType | null
  borrowed_at: string | null
  expected_return_date: string | null
  days_to_due: number | null
  is_overdue: boolean
  return_pending: boolean
  return_request_id: number | null
  version: number
}

export interface AssetHistoryItem {
  id: number
  asset_id: number
  request_id: number | null
  action: string
  action_label: string
  from_status: AssetStatus
  from_status_label: string
  to_status: AssetStatus
  to_status_label: string
  before_snapshot: Record<string, unknown>
  after_snapshot: Record<string, unknown>
  operator_name: string | null
  summary: string | null
  created_at: string
}

export interface ScanAssetResult {
  asset: AvailableAsset
  requests: AssetRequestItem[]
}

export interface RequestCreatePayload {
  request_type: Exclude<AssetRequestType, 'RETURN'>
  category_id: number
  reason?: string | null
  expected_return_date?: string | null
}

export interface ReturnCreatePayload {
  asset_id: number
  reason?: string | null
}

export interface OutboundPayload {
  version: number
  asset_id?: number | null
  location?: string | null
  comment?: string | null
}

export interface ReturnConfirmPayload {
  version: number
  location?: string | null
  comment?: string | null
}

export const REQUEST_TYPE_LABELS: Record<AssetRequestType, string> = {
  REQUISITION: '领用',
  BORROW: '借用',
  RETURN: '归还',
}

export const REQUEST_STATUS_LABELS: Record<AssetRequestStatus, string> = {
  PENDING_APPROVAL: '待审批',
  PENDING_OUTBOUND: '待出库',
  BORROWED: '借用中',
  PENDING_RETURN: '待归还确认',
  COMPLETED: '已完成',
  REJECTED: '已驳回',
  CANCELLED: '已取消',
}

export const REQUEST_STATUS_TAG_TYPES: Record<AssetRequestStatus, TagType> = {
  PENDING_APPROVAL: 'warning',
  PENDING_OUTBOUND: 'primary',
  BORROWED: 'warning',
  PENDING_RETURN: 'warning',
  COMPLETED: 'success',
  REJECTED: 'danger',
  CANCELLED: 'info',
}

export const APPROVAL_STEP_TAG_TYPES: Record<ApprovalTaskStatus, TagType> = {
  PENDING: 'warning',
  WAITING: 'info',
  APPROVED: 'success',
  REJECTED: 'danger',
  SKIPPED: 'info',
}

const FLOW_STEPS: Record<AssetRequestType, string[]> = {
  REQUISITION: ['提交申请', '审批', '确认出库', '完成'],
  BORROW: ['提交申请', '审批', '确认出库', '借用中', '已归还'],
  RETURN: ['发起归还', '归还确认', '入库完成'],
}

const FLOW_ACTIVE: Record<AssetRequestType, Partial<Record<AssetRequestStatus, number>>> = {
  REQUISITION: {
    PENDING_APPROVAL: 1,
    PENDING_OUTBOUND: 2,
    COMPLETED: 4,
  },
  BORROW: {
    PENDING_APPROVAL: 1,
    PENDING_OUTBOUND: 2,
    BORROWED: 3,
    COMPLETED: 5,
  },
  RETURN: {
    PENDING_RETURN: 1,
    COMPLETED: 3,
  },
}

export function flowSteps(requestType: AssetRequestType): string[] {
  return FLOW_STEPS[requestType] ?? FLOW_STEPS.REQUISITION
}

export function flowActive(
  requestType: AssetRequestType,
  status: AssetRequestStatus,
): number {
  const mapping = FLOW_ACTIVE[requestType] ?? {}
  if (status === 'REJECTED') return 1
  if (status === 'CANCELLED') return mapping[status] ?? 1
  return mapping[status] ?? 0
}

export function isFlowInterrupted(status: AssetRequestStatus): boolean {
  return status === 'REJECTED' || status === 'CANCELLED'
}
