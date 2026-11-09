import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { authApi } from '@/api/auth'
import type {
  FieldPermission,
  LoginPayload,
  LoginResult,
  MenuNode,
  UserProfile,
} from '@/types/api'
import {
  clearTokenBundle,
  getAccessToken,
  getRefreshToken,
  saveTokenBundle,
} from '@/utils/token'

export const useAuthStore = defineStore('auth', () => {
  const accessToken = ref<string | null>(getAccessToken())
  const profile = ref<UserProfile | null>(null)
  const roleNames = ref<string[]>([])
  const permissions = ref<string[]>([])
  const menus = ref<MenuNode[]>([])
  const fieldPermissions = ref<Record<string, Record<string, FieldPermission>>>({})
  const dataScope = ref('')
  const dataScopeLabel = ref('')
  // 资产域语义：domainScope === 'ALL' 表示显式拥有全部域；
  // 'CUSTOM' + 空 assetDomains 表示无任何资产域权限，绝不能当作“不限”。
  const domainScope = ref('')
  const assetDomains = ref<string[]>([])
  const resourceScopes = ref<Record<string, string>>({})
  const permissionsLoaded = ref(false)
  const isSuperAdmin = ref(false)
  const loadingProfile = ref(false)

  const isAuthenticated = computed(() => Boolean(accessToken.value))

  async function login(payload: LoginPayload): Promise<LoginResult> {
    const result = await authApi.login(payload)
    saveTokenBundle(result)
    accessToken.value = result.access_token
    try {
      await fetchProfile()
    } catch (error) {
      reset()
      throw error
    }
    return result
  }

  async function fetchProfile(): Promise<void> {
    loadingProfile.value = true
    try {
      const currentUser = await authApi.me()
      profile.value = currentUser.user
      roleNames.value = currentUser.roles.map((role) => role.name)
      permissions.value = currentUser.permissions
      menus.value = currentUser.menus
      fieldPermissions.value = currentUser.field_permissions ?? {}
      dataScope.value = currentUser.data_scope
      dataScopeLabel.value = currentUser.data_scope_label
      domainScope.value = currentUser.domain_scope ?? ''
      assetDomains.value = currentUser.asset_domains ?? []
      resourceScopes.value = currentUser.resource_scopes ?? {}
      permissionsLoaded.value = true
      isSuperAdmin.value = currentUser.roles.some((role) => role.code === 'SUPER_ADMIN')
      accessToken.value = getAccessToken()
    } finally {
      loadingProfile.value = false
    }
  }

  async function logout(): Promise<void> {
    try {
      await authApi.logout(getRefreshToken())
    } catch {
      // 令牌可能已过期；本地清理必须始终执行
    } finally {
      reset()
    }
  }

  function reset(): void {
    clearTokenBundle()
    accessToken.value = null
    profile.value = null
    roleNames.value = []
    permissions.value = []
    menus.value = []
    fieldPermissions.value = {}
    dataScope.value = ''
    dataScopeLabel.value = ''
    domainScope.value = ''
    assetDomains.value = []
    resourceScopes.value = {}
    permissionsLoaded.value = false
    isSuperAdmin.value = false
  }

  function hasPerm(code: string): boolean {
    return isSuperAdmin.value || permissions.value.includes(code)
  }

  function hasAnyPerm(codes: string[]): boolean {
    return codes.some((code) => hasPerm(code))
  }

  function fieldPermission(resource: string, field: string): FieldPermission {
    if (isSuperAdmin.value) return { can_view: true, can_edit: true }
    return fieldPermissions.value[resource]?.[field] ?? { can_view: true, can_edit: true }
  }

  function canViewField(resource: string, field: string): boolean {
    return fieldPermission(resource, field).can_view
  }

  function canEditField(resource: string, field: string): boolean {
    return fieldPermission(resource, field).can_edit
  }

  return {
    profile,
    roleNames,
    permissions,
    menus,
    fieldPermissions,
    dataScope,
    dataScopeLabel,
    domainScope,
    assetDomains,
    resourceScopes,
    permissionsLoaded,
    isSuperAdmin,
    loadingProfile,
    isAuthenticated,
    login,
    fetchProfile,
    logout,
    reset,
    hasPerm,
    hasAnyPerm,
    canViewField,
    canEditField,
  }
})
