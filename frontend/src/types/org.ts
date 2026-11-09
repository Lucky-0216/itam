export interface DeptNode {
  id: number
  parent_id: number | null
  name: string
  code: string
  leader: string | null
  manager_id: number | null
  manager_name: string | null
  phone: string | null
  path: string
  level: number
  sort: number
  status: number
  remark: string | null
  source: string
  ldap_dn: string | null
  version: number
  user_count: number
  children: DeptNode[]
}

export interface DeptPayload {
  parent_id: number | null
  name: string
  code: string
  leader?: string | null
  manager_id?: number | null
  phone?: string | null
  sort: number
  status: number
  remark?: string | null
}

export interface DeptUpdatePayload extends DeptPayload {
  version: number
}

export interface UserRoleItem {
  id: number
  code: string
  name: string
  data_scope: string
}

export interface OrgUser {
  id: number
  username: string
  real_name: string
  employee_no: string | null
  email: string | null
  phone: string | null
  avatar: string | null
  dept_id: number | null
  dept_name: string | null
  dept_path: string | null
  position: string | null
  status: number
  source: string
  must_change_password: boolean
  last_login_at: string | null
  created_at: string
  version: number
  roles: UserRoleItem[]
}

export interface OrgUserDetail extends OrgUser {
  remark: string | null
  token_version: number
}

export interface UserPage {
  items: OrgUser[]
  total: number
  page: number
  page_size: number
}

export interface UserQuery {
  page: number
  page_size: number
  keyword?: string
  dept_id?: number
  include_child?: boolean
  status?: number
  source?: string
}

export interface UserCreatePayload {
  username: string
  password: string
  real_name: string
  dept_id: number
  position?: string | null
  employee_no?: string | null
  email?: string | null
  phone?: string | null
  status: number
  role_ids: number[]
  remark?: string | null
}

export interface UserUpdatePayload {
  real_name: string
  dept_id: number
  position?: string | null
  employee_no?: string | null
  email?: string | null
  phone?: string | null
  role_ids?: number[]
  remark?: string | null
  version: number
}

export interface UserStatusPayload {
  status: number
  version: number
}

export interface ResetPasswordPayload {
  new_password: string
  version: number
}

export interface SyncPolicy {
  source_priority: string
  conflict_strategy: string
  protect_local: boolean
  disable_scope: string
  version: number
}

export interface SyncPolicyUpdate extends Omit<SyncPolicy, 'version'> {
  version: number
}
