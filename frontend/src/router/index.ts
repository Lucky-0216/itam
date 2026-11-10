import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

import { pinia } from '@/stores'
import { useAuthStore } from '@/stores/auth'

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/login/index.vue'),
    meta: { title: '登录', public: true },
  },
  {
    path: '/',
    component: () => import('@/components/layout/AppLayout.vue'),
    redirect: '/dashboard',
    children: [
      {
        path: 'dashboard',
        name: 'Dashboard',
        component: () => import('@/views/dashboard/index.vue'),
        meta: { title: '工作台', perm: 'dashboard:view', icon: 'Odometer' },
      },
      {
        path: 'assets/categories',
        name: 'AssetCategories',
        component: () => import('@/views/assets/categories/index.vue'),
        meta: { title: '资产分类', perm: 'asset:category:view', icon: 'Files' },
      },
      {
        path: 'assets/ledger',
        name: 'AssetLedger',
        component: () => import('@/views/assets/ledger/index.vue'),
        meta: { title: '资产台账', perm: 'asset:ledger:view', icon: 'Monitor' },
      },
      {
        path: 'assets/requisitions',
        name: 'AssetRequisitions',
        component: () => import('@/views/assets/requisitions/index.vue'),
        meta: { title: '领用申请', perm: 'asset:requisition:view', icon: 'Tickets' },
      },
      {
        path: 'assets/mine',
        name: 'MyAssets',
        component: () => import('@/views/assets/mine/index.vue'),
        meta: { title: '我的资产', perm: 'asset:mine:view', icon: 'User' },
      },
      {
        path: 'assets/review',
        name: 'AssetReview',
        component: () => import('@/views/assets/review/index.vue'),
        meta: { title: '业务审批', perm: 'asset:request:review', icon: 'Tools' },
      },
      {
        path: 'assets/outbound',
        name: 'AssetOutbound',
        component: () => import('@/views/assets/review/index.vue'),
        meta: { title: '资产领用确认', perm: 'asset:outbound:view', icon: 'Box' },
      },
      {
        path: 'assets/direct-outbound',
        name: 'AssetDirectOutbound',
        component: () => import('@/views/assets/direct-outbound/index.vue'),
        meta: {
          title: '资产出库',
          perm: 'asset:outbound:direct',
          icon: 'Promotion',
        },
      },
      {
        path: 'assets/returns',
        name: 'AssetReturnReview',
        component: () => import('@/views/assets/review/index.vue'),
        meta: { title: '资产归还确认', perm: 'asset:return:confirm:view', icon: 'Connection' },
      },
      {
        path: 'assets/transfers',
        name: 'AssetTransfers',
        component: () => import('@/views/assets/transfers/index.vue'),
        meta: { title: '资产调拨', perm: 'asset:transfer:view', icon: 'Connection' },
      },
      {
        path: 'assets/scraps',
        name: 'AssetScraps',
        component: () => import('@/views/assets/scraps/index.vue'),
        meta: { title: '资产报废', perm: 'asset:scrap:view', icon: 'Document' },
      },
      {
        path: 'assets/inventory',
        name: 'AssetInventory',
        component: () => import('@/views/assets/inventory/index.vue'),
        meta: { title: '资产盘点', perm: 'asset:inventory:view', icon: 'Files' },
      },
      {
        path: 'assets/inbounds',
        name: 'AssetInbounds',
        component: () => import('@/views/assets/inbounds/index.vue'),
        meta: { title: '资产入库', perm: 'asset:inbound:view', icon: 'Box' },
      },
      {
        path: 'assets/stock',
        name: 'AssetStock',
        component: () => import('@/views/assets/stock/index.vue'),
        meta: { title: '库存管理', perm: 'asset:stock:view', icon: 'Grid' },
      },
      {
        path: 'assets/maintenance',
        name: 'AssetMaintenance',
        component: () => import('@/views/assets/maintenance/index.vue'),
        meta: { title: '维修管理', perm: 'asset:maintenance:view', icon: 'Tools' },
      },
      {
        path: 'assets/contracts',
        name: 'AssetContracts',
        component: () => import('@/views/assets/contracts/index.vue'),
        meta: { title: '合同管理', perm: 'asset:contract:view', icon: 'Memo' },
      },
      {
        path: 'assets/reports',
        name: 'AssetReports',
        component: () => import('@/views/assets/reports/index.vue'),
        meta: { title: '报表分析', perm: 'asset:report:view', icon: 'DataAnalysis' },
      },
      {
        path: 'assets/reminders',
        name: 'AssetReminders',
        component: () => import('@/views/assets/reminders/index.vue'),
        meta: { title: '到期提醒', perm: 'asset:reminder:view', icon: 'Bell' },
      },
      {
        path: 'system/org',
        name: 'SystemOrg',
        component: () => import('@/views/system/org/index.vue'),
        meta: { title: '组织架构', perm: 'system:org:view', icon: 'OfficeBuilding' },
      },
      {
        path: 'system/dept-managers',
        name: 'SystemDeptManagers',
        component: () => import('@/views/system/dept-managers/index.vue'),
        meta: { title: '部门负责人', perm: 'system:dept-manager:view', icon: 'UserFilled' },
      },
      {
        path: 'system/roles',
        name: 'SystemRoles',
        component: () => import('@/views/system/roles/index.vue'),
        meta: { title: '角色权限', perm: 'system:role:view', icon: 'Key' },
      },
      {
        path: 'system/audit',
        name: 'SystemAudit',
        component: () => import('@/views/system/audit/index.vue'),
        meta: { title: '审计日志', perm: 'system:audit:view', icon: 'Document' },
      },
      {
        path: 'system/ldap',
        name: 'SystemLdap',
        component: () => import('@/views/system/ldap/index.vue'),
        meta: { title: '域控同步', perm: 'system:ldap:view', icon: 'Connection' },
      },
      {
        path: 'system/dingtalk',
        name: 'SystemDingtalk',
        component: () => import('@/views/system/dingtalk/index.vue'),
        meta: { title: '钉钉同步', perm: 'system:dingtalk:view', icon: 'ChatDotRound' },
      },
      {
        path: 'system/org-sync-policy',
        name: 'SystemOrgSyncPolicy',
        component: () => import('@/views/system/org-sync-policy/index.vue'),
        meta: {
          title: '组织同步策略',
          perm: 'system:org-sync-policy:view',
          icon: 'SetUp',
        },
      },
      {
        path: 'system/branding',
        name: 'SystemBranding',
        component: () => import('@/views/system/branding/index.vue'),
        meta: {
          title: '品牌与首页',
          perm: 'system:settings:view',
          icon: 'Brush',
        },
      },
      {
        path: 'system/approval-flows',
        name: 'SystemApprovalFlows',
        component: () => import('@/views/system/approval-flows/index.vue'),
        meta: {
          title: '审批流程配置',
          perm: 'asset:request:flow:view',
          icon: 'Share',
        },
      },
      {
        path: 'todos',
        name: 'TodoCenter',
        component: () => import('@/views/todos/index.vue'),
        meta: { title: '我的待办', icon: 'Finished' },
      },
      {
        path: 'change-password',
        name: 'ChangePassword',
        component: () => import('@/views/auth/ChangePassword.vue'),
        meta: { title: '修改密码' },
      },
      {
        path: 'settings/appearance',
        name: 'AppearanceSettings',
        component: () => import('@/views/settings/appearance.vue'),
        meta: { title: '外观设置' },
      },
      {
        path: '403',
        name: 'Forbidden',
        component: () => import('@/views/error/403.vue'),
        meta: { title: '无访问权限' },
      },
    ],
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'NotFound',
    component: () => import('@/views/error/404.vue'),
    meta: { title: '页面不存在', public: true },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 }),
})

router.beforeEach(async (to) => {
  document.title = to.meta.title ? `${to.meta.title} · ITAM` : 'ITAM · IT 资产管理系统'
  const auth = useAuthStore(pinia)

  if (to.meta.public) {
    if (to.path === '/login' && auth.isAuthenticated) {
      return { path: '/dashboard' }
    }
    return true
  }

  if (!auth.isAuthenticated) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }

  if (!auth.profile) {
    try {
      await auth.fetchProfile()
    } catch {
      auth.reset()
      return { path: '/login', query: { redirect: to.fullPath } }
    }
  }

  const current = auth.profile
  if (current?.must_change_password && to.path !== '/change-password') {
    return { path: '/change-password' }
  }

  if (to.meta.perm && !auth.hasPerm(to.meta.perm)) {
    return { path: '/403' }
  }

  return true
})

export default router
