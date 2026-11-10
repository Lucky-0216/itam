<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch, type Component } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  ArrowDown,
  ArrowRight,
  Bell,
  Brush,
  Check,
  Connection,
  DataAnalysis,
  Expand,
  Finished,
  Fold,
  FullScreen,
  InfoFilled,
  Lock,
  Moon,
  OfficeBuilding,
  Refresh,
  Search,
  Sunny,
  SwitchButton,
  VideoPause,
  VideoPlay,
  Warning,
} from '@element-plus/icons-vue'

import { notificationApi } from '@/api/notifications'
import { searchApi } from '@/api/search'
import { useAppStore, type ThemePrimary } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import { useTodoStore } from '@/stores/todo'
import type { NotificationItem } from '@/types/notification'
import type { SearchItem, SearchItemType } from '@/types/search'
import { formatDateTime, initials } from '@/utils/format'

const emit = defineEmits<{
  (event: 'toggle-sidebar'): void
  (event: 'refresh-page'): void
}>()

const appStore = useAppStore()
const auth = useAuthStore()
const todoStore = useTodoStore()
const route = useRoute()
const router = useRouter()
const canViewReminders = computed(() => auth.hasPerm('asset:reminder:view'))

const themePrimary: { value: ThemePrimary; label: string; hint: string; swatch: string }[] = [
  { value: 'blue', label: '雾蓝', hint: '沉静 · 默认', swatch: 'linear-gradient(120deg, #47679d, #5b82b6)' },
  { value: 'teal', label: '青瓷', hint: '松绿 · 温和', swatch: 'linear-gradient(120deg, #3f6f68, #5d968c)' },
  { value: 'violet', label: '黛紫', hint: '雅致 · 克制', swatch: 'linear-gradient(120deg, #57497f, #7b6aa9)' },
  { value: 'white', label: '纯白', hint: '单色 · 极简', swatch: 'linear-gradient(120deg, #ffffff, #e9edf3)' },
]

const isFullscreen = ref(false)
const refreshing = ref(false)
const notificationDrawer = ref(false)
const notificationLoading = ref(false)
const notifications = ref<NotificationItem[]>([])
const readIds = ref<string[]>(loadReadIds())
const readIdSet = computed(() => new Set(readIds.value))
const unreadCount = computed(
  () => notifications.value.filter((item) => !readIdSet.value.has(item.id)).length,
)
let refreshTimer: ReturnType<typeof setTimeout> | undefined
let notificationTimer: ReturnType<typeof setInterval> | undefined

const SEARCH_GROUP_LABELS: Record<SearchItemType, string> = {
  asset: '资产',
  user: '人员',
  dept: '部门',
}
const SEARCH_GROUP_ORDER: SearchItemType[] = ['asset', 'user', 'dept']

const searchBoxRef = ref<HTMLElement>()
const searchKeyword = ref('')
const searchOpen = ref(false)
const searchLoading = ref(false)
const searchItems = ref<SearchItem[]>([])
let searchTimer: ReturnType<typeof setTimeout> | undefined
let searchSeq = 0

const searchGroups = computed(() =>
  SEARCH_GROUP_ORDER.map((type) => ({
    type,
    label: SEARCH_GROUP_LABELS[type],
    items: searchItems.value.filter((item) => item.type === type),
  })).filter((group) => group.items.length > 0),
)

function closeSearch(): void {
  searchOpen.value = false
}

function onSearchInput(): void {
  if (searchTimer) {
    clearTimeout(searchTimer)
    searchTimer = undefined
  }
  const keyword = searchKeyword.value.trim()
  searchOpen.value = true
  if (!keyword) {
    searchSeq += 1
    searchLoading.value = false
    searchItems.value = []
    return
  }
  searchTimer = setTimeout(() => {
    void runSearch(keyword)
  }, 280)
}

async function runSearch(keyword: string): Promise<void> {
  const seq = ++searchSeq
  searchLoading.value = true
  try {
    const result = await searchApi.global(keyword)
    if (seq !== searchSeq) return
    searchItems.value = result.items
  } catch {
    if (seq === searchSeq) searchItems.value = []
  } finally {
    if (seq === searchSeq) searchLoading.value = false
  }
}

