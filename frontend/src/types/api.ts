export interface ApiEnvelope<T> {
  code: number
  message: string
  data: T
}

export interface TokenBundle {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
}

export interface LoginPayload {
  username: string
  password: string
}

export interface LoginUserInfo {
  id: number
  username: string
  real_name: string
  dept_name?: string | null
  avatar?: string | null
}

export interface LoginResult extends TokenBundle {
  must_change_password: boolean
  user: LoginUserInfo
}

export interface RoleBrief {
  id: number
  code: string
  name: string
  data_scope: string
}

export interface MenuNode {
  id: number
  parent_id?: number | null
  name: string
  type: 'DIR' | 'MENU' | 'BUTTON' | string
  path?: string | null
  component?: string | null
  icon?: string | null
  sort: number
  permission_code?: string | null
  children: MenuNode[]
}

export interface FieldPermission {
  can_view: boolean
  can_edit: boolean
}

export interface UserProfile {
  id: number
  username: string
  real_name: string
  employee_no?: string | null
  email?: string | null
  phone?: string | null
  avatar?: string | null
  dept_id?: number | null
  dept_name?: string | null
  position?: string | null
  status: number
  source?: string
  must_change_password: boolean
  last_login_at?: string | null
}

export interface CurrentUser {
  user: UserProfile
  roles: RoleBrief[]
  permissions: string[]
  data_scope: string
  data_scope_label: string
  custom_dept_ids: number[]
  /** 角色级资产域范围：ALL=显式全部域；CUSTOM 时以 asset_domains 为准。 */
  domain_scope: string
  /** CUSTOM 且为空数组时表示无任何资产域权限，不得视为不限。 */
  asset_domains: string[]
  /** 资源 → 细化后的数据范围；未包含的资源沿用 data_scope。 */
  resource_scopes: Record<string, string>
  menus: MenuNode[]
  field_permissions: Record<string, Record<string, FieldPermission>>
}

export interface ChangePasswordPayload {
  old_password: string
  new_password: string
}
