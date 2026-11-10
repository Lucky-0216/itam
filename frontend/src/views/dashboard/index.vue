<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import dayjs from 'dayjs'
import * as echarts from 'echarts/core'
import type { EChartsCoreOption } from 'echarts/core'
import {
  ArrowRight,
  Bell,
  Box,
  DataAnalysis,
  Document,
  Files,
  Finished,
  Money,
  Monitor,
  Odometer,
  Refresh,
  ShoppingCart,
  Tickets,
  Van,
  WarningFilled,
} from '@element-plus/icons-vue'

import { dashboardApi } from '@/api/dashboard'
import EChart from '@/components/charts/EChart.vue'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import { useBrandingStore } from '@/stores/branding'
import { useTodoStore } from '@/stores/todo'
import {
  ASSET_STATUS_TAG_TYPES,
  type AssetStatus,
} from '@/types/asset'
import type {
  CategorySlice,
  DashboardMetrics,
  DashboardScope,
  DashboardSummary,
  DeptSlice,
  RecentAssetItem,
  StatusSlice,
  TrendPoint,
  WarrantyItem,
} from '@/types/dashboard'
import type { Announcement } from '@/types/branding'
import type { TodoCategoryGroup, TodoItem } from '@/types/todo'
import { formatDateTime, greeting, todayLabel } from '@/utils/format'

const EMPTY_METRICS: DashboardMetrics = {
  total_assets: 0,
  total_value: 0,
  pending_stock: 0,
  in_stock: 0,
  in_use: 0,
  idle: 0,
  repairing: 0,
  pending_scrap: 0,
  scrapped: 0,
  warranty_30d: 0,
  month_inbound: 0,
  month_requisition: 0,
  contract_expiring: 0,
  idle_rate: 0,
}

const STATUS_COLORS: Record<string, string> = {
  PENDING_STOCK: '#f59e0b',
  IN_STOCK: '#0ea5e9',
  IN_USE: '#2563eb',
  IDLE: '#14b8a6',
  REPAIRING: '#8b5cf6',
  PENDING_SCRAP: '#f97316',
  SCRAPPED: '#94a3b8',
}

const router = useRouter()
const app = useAppStore()
const auth = useAuthStore()
const brandingStore = useBrandingStore()
const todoStore = useTodoStore()

const loading = ref(false)
const failed = ref(false)
const summary = ref<DashboardSummary | null>(null)
const lastUpdated = ref('')
const scope = ref<DashboardScope>('personal')
const filters = reactive({
  dept_id: undefined as number | undefined,
  months: 12,
})
let summarySeq = 0

const isPersonal = computed(() => scope.value === 'personal')

const MONTH_OPTIONS = [
  { value: 3, label: '近 3 个月' },
  { value: 6, label: '近 6 个月' },
  { value: 12, label: '近 12 个月' },
  { value: 0, label: '全部' },
]

const deptOptions = computed(() =>
  (summary.value?.dept_options ?? []).map((dept) => ({
    value: dept.id,
    label: `${'· '.repeat(Math.max(0, dept.level - 1))}${dept.name}`,
  })),
)

const displayName = computed(() => auth.profile?.real_name || auth.profile?.username || '用户')
const announcements = computed<Announcement[]>(() => brandingStore.announcements)
const welcomeText = computed(() => {
  const template = brandingStore.branding.dashboard_welcome.trim()
  if (!template) return ''
  return template
    .replaceAll('{name}', displayName.value)
    .replaceAll('{greeting}', greeting())
})
const metrics = computed<DashboardMetrics>(() => summary.value?.metrics ?? EMPTY_METRICS)
const statusDistribution = computed<StatusSlice[]>(() => summary.value?.status_distribution ?? [])
const categoryDistribution = computed<CategorySlice[]>(
  () => summary.value?.category_distribution ?? [],
)
const deptDistribution = computed<DeptSlice[]>(() => summary.value?.dept_distribution ?? [])
const purchaseTrend = computed<TrendPoint[]>(() => summary.value?.purchase_trend ?? [])
const warrantyExpiring = computed<WarrantyItem[]>(() => summary.value?.warranty_expiring ?? [])
const recentAssets = computed<RecentAssetItem[]>(() => summary.value?.recent_assets ?? [])

const inUseRate = computed(() =>
  metrics.value.total_assets
    ? Math.round((metrics.value.in_use / metrics.value.total_assets) * 100)
    : 0,
)
const avgPrice = computed(() =>
  metrics.value.total_assets ? metrics.value.total_value / metrics.value.total_assets : 0,
)
const currentMonthNew = computed(() => {
  const points = purchaseTrend.value
  return points.length ? points[points.length - 1].count : 0
})
const maxDeptCount = computed(() =>
  Math.max(1, ...deptDistribution.value.map((item) => item.count)),
)
const periodNew = computed(() => summary.value?.period.new_assets ?? 0)

const canViewLedger = computed(() => auth.hasPerm('asset:ledger:view'))
const canViewMine = computed(() => auth.hasPerm('asset:mine:view'))
const canDrill = computed(() =>
  isPersonal.value ? canViewMine.value : canViewLedger.value,
)

function drillTitle(label?: string | null): string | undefined {
  if (!canDrill.value) return undefined
  if (isPersonal.value) return '查看我的资产'
  return label ? `查看「${label}」资产` : '查看资产'
}
const canViewAudit = computed(() => auth.hasPerm('system:audit:view'))
const canViewCategories = computed(() => auth.hasPerm('asset:category:view'))

const TODO_TONES: Record<string, string> = {
  APPROVAL: 'blue',
  CONFIRM: 'cyan',
  HANDLE: 'violet',
  MINE: 'amber',
  DUE: 'rose',
}

const todoGroups = computed<TodoCategoryGroup[]>(() =>
  todoStore.categories.filter((group) => group.count > 0),
)

function todoTone(category: string): string {
  return TODO_TONES[category] ?? 'blue'
}

function announcementTagType(
  level: Announcement['level'],
): 'primary' | 'warning' | 'danger' {
  if (level === 'IMPORTANT') return 'danger'
  if (level === 'WARNING') return 'warning'
  return 'primary'
}

function todoStatusTag(
  status: string,
): 'primary' | 'success' | 'info' | 'warning' | 'danger' {
  if (status === 'COMPLETED') return 'success'
  if (status === 'REJECTED') return 'danger'
  if (status === 'CANCELLED') return 'info'
  if (status.startsWith('PENDING') || status === 'WAITING') return 'warning'
  if (status === 'BORROWED' || status === 'REPAIRING' || status === 'IN_PROGRESS') return 'primary'
  return 'info'
}

function openTodoCenter(): void {
  void router.push('/todos')
}

function openTodoCategory(category: string): void {
  void router.push({ path: '/todos', query: { category } })
}

function openTodoItem(item: TodoItem): void {
  void router.push(item.link)
}

