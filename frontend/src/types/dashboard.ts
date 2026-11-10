export type DashboardScope = 'personal' | 'org'

export interface DashboardMetrics {
  total_assets: number
  total_value: number
  pending_stock: number
  in_stock: number
  in_use: number
  idle: number
  repairing: number
  pending_scrap: number
  scrapped: number
  warranty_30d: number
  month_inbound: number
  month_requisition: number
  contract_expiring: number
  idle_rate: number
}

export interface StatusSlice {
  status: string
  label: string
  count: number
}

export interface CategorySlice {
  category_id: number | null
  name: string
  count: number
}

export interface DeptSlice {
  dept_id: number | null
  name: string
  count: number
}

export interface TrendPoint {
  month: string
  count: number
}

export interface WarrantyItem {
  id: number
  asset_no: string
  name: string
  category_name: string | null
  dept_name: string | null
  custodian_name: string | null
  warranty_end: string
  days_left: number
}

export interface RecentAssetItem {
  id: number
  asset_no: string
  name: string
  category_name: string | null
  dept_name: string | null
  status: string
  status_label: string
  created_at: string
}

export interface DashboardPeriod {
  months: number
  start_date: string
  new_assets: number
  inbound: number
  requisition: number
}

export interface DashboardDeptOption {
  id: number
  parent_id: number | null
  name: string
  level: number
}

export interface DashboardSummary {
  scope: DashboardScope
  metrics: DashboardMetrics
  status_distribution: StatusSlice[]
  category_distribution: CategorySlice[]
  dept_distribution: DeptSlice[]
  purchase_trend: TrendPoint[]
  warranty_expiring: WarrantyItem[]
  recent_assets: RecentAssetItem[]
  data_scope_label: string
  period: DashboardPeriod
  dept_options: DashboardDeptOption[]
  dept_id: number | null
}