function openSearch(): void {
  if (searchKeyword.value.trim()) searchOpen.value = true
}

function clearSearch(): void {
  if (searchTimer) {
    clearTimeout(searchTimer)
    searchTimer = undefined
  }
  searchSeq += 1
  searchKeyword.value = ''
  searchItems.value = []
  searchLoading.value = false
  searchOpen.value = false
}

function goSearchItem(item: SearchItem): void {
  closeSearch()
  if (item.type === 'asset') {
    void router.push({ path: '/assets/ledger', query: { keyword: item.keyword } })
  } else if (item.type === 'user') {
    void router.push({ path: '/system/org', query: { keyword: item.keyword } })
  } else {
    void router.push({ path: '/system/org', query: { dept_id: String(item.id) } })
  }
}

async function handleSearchEnter(): Promise<void> {
  const keyword = searchKeyword.value.trim()
  if (!keyword) return
  if (searchTimer) {
    clearTimeout(searchTimer)
    searchTimer = undefined
  }
  await runSearch(keyword)
  const first = searchItems.value[0]
  if (first) {
    goSearchItem(first)
  } else {
    ElMessage.info('没有找到匹配的资产 / 人员 / 部门')
  }
}

function handleDocumentClick(event: MouseEvent): void {
  if (!searchOpen.value) return
  if (searchBoxRef.value?.contains(event.target as Node)) return
  closeSearch()
}

watch(
  () => route.fullPath,
  () => closeSearch(),
)

const READ_STORAGE_KEY = 'itam:read-notifications'

function loadReadIds(): string[] {
  try {
    const raw = localStorage.getItem(READ_STORAGE_KEY)
    const parsed = raw ? JSON.parse(raw) : []
    return Array.isArray(parsed) ? parsed.filter((item) => typeof item === 'string') : []
  } catch {
    return []
  }
}

function persistReadIds(): void {
  try {
    localStorage.setItem(READ_STORAGE_KEY, JSON.stringify(readIds.value))
  } catch {
    // 本地存储不可用时仅影响已读标记
  }
}

const pageTitle = computed(() => route.meta.title || '工作台')
const displayName = computed(() => auth.profile?.real_name || auth.profile?.username || '未登录')
const roleLabel = computed(() => auth.roleNames.join(' · ') || '暂无角色')
const sidebarIcon = computed(() => (appStore.sidebarCollapsed ? Expand : Fold))

function toggleFullscreen(): void {
  if (document.fullscreenElement) {
    void document.exitFullscreen()
    return
  }
  document.documentElement.requestFullscreen().catch(() => {
    ElMessage.warning('当前浏览器不支持全屏模式')
  })
}

function syncFullscreen(): void {
  isFullscreen.value = Boolean(document.fullscreenElement)
}

function handleRefresh(): void {
  if (refreshing.value) return
  refreshing.value = true
  emit('refresh-page')
  refreshTimer = setTimeout(() => {
    refreshing.value = false
  }, 650)
}

async function loadNotifications(): Promise<void> {
  notificationLoading.value = true
  try {
    const result = await notificationApi.summary()
    notifications.value = result.items
    const validIds = new Set(result.items.map((item) => item.id))
    readIds.value = readIds.value.filter((id) => validIds.has(id))
  } finally {
    notificationLoading.value = false
  }
}

function openNotifications(): void {
  notificationDrawer.value = true
  void loadNotifications()
}

function markRead(id: string): void {
  if (readIdSet.value.has(id)) return
  readIds.value = [...readIds.value, id]
  persistReadIds()
}

function markAllRead(): void {
  readIds.value = notifications.value.map((item) => item.id)
  persistReadIds()
}

function handleNotificationClick(item: NotificationItem): void {
  markRead(item.id)
  notificationDrawer.value = false
  if (item.link) {
    void router.push(item.link)
  }
}

function openTodoCenter(): void {
  void todoStore.refresh()
  void router.push('/todos')
}

function openReminderCenter(): void {
  notificationDrawer.value = false
  void router.push('/assets/reminders')
}

function notificationIcon(item: NotificationItem): Component {
  if (item.level === 'danger' || item.level === 'warning') return Warning
  if (item.category === 'ldap') return Connection
  if (item.category === 'security') return Lock
  return InfoFilled
}