function visibleTodoItems(group: TodoCategoryGroup): TodoItem[] {
  return group.items.slice(0, 3)
}

function todoRest(group: TodoCategoryGroup): number {
  return Math.max(0, group.count - visibleTodoItems(group).length)
}

function cssVar(name: string, fallback: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return value || fallback
}

const chartPalette = computed(() => {
  const dark = app.isDark
  const primaryName = app.primary
  return {
    dark,
    primaryName,
    text2: cssVar('--text-2', '#5c6b83'),
    text3: cssVar('--text-3', '#93a0b4'),
    border: cssVar('--border', '#e5ebf4'),
    surface: cssVar('--surface', '#ffffff'),
    brand: cssVar('--brand', '#2563eb'),
    cyan: cssVar('--brand-cyan', '#06b6d4'),
  }
})

function withAlpha(color: string, alpha: number): string {
  if (!color.startsWith('#')) return color
  const hex =
    color.length === 4
      ? `#${color[1]}${color[1]}${color[2]}${color[2]}${color[3]}${color[3]}`
      : color
  if (hex.length !== 7) return color
  const r = Number.parseInt(hex.slice(1, 3), 16)
  const g = Number.parseInt(hex.slice(3, 5), 16)
  const b = Number.parseInt(hex.slice(5, 7), 16)
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}

function tooltipStyle(): Record<string, unknown> {
  const palette = chartPalette.value
  return {
    backgroundColor: cssVar('--el-bg-color-overlay', '#fdfdfe'),
    borderColor: palette.border,
    borderWidth: 1,
    padding: [8, 12],
    textStyle: { color: cssVar('--text-1', '#1d2430'), fontSize: 12 },
    extraCssText:
      'border-radius:10px;box-shadow:0 14px 34px -20px rgba(15,23,42,0.45);',
  }
}

const statusOption = computed<EChartsCoreOption>(() => {
  const palette = chartPalette.value
  const slices = statusDistribution.value.filter((item) => item.count > 0)
  return {
    tooltip: {
      trigger: 'item',
      formatter: '{b}<br/>{c} 项 · {d}%',
      ...tooltipStyle(),
    },
    series: [
      {
        type: 'pie',
        radius: ['60%', '84%'],
        center: ['50%', '50%'],
        avoidLabelOverlap: true,
        padAngle: 2,
        cursor: 'pointer',
        itemStyle: {
          borderRadius: 6,
          borderColor: palette.surface,
          borderWidth: 3,
        },
        label: { show: false },
        labelLine: { show: false },
        emphasis: {
          scale: true,
          scaleSize: 5,
          itemStyle: { shadowBlur: 16, shadowColor: 'rgba(15,23,42,0.18)' },
        },
        data: slices.map((item) => ({
          name: item.label,
          value: item.count,
          status: item.status,
          itemStyle: { color: statusColor(item.status) },
        })),
      },
    ],
  }
})

const trendOption = computed<EChartsCoreOption>(() => {
  const palette = chartPalette.value
  const points = purchaseTrend.value
  const yearly = points.length > 0 && points[0].month.length === 4
  return {
    grid: { left: 6, right: 16, top: 18, bottom: 2, containLabel: true },
    tooltip: {
      trigger: 'axis',
      axisPointer: {
        type: 'line',
        lineStyle: { color: palette.brand, type: 'dashed' },
      },
      formatter: '{b}<br/>新增资产 {c} 项',
      ...tooltipStyle(),
    },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: points.map((item) =>
        yearly ? `${item.month}年` : `${Number(item.month.slice(5))}月`,
      ),
      axisLine: { lineStyle: { color: palette.border } },
      axisTick: { show: false },
      axisLabel: {
        color: palette.text3,
        fontSize: 10.5,
        interval: yearly ? (points.length > 12 ? 'auto' : 0) : 1,
      },
    },
    yAxis: {
      type: 'value',
      minInterval: 1,
      splitNumber: 4,
      axisLabel: { color: palette.text3, fontSize: 10.5 },
      splitLine: { lineStyle: { color: palette.border, type: 'dashed' } },
    },
    series: [
      {
        name: '新增资产',
        type: 'line',
        smooth: 0.35,
        showSymbol: false,
        symbol: 'circle',
        symbolSize: 6,
        data: points.map((item) => item.count),
        lineStyle: { width: 2.5, color: palette.brand },
        itemStyle: { color: palette.brand, borderColor: palette.surface, borderWidth: 2 },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: withAlpha(palette.brand, palette.dark ? 0.34 : 0.2) },
            { offset: 1, color: withAlpha(palette.brand, 0) },
          ]),
        },
        emphasis: { focus: 'series' },
      },
    ],
  }
})

const categoryOption = computed<EChartsCoreOption>(() => {
  const palette = chartPalette.value
  const list = [...categoryDistribution.value].reverse()
  return {
    grid: { left: 4, right: 34, top: 8, bottom: 2, containLabel: true },
    tooltip: {
      trigger: 'axis',
      axisPointer: {
        type: 'shadow',
        shadowStyle: {
          color: palette.dark ? 'rgba(148,178,224,0.06)' : 'rgba(15,23,42,0.04)',
        },
      },
      formatter: '{b}<br/>{c} 项资产',
      ...tooltipStyle(),
    },
    xAxis: {
      type: 'value',
      minInterval: 1,
      splitLine: { lineStyle: { color: palette.border, type: 'dashed' } },
      axisLabel: { color: palette.text3, fontSize: 10.5 },
    },
    yAxis: {
      type: 'category',
      data: list.map((item) => item.name),
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: {
        color: palette.text2,
        fontSize: 11.5,
        width: 92,
        overflow: 'truncate',
      },
    },
    series: [
      {
        type: 'bar',
        barWidth: 12,
        cursor: 'pointer',
        showBackground: true,
        backgroundStyle: {
          color: palette.dark ? 'rgba(148,178,224,0.05)' : 'rgba(15,23,42,0.03)',
          borderRadius: 6,
        },
        itemStyle: {
          borderRadius: [0, 6, 6, 0],
          color: new echarts.graphic.LinearGradient(0, 0, 1, 0, [
            { offset: 0, color: withAlpha(palette.brand, 0.75) },
            { offset: 1, color: palette.cyan },
          ]),
        },
        label: {
          show: true,
          position: 'right',
          color: palette.text2,
          fontSize: 11,
          formatter: '{c}',
        },
        data: list.map((item) => ({
          value: item.count,
          category_id: item.category_id,
        })),
      },
    ],
  }
})

function statusColor(status: string): string {
  return STATUS_COLORS[status] ?? '#94a3b8'
}

function statusTagType(status: string) {
  return ASSET_STATUS_TAG_TYPES[status as AssetStatus] ?? 'info'
}

function formatAmount(value: number | null | undefined, decimals = 0): string {
  return Number(value ?? 0).toLocaleString('zh-CN', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })
}

