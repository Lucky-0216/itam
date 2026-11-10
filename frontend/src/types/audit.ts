export interface AuditLogItem {
  id: number
  user_id: number | null
  username: string | null
  action: string
  module: string
  resource_type: string | null
  resource_id: string | null
  summary: string | null
  method: string | null
  path: string | null
  ip: string | null
  user_agent: string | null
  request_id: string | null
  status: 'SUCCESS' | 'FAILED'
  created_at: string
}

export interface AuditLogDetail extends AuditLogItem {
  before_data: unknown
  after_data: unknown
  before_labels?: Record<string, string> | null
  after_labels?: Record<string, string> | null
}

export interface AuditLogPage {
  items: AuditLogItem[]
  total: number
  page: number
  page_size: number
}

export interface AuditQuery {
  page?: number
  page_size?: number
  keyword?: string
  module?: string
  action?: string
  status?: string
  start_time?: string
  end_time?: string
}

export interface AuditFilterOptions {
  modules: string[]
  actions: string[]
}
