import type { AssetStatus } from '@/types/asset'
import type { TagType } from '@/types/assetFlow'

export type TransferStatus =
  | 'PENDING_APPROVAL'
  | 'PENDING_TRANSFER'
  | 'COMPLETED'
  | 'REJECTED'
  | 'CANCELLED'

export type ScrapStatus =
  | 'PENDING_APPROVAL'
  | 'PENDING_DISPOSAL'
  | 'COMPLETED'
  | 'REJECTED'
  | 'CANCELLED'

export type InventoryStatus = 'IN_PROGRESS' | 'COMPLETED' | 'CANCELLED'
export type InventoryResult = 'PENDING' | 'NORMAL' | 'ABNORMAL' | 'MISSING'
export type InventoryAdjustmentStatus = 'PENDING' | 'APPROVED' | 'REJECTED'

export interface OpsAsset {
  id: number
  asset_no: string
  name: string
  category_name: string | null
  model_name: string | null
  serial_no: string | null
  location: string | null
  dept_id: number | null
  dept_name: string | null
  custodian_id: number | null
  custodian_name: string | null
  status: AssetStatus
  status_label: string
  version: number
}

export interface OpsAssetPage {
  items: OpsAsset[]
  total: number
  page: number
  page_size: number
}

export interface DeptOption {
  id: number
  parent_id: number | null
  name: string
  level: number
  path: string
}

export interface UserOption {
  id: number
  name: string
  username: string
  dept_id: number | null
  dept_name: string | null
}

export interface CategoryOption {
  id: number
  parent_id: number | null
  name: string
  level: number
  path: string
}

export interface TransferItem {
  id: number
  transfer_no: string
  status: TransferStatus
  status_label: string
  status_tag_type: TagType
  asset_id: number
  asset_no: string
  asset_name: string
  asset_version: number
  asset_status: AssetStatus
  asset_status_label: string
  from_dept_id: number | null
  from_dept_name: string | null
  from_custodian_id: number | null
  from_custodian_name: string | null
  from_location: string | null
  to_dept_id: number | null
  to_dept_name: string | null
  to_custodian_id: number | null
  to_custodian_name: string | null
  to_location: string | null
  reason: string | null
  applicant_id: number
  applicant_name: string
  applicant_dept_id: number | null
  applicant_dept_name: string | null
  approver_name: string | null
  approved_at: string | null
  approval_comment: string | null
  dingtalk_instance_id: string | null
  dingtalk_status: 'RUNNING' | 'APPROVED' | 'REJECTED' | 'TERMINATED' | null
  dingtalk_result: string | null
  completed_by_name: string | null
  completed_at: string | null
  completion_comment: string | null
  can_approve: boolean
  can_reject: boolean
  can_confirm: boolean
  can_cancel: boolean
  version: number
  created_at: string
  updated_at: string
}

export interface TransferPage {
  items: TransferItem[]
  total: number
  page: number
  page_size: number
}

export interface ScrapItem {
  id: number
  scrap_no: string
  status: ScrapStatus
  status_label: string
  status_tag_type: TagType
  asset_id: number
  asset_no: string
  asset_name: string
  asset_version: number
  asset_status: AssetStatus
  asset_status_label: string
  from_status: AssetStatus
  from_status_label: string
  from_dept_id: number | null
  from_dept_name: string | null
  from_custodian_id: number | null
  from_custodian_name: string | null
  from_location: string | null
  reason: string
  disposal_method: string | null
  residual_value: number | null
  applicant_id: number
  applicant_name: string
  applicant_dept_id: number | null
  applicant_dept_name: string | null
  approver_name: string | null
  approved_at: string | null
  approval_comment: string | null
  completed_by_name: string | null
  completed_at: string | null
  completion_comment: string | null
  can_approve: boolean
  can_reject: boolean
  can_confirm: boolean
  can_cancel: boolean
  version: number
  created_at: string
  updated_at: string
}

export interface ScrapPage {
  items: ScrapItem[]
  total: number
  page: number
  page_size: number
}

export interface TransferCreatePayload {
  asset_id: number
  to_dept_id?: number | null
  to_custodian_id?: number | null
  to_location?: string | null
  reason?: string | null
}

export interface ScrapCreatePayload {
  asset_id: number
  reason: string
  disposal_method?: string | null
  residual_value?: number | null
}

export interface OpsConfirmPayload {
  version: number
  comment?: string | null
}

export interface InventoryTaskItem {
  id: number
  task_no: string
  name: string
  status: InventoryStatus
  status_label: string
  status_tag_type: TagType
  scope_dept_id: number | null
  scope_dept_name: string | null
  include_child: boolean
  scope_category_id: number | null
  scope_category_name: string | null
  include_child_category: boolean
  planned_date: string | null
  remark: string | null
  started_at: string | null
  completed_at: string | null
  cancelled_at: string | null
  cancel_reason: string | null
  created_by_name: string | null
  total_assets: number
  checked_assets: number
  normal_count: number
  abnormal_count: number
  missing_count: number
  surplus_count: number
  pending_count: number
  can_manage: boolean
  adjustment_id: number | null
  adjustment_no: string | null
  adjustment_status: InventoryAdjustmentStatus | null
  adjustment_status_label: string | null
  adjustment_status_tag_type: TagType | null
  adjustment_version: number | null
  can_submit_adjustment: boolean
  can_approve_adjustment: boolean
  version: number
  created_at: string
  updated_at: string
}

