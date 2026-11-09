import { request } from '@/api/request'
import type {
  AdminMenuNode,
  DataPermissionsAssignPayload,
  FieldPermissionsAssignPayload,
  MenuAssignPayload,
  RoleBriefOption,
  RoleCreatePayload,
  RoleDetail,
  RoleMeta,
  RolePage,
  RoleQuery,
  RoleUpdatePayload,
  RoleUserOption,
  RoleUsersAssignPayload,
} from '@/types/rbac'

export const roleApi = {
  listRoles(params: RoleQuery): Promise<RolePage> {
    return request<RolePage>({ url: '/roles', params })
  },

  roleOptions(): Promise<RoleBriefOption[]> {
    return request<RoleBriefOption[]>({ url: '/roles/options/all' })
  },

  meta(): Promise<RoleMeta> {
    return request<RoleMeta>({ url: '/roles/options/meta' })
  },

  menuTree(): Promise<AdminMenuNode[]> {
    return request<AdminMenuNode[]>({ url: '/roles/menu-tree' })
  },

  userOptions(keyword?: string): Promise<RoleUserOption[]> {
    return request<RoleUserOption[]>({
      url: '/roles/user-options',
      params: { keyword: keyword || undefined },
    })
  },

  getRole(id: number): Promise<RoleDetail> {
    return request<RoleDetail>({ url: `/roles/${id}` })
  },

  createRole(payload: RoleCreatePayload): Promise<RoleDetail> {
    return request<RoleDetail>({ url: '/roles', method: 'post', data: payload })
  },

  updateRole(id: number, payload: RoleUpdatePayload): Promise<RoleDetail> {
    return request<RoleDetail>({ url: `/roles/${id}`, method: 'put', data: payload })
  },

  deleteRole(id: number): Promise<null> {
    return request<null>({ url: `/roles/${id}`, method: 'delete' })
  },

  assignMenus(id: number, payload: MenuAssignPayload): Promise<RoleDetail> {
    return request<RoleDetail>({ url: `/roles/${id}/menus`, method: 'put', data: payload })
  },

  assignDataPermissions(
    id: number,
    payload: DataPermissionsAssignPayload,
  ): Promise<RoleDetail> {
    return request<RoleDetail>({
      url: `/roles/${id}/data-permissions`,
      method: 'put',
      data: payload,
    })
  },

  assignFieldPermissions(
    id: number,
    payload: FieldPermissionsAssignPayload,
  ): Promise<RoleDetail> {
    return request<RoleDetail>({
      url: `/roles/${id}/field-permissions`,
      method: 'put',
      data: payload,
    })
  },

  assignUsers(id: number, payload: RoleUsersAssignPayload): Promise<RoleDetail> {
    return request<RoleDetail>({ url: `/roles/${id}/users`, method: 'put', data: payload })
  },
}
