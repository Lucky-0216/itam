import { request } from '@/api/request'
import type {
  DeptNode,
  DeptPayload,
  DeptUpdatePayload,
  OrgUserDetail,
  ResetPasswordPayload,
  SyncPolicy,
  SyncPolicyUpdate,
  UserCreatePayload,
  UserPage,
  UserQuery,
  UserStatusPayload,
  UserUpdatePayload,
} from '@/types/org'

export const orgApi = {
  departmentTree(source?: string): Promise<DeptNode[]> {
    return request<DeptNode[]>({ url: '/departments/tree', params: { source } })
  },

  createDepartment(payload: DeptPayload): Promise<DeptNode> {
    return request<DeptNode>({ url: '/departments', method: 'post', data: payload })
  },

  updateDepartment(id: number, payload: DeptUpdatePayload): Promise<DeptNode> {
    return request<DeptNode>({ url: `/departments/${id}`, method: 'put', data: payload })
  },

  deleteDepartment(id: number): Promise<null> {
    return request<null>({ url: `/departments/${id}`, method: 'delete' })
  },

  listUsers(params: UserQuery): Promise<UserPage> {
    return request<UserPage>({ url: '/users', params })
  },

  getUser(id: number): Promise<OrgUserDetail> {
    return request<OrgUserDetail>({ url: `/users/${id}` })
  },

  createUser(payload: UserCreatePayload): Promise<OrgUserDetail> {
    return request<OrgUserDetail>({ url: '/users', method: 'post', data: payload })
  },

  updateUser(id: number, payload: UserUpdatePayload): Promise<OrgUserDetail> {
    return request<OrgUserDetail>({ url: `/users/${id}`, method: 'put', data: payload })
  },

  setUserStatus(id: number, payload: UserStatusPayload): Promise<OrgUserDetail> {
    return request<OrgUserDetail>({
      url: `/users/${id}/status`,
      method: 'put',
      data: payload,
    })
  },

  resetPassword(id: number, payload: ResetPasswordPayload): Promise<null> {
    return request<null>({
      url: `/users/${id}/reset-password`,
      method: 'post',
      data: payload,
    })
  },

  deleteUser(id: number): Promise<null> {
    return request<null>({ url: `/users/${id}`, method: 'delete' })
  },

  getSyncPolicy(): Promise<SyncPolicy> {
    return request<SyncPolicy>({ url: '/sync-policy' })
  },

  updateSyncPolicy(payload: SyncPolicyUpdate): Promise<SyncPolicy> {
    return request<SyncPolicy>({ url: '/sync-policy', method: 'put', data: payload })
  },
}