function notificationCategory(category: string): string {
  return (
    {
      asset: '资产提醒',
      ldap: '域控同步',
      security: '安全提醒',
      contract: '合同提醒',
      inventory: '盘点提醒',
    }[category] || '系统通知'
  )
}

async function handleLogout(): Promise<void> {
  try {
    await ElMessageBox.confirm('退出后需要重新登录才能继续使用系统。', '确认退出登录', {
      confirmButtonText: '退出登录',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return
  }
  await auth.logout()
  todoStore.reset()
  ElMessage.success('已安全退出')
  void router.replace('/login')
}

function handleCommand(command: string): void {
  if (command === 'password') {
    void router.push('/change-password')
  } else if (command === 'appearance') {
    void router.push('/settings/appearance')
  } else if (command === 'logout') {
    void handleLogout()
  }
}

onMounted(() => {
  syncFullscreen()
  document.addEventListener('fullscreenchange', syncFullscreen)
  document.addEventListener('click', handleDocumentClick)
  todoStore.start()
  void loadNotifications()
  notificationTimer = setInterval(() => {
    void loadNotifications()
  }, 5 * 60 * 1000)
})

onBeforeUnmount(() => {
  document.removeEventListener('fullscreenchange', syncFullscreen)
  document.removeEventListener('click', handleDocumentClick)
  todoStore.stop()
  if (refreshTimer) clearTimeout(refreshTimer)
  if (notificationTimer) clearInterval(notificationTimer)
  if (searchTimer) clearTimeout(searchTimer)
})
</script>

<template>
  <header class="app-header">
    <div class="header-left">
      <el-tooltip :content="appStore.sidebarCollapsed ? '展开导航' : '收起导航'" placement="bottom">
        <button class="header-icon-btn" type="button" aria-label="切换导航" @click="emit('toggle-sidebar')">
          <el-icon :size="19"><component :is="sidebarIcon" /></el-icon>
        </button>
      </el-tooltip>
      <div class="header-divider" />
      <div class="header-breadcrumb">
        <span class="breadcrumb-home">ITAM</span>
        <span class="breadcrumb-separator">/</span>
        <span class="breadcrumb-current">{{ pageTitle }}</span>
      </div>
    </div>

    <div class="header-right">
      <div ref="searchBoxRef" class="global-search">
        <el-input
          v-model="searchKeyword"
          class="global-search-input"
          placeholder="搜索资产编号 / 序列号 / 人员 / 部门"
          clearable
          :prefix-icon="Search"
          @input="onSearchInput"
          @focus="openSearch"
          @keyup.enter="handleSearchEnter"
          @clear="clearSearch"
        />
        <div v-if="searchOpen && searchKeyword.trim()" class="search-panel">
          <div v-if="searchLoading" class="search-hint-row">搜索中…</div>
          <template v-else-if="searchGroups.length">
            <div v-for="group in searchGroups" :key="group.type" class="search-group">
              <p class="search-group-label">{{ group.label }}</p>
              <button
                v-for="item in group.items"
                :key="`${item.type}-${item.id}`"
                type="button"
                class="search-item"
                @click="goSearchItem(item)"
              >
                <span class="search-item-title">{{ item.title }}</span>
                <span v-if="item.subtitle" class="search-item-subtitle">{{ item.subtitle }}</span>
              </button>
            </div>
          </template>
          <div v-else class="search-hint-row">没有找到匹配的资产 / 人员 / 部门</div>
        </div>
      </div>

      <el-tooltip content="刷新当前页" placement="bottom">
        <button
          class="header-icon-btn"
          :class="{ 'is-active': refreshing }"
          type="button"
          aria-label="刷新当前页"
          @click="handleRefresh"
        >
          <el-icon :size="18" :class="{ 'spin-once': refreshing }"><Refresh /></el-icon>
        </button>
      </el-tooltip>

      <el-tooltip :content="appStore.animationsEnabled ? '关闭页面动效' : '开启页面动效'" placement="bottom">
        <button
          class="header-icon-btn"
          :class="{ 'is-active': !appStore.animationsEnabled }"
          type="button"
          aria-label="切换页面动效"
          @click="appStore.toggleAnimations()"
        >
          <el-icon :size="18">
            <component :is="appStore.animationsEnabled ? VideoPause : VideoPlay" />
          </el-icon>
        </button>
      </el-tooltip>

      <el-dropdown trigger="click" placement="bottom-end">
        <button class="header-icon-btn" type="button" aria-label="主题设置">
          <el-icon :size="18"><Brush /></el-icon>
        </button>
        <template #dropdown>
          <div class="theme-panel">
            <p class="theme-label">外观模式</p>
            <div class="theme-mode">
              <button
                type="button"
                class="theme-mode-btn"
                :class="{ active: !appStore.isDark }"
                @click="appStore.setTheme('light')"
              >
                <el-icon><Sunny /></el-icon>
                <span>亮色</span>
              </button>
              <button
                type="button"
                class="theme-mode-btn"
                :class="{ active: appStore.isDark }"
                @click="appStore.setTheme('dark')"
              >
                <el-icon><Moon /></el-icon>
                <span>暗色</span>
              </button>
            </div>

            <p class="theme-label">主色</p>
            <div class="theme-list">
              <button
                v-for="item in themePrimary"
                :key="item.value"
                type="button"
                class="theme-option"
                :class="{ active: appStore.primary === item.value }"
                @click="appStore.setPrimary(item.value)"
              >
                <span class="theme-swatch" :style="{ background: item.swatch }" />
                <span class="theme-copy">
                  <strong>{{ item.label }}</strong>
                  <small>{{ item.hint }}</small>
                </span>
                <el-icon v-if="appStore.primary === item.value" class="theme-check">
                  <Check />
                </el-icon>
              </button>
            </div>
            <button class="theme-more" type="button" @click="router.push('/settings/appearance')">
              更多外观设置
              <el-icon><ArrowRight /></el-icon>
            </button>
          </div>
        </template>
      </el-dropdown>

      <el-tooltip :content="isFullscreen ? '退出全屏' : '全屏显示'" placement="bottom">
        <button class="header-icon-btn" type="button" aria-label="切换全屏" @click="toggleFullscreen">
          <el-icon :size="18"><FullScreen /></el-icon>
        </button>
      </el-tooltip>

      <el-tooltip
        :content="todoStore.total ? `我的待办 · ${todoStore.total} 项未完成` : '我的待办'"
        placement="bottom"
      >
        <button class="header-icon-btn todo-btn" type="button" aria-label="我的待办" @click="openTodoCenter">
          <el-icon :size="18"><Finished /></el-icon>
          <span v-if="todoStore.total" class="notification-badge todo-badge">
            {{ todoStore.total > 99 ? '99+' : todoStore.total }}
          </span>
        </button>
      </el-tooltip>

      <el-tooltip :content="unreadCount ? `${unreadCount} 条未读通知` : '通知中心'" placement="bottom">
        <button class="header-icon-btn notification-btn" type="button" aria-label="通知中心" @click="openNotifications">
          <el-icon :size="18"><Bell /></el-icon>
          <span v-if="unreadCount" class="notification-badge">
            {{ unreadCount > 99 ? '99+' : unreadCount }}
          </span>
        </button>
      </el-tooltip>

      <div class="header-divider" />

      <el-dropdown trigger="click" placement="bottom-end" @command="handleCommand">
        <div class="user-chip" role="button" tabindex="0">
          <div class="user-avatar">{{ initials(displayName) }}</div>
          <div class="user-meta">
            <span class="user-name">{{ displayName }}</span>
            <span class="user-role">{{ roleLabel }}</span>
          </div>
          <el-icon class="user-arrow" :size="12"><ArrowDown /></el-icon>
        </div>
        <template #dropdown>
          <el-dropdown-menu>
            <div class="user-dropdown-head">
              <div class="dd-avatar">{{ initials(displayName) }}</div>
              <div class="dd-copy">
                <strong class="dd-name">{{ displayName }}</strong>
                <span class="dd-username">@{{ auth.profile?.username || '—' }}</span>
              </div>
            </div>
            <div class="dd-meta">
              <span class="dd-meta-row">
                <el-icon><OfficeBuilding /></el-icon>
                {{ auth.profile?.dept_name || '未分配部门' }}
                <template v-if="auth.profile?.position"> · {{ auth.profile.position }}</template>
              </span>
              <span class="dd-meta-row">
                <el-icon><DataAnalysis /></el-icon>
                数据范围：{{ auth.dataScopeLabel || '—' }}
              </span>
              <span class="dd-meta-row">
                <el-icon><Lock /></el-icon>
                最近登录：{{ formatDateTime(auth.profile?.last_login_at) }}
              </span>
            </div>
            <el-dropdown-item command="appearance" :icon="Brush">外观设置</el-dropdown-item>
            <el-dropdown-item command="password" :icon="Lock">修改密码</el-dropdown-item>
            <el-dropdown-item command="logout" :icon="SwitchButton" divided>退出登录</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>
  </header>

  <el-drawer
    v-model="notificationDrawer"
    size="400px"
    class="notification-drawer"
    destroy-on-close
  >
    <template #header>
      <div class="drawer-head">
        <div>
          <p class="drawer-eyebrow">NOTIFICATIONS</p>
          <h3 class="drawer-title">
            通知中心
            <span v-if="unreadCount" class="drawer-count">{{ unreadCount }} 条未读</span>
          </h3>
        </div>
        <div class="drawer-actions">
          <el-button text size="small" :disabled="!unreadCount" @click="markAllRead">全部已读</el-button>
          <el-button
            text
            size="small"
            :icon="Refresh"
            :loading="notificationLoading"
            @click="loadNotifications"
          >
            刷新
          </el-button>
        </div>
      </div>
    </template>

    <div v-loading="notificationLoading" class="notification-list">
      <div v-if="!notifications.length && !notificationLoading" class="notification-empty">
        <span class="empty-icon"><el-icon><Bell /></el-icon></span>
        <p>暂无提醒</p>
        <span>保修、合同、借用、盘点等提醒会在这里展示</span>
      </div>

      <button
        v-for="item in notifications"
        :key="item.id"
        type="button"
        class="notification-item"
        :class="[`level-${item.level}`, { unread: !readIdSet.has(item.id) }]"
        @click="handleNotificationClick(item)"
      >
        <span class="notification-icon">
          <el-icon><component :is="notificationIcon(item)" /></el-icon>
        </span>
        <span class="notification-body">
          <span class="notification-top">
            <strong>{{ item.title }}</strong>
            <span class="notification-time">{{ formatDateTime(item.occurred_at) }}</span>
          </span>
          <span class="notification-desc">{{ item.description }}</span>
          <span class="notification-foot">
            <span class="notification-category">{{ notificationCategory(item.category) }}</span>
            <span v-if="!readIdSet.has(item.id)" class="unread-dot">未读</span>
            <el-icon v-if="item.link" class="notification-link"><ArrowRight /></el-icon>
          </span>
        </span>
      </button>
    </div>

    <div v-if="canViewReminders" class="drawer-footer">
      <el-button type="primary" plain :icon="Bell" @click="openReminderCenter">
        进入到期提醒中心
      </el-button>
      <span>保修 / 合同 / 借用 / 盘点统一视图</span>
    </div>
  </el-drawer>
</template>

<style scoped>
.global-search {
  position: relative;
  width: 260px;
}

.global-search-input :deep(.el-input__wrapper) {
  border-radius: 11px;
  background: var(--surface-muted);
  box-shadow: none;
}

.global-search-input :deep(.el-input__wrapper.is-focus) {
  background: var(--surface);
  box-shadow: 0 0 0 1px var(--brand) inset;
}

.search-panel {
  position: absolute;
  top: calc(100% + 10px);
  right: 0;
  z-index: 40;
  width: 340px;
  max-height: 420px;
  overflow-y: auto;
  padding: 8px;
  border: 1px solid var(--border);
  border-radius: 14px;
  background: var(--surface);
  box-shadow: 0 18px 40px rgba(15, 23, 42, 0.16);
}

.search-group + .search-group {
  margin-top: 6px;
  padding-top: 6px;
  border-top: 1px dashed var(--border);
}

.search-group-label {
  margin: 2px 8px 6px;
  color: var(--text-3);
  font-size: 10.5px;
  font-weight: 600;
  letter-spacing: 0.08em;
}

.search-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  width: 100%;
  padding: 8px 10px;
  border: none;
  border-radius: 9px;
  background: transparent;
  text-align: left;
  cursor: pointer;
}

.search-item:hover {
  background: var(--surface-muted);
}

.search-item-title {
  color: var(--text-1);
  font-size: 12.8px;
  font-weight: 600;
}

.search-item-subtitle {
  overflow: hidden;
  color: var(--text-3);
  font-size: 11.5px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.search-hint-row {
  padding: 18px 10px;
  color: var(--text-3);
  font-size: 12px;
  text-align: center;
}

@media (max-width: 1100px) {
  .global-search {
    display: none;
  }
}

.user-arrow {
  color: var(--text-3);
  margin-left: 2px;
}

.spin-once {
  animation: header-spin 0.6s cubic-bezier(0.22, 1, 0.36, 1);
}

@keyframes header-spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

.user-dropdown-head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px 10px;
}

.dd-avatar {
  display: grid;
  place-items: center;
  width: 38px;
  height: 38px;
  border-radius: 11px;
  background: var(--gradient-brand);
  color: var(--on-brand);
  font-size: 12.5px;
  font-weight: 700;
}

.dd-copy {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.dd-name {
  color: var(--text-1);
  font-size: 13.5px;
  font-weight: 600;
}

.dd-username {
  color: var(--text-3);
  font-size: 11.5px;
}

.dd-meta {
  display: flex;
  flex-direction: column;
  gap: 5px;
  padding: 2px 12px 10px;
  border-bottom: 1px solid var(--border);
  margin-bottom: 4px;
}

.dd-meta-row {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--text-2);
  font-size: 12px;
  white-space: nowrap;
}

.dd-meta-row .el-icon {
  color: var(--text-3);
  font-size: 13px;
}

:deep(.el-dropdown-menu__item) {
  font-size: 13px;
}

.theme-panel {
  width: 236px;
  padding: 12px;
}

.theme-label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 0 2px 8px;
  color: var(--text-3);
  font-size: 10.5px;
  font-weight: 700;
  letter-spacing: 0.1em;
}