function deptWidth(count: number): string {
  return `${Math.max(6, Math.round((count / maxDeptCount.value) * 100))}%`
}

function warrantyTagType(daysLeft: number): 'danger' | 'warning' | 'success' {
  if (daysLeft <= 7) return 'danger'
  if (daysLeft <= 30) return 'warning'
  return 'success'
}

function formatDate(value?: string | null): string {
  return value ? dayjs(value).format('YYYY-MM-DD') : '—'
}

async function fetchSummary(): Promise<void> {
  const seq = ++summarySeq
  loading.value = true
  try {
    const data = await dashboardApi.summary({
      scope: scope.value,
      dept_id: filters.dept_id,
      months: filters.months,
    })
    if (seq !== summarySeq) return
    summary.value = data
    failed.value = false
    lastUpdated.value = dayjs().format('HH:mm:ss')
  } catch {
    if (seq === summarySeq) failed.value = true
  } finally {
    if (seq === summarySeq) loading.value = false
  }
}

watch(scope, (value) => {
  if (value === 'personal' && filters.dept_id !== undefined) {
    filters.dept_id = undefined
  }
})

watch([scope, filters], () => {
  void fetchSummary()
})

function openLedger(): void {
  void router.push(isPersonal.value ? '/assets/mine' : '/assets/ledger')
}

function drillStatus(status: string): void {
  if (isPersonal.value) {
    if (canViewMine.value) void router.push('/assets/mine')
    return
  }
  if (!canViewLedger.value) return
  void router.push({ path: '/assets/ledger', query: { status } })
}

function drillStatusItem(item: StatusSlice): void {
  if (item.count > 0) drillStatus(item.status)
}

function drillCategory(categoryId: number | null | undefined): void {
  if (isPersonal.value) {
    if (canViewMine.value) void router.push('/assets/mine')
    return
  }
  if (!canViewLedger.value || !categoryId) return
  void router.push({
    path: '/assets/ledger',
    query: { category_id: String(categoryId) },
  })
}

function drillDept(deptId: number | null | undefined): void {
  if (isPersonal.value) {
    if (canViewMine.value) void router.push('/assets/mine')
    return
  }
  if (!canViewLedger.value || !deptId) return
  void router.push({ path: '/assets/ledger', query: { dept_id: String(deptId) } })
}

interface ChartClickData {
  status?: string
  category_id?: number | null
}

function handleStatusChartClick(params: unknown): void {
  const data = (params as { data?: ChartClickData }).data
  if (data?.status) drillStatus(data.status)
}

function handleCategoryChartClick(params: unknown): void {
  const data = (params as { data?: ChartClickData }).data
  if (data?.category_id !== undefined) drillCategory(data.category_id)
}

function openAudit(): void {
  void router.push('/system/audit')
}

function openCategories(): void {
  void router.push('/assets/categories')
}

onMounted(() => {
  todoStore.start()
  void brandingStore.loadAnnouncements()
  void fetchSummary()
})
</script>