export interface InventoryTaskPage {
  items: InventoryTaskItem[]
  total: number
  page: number
  page_size: number
}

export interface InventoryItem {
  id: number
  task_id: number
  asset_id: number
  asset_no: string
  asset_name: string
  category_name: string | null
  dept_name: string | null
  location: string | null
  custodian_name: string | null
  expected_status: AssetStatus
  expected_status_label: string
  result: InventoryResult
  result_label: string
  result_tag_type: TagType
  actual_location: string | null
  remark: string | null
  checked_by_name: string | null
  checked_at: string | null
  created_at: string
}

export interface InventoryItemPage {
  items: InventoryItem[]
  total: number
  page: number
  page_size: number
}

export interface InventoryCreatePayload {
  name: string
  scope_dept_id?: number | null
  include_child: boolean
  scope_category_id?: number | null
  include_child_category: boolean
  planned_date?: string | null
  remark?: string | null
}

export interface InventoryItemUpdatePayload {
  result: Exclude<InventoryResult, 'PENDING'>
  actual_location?: string | null
  remark?: string | null
}

export interface InventorySurplusItem {
  id: number
  task_id: number
  asset_no: string
  name: string
  category_id: number
  category_name: string | null
  model_id: number | null
  model_name: string | null
  dept_id: number | null
  dept_name: string | null
  serial_no: string | null
  location: string | null
  purchase_date: string | null
  purchase_price: number | null
  remark: string | null
  created_by_name: string | null
  created_asset_id: number | null
  applied_at: string | null
  created_at: string
}

export interface InventorySurplusCreatePayload {
  asset_no: string
  name: string
  category_id: number
  model_id?: number | null
  dept_id?: number | null
  serial_no?: string | null
  location?: string | null
  purchase_date?: string | null
  purchase_price?: number | null
  remark?: string | null
}

export interface InventoryAdjustmentItem {
  id: number
  task_id: number
  task_no: string
  task_name: string
  adjustment_no: string
  status: InventoryAdjustmentStatus
  status_label: string
  status_tag_type: TagType
  loss_count: number
  surplus_count: number
  reason: string | null
  requested_by_name: string | null
  requested_at: string
  reviewed_by_name: string | null
  reviewed_at: string | null
  review_comment: string | null
  version: number
  created_at: string
  updated_at: string
}

export interface InventoryReport {
  task: InventoryTaskItem
  missing_items: InventoryItem[]
  abnormal_items: InventoryItem[]
  surplus_items: InventorySurplusItem[]
  adjustment: InventoryAdjustmentItem | null
  generated_at: string
}

export const TRANSFER_STATUS_LABELS: Record<TransferStatus, string> = {
  PENDING_APPROVAL: '待审批',
  PENDING_TRANSFER: '待确认调拨',
  COMPLETED: '已完成',
  REJECTED: '已驳回',
  CANCELLED: '已取消',
}

export const SCRAP_STATUS_LABELS: Record<ScrapStatus, string> = {
  PENDING_APPROVAL: '待审批',
  PENDING_DISPOSAL: '待报废处置',
  COMPLETED: '已完成',
  REJECTED: '已驳回',
  CANCELLED: '已取消',
}

export const INVENTORY_STATUS_LABELS: Record<InventoryStatus, string> = {
  IN_PROGRESS: '盘点中',
  COMPLETED: '已完成',
  CANCELLED: '已取消',
}

export const INVENTORY_RESULT_LABELS: Record<InventoryResult, string> = {
  PENDING: '待核对',
  NORMAL: '正常',
  ABNORMAL: '异常',
  MISSING: '盘亏',
}

const TRANSFER_STEPS = ['发起调拨', '审批', '确认调拨', '完成']
const TRANSFER_ACTIVE: Record<TransferStatus, number> = {
  PENDING_APPROVAL: 1,
  PENDING_TRANSFER: 2,
  COMPLETED: 4,
  REJECTED: 1,
  CANCELLED: 1,
}

const SCRAP_STEPS = ['发起报废', '审批', '报废处置', '完成']
const SCRAP_ACTIVE: Record<ScrapStatus, number> = {
  PENDING_APPROVAL: 1,
  PENDING_DISPOSAL: 2,
  COMPLETED: 4,
  REJECTED: 1,
  CANCELLED: 1,
}

export function transferSteps(): string[] {
  return TRANSFER_STEPS
}

export function transferActive(status: TransferStatus): number {
  return TRANSFER_ACTIVE[status] ?? 0
}

export function scrapSteps(): string[] {
  return SCRAP_STEPS
}

export function scrapActive(status: ScrapStatus): number {
  return SCRAP_ACTIVE[status] ?? 0
}

export function isTransferInterrupted(status: TransferStatus): boolean {
  return status === 'REJECTED' || status === 'CANCELLED'
}

export function isScrapInterrupted(status: ScrapStatus): boolean {
  return status === 'REJECTED' || status === 'CANCELLED'
}
