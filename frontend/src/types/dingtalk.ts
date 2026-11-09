export type DingTalkSyncStatus = 'RUNNING' | 'SUCCESS' | 'PARTIAL' | 'FAILED'

export interface DingTalkConfig {
  id: number
  enabled: boolean
  corp_id: string
  app_key: string
  has_secret: boolean
  agent_id: number | null
  default_role_id: number | null
  default_role_name: string | null
  root_dept_id: number | null
  root_dept_name: string | null
  sync_interval_minutes: number
  disable_on_leave: boolean
  match_existing: boolean
  approval_enabled: boolean
  requisition_process_code: string | null
  borrow_process_code: string | null
  transfer_process_code: string | null
  has_callback_token: boolean
  has_callback_aes_key: boolean
  last_sync_at: string | null
  last_sync_status: DingTalkSyncStatus | null
  last_sync_message: string | null
  last_test_at: string | null
  last_test_status: 'SUCCESS' | 'FAILED' | null
  last_test_message: string | null
  version: number
  created_at: string | null
  updated_at: string | null
}

export interface DingTalkConfigPayload {
  enabled: boolean
  corp_id: string
  app_key: string
  app_secret?: string | null
  agent_id: number | null
  default_role_id: number | null
  root_dept_id: number | null
  sync_interval_minutes: number
  disable_on_leave: boolean
  match_existing: boolean
  approval_enabled: boolean
  requisition_process_code: string | null
  borrow_process_code: string | null
  transfer_process_code: string | null
  callback_token?: string | null
  callback_aes_key?: string | null
}

export interface DingTalkConfigUpdatePayload extends DingTalkConfigPayload {
  version?: number
}

export interface DingTalkTestResult {
  success: boolean
  message: string
  corp_id: string | null
  dept_sample: number
  user_sample: number
  elapsed_ms: number
  checked_at: string
}

export interface DingTalkSyncLog {
  id: number
  trigger_type: 'MANUAL' | 'SCHEDULED' | string
  status: DingTalkSyncStatus
  started_at: string
  finished_at: string | null
  duration_ms: number
  dept_total: number
  dept_created: number
  dept_updated: number
  user_total: number
  user_created: number
  user_updated: number
  user_matched: number
  user_disabled: number
  user_skipped: number
  error_count: number
  operator_name: string | null
  message: string | null
  details: Array<{ level: string; message: string }> | null
  error_message: string | null
}

export interface DingTalkSyncLogPage {
  items: DingTalkSyncLog[]
  total: number
  page: number
  page_size: number
}

export interface DingTalkRoleOption {
  id: number
  code: string
  name: string
}

export interface DingTalkDeptOption {
  id: number
  parent_id: number | null
  name: string
  level: number
  status: number
}

export interface DingTalkOptions {
  roles: DingTalkRoleOption[]
  depts: DingTalkDeptOption[]
  dingtalk_dept_count: number
  dingtalk_user_count: number
}

export interface DingTalkSyncAccepted {
  accepted: boolean
  config_id: number
  trigger_type: string
}