<template>
  <div class="page dashboard-page">
    <header class="page-header dashboard-header">
      <div>
        <p class="page-eyebrow">ASSET OVERVIEW</p>
        <h1 class="page-title">{{ greeting() }}，{{ displayName }}</h1>
        <p class="page-subtitle">
          {{ todayLabel() }} · 数据范围：{{
            summary?.data_scope_label || auth.dataScopeLabel || '未配置'
          }}
          · 统计口径为未删除资产
        </p>
      </div>
      <div class="header-actions">
        <div class="dashboard-filters">
          <el-radio-group v-model="scope" class="filter-scope">
            <el-radio-button value="personal">我的资产</el-radio-button>
            <el-radio-button value="org">组织视角</el-radio-button>
          </el-radio-group>
          <el-select
            v-if="!isPersonal"
            v-model="filters.dept_id"
            class="filter-dept"
            placeholder="全部部门"
            clearable
          >
            <el-option
              v-for="option in deptOptions"
              :key="option.value"
              :label="option.label"
              :value="option.value"
            />
          </el-select>
          <el-select v-model="filters.months" class="filter-months">
            <el-option
              v-for="option in MONTH_OPTIONS"
              :key="option.value"
              :label="option.label"
              :value="option.value"
            />
          </el-select>
        </div>
        <span v-if="lastUpdated" class="refresh-hint">更新于 {{ lastUpdated }}</span>
        <el-button :icon="Refresh" :loading="loading" @click="fetchSummary">刷新数据</el-button>
      </div>
    </header>

    <section v-if="welcomeText || announcements.length" class="welcome-strip">
      <p v-if="welcomeText" class="welcome-text">{{ welcomeText }}</p>
      <div v-if="announcements.length" class="announcement-list">
        <article v-for="item in announcements" :key="item.id" class="announcement-item">
          <el-tag
            :type="announcementTagType(item.level)"
            effect="light"
            size="small"
            class="announcement-tag"
          >
            {{ item.level_label }}
          </el-tag>
          <div class="announcement-body">
            <strong>{{ item.title }}</strong>
            <p>{{ item.content }}</p>
          </div>
          <span class="announcement-meta">
            {{ item.end_at ? `至 ${formatDateTime(item.end_at)}` : '长期有效' }}
          </span>
        </article>
      </div>
    </section>

    <section v-if="failed && !summary" class="surface-card error-panel">
      <el-empty description="驾驶舱数据加载失败，请检查服务状态后重试">
        <el-button type="primary" :icon="Refresh" :loading="loading" @click="fetchSummary">
          重新加载
        </el-button>
      </el-empty>
    </section>

    <template v-else>
      <section class="overview-hero" :class="{ 'is-loading': loading && !summary }">
        <span class="hero-glow hero-glow-a" aria-hidden="true" />
        <span class="hero-glow hero-glow-b" aria-hidden="true" />
        <span class="hero-grid" aria-hidden="true" />

        <div class="hero-copy">
          <p class="hero-eyebrow">ASSET COMMAND CENTER</p>
          <div class="hero-value-row">
            <span class="hero-currency">¥</span>
            <span class="hero-value">{{ formatAmount(metrics.total_value) }}</span>
          </div>
          <p class="hero-caption">
            {{ isPersonal ? '我的资产总值' : '当前数据范围内资产总值' }}
          </p>

          <div class="hero-pills">
            <span class="hero-pill"><strong>{{ metrics.total_assets }}</strong> 项资产</span>
            <span class="hero-pill"><strong>{{ metrics.in_use }}</strong> 项在用</span>
            <span v-if="metrics.warranty_30d" class="hero-pill pill-warning">
              <strong>{{ metrics.warranty_30d }}</strong> 项 30 天内到保
            </span>
          </div>

          <div class="hero-actions">
            <el-button
              v-if="canDrill"
              type="primary"
              :icon="Monitor"
              @click="openLedger"
            >
              {{ isPersonal ? '进入我的资产' : '进入资产台账' }}
            </el-button>
            <el-button v-if="canViewAudit" class="ghost-btn" :icon="Document" @click="openAudit">
              审计日志
            </el-button>
            <el-button
              v-if="canViewCategories"
              class="ghost-btn"
              :icon="Files"
              @click="openCategories"
            >
              分类维护
            </el-button>
          </div>
        </div>

        <div class="hero-gauge">
          <el-progress
            type="circle"
            :percentage="inUseRate"
            :width="132"
            :stroke-width="10"
            :color="chartPalette.cyan"
          >
            <template #default="{ percentage }">
              <span class="gauge-value">{{ percentage }}<small>%</small></span>
              <span class="gauge-label">资产利用率</span>
            </template>
          </el-progress>
          <p class="gauge-foot">在用 {{ metrics.in_use }} / 全部 {{ metrics.total_assets }}</p>
          <div class="gauge-mini">
            <span>
              <em>+{{ currentMonthNew }}</em>
              {{ filters.months === 0 ? '本年新增' : '本月新增' }}
            </span>
            <span><em>{{ metrics.pending_stock }}</em> 待入库</span>
          </div>
        </div>
      </section>

      <section class="metric-grid">
        <article class="metric-card surface-card hover-lift">
          <span class="metric-icon tone-blue"><el-icon><Box /></el-icon></span>
          <div class="metric-body">
            <p class="metric-label">资产总数</p>
            <p class="metric-value">{{ formatAmount(metrics.total_assets) }}</p>
            <p class="metric-foot">在用 {{ metrics.in_use }} · 在库 {{ metrics.in_stock }}</p>
          </div>
        </article>

        <article class="metric-card surface-card hover-lift">
          <span class="metric-icon tone-cyan"><el-icon><Monitor /></el-icon></span>
          <div class="metric-body">
            <p class="metric-label">在用资产</p>
            <p class="metric-value">{{ formatAmount(metrics.in_use) }}</p>
            <p class="metric-foot">占全部 {{ inUseRate }}% · 闲置 {{ metrics.idle }} 项</p>
          </div>
        </article>

        <article class="metric-card surface-card hover-lift">
          <span class="metric-icon tone-violet"><el-icon><Money /></el-icon></span>
          <div class="metric-body">
            <p class="metric-label">资产总值</p>
            <p class="metric-value metric-value-money">
              ¥ {{ formatAmount(metrics.total_value, 2) }}
            </p>
            <p class="metric-foot">均价 ¥ {{ formatAmount(avgPrice, 2) }}</p>
          </div>
        </article>

        <article class="metric-card surface-card hover-lift">
          <span class="metric-icon tone-amber"><el-icon><WarningFilled /></el-icon></span>
          <div class="metric-body">
            <p class="metric-label">30 天内保修到期</p>
            <p class="metric-value">{{ formatAmount(metrics.warranty_30d) }}</p>
            <p class="metric-foot">请优先安排续保或更换计划</p>
          </div>
        </article>

        <article class="metric-card surface-card hover-lift">
          <span class="metric-icon tone-emerald"><el-icon><Van /></el-icon></span>
          <div class="metric-body">
            <p class="metric-label">本月入库</p>
            <p class="metric-value">{{ formatAmount(metrics.month_inbound) }}</p>
            <p class="metric-foot">
              {{
                filters.months === 0
                  ? `全部历史合计 ${summary?.period.inbound ?? 0}`
                  : `近 ${filters.months} 个月合计 ${summary?.period.inbound ?? 0}`
              }}
            </p>
          </div>
        </article>

        <article class="metric-card surface-card hover-lift">
          <span class="metric-icon tone-sky"><el-icon><ShoppingCart /></el-icon></span>
          <div class="metric-body">
            <p class="metric-label">本月领用</p>
            <p class="metric-value">{{ formatAmount(metrics.month_requisition) }}</p>
            <p class="metric-foot">
              {{
                filters.months === 0
                  ? `全部历史 ${summary?.period.requisition ?? 0} 单`
                  : `近 ${filters.months} 个月 ${summary?.period.requisition ?? 0} 单`
              }}
            </p>
          </div>
        </article>

        <article class="metric-card surface-card hover-lift">
          <span class="metric-icon tone-rose"><el-icon><Tickets /></el-icon></span>
          <div class="metric-body">
            <p class="metric-label">30 天内合同到期</p>
            <p class="metric-value">{{ formatAmount(metrics.contract_expiring) }}</p>
            <p class="metric-foot">请及时续签或终止</p>
          </div>
        </article>

        <article class="metric-card surface-card hover-lift">
          <span class="metric-icon tone-slate"><el-icon><Odometer /></el-icon></span>
          <div class="metric-body">
            <p class="metric-label">闲置率</p>
            <p class="metric-value">{{ metrics.idle_rate }}<small>%</small></p>
            <p class="metric-foot">闲置 {{ metrics.idle }} 项 · 在库 {{ metrics.in_stock }} 项</p>
          </div>
        </article>
      </section>

      <section class="panel surface-card todo-panel">
        <header class="panel-header">
          <div>
            <p class="panel-eyebrow">MY TODO</p>
            <h2 class="panel-title">我的待办</h2>
          </div>
          <div class="todo-head-actions">
            <span class="todo-total"><strong>{{ todoStore.total }}</strong> 项未完成</span>
            <el-button link type="primary" @click="openTodoCenter">
              进入待办中心
              <el-icon><ArrowRight /></el-icon>
            </el-button>
          </div>
        </header>

        <div v-if="todoStore.total" class="todo-groups">
          <article v-for="group in todoGroups" :key="group.category" class="todo-group">
            <header class="todo-group-head">
              <span class="todo-dot" :class="`tone-${todoTone(group.category)}`" />
              <strong>{{ group.label }}</strong>
              <span class="todo-group-count">{{ group.count }}</span>
              <button
                class="todo-group-more"
                type="button"
                @click="openTodoCategory(group.category)"
              >
                全部
                <el-icon><ArrowRight /></el-icon>
              </button>
            </header>
            <ul class="todo-items">
              <li v-for="item in visibleTodoItems(group)" :key="item.key">
                <button type="button" class="todo-item" @click="openTodoItem(item)">
                  <span class="todo-item-head">
                    <span class="todo-type" :class="`tone-${todoTone(item.category)}`">
                      {{ item.todo_type_label }}
                    </span>
                    <span class="todo-time">{{ formatDateTime(item.occurred_at) }}</span>
                  </span>
                  <span class="todo-item-title">{{ item.title }}</span>
                  <span class="todo-item-foot">
                    <span class="todo-related">
                      {{
                        item.related_name
                          ? `相关人：${item.related_name}`
                          : item.subtitle || item.doc_no
                      }}
                    </span>
                    <el-tag
                      :type="todoStatusTag(item.status)"
                      size="small"
                      effect="light"
                      round
                    >
                      {{ item.status_label }}
                    </el-tag>
                  </span>
                </button>
              </li>
            </ul>
            <p v-if="todoRest(group)" class="todo-group-rest">另有 {{ todoRest(group) }} 项</p>
          </article>
        </div>

        <div v-else class="todo-empty">
          <span class="todo-empty-icon"><el-icon><Finished /></el-icon></span>
          <div class="todo-empty-copy">
            <strong>暂无未完成事项</strong>
            <span>审批、确认、处理与借用到期提醒会集中展示在这里</span>
          </div>
          <el-button link type="primary" @click="openTodoCenter">打开待办中心</el-button>
        </div>
      </section>

      <section class="chart-grid">
        <article class="panel surface-card">
          <header class="panel-header">
            <div>
              <p class="panel-eyebrow">STATUS</p>
              <h2 class="panel-title">资产状态分布</h2>
            </div>
            <span class="panel-meta">{{ metrics.total_assets }} 项资产</span>
          </header>

          <div v-if="metrics.total_assets" class="status-body">
            <div class="donut-wrap">
              <EChart :option="statusOption" height="208px" @click="handleStatusChartClick" />
              <div class="donut-center">
                <strong>{{ metrics.total_assets }}</strong>
                <span>资产总量</span>
              </div>
            </div>
            <ul class="status-legend">
              <li
                v-for="item in statusDistribution"
                :key="item.status"
                :class="{ clickable: canDrill && item.count > 0 }"
                :title="item.count > 0 ? drillTitle(item.label) : undefined"
                @click="drillStatusItem(item)"
              >
                <span class="legend-dot" :style="{ background: statusColor(item.status) }" />
                <span class="legend-label">{{ item.label }}</span>
                <strong>{{ item.count }}</strong>
              </li>
            </ul>
          </div>
          <div v-else class="chart-empty">
            <el-empty :image-size="64" description="暂无资产数据" />
          </div>
        </article>

        <article class="panel surface-card">
          <header class="panel-header">
            <div>
              <p class="panel-eyebrow">PURCHASE TREND</p>
              <h2 class="panel-title">
                {{ filters.months === 0 ? '历年购置趋势' : `近 ${filters.months} 个月购置趋势` }}
              </h2>
            </div>
            <span class="panel-meta">
              {{ filters.months === 0 ? '累计新增' : '区间新增' }} {{ periodNew }} 项
            </span>
          </header>
          <EChart :option="trendOption" height="262px" />
        </article>
      </section>

      <section class="chart-grid">
        <article class="panel surface-card">
          <header class="panel-header">
            <div>
              <p class="panel-eyebrow">CATEGORY</p>
              <h2 class="panel-title">资产分类分布</h2>
            </div>
            <span class="panel-meta">按一级分类聚合</span>
          </header>

          <EChart
            v-if="categoryDistribution.length"
            :option="categoryOption"
            height="262px"
            @click="handleCategoryChartClick"
          />
          <div v-else class="chart-empty">
            <el-empty :image-size="64" description="暂无分类数据" />
          </div>
        </article>

        <article class="panel surface-card">
          <header class="panel-header">
            <div>
              <p class="panel-eyebrow">DEPARTMENT</p>
              <h2 class="panel-title">
                {{ isPersonal ? '我的资产部门分布' : '部门资产持有' }}
              </h2>
            </div>
            <span class="panel-meta">Top 8</span>
          </header>

          <ul v-if="deptDistribution.length" class="dept-list">
            <li
              v-for="(dept, index) in deptDistribution"
              :key="dept.dept_id ?? dept.name"
              class="dept-item"
              :class="{ clickable: canDrill && dept.dept_id }"
              :title="dept.dept_id ? drillTitle(dept.name) : undefined"
              @click="drillDept(dept.dept_id)"
            >
              <span class="dept-rank" :class="{ top: index < 3 }">
                {{ String(index + 1).padStart(2, '0') }}
              </span>
              <div class="dept-main">
                <div class="dept-row">
                  <span class="dept-name">{{ dept.name }}</span>
                  <strong>{{ dept.count }}<small> 项</small></strong>
                </div>
                <div class="dept-track">
                  <span class="dept-bar" :style="{ width: deptWidth(dept.count) }" />
                </div>
              </div>
            </li>
          </ul>
          <div v-else class="chart-empty">
            <el-empty :image-size="64" description="暂无部门持有数据" />
          </div>
        </article>
      </section>

      <section class="bottom-grid">
        <article class="panel surface-card">
          <header class="panel-header">
            <div>
              <p class="panel-eyebrow">WARRANTY ALERT</p>
              <h2 class="panel-title">保修临期提醒</h2>
            </div>
            <el-button v-if="canDrill" link type="primary" @click="openLedger">
              {{ isPersonal ? '我的资产' : '资产台账' }}
              <el-icon><ArrowRight /></el-icon>
            </el-button>
          </header>

          <el-table
            v-if="warrantyExpiring.length"
            :data="warrantyExpiring"
            size="small"
            class="mini-table"
          >
            <el-table-column label="资产" min-width="170">
              <template #default="{ row }">
                <div class="cell-stack">
                  <strong>{{ row.name }}</strong>
                  <span>{{ row.asset_no }}</span>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="分类 / 部门" min-width="140">
              <template #default="{ row }">
                <div class="cell-stack">
                  <span>{{ row.category_name || '—' }}</span>
                  <span>{{ row.dept_name || '未分配部门' }}</span>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="责任人" width="100">
              <template #default="{ row }">
                <span class="cell-text">{{ row.custodian_name || '—' }}</span>
              </template>
            </el-table-column>
            <el-table-column label="保修到期" width="160" align="right">
              <template #default="{ row }">
                <div class="warranty-cell">
                  <span class="cell-text">{{ formatDate(row.warranty_end) }}</span>
                  <el-tag
                    :type="warrantyTagType(row.days_left)"
                    size="small"
                    effect="light"
                    round
                  >
                    {{ row.days_left }} 天
                  </el-tag>
                </div>
              </template>
            </el-table-column>
          </el-table>
          <div v-else class="chart-empty">
            <el-empty :image-size="64" description="未来 60 天内暂无到保资产" />
          </div>
        </article>

        <article class="panel surface-card">
          <header class="panel-header">
            <div>
              <p class="panel-eyebrow">RECENT</p>
              <h2 class="panel-title">{{ isPersonal ? '我的最近资产' : '最近入库' }}</h2>
            </div>
            <el-button v-if="canDrill" link type="primary" @click="openLedger">
              查看全部
              <el-icon><ArrowRight /></el-icon>
            </el-button>
          </header>

          <ul v-if="recentAssets.length" class="recent-list">
            <li v-for="asset in recentAssets" :key="asset.id" class="recent-item">
              <span class="recent-mark"><el-icon><Box /></el-icon></span>
              <div class="recent-main">
                <div class="recent-title">
                  <strong>{{ asset.name }}</strong>
                  <el-tag
                    :type="statusTagType(asset.status)"
                    size="small"
                    effect="light"
                    round
                  >
                    {{ asset.status_label }}
                  </el-tag>
                </div>
                <p>
                  {{ asset.asset_no }} · {{ asset.category_name || '未分类' }} ·
                  {{ asset.dept_name || '未分配部门' }}
                </p>
              </div>
              <span class="recent-time">{{ formatDateTime(asset.created_at) }}</span>
            </li>
          </ul>
          <div v-else class="chart-empty">
            <el-empty :image-size="64" description="暂无资产记录" />
          </div>
        </article>
      </section>
    </template>
  </div>
