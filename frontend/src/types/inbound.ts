import type { TagType } from '@/types/assetFlow'

export type InboundStatus = 'PENDING' | 'COMPLETED' | 'CANCELLED'
export type InboundType = 'PURCHASE' | 'OTHER'

export interface InboundCategoryOption {
  id: number
  parent_id: number | null
  name: string
  level: number
  path: string
}

export interface InboundModelOption {
  id: number
  category_id: number
  name: string
  code: string
  brand: string | null
  spec: string | null
  unit: string
}

export interface InboundDeptOption {
  id: number
  parent_id: number | null
  name: string
  level: number
  path: string
}

export interface InboundItem {
  id: number
  category_id: number
  category_name: string
  model_id: number | null
  model_name: string | null
  name: string
  quantity: number
  base_asset_no: string | null
  asset_nos: string[]
  unit_price: number | null
  amount: number
  warranty_end: string | null
  remark: string | null
}

export interface InboundItemPayload {
  category_id: number
  model_id?: number | null
  name: string
  quantity: number
  base_asset_no?: string | null
  asset_nos?: string[] | null
  unit_price?: number | null
  warranty_end?: string | null
  remark?: string | null
}

export interface InboundCreatePayload {
  inbound_type: InboundType
  supplier?: string | null
  purchase_date?: string | null
  location?: string | null
  dept_id?: number | null
  remark?: string | null
  source_inbound_id?: number | null
  items: InboundItemPayload[]
}

export interface InboundUpdatePayload extends InboundCreatePayload {
  version: number
}

export interface InboundReversePayload {
  asset_nos: string[]
  reason: string
  version: number
}

export interface InboundAsset {
  id: number
  asset_no: string
  name: string
  status: string
  status_label: string
  can_reverse: boolean
}

export interface Inbound {
  id: number
  inbound_no: string
  inbound_type: InboundType
  inbound_type_label: string
  status: InboundStatus
  status_label: string
  status_tag_type: TagType
  supplier: string | null
  purchase_date: string | null
  location: string | null
  dept_id: number | null
  dept_name: string | null
  total_quantity: number
  total_amount: number
  remark: string | null
  created_by_name: string | null
  confirmed_by_name: string | null
  confirmed_at: string | null
  completion_comment: string | null
  cancelled_at: string | null
  cancel_reason: string | null
  can_confirm: boolean
  can_cancel: boolean
  can_edit: boolean
  can_reverse: boolean
  can_supplement: boolean
  source_inbound_id: number | null
  version: number
  created_at: string
  updated_at: string
  items: InboundItem[]
  assets: InboundAsset[]
}

export interface InboundPage {
  items: Inbound[]
  total: number
  page: number
  page_size: number
}

export interface InboundCodePreview {
  base_asset_no: string
  codes: string[]
}

export interface StockLocation {
  location: string | null
  location_label: string
  asset_count: number
  total_value: number
}

export interface StockWarning {
  category_id: number
  category_name: string
  stock_count: number
  safety_stock: number
  shortage: number
}

export interface StockOverview {
  in_stock_count: number
  in_stock_value: number
  location_count: number
  warning_count: number
  locations: StockLocation[]
  warnings: StockWarning[]
}

export interface StockAsset {
  id: number
  asset_no: string
  name: string
  category_id: number
  category_name: string | null
  model_name: string | null
  serial_no: string | null
  location: string | null
  dept_id: number | null
  dept_name: string | null
  purchase_price: number | null
  warranty_end: string | null
  remark: string | null
  created_at: string
}

export interface StockAssetPage {
  items: StockAsset[]
  total: number
  page: number
  page_size: number
}

export interface StockCategoryOption extends InboundCategoryOption {
  safety_stock: number
}

export const INBOUND_STATUS_LABELS: Record<InboundStatus, string> = {
  PENDING: '待确认入库',
  COMPLETED: '已入库',
  CANCELLED: '已取消',
}

export const INBOUND_TYPE_LABELS: Record<InboundType, string> = {
  PURCHASE: '采购入库',
  OTHER: '其他入库',
}

const INBOUND_STEPS = ['创建入库单', '待确认', '验收入库', '完成']
const INBOUND_ACTIVE: Record<InboundStatus, number> = {
  PENDING: 2,
  COMPLETED: 4,
  CANCELLED: 1,
}

export function inboundSteps(): string[] {
  return INBOUND_STEPS
}

export function inboundActive(status: InboundStatus): number {
  return INBOUND_ACTIVE[status] ?? 0
}

export function isInboundInterrupted(status: InboundStatus): boolean {
  return status === 'CANCELLED'
}