.theme-list + .theme-label {
  margin-top: 14px;
}

.theme-more {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  width: 100%;
  margin-top: 10px;
  padding: 7px 0 2px;
  border: 0;
  border-top: 1px solid var(--border);
  background: transparent;
  color: var(--text-3);
  font-size: 11.5px;
  cursor: pointer;
}

.theme-more:hover {
  color: var(--brand);
}

.theme-mode {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin-bottom: 14px;
}

.theme-mode-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 34px;
  border: 1px solid var(--border);
  border-radius: 9px;
  background: var(--surface-muted);
  color: var(--text-2);
  font-size: 12.5px;
  cursor: pointer;
  transition: border-color 0.18s ease, background-color 0.18s ease, color 0.18s ease;
}

.theme-mode-btn:hover {
  border-color: var(--border-strong);
  color: var(--text-1);
}

.theme-mode-btn.active {
  border-color: var(--brand);
  background: var(--brand-soft);
  color: var(--brand-strong);
}

html.dark .theme-mode-btn.active {
  color: color-mix(in srgb, var(--brand) 58%, #ffffff);
}

.theme-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.theme-option {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 8px 10px;
  border: 1px solid transparent;
  border-radius: 10px;
  background: transparent;
  text-align: left;
  cursor: pointer;
  transition: background-color 0.18s ease, border-color 0.18s ease;
}

.theme-option:hover {
  background: var(--surface-muted);
}

.theme-option.active {
  border-color: var(--brand);
  background: var(--brand-soft);
}

.theme-swatch {
  width: 26px;
  height: 26px;
  flex-shrink: 0;
  border-radius: 8px;
  box-shadow: inset 0 0 0 1px rgba(15, 23, 42, 0.16);
}

.theme-copy {
  display: flex;
  flex-direction: column;
  line-height: 1.3;
}

.theme-copy strong {
  color: var(--text-1);
  font-size: 12.5px;
  font-weight: 600;
}

.theme-copy small {
  color: var(--text-3);
  font-size: 11px;
}

.theme-check {
  margin-left: auto;
  color: var(--brand);
  font-size: 14px;
}

.notification-btn {
  position: relative;
}

.todo-btn {
  position: relative;
}

.todo-badge {
  background: var(--brand);
  color: var(--on-brand);
}

.notification-badge {
  position: absolute;
  top: -3px;
  right: -5px;
  min-width: 17px;
  height: 17px;
  padding: 0 4px;
  border-radius: 999px;
  background: var(--danger);
  color: #fff;
  font-size: 10px;
  font-weight: 700;
  line-height: 17px;
  text-align: center;
  box-shadow: 0 0 0 2px var(--surface);
}

.drawer-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
}