</template>

<style scoped>
.dashboard-page {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.dashboard-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 18px;
  flex-wrap: wrap;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.dashboard-filters {
  display: flex;
  align-items: center;
  gap: 8px;
}

.filter-dept {
  width: 170px;
}

.filter-months {
  width: 122px;
}

.refresh-hint {
  color: var(--text-3);
  font-size: 11.5px;
}

.error-panel {
  padding: 42px 24px;
}

.welcome-strip {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 18px 22px;
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  background:
    var(--gradient-brand-soft),
    var(--surface);
}

.welcome-text {
  color: var(--text-1);
  font-size: 14.5px;
  line-height: 1.7;
}

.announcement-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.announcement-item {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding-top: 10px;
  border-top: 1px dashed var(--border);
}

.announcement-item:first-child {
  padding-top: 0;
  border-top: none;
}

.announcement-tag {
  flex-shrink: 0;
  margin-top: 2px;
}

.announcement-body {
  flex: 1;
  min-width: 0;
}

.announcement-body strong {
  display: block;
  color: var(--text-1);
  font-size: 13.5px;
  font-weight: 600;
}

.announcement-body p {
  margin-top: 3px;
  color: var(--text-2);
  font-size: 12.5px;
  line-height: 1.65;
  white-space: pre-line;
}

.announcement-meta {
  flex-shrink: 0;
  color: var(--text-3);
  font-size: 11.5px;
  white-space: nowrap;
}

/* Hero */
.overview-hero {
  position: relative;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 236px;
  align-items: center;
  gap: 28px;
  overflow: hidden;
  padding: 30px 36px;
  border: 1px solid var(--hero-border);
  border-radius: var(--radius-lg);
  background:
    radial-gradient(720px 320px at 88% -10%, var(--hero-glow-a), transparent 62%),
    radial-gradient(620px 320px at 0% 120%, var(--hero-glow-b), transparent 60%),
    var(--hero-base);
  box-shadow: var(--hero-shadow);
}

.overview-hero.is-loading {
  opacity: 0.86;
}

.hero-glow {
  position: absolute;
  border-radius: 50%;
  filter: blur(70px);
  pointer-events: none;
}

.hero-glow-a {
  width: 300px;
  height: 300px;
  top: -150px;
  right: 16%;
  background: var(--hero-glow-a);
}

.hero-glow-b {
  width: 260px;
  height: 260px;
  bottom: -160px;
  left: 24%;
  background: var(--hero-glow-b);
}

.hero-grid {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(var(--hero-grid-line) 1px, transparent 1px),
    linear-gradient(90deg, var(--hero-grid-line) 1px, transparent 1px);
  background-size: 46px 46px;
  mask-image: radial-gradient(ellipse 80% 120% at 70% 20%, #000 10%, transparent 72%);
  pointer-events: none;
}

.hero-copy {
  position: relative;
  z-index: 2;
  min-width: 0;
}

.hero-eyebrow {
  color: var(--hero-accent-ink);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.22em;
}

.hero-value-row {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-top: 12px;
  line-height: 1;
}

.hero-currency {
  color: var(--hero-accent-ink);
  font-family: var(--font-number);
  font-size: 24px;
  font-weight: 600;
}

.hero-value {
  color: var(--hero-text);
  font-family: var(--font-number);
  font-size: clamp(32px, 4.4vw, 48px);
  font-weight: 700;
  letter-spacing: -0.035em;
  text-shadow: var(--hero-value-shadow);
}

.hero-caption {
  margin-top: 8px;
  color: var(--hero-muted);
  font-size: 12.5px;
}

.hero-pills {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 18px;
}

.hero-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 6px 12px;
  border: 1px solid var(--hero-pill-border);
  border-radius: 999px;
  background: var(--hero-pill-bg);
  color: var(--hero-pill-text);
  font-size: 11.5px;
  white-space: nowrap;
}

.hero-pill strong {
  color: var(--hero-pill-strong);
  font-family: var(--font-number);
  font-size: 13px;
  font-weight: 700;
}

.hero-pill.pill-warning {
  border-color: var(--hero-warn-border);
  background: var(--hero-warn-bg);
  color: var(--hero-warn-text);
}

.hero-pill.pill-warning strong {
  color: var(--hero-warn-strong);
}

.hero-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 22px;
}

