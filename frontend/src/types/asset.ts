export type AssetCategoryType = 'HARDWARE' | 'SOFTWARE' | 'ACCESSORY' | 'CONSUMABLE'
export type AssetFieldType = 'TEXT' | 'NUMBER' | 'DATE' | 'SELECT'
export type AssetStatus =
  | 'PENDING_STOCK'
  | 'IN_STOCK'
  | 'IN_USE'
  | 'BORROWED'
  | 'IDLE'
  | 'REPAIRING'
  | 'PENDING_SCRAP'
  | 'SCRAPPED'

export interface CategoryField {
  id: number
  category_id: number
  name: string
  field_key: string
  field_type: AssetFieldType
  required: boolean
  options: string[] | null
  sort: number
  status: number
  remark: string | null
  version: number
}

export interface AssetCategory {
  id: number
  parent_id: number | null
  name: string
  code: string
  category_type: AssetCategoryType
  path: string
  level: number
  sort: number
  safety_stock: number
  status: number
  remark: string | null
  version: number
  model_count: number
  asset_count: number
  field_defs: CategoryField[]
  children: AssetCategory[]
}

export interface CategoryPayload {
  parent_id: number | null
  name: string
  code: string
  category_type?: AssetCategoryType | null
  sort: number
  safety_stock: number
  status: number
  remark?: string | null
}

export interface CategoryUpdatePayload extends CategoryPayload {
  version: number
}

export interface CategoryFieldPayload {
  name: string
  field_key: string
  field_type: AssetFieldType
  required: boolean
  options?: string[] | null
  sort: number
  status: number
  remark?: string | null
}

export interface CategoryFieldUpdatePayload extends CategoryFieldPayload {
  version: number
}

export interface AssetModel {
  id: number
  category_id: number
  category_name: string | null
  name: string
  code: string
  brand: string | null
  spec: string | null
  unit: string
  depreciation_months: number | null
  residual_rate: number
  status: number
  remark: string | null
  version: number
  asset_count: number
  created_at: string
  updated_at: string
}

export interface ModelPage {
  items: AssetModel[]
  total: number
  page: number
  page_size: number
}

export interface ModelQuery {
  page: number
  page_size: number
  category_id?: number
  include_child?: boolean
  keyword?: string
  status?: number
}

export interface ModelPayload {
  category_id: number
  name: string
  code: string
  brand?: string | null
  spec?: string | null
  unit: string
  depreciation_months?: number | null
  residual_rate: number
  status: number
  remark?: string | null
}

export interface ModelUpdatePayload extends ModelPayload {
  version: number
}

export interface AssetItem {
  id: number
  asset_no: string
  name: string
  category_id: number
  category_name: string | null
  category_type: AssetCategoryType | null
  model_id: number | null
  model_name: string | null
  model_brand: string | null
  serial_no: string | null
  mac_address: string | null
  purchase_date: string | null
  supplier: string | null
  purchase_price: number | null
  warranty_end: string | null
  location: string | null
  dept_id: number | null
  dept_name: string | null
  custodian_id: number | null
  custodian_name: string | null
  status: AssetStatus
  status_label: string
  custom_fields: Record<string, unknown>
  remark: string | null
  masked_fields: string[]
  version: number
  created_at: string
  updated_at: string
}

export interface AssetPage {
  items: AssetItem[]
  total: number
  page: number
  page_size: number
}

export interface AssetQuery {
  page: number
  page_size: number
  keyword?: string
  category_id?: number
  include_child?: boolean
  status?: AssetStatus
  dept_id?: number
  custodian_id?: number
  warranty_days?: number
}

export interface AssetPayload {
  asset_no?: string | null
  name: string
  category_id: number
  model_id?: number | null
  serial_no?: string | null
  mac_address?: string | null
  purchase_date?: string | null
  supplier?: string | null
  purchase_price?: number | null
  warranty_end?: string | null
  location?: string | null
  dept_id?: number | null
  custodian_id?: number | null
  remark?: string | null
  custom_fields: Record<string, unknown>
}

export interface AssetUpdatePayload extends Omit<AssetPayload, 'asset_no'> {
  version: number
}

export interface AssetStockInPayload {
  version: number
}

export interface AssetBatchUpdatePayload {
  asset_ids: number[]
  dept_id?: number | null
  custodian_id?: number | null
  location?: string | null
  clear_dept?: boolean
  clear_custodian?: boolean
  clear_location?: boolean
}

export interface AssetBatchUpdateResult {
  updated: number
}

export interface CustodianOption {
  id: number
  username: string
  real_name: string
  dept_id: number | null
  dept_name: string | null
}

export interface AssetDeptOption {
  id: number
  parent_id: number | null
  name: string
  path: string
  level: number
}

export interface AssetTimelineItem {
  id: number
  action: string
  summary: string | null
  username: string | null
  status: string
  created_at: string
}

export interface AssetAttachment {
  id: number
  asset_id: number
  file_name: string
  content_type: string | null
  file_size: number
  kind: 'IMAGE' | 'FILE'
  uploaded_by_name: string | null
  created_at: string
}

export const CATEGORY_TYPE_LABELS: Record<AssetCategoryType, string> = {
  HARDWARE: '硬件',
  SOFTWARE: '软件',
  ACCESSORY: '配件',
  CONSUMABLE: '耗材',
}

export const FIELD_TYPE_LABELS: Record<AssetFieldType, string> = {
  TEXT: '文本',
  NUMBER: '数字',
  DATE: '日期',
  SELECT: '下拉选项',
}

export const ASSET_STATUS_LABELS: Record<AssetStatus, string> = {
  PENDING_STOCK: '待入库',
  IN_STOCK: '在库',
  IN_USE: '在用',
  BORROWED: '借出',
  IDLE: '闲置',
  REPAIRING: '维修中',
  PENDING_SCRAP: '待报废',
  SCRAPPED: '已报废',
}

export const ASSET_STATUS_TAG_TYPES: Record<
  AssetStatus,
  'primary' | 'success' | 'info' | 'warning' | 'danger'
> = {
  PENDING_STOCK: 'info',
  IN_STOCK: 'success',
  IN_USE: 'primary',
  BORROWED: 'warning',
  IDLE: 'warning',
  REPAIRING: 'warning',
  PENDING_SCRAP: 'danger',
  SCRAPPED: 'info',
}