.drawer-eyebrow {
  margin: 0;
  color: var(--text-3);
  font-size: 10.5px;
  letter-spacing: 0.08em;
}

.drawer-title {
  display: flex;
  align-items: baseline;
  gap: 9px;
  margin: 3px 0 0;
  color: var(--text-1);
  font-size: 17px;
  font-weight: 650;
}

.drawer-count {
  color: var(--brand);
  font-size: 11.5px;
  font-weight: 500;
}

.drawer-actions {
  display: flex;
  align-items: center;
  gap: 2px;
}

.notification-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 180px;
}

.notification-item {
  display: flex;
  align-items: flex-start;
  gap: 11px;
  width: 100%;
  padding: 13px 14px;
  border: 1px solid var(--border);
  border-radius: 13px;
  background: var(--surface);
  text-align: left;
  cursor: pointer;
  transition:
    border-color 0.18s ease,
    background-color 0.18s ease,
    transform 0.18s ease;
}

.notification-item:hover {
  border-color: var(--brand);
  background: var(--surface-muted);
  transform: translateY(-1px);
}

.notification-item.unread {
  border-color: var(--brand);
  background: var(--gradient-brand-soft);
}

.notification-item.unread:hover {
  border-color: var(--brand);
}

.notification-icon {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  flex-shrink: 0;
  border-radius: 10px;
  background: var(--surface);
  color: var(--brand);
}