.hero-actions :deep(.el-button) {
  border-radius: 11px;
  font-weight: 500;
}

.hero-actions :deep(.el-button--primary) {
  box-shadow: 0 14px 30px -16px var(--brand-glow);
}

.hero-actions :deep(.ghost-btn) {
  border-color: var(--hero-ghost-border);
  background: var(--hero-ghost-bg);
  color: var(--hero-ghost-text);
}

.hero-actions :deep(.ghost-btn:hover) {
  border-color: var(--hero-ghost-hover-border);
  background: var(--hero-ghost-hover-bg);
  color: var(--hero-ghost-hover-text);
}

.hero-gauge {
  position: relative;
  z-index: 2;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-self: center;
  text-align: center;
}

.hero-gauge :deep(.el-progress-circle__track) {
  stroke: var(--hero-track);
}

.hero-gauge :deep(.el-progress__text) {
  display: flex;
  flex-direction: column;
  gap: 3px;
  color: var(--hero-strong);
}

.gauge-value {
  color: var(--hero-strong);
  font-family: var(--font-number);
  font-size: 26px;
  font-weight: 700;
  line-height: 1;
  letter-spacing: -0.02em;
}

.gauge-value small {
  margin-left: 1px;
  color: var(--hero-accent-ink);
  font-size: 12px;
  font-weight: 600;
}

.gauge-label {
  color: var(--hero-faint);
  font-size: 10.5px;
  letter-spacing: 0.08em;
}

.gauge-foot {
  margin-top: 10px;
  color: var(--hero-muted);
  font-size: 11.5px;
}

.gauge-mini {
  display: flex;
  gap: 16px;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px dashed var(--hero-divider);
  color: var(--hero-faint);
  font-size: 10.5px;
}

.gauge-mini em {
  color: var(--hero-strong);
  font-family: var(--font-number);
  font-size: 12px;
  font-style: normal;
  font-weight: 700;
}

/* Metrics */
.metric-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
}

.metric-card {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  padding: 20px 20px 18px;
}

.metric-icon {
  display: grid;
  place-items: center;
  width: 42px;
  height: 42px;
  flex-shrink: 0;
  border-radius: 13px;
}

.metric-icon .el-icon {
  font-size: 19px;
}

.tone-blue {
  background: var(--brand-soft);
  color: var(--brand);
}

.tone-cyan {
  background: color-mix(in srgb, var(--brand-cyan) 14%, transparent);
  color: var(--brand-cyan);
}

.tone-violet {
  background: rgba(99, 102, 241, 0.12);
  color: #6366f1;
}

.tone-amber {
  background: rgba(245, 158, 11, 0.13);
  color: #d97706;
}

.tone-emerald {
  background: rgba(16, 185, 129, 0.12);
  color: #059669;
}

.tone-sky {
  background: rgba(14, 165, 233, 0.12);
  color: #0284c7;
}

.tone-rose {
  background: rgba(225, 29, 72, 0.1);
  color: #e11d48;
}

.tone-slate {
  background: rgba(100, 116, 139, 0.12);
  color: #475569;
}

html.dark .metric-icon.tone-violet {
  background: rgba(129, 140, 248, 0.16);
  color: #a5b4fc;
}

html.dark .metric-icon.tone-amber {
  background: rgba(245, 158, 11, 0.16);
  color: #fbbf24;
}

html.dark .metric-icon.tone-emerald {
  background: rgba(16, 185, 129, 0.16);
  color: #34d399;
}

html.dark .metric-icon.tone-sky {
  background: rgba(56, 189, 248, 0.16);
  color: #38bdf8;
}

html.dark .metric-icon.tone-rose {
  background: rgba(244, 63, 94, 0.16);
  color: #fb7185;
}

html.dark .metric-icon.tone-slate {
  background: rgba(148, 163, 184, 0.16);
  color: #cbd5e1;
}

.metric-body {
  min-width: 0;
  flex: 1;
}

.metric-label {
  color: var(--text-2);
  font-size: 12px;
}

.metric-value {
  margin: 3px 0;
  color: var(--text-1);
  font-family: var(--font-number);
  font-size: 29px;
  font-weight: 700;
  line-height: 1.15;
  letter-spacing: -0.03em;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.metric-value-money {
  font-size: 24px;
}

.metric-value small {
  margin-left: 2px;
  color: var(--text-3);
  font-size: 14px;
  font-weight: 600;
}

.metric-foot {
  color: var(--text-3);
  font-size: 11px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* Panels */
.chart-grid,
.bottom-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 16px;
}

.bottom-grid {
  grid-template-columns: minmax(0, 1.3fr) minmax(0, 0.9fr);
}

.panel {
  min-width: 0;
  padding: 22px 24px 20px;
}

.panel-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
  margin-bottom: 16px;
}

.panel-eyebrow {
  color: var(--text-3);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.18em;
}

.panel-title {
  margin-top: 4px;
  color: var(--text-1);
  font-size: 16.5px;
  font-weight: 650;
  letter-spacing: -0.015em;
}

.panel-meta {
  padding: 5px 11px;
  border-radius: 999px;
  background: var(--brand-soft);
  color: var(--brand);
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}

.panel-header :deep(.el-button.is-link) {
  font-size: 12px;
  font-weight: 500;
}

.panel-header :deep(.el-button.is-link .el-icon) {
  margin-left: 2px;
}

.chart-empty {
  display: grid;
  place-items: center;
  min-height: 200px;
}

.chart-empty :deep(.el-empty) {
  padding: 12px 0;
}

.chart-empty :deep(.el-empty__description p) {
  color: var(--text-3);
  font-size: 12px;
}

/* Status panel */
.status-body {
  display: grid;
  grid-template-columns: minmax(168px, 0.9fr) minmax(0, 1fr);
  align-items: center;
  gap: 18px;
}

.donut-wrap {
  position: relative;
}

.donut-center {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  pointer-events: none;
  transform: translateY(-4px);
}

.donut-center strong {
  color: var(--text-1);
  font-family: var(--font-number);
  font-size: 27px;
  font-weight: 700;
  letter-spacing: -0.03em;
  line-height: 1;
}

.donut-center span {
  color: var(--text-3);
  font-size: 10.5px;
}

.status-legend {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.status-legend li {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 5px 4px;
  border-radius: 8px;
  transition: background-color 0.2s ease;
}

.status-legend li:hover {
  background: var(--surface-muted);
}

.status-legend li.clickable {
  cursor: pointer;
}

.legend-dot {
  width: 8px;
  height: 8px;
  flex-shrink: 0;
  border-radius: 3px;
}

.legend-label {
  flex: 1;
  color: var(--text-2);
  font-size: 12px;
}

.status-legend strong {
  color: var(--text-1);
  font-family: var(--font-number);
  font-size: 13px;
  font-weight: 700;
}

/* Department */
.dept-list {
  display: flex;
  flex-direction: column;
  gap: 3px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.dept-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 7px 4px;
  border-radius: 10px;
  transition: background-color 0.18s ease;
}

.dept-item.clickable {
  cursor: pointer;
}

.dept-item.clickable:hover {
  background: var(--surface-muted);
}

.dept-rank {
  display: grid;
  place-items: center;
  width: 26px;
  height: 24px;
  flex-shrink: 0;
  border-radius: 7px;
  background: var(--surface-muted);
  color: var(--text-3);
  font-family: var(--font-number);
  font-size: 10.5px;
  font-weight: 700;
  letter-spacing: 0.02em;
}

.dept-rank.top {
  background: var(--brand-soft);
  color: var(--brand);
}

.dept-main {
  min-width: 0;
  flex: 1;
}

.dept-row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 6px;
}