.notification-item.level-danger .notification-icon {
  background: rgba(239, 68, 68, 0.1);
  color: #ef4444;
}

.notification-item.level-warning .notification-icon {
  background: rgba(245, 158, 11, 0.13);
  color: #d97706;
}

.notification-icon svg {
  width: 16px;
  height: 16px;
}

.notification-body {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
  flex: 1;
}

.notification-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.notification-top strong {
  color: var(--text-1);
  font-size: 12.8px;
  font-weight: 600;
  line-height: 1.5;
}

.notification-time {
  flex-shrink: 0;
  color: var(--text-3);
  font-size: 10.5px;
  line-height: 1.7;
}

.notification-desc {
  display: -webkit-box;
  overflow: hidden;
  color: var(--text-2);
  font-size: 11.8px;
  line-height: 1.6;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.notification-foot {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 2px;
}

.notification-category {
  padding: 1px 7px;
  border-radius: 999px;
  background: var(--surface-muted);
  color: var(--text-3);
  font-size: 10.5px;
}

.notification-item.unread .notification-category {
  background: var(--brand-soft);
  color: var(--brand);
}

.unread-dot {
  color: var(--brand);
  font-size: 10.5px;
  font-weight: 600;
}

.notification-link {
  margin-left: auto;
  color: var(--text-3);
  font-size: 12px;
}

.notification-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 48px 16px;
  color: var(--text-3);
  text-align: center;
}

.empty-icon {
  display: grid;
  place-items: center;
  width: 52px;
  height: 52px;
  margin-bottom: 6px;
  border-radius: 16px;
  background: var(--surface-muted);
  color: var(--text-3);
}

.empty-icon svg {
  width: 24px;
  height: 24px;
}

.notification-empty p {
  margin: 0;
  color: var(--text-1);
  font-size: 13.5px;
  font-weight: 600;
}

.notification-empty span {
  font-size: 11.5px;
}

.drawer-footer {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding-top: 16px;
  margin-top: 16px;
  border-top: 1px dashed var(--border);
}

.drawer-footer span {
  color: var(--text-3);
  font-size: 11px;
}

:deep(.el-drawer__header) {
  margin-bottom: 14px;
  padding: 20px 20px 0;
}

:deep(.el-drawer__body) {
  padding: 0 20px 20px;
}
</style>