.dept-name {
  color: var(--text-1);
  font-size: 12.5px;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.dept-row strong {
  color: var(--text-1);
  font-family: var(--font-number);
  font-size: 13px;
  font-weight: 700;
}

.dept-row small {
  color: var(--text-3);
  font-family: var(--font-sans);
  font-size: 10px;
  font-weight: 400;
}

.dept-track {
  height: 5px;
  overflow: hidden;
  border-radius: 999px;
  background: var(--surface-muted);
}

.dept-bar {
  display: block;
  height: 100%;
  border-radius: 999px;
  background: var(--gradient-brand);
  transition: width 0.5s cubic-bezier(0.22, 1, 0.36, 1);
}

/* Tables & lists */
.mini-table {
  width: 100%;
  --el-table-border-color: var(--border);
  --el-table-header-bg-color: var(--surface-muted);
  background: transparent;
}

.mini-table :deep(.el-table__cell) {
  padding: 8px 0;
}

.mini-table :deep(.el-table__inner-wrapper::before) {
  display: none;
}

.mini-table :deep(th.el-table__cell) {
  color: var(--text-3);
  font-size: 11px;
  font-weight: 600;
}

.cell-stack {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.cell-stack strong {
  color: var(--text-1);
  font-size: 12.5px;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.cell-stack span {
  color: var(--text-3);
  font-size: 10.5px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.cell-text {
  color: var(--text-2);
  font-size: 12px;
}

.warranty-cell {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
}

.recent-list {
  display: flex;
  flex-direction: column;
  margin: 0;
  padding: 0;
  list-style: none;
}

.recent-item {
  display: flex;
  align-items: center;
  gap: 11px;
  padding: 9px 4px;
  border-bottom: 1px dashed var(--border);
}

.recent-item:last-child {
  border-bottom: none;
  padding-bottom: 0;
}

.recent-mark {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  flex-shrink: 0;
  border-radius: 9px;
  background: var(--brand-soft);
  color: var(--brand);
}

.recent-mark .el-icon {
  font-size: 15px;
}

.recent-main {
  min-width: 0;
  flex: 1;
}

.recent-title {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.recent-title strong {
  color: var(--text-1);
  font-size: 12.5px;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.recent-main p {
  margin-top: 2px;
  color: var(--text-3);
  font-size: 10.5px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.recent-time {
  flex-shrink: 0;
  color: var(--text-3);
  font-size: 10.5px;
}

.todo-panel {
  padding: 22px 24px;
}

.todo-head-actions {
  display: flex;
  align-items: center;
  gap: 14px;
}

.todo-total {
  color: var(--text-3);
  font-size: 12px;
}

.todo-total strong {
  margin-right: 2px;
  color: var(--brand);
  font-size: 16px;
  font-weight: 700;
}

.todo-groups {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(248px, 1fr));
  gap: 14px;
  margin-top: 14px;
}

.todo-group {
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: 13px;
  background: var(--surface-muted);
}

.todo-group-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}

.todo-group-head strong {
  color: var(--text-1);
  font-size: 12.8px;
  font-weight: 650;
}

.todo-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.todo-dot.tone-blue {
  background: var(--brand);
}

.todo-dot.tone-cyan {
  background: var(--brand-cyan);
}

.todo-dot.tone-violet {
  background: #7c3aed;
}

.todo-dot.tone-amber {
  background: #d97706;
}

.todo-dot.tone-rose {
  background: #e11d48;
}

.todo-group-count {
  padding: 0 6px;
  border-radius: 999px;
  background: var(--surface);
  color: var(--text-2);
  font-size: 10.5px;
  font-weight: 700;
  line-height: 16px;
}

.todo-group-more {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  margin-left: auto;
  padding: 0;
  border: none;
  background: transparent;
  color: var(--brand);
  font: inherit;
  font-size: 10.8px;
  cursor: pointer;
}

.todo-items {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.todo-item {
  display: flex;
  flex-direction: column;
  gap: 5px;
  width: 100%;
  padding: 10px 11px;
  border: 1px solid var(--border);
  border-radius: 11px;
  background: var(--surface);
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.18s ease, box-shadow 0.18s ease, transform 0.18s ease;
}

.todo-item:hover {
  transform: translateY(-1px);
  border-color: var(--brand);
  box-shadow: var(--shadow-sm);
}

.todo-item-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.todo-type {
  padding: 1px 7px;
  border-radius: 999px;
  font-size: 10.5px;
  font-weight: 600;
}

.todo-type.tone-blue {
  background: var(--brand-soft);
  color: var(--brand);
}

.todo-type.tone-cyan {
  background: color-mix(in srgb, var(--brand-cyan) 14%, transparent);
  color: var(--brand-cyan);
}

.todo-type.tone-violet {
  background: rgba(124, 58, 237, 0.1);
  color: #7c3aed;
}

.todo-type.tone-amber {
  background: rgba(245, 158, 11, 0.13);
  color: #b45309;
}

.todo-type.tone-rose {
  background: rgba(225, 29, 72, 0.09);
  color: #e11d48;
}

html.dark .todo-type.tone-violet {
  background: rgba(124, 58, 237, 0.2);
  color: #c4b5fd;
}

html.dark .todo-type.tone-amber {
  background: rgba(245, 158, 11, 0.18);
  color: #fbbf24;
}

html.dark .todo-type.tone-rose {
  background: rgba(225, 29, 72, 0.18);
  color: #fb7185;
}

html.dark .todo-dot.tone-violet {
  background: #a78bfa;
}

html.dark .todo-dot.tone-amber {
  background: #fbbf24;
}

html.dark .todo-dot.tone-rose {
  background: #fb7185;
}

.todo-time {
  color: var(--text-3);
  font-size: 10.5px;
  font-variant-numeric: tabular-nums;
}

.todo-item-title {
  overflow: hidden;
  color: var(--text-1);
  font-size: 12.3px;
  font-weight: 600;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.todo-item-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.todo-related {
  overflow: hidden;
  color: var(--text-3);
  font-size: 10.8px;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.todo-group-rest {
  margin: 8px 2px 0;
  color: var(--text-3);
  font-size: 10.8px;
}

.todo-empty {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 18px 6px 8px;
}

.todo-empty-icon {
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  flex-shrink: 0;
  border-radius: 14px;
  background: var(--gradient-brand-soft);
  color: var(--brand);
}

.todo-empty-icon .el-icon {
  font-size: 21px;
}

.todo-empty-copy {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 1;
}

.todo-empty-copy strong {
  color: var(--text-1);
  font-size: 13px;
  font-weight: 600;
}

.todo-empty-copy span {
  color: var(--text-3);
  font-size: 11.5px;
}

@media (max-width: 720px) {
  .todo-panel {
    padding: 18px 16px;
  }

  .todo-groups {
    grid-template-columns: 1fr;
  }

  .todo-empty {
    flex-wrap: wrap;
  }
}

@media (max-width: 1280px) {
  .metric-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 1180px) {
  .bottom-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 1040px) {
  .chart-grid {
    grid-template-columns: 1fr;
  }

  .status-body {
    grid-template-columns: minmax(200px, 0.8fr) minmax(0, 1fr);
  }
}

@media (max-width: 900px) {
  .overview-hero {
    grid-template-columns: 1fr;
    padding: 26px 24px;
  }

  .hero-gauge {
    display: none;
  }
}

@media (max-width: 720px) {
  .metric-grid {
    grid-template-columns: 1fr;
  }

  .dashboard-filters {
    width: 100%;
  }

  .filter-dept,
  .filter-months {
    flex: 1;
    width: auto;
  }

  .metric-card {
    padding: 16px;
  }

  .panel {
    padding: 18px 16px;
  }

  .status-body {
    grid-template-columns: 1fr;
    gap: 10px;
  }

  .donut-wrap {
    max-width: 240px;
    margin: 0 auto;
  }

  .status-legend {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 0 12px;
  }

  .recent-time {
    display: none;
  }

  .overview-hero {
    padding: 22px 18px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .dept-bar,
  .status-legend li {
    transition: none;
  }
}
</style>
