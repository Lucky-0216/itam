<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Download, InfoFilled, Refresh, Search } from '@element-plus/icons-vue'
import dayjs from 'dayjs'
import type { EChartsCoreOption } from 'echarts/core'

import { reportApi } from '@/api/report'
import EChart from '@/components/charts/EChart.vue'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import {
  ASSET_STATUS_LABELS,
  ASSET_STATUS_TAG_TYPES,
  type AssetStatus,
} from '@/types/asset'
import type {
  AssetReportOverview,
  ComplianceAssetPage,
  ComplianceIssueSummary,
  ComplianceSummary,
  IdleAssetPage,
  ReportAssetPage,
  ReportCategoryOption,
  ReportDeptOption,
  ReportFilters,
  ReportFormat,
  ReportMetrics,
  ReportOptions,
  ReportType,
  TreeOption,
} from '@/types/report'

type TabKey = ReportType

const auth = useAuthStore()
const app = useAppStore()
const canExport = computed(() => auth.hasPerm('asset:report:export'))

const EMPTY_METRICS: ReportMetrics = {
  total_count: 0,
  total_value: 0,
  avg_value: 0,
  in_use_count: 0,
  in_stock_count: 0,
  idle_count: 0,
  idle_value: 0,
  repairing_count: 0,
  pending_scrap_count: 0,
  scrapped_count: 0,
  warranty_expiring_30d: 0,
  warranty_expired: 0,
  compliance_asset_count: 0,
}

const TAB_LABELS: Record<TabKey, string> = {
  OVERVIEW: '资产分析概览',
  ASSETS: '资产清单',
  IDLE: '闲置资产',
  COMPLIANCE: '合规检查',
}

const STATUS_COLORS: Record<string, string> = {
  PENDING_STOCK: '#f59e0b',
  IN_STOCK: '#0ea5e9',
  IN_USE: '#2563eb',
  BORROWED: '#0d9488',
  IDLE: '#14b8a6',
  REPAIRING: '#8b5cf6',
  PENDING_SCRAP: '#f97316',
  SCRAPPED: '#94a3b8',
}

const statusOptions = Object.entries(ASSET_STATUS_LABELS) as Array<[AssetStatus, string]>

const activeTab = ref<TabKey>('OVERVIEW')
const overviewLoading = ref(false)
const tableLoading = ref(false)
const summaryLoading = ref(false)
const exporting = ref(false)

const overview = ref<AssetReportOverview | null>(null)
const options = ref<ReportOptions>({ departments: [], categories: [] })
const assetPage = ref<ReportAssetPage>({ items: [], total: 0, page: 1, page_size: 10 })
const idlePage = ref<IdleAssetPage>({ items: [], total: 0, page: 1, page_size: 10 })
const compliancePage = ref<ComplianceAssetPage>({
  items: [],
  total: 0,
  page: 1,
  page_size: 10,
})
const complianceSummary = ref<ComplianceSummary | null>(null)
const complianceIssue = ref<string | undefined>()
const complianceIssueLabel = computed(
  () =>
    complianceSummary.value?.items.find(
      (item) => item.issue_type === complianceIssue.value,
    )?.label ?? '问题明细',
)

const page = ref(1)
const pageSize = ref(10)

const query = reactive({
  keyword: '',
  status: undefined as AssetStatus | undefined,
  category_id: undefined as number | undefined,
  dept_id: undefined as number | undefined,
  purchaseRange: [] as string[] | null,
})

const metrics = computed<ReportMetrics>(() => overview.value?.metrics ?? EMPTY_METRICS)
const statusDistribution = computed(() => overview.value?.status_distribution ?? [])
const deptDistribution = computed(() => overview.value?.dept_distribution ?? [])
const categoryDistribution = computed(() => overview.value?.category_distribution ?? [])
const purchaseTrend = computed(() => overview.value?.purchase_trend ?? [])
const maxDeptBase = computed(() =>
  Math.max(
    1,
    ...deptDistribution.value.map((item) => Math.max(item.value, item.count)),
  ),
)

function buildTree<T extends { id: number; parent_id: number | null; name: string }>(
  items: T[],
): TreeOption[] {
  const nodes = new Map<number, TreeOption>()
  items.forEach((item) => nodes.set(item.id, { value: item.id, label: item.name, children: [] }))
  const roots: TreeOption[] = []
  items.forEach((item) => {
    const node = nodes.get(item.id)
    if (!node) return
    const parent = item.parent_id ? nodes.get(item.parent_id) : undefined
    if (parent) {
      parent.children?.push(node)
    } else {
      roots.push(node)
    }
  })
  return roots
}

const categoryTree = computed(() =>
  buildTree<ReportCategoryOption>(options.value.categories),
)
const deptTree = computed(() => buildTree<ReportDeptOption>(options.value.departments))

function baseParams(): ReportFilters {
  const [from, to] = query.purchaseRange ?? []
  return {
    keyword: query.keyword.trim() || undefined,
    status: query.status,
    category_id: query.category_id,
    include_child: true,
    dept_id: query.dept_id,
    purchase_from: from || undefined,
    purchase_to: to || undefined,
  }
}

function paramsFor(tab: TabKey): ReportFilters {
  const params = baseParams()
  if (tab === 'IDLE') delete params.status
  return params
}

async function loadOptions(): Promise<void> {
  try {
    options.value = await reportApi.options()
  } catch {
    // 错误提示由请求拦截器统一处理
  }
}

async function loadOverview(): Promise<void> {
  overviewLoading.value = true
  try {
    overview.value = await reportApi.overview(paramsFor('OVERVIEW'))
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    overviewLoading.value = false
  }
}

async function loadAssets(): Promise<void> {
  tableLoading.value = true
  try {
    assetPage.value = await reportApi.assets({
      ...paramsFor('ASSETS'),
      page: page.value,
      page_size: pageSize.value,
    })
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    tableLoading.value = false
  }
}

async function loadIdle(): Promise<void> {
  tableLoading.value = true
  try {
    idlePage.value = await reportApi.idle({
      ...paramsFor('IDLE'),
      page: page.value,
      page_size: pageSize.value,
    })
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    tableLoading.value = false
  }
}

async function loadComplianceSummary(): Promise<void> {
  summaryLoading.value = true
  try {
    complianceSummary.value = await reportApi.complianceSummary(paramsFor('COMPLIANCE'))
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    summaryLoading.value = false
  }
}

async function loadCompliance(): Promise<void> {
  tableLoading.value = true
  try {
    compliancePage.value = await reportApi.compliance({
      ...paramsFor('COMPLIANCE'),
      page: page.value,
      page_size: pageSize.value,
      issue_type: complianceIssue.value,
    })
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    tableLoading.value = false
  }
}

function loadActivePage(): void {
  if (activeTab.value === 'ASSETS') {
    void loadAssets()
  } else if (activeTab.value === 'IDLE') {
    void loadIdle()
  } else if (activeTab.value === 'COMPLIANCE') {
    void loadCompliance()
  }
}

function refreshAll(): void {
  if (activeTab.value === 'OVERVIEW') {
    void loadOverview()
    return
  }
  void loadOverview()
  if (activeTab.value === 'COMPLIANCE') {
    void loadComplianceSummary()
  }
  loadActivePage()
}

function handleQuery(): void {
  page.value = 1
  complianceIssue.value = undefined
  refreshAll()
}

function handleReset(): void {
  query.keyword = ''
  query.status = undefined
  query.category_id = undefined
  query.dept_id = undefined
  query.purchaseRange = []
  complianceIssue.value = undefined
  page.value = 1
  refreshAll()
}

function handleTabChange(name: string | number): void {
  const tab = String(name) as TabKey
  if (!TAB_LABELS[tab]) return
  page.value = 1
  if (tab === 'OVERVIEW') {
    void loadOverview()
    return
  }
  if (tab === 'ASSETS') {
    void loadAssets()
    return
  }
  if (tab === 'IDLE') {
    void loadOverview()
    void loadIdle()
    return
  }
  void loadComplianceSummary()
  void loadCompliance()
}

function openTab(tab: TabKey): void {
  activeTab.value = tab
}

function handlePageChange(value: number): void {
  page.value = value
  loadActivePage()
}

function handleSizeChange(value: number): void {
  pageSize.value = value
  page.value = 1
  loadActivePage()
}

function selectIssue(issueType?: string): void {
  complianceIssue.value = issueType
  page.value = 1
  void loadCompliance()
}

function statusColor(status: string): string {
  return STATUS_COLORS[status] ?? '#94a3b8'
}

function statusTagType(status: string) {
  return ASSET_STATUS_TAG_TYPES[status as AssetStatus] ?? 'info'
}

function issueTagType(severity: string): 'warning' | 'info' {
  return severity === 'warning' ? 'warning' : 'info'
}

function formatInt(value: number | null | undefined): string {
  return Number(value ?? 0).toLocaleString('zh-CN')
}

function formatMoney(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return `¥ ${Number(value).toLocaleString('zh-CN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`
}

function formatDate(value: string | null | undefined): string {
  return value || '—'
}

function generatedText(): string {
  if (!overview.value) return '—'
  return dayjs(overview.value.generated_at).format('YYYY-MM-DD HH:mm')
}

function deptBarWidth(value: number, count: number): string {
  const base = Math.max(value, count)
  return `${Math.max(6, Math.round((base / maxDeptBase.value) * 100))}%`
}

function cssVar(name: string, fallback: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return value || fallback
}

const chartPalette = computed(() => {
  const dark = app.isDark
  return {
    dark,
    primary: app.primary,
    text2: cssVar('--text-2', '#5c6b83'),
    text3: cssVar('--text-3', '#93a0b4'),
    border: cssVar('--border', '#e5ebf4'),
    surface: cssVar('--surface', '#ffffff'),
    brand: cssVar('--brand', '#4a6da8'),
  }
})

function tooltipStyle(): Record<string, unknown> {
  const palette = chartPalette.value
  return {
    backgroundColor: cssVar('--el-bg-color-overlay', '#fdfdfe'),
    borderColor: palette.border,
    borderWidth: 1,
    padding: [8, 12],
    textStyle: { color: cssVar('--text-1', '#1d2430'), fontSize: 12 },
    extraCssText: 'border-radius:10px;box-shadow:0 14px 34px -20px rgba(15,23,42,0.45);',
  }
}

const statusOption = computed<EChartsCoreOption>(() => {
  const palette = chartPalette.value
  const slices = statusDistribution.value.filter((item) => item.count > 0)
  return {
    tooltip: {
      trigger: 'item',
      formatter: '{b}<br/>{c} 台 · {d}%',
      ...tooltipStyle(),
    },
    series: [
      {
        type: 'pie',
        radius: ['58%', '82%'],
        center: ['50%', '50%'],
        padAngle: 2,
        itemStyle: {
          borderRadius: 6,
          borderColor: palette.surface,
          borderWidth: 3,
        },
        label: { show: false },
        labelLine: { show: false },
        data: slices.map((item) => ({
          name: item.label,
          value: item.count,
          itemStyle: { color: statusColor(item.status) },
        })),
      },
    ],
  }
})

const trendOption = computed<EChartsCoreOption>(() => {
  const palette = chartPalette.value
  const points = purchaseTrend.value
  return {
    grid: { left: 6, right: 16, top: 18, bottom: 2, containLabel: true },
    tooltip: {
      trigger: 'axis',
      formatter: '{b}<br/>新增资产 {c} 台',
      ...tooltipStyle(),
    },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: points.map((item) => `${Number(item.month.slice(5))}月`),
      axisLine: { lineStyle: { color: palette.border } },
      axisTick: { show: false },
      axisLabel: { color: palette.text3, fontSize: 10.5, interval: 1 },
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
        type: 'line',
        smooth: 0.35,
        showSymbol: false,
        data: points.map((item) => item.count),
        lineStyle: { width: 2.5, color: palette.brand },
        itemStyle: { color: palette.brand, borderColor: palette.surface, borderWidth: 2 },
        areaStyle: { color: palette.brand, opacity: 0.12 },
      },
    ],
  }
})

const categoryOption = computed<EChartsCoreOption>(() => {
  const palette = chartPalette.value
  const list = [...categoryDistribution.value].slice(0, 8).reverse()
  return {
    grid: { left: 4, right: 34, top: 8, bottom: 2, containLabel: true },
    tooltip: {
      trigger: 'axis',
      formatter: '{b}<br/>{c} 台资产',
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
      axisLabel: { color: palette.text2, fontSize: 11.5, width: 92, overflow: 'truncate' },
    },
    series: [
      {
        type: 'bar',
        barWidth: 12,
        showBackground: true,
        backgroundStyle: { color: 'rgba(15,23,42,0.04)', borderRadius: 6 },
        itemStyle: { borderRadius: [0, 6, 6, 0], color: palette.brand },
        label: {
          show: true,
          position: 'right',
          color: palette.text2,
          fontSize: 11,
        },
        data: list.map((item) => item.count),
      },
    ],
  }
})

async function handleExport(format: string): Promise<void> {
  if (!canExport.value) return
  const exportFormat: ReportFormat = format === 'PDF' ? 'PDF' : 'XLSX'
  exporting.value = true
  try {
    const blob = await reportApi.exportReport({
      ...paramsFor(activeTab.value),
      report: activeTab.value,
      format: exportFormat,
      issue_type:
        activeTab.value === 'COMPLIANCE' ? complianceIssue.value : undefined,
    })
    if (blob.type.includes('application/json')) {
      const body = JSON.parse(await blob.text()) as { message?: string }
      ElMessage.error(body.message || '导出失败')
      return
    }
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `ITAM-${TAB_LABELS[activeTab.value]}-${dayjs().format(
      'YYYYMMDD-HHmmss',
    )}.${exportFormat === 'XLSX' ? 'xlsx' : 'pdf'}`
    document.body.appendChild(link)
    link.click()
    link.remove()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
    ElMessage.success('报表已导出')
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    exporting.value = false
  }
}

function issueCardClass(issue: ComplianceIssueSummary): Record<string, boolean> {
  return {
    [`is-${issue.severity}`]: true,
    active: complianceIssue.value === issue.issue_type,
  }
}

onMounted(() => {
  void loadOptions()
  void loadOverview()
})
</script>

<template>
  <section class="page">
    <header class="page-header">
      <div>
        <p class="page-eyebrow">REPORTING &amp; INSIGHT</p>
        <h1 class="page-title">报表分析</h1>
        <p class="page-subtitle">
          按数据权限统计资产状态、部门与价值分布，识别闲置与合规风险，支持 Excel / PDF 导出。
        </p>
      </div>
      <div class="page-actions">
        <el-button :icon="Refresh" :loading="overviewLoading || tableLoading" @click="refreshAll">
          刷新
        </el-button>
        <el-dropdown v-if="canExport" trigger="click" :disabled="exporting" @command="handleExport">
          <el-button type="primary" :icon="Download" :loading="exporting">
            导出报表
          </el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="XLSX">导出 Excel</el-dropdown-item>
              <el-dropdown-item command="PDF">导出 PDF</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </header>

    <section class="surface-card panel filter-panel">
      <div class="filter-bar">
        <el-input
          v-model="query.keyword"
          :prefix-icon="Search"
          placeholder="资产编号 / 名称 / 序列号 / 位置"
          clearable
          class="filter-keyword"
          @keyup.enter="handleQuery"
          @clear="handleQuery"
        />
        <el-tree-select
          v-model="query.category_id"
          :data="categoryTree"
          :props="{ value: 'value', label: 'label', children: 'children' }"
          placeholder="资产分类"
          clearable
          check-strictly
          :render-after-expand="false"
          class="filter-tree"
        />
        <el-tree-select
          v-model="query.dept_id"
          :data="deptTree"
          :props="{ value: 'value', label: 'label', children: 'children' }"
          placeholder="所属部门"
          clearable
          check-strictly
          :render-after-expand="false"
          class="filter-tree"
        />
        <el-select
          v-if="activeTab !== 'IDLE'"
          v-model="query.status"
          placeholder="资产状态"
          clearable
          class="filter-select"
        >
          <el-option
            v-for="[value, label] in statusOptions"
            :key="value"
            :label="label"
            :value="value"
          />
        </el-select>
        <el-date-picker
          v-model="query.purchaseRange"
          type="daterange"
          value-format="YYYY-MM-DD"
          start-placeholder="采购开始日期"
          end-placeholder="采购结束日期"
          range-separator="至"
          class="filter-date"
        />
        <div class="filter-actions">
          <el-button type="primary" :icon="Search" @click="handleQuery">查询</el-button>
          <el-button @click="handleReset">重置</el-button>
        </div>
      </div>
    </section>

    <el-tabs v-model="activeTab" class="report-tabs" @tab-change="handleTabChange">
      <el-tab-pane label="概览分析" name="OVERVIEW" />
      <el-tab-pane label="资产清单" name="ASSETS" />
      <el-tab-pane label="闲置资产" name="IDLE" />
      <el-tab-pane label="合规检查" name="COMPLIANCE" />
    </el-tabs>

    <div v-if="activeTab === 'OVERVIEW'" v-loading="overviewLoading" class="tab-body">
      <div class="overview-meta">
        <span v-if="overview">
          数据范围：{{ overview.data_scope_label }} · 统计时间：{{ generatedText() }}
        </span>
        <span v-else>正在加载报表数据…</span>
      </div>

      <section class="metric-grid">
        <article class="metric-card surface-card">
          <span class="metric-label">资产总数</span>
          <strong class="metric-value">{{ formatInt(metrics.total_count) }}</strong>
          <small>总价值 {{ formatMoney(metrics.total_value) }}</small>
        </article>
        <article class="metric-card surface-card is-blue">
          <span class="metric-label">在用资产</span>
          <strong class="metric-value">{{ formatInt(metrics.in_use_count) }}</strong>
          <small>在库 {{ formatInt(metrics.in_stock_count) }} 台</small>
        </article>
        <article class="metric-card surface-card is-teal clickable" @click="openTab('IDLE')">
          <span class="metric-label">闲置资产</span>
          <strong class="metric-value">{{ formatInt(metrics.idle_count) }}</strong>
          <small>账面价值 {{ formatMoney(metrics.idle_value) }}</small>
        </article>
        <article class="metric-card surface-card is-violet">
          <span class="metric-label">维修中 / 待报废</span>
          <strong class="metric-value">
            {{ formatInt(metrics.repairing_count) }} / {{ formatInt(metrics.pending_scrap_count) }}
          </strong>
          <small>已报废 {{ formatInt(metrics.scrapped_count) }} 台</small>
        </article>
        <article class="metric-card surface-card is-amber">
          <span class="metric-label">30 天内保修到期</span>
          <strong class="metric-value">{{ formatInt(metrics.warranty_expiring_30d) }}</strong>
          <small>请安排续保或更换计划</small>
        </article>
        <article class="metric-card surface-card is-orange">
          <span class="metric-label">保修已到期</span>
          <strong class="metric-value">{{ formatInt(metrics.warranty_expired) }}</strong>
          <small>仍在库 / 在用 / 维修中的资产</small>
        </article>
        <article class="metric-card surface-card is-slate">
          <span class="metric-label">平均单价</span>
          <strong class="metric-value">{{ formatMoney(metrics.avg_value) }}</strong>
          <small>按全部资产计算</small>
        </article>
        <article
          class="metric-card surface-card is-danger clickable"
          @click="openTab('COMPLIANCE')"
        >
          <span class="metric-label">存在合规问题</span>
          <strong class="metric-value">{{ formatInt(metrics.compliance_asset_count) }}</strong>
          <small>项资产，点击查看明细</small>
        </article>
      </section>

      <section class="chart-grid">
        <article class="surface-card panel">
          <header class="panel-header">
            <div>
              <p class="panel-eyebrow">STATUS</p>
              <h2 class="panel-title">资产状态分布</h2>
            </div>
            <span class="panel-meta">{{ formatInt(metrics.total_count) }} 台</span>
          </header>
          <div v-if="metrics.total_count" class="status-body">
            <div class="donut-wrap">
              <EChart :option="statusOption" height="220px" />
              <div class="donut-center">
                <strong>{{ formatInt(metrics.total_count) }}</strong>
                <span>资产总量</span>
              </div>
            </div>
            <ul class="status-legend">
              <li v-for="item in statusDistribution" :key="item.status">
                <span class="legend-dot" :style="{ background: statusColor(item.status) }" />
                <span class="legend-label">{{ item.label }}</span>
                <strong>{{ formatInt(item.count) }}</strong>
                <small>{{ formatMoney(item.value) }}</small>
              </li>
            </ul>
          </div>
          <div v-else class="chart-empty">
            <el-empty :image-size="64" description="暂无资产数据" />
          </div>
        </article>

        <article class="surface-card panel">
          <header class="panel-header">
            <div>
              <p class="panel-eyebrow">PURCHASE TREND</p>
              <h2 class="panel-title">近 12 个月采购趋势</h2>
            </div>
            <span class="panel-meta">按采购日期统计</span>
          </header>
          <EChart :option="trendOption" height="250px" />
        </article>
      </section>

      <section class="chart-grid">
        <article class="surface-card panel">
          <header class="panel-header">
            <div>
              <p class="panel-eyebrow">CATEGORY</p>
              <h2 class="panel-title">分类资产分布</h2>
            </div>
            <span class="panel-meta">Top 8</span>
          </header>
          <EChart
            v-if="categoryDistribution.length"
            :option="categoryOption"
            height="260px"
          />
          <div v-else class="chart-empty">
            <el-empty :image-size="64" description="暂无分类数据" />
          </div>
        </article>

        <article class="surface-card panel">
          <header class="panel-header">
            <div>
              <p class="panel-eyebrow">DEPARTMENT &amp; VALUE</p>
              <h2 class="panel-title">部门资产与价值</h2>
            </div>
            <span class="panel-meta">按资产价值排序</span>
          </header>
          <ul v-if="deptDistribution.length" class="dept-list">
            <li
              v-for="(dept, index) in deptDistribution.slice(0, 8)"
              :key="dept.dept_id ?? dept.name"
              class="dept-item"
            >
              <span class="dept-rank" :class="{ top: index < 3 }">
                {{ String(index + 1).padStart(2, '0') }}
              </span>
              <div class="dept-main">
                <div class="dept-row">
                  <span class="dept-name">{{ dept.name }}</span>
                  <span class="dept-number">
                    <strong>{{ formatInt(dept.count) }}</strong> 台
                    <small>{{ formatMoney(dept.value) }}</small>
                  </span>
                </div>
                <div class="dept-track">
                  <span
                    class="dept-bar"
                    :style="{ width: deptBarWidth(dept.value, dept.count) }"
                  />
                </div>
              </div>
            </li>
          </ul>
          <div v-else class="chart-empty">
            <el-empty :image-size="64" description="暂无部门数据" />
          </div>
        </article>
      </section>
    </div>

    <div v-else-if="activeTab === 'ASSETS'" class="tab-body">
      <section class="surface-card panel">
        <header class="panel-header">
          <div>
            <p class="panel-eyebrow">ASSET LIST</p>
            <h2 class="panel-title">资产清单</h2>
          </div>
          <span class="panel-meta">共 {{ formatInt(assetPage.total) }} 台资产</span>
        </header>
        <el-table v-loading="tableLoading" :data="assetPage.items" row-key="id">
          <el-table-column label="资产" min-width="180">
            <template #default="{ row }">
              <div class="stack-cell">
                <strong>{{ row.name }}</strong>
                <small class="mono">{{ row.asset_no }}</small>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="分类 / 型号" min-width="150">
            <template #default="{ row }">
              <div class="stack-cell">
                <span>{{ row.category_name || '未分类' }}</span>
                <small>{{ row.model_name || '—' }}</small>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="部门 / 责任人" min-width="150">
            <template #default="{ row }">
              <div class="stack-cell">
                <span>{{ row.dept_name || '未分配部门' }}</span>
                <small>{{ row.custodian_name || '未指定' }}</small>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag :type="statusTagType(row.status)" effect="light">
                {{ row.status_label }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="采购日期" width="115">
            <template #default="{ row }">{{ formatDate(row.purchase_date) }}</template>
          </el-table-column>
          <el-table-column label="购置金额" width="130" align="right">
            <template #default="{ row }">{{ formatMoney(row.purchase_price) }}</template>
          </el-table-column>
          <el-table-column label="保修到期" width="115">
            <template #default="{ row }">{{ formatDate(row.warranty_end) }}</template>
          </el-table-column>
          <el-table-column label="存放位置" min-width="130">
            <template #default="{ row }">{{ row.location || '—' }}</template>
          </el-table-column>
          <el-table-column label="序列号" min-width="150">
            <template #default="{ row }">
              <span class="mono">{{ row.serial_no || '—' }}</span>
            </template>
          </el-table-column>
          <template #empty>
            <el-empty :image-size="72" description="暂无符合条件的资产" />
          </template>
        </el-table>
        <div class="table-footer">
          <el-pagination
            v-model:current-page="page"
            v-model:page-size="pageSize"
            :total="assetPage.total"
            :page-sizes="[10, 20, 50, 100]"
            layout="total, sizes, prev, pager, next"
            background
            @current-change="handlePageChange"
            @size-change="handleSizeChange"
          />
        </div>
      </section>
    </div>

    <div v-else-if="activeTab === 'IDLE'" class="tab-body">
      <section class="mini-grid">
        <article class="surface-card mini-card">
          <span>闲置资产</span>
          <strong>{{ formatInt(metrics.idle_count) }}</strong>
          <small>台（当前筛选范围）</small>
        </article>
        <article class="surface-card mini-card is-teal">
          <span>闲置资产账面价值</span>
          <strong>{{ formatMoney(metrics.idle_value) }}</strong>
          <small>建议优先盘活或调拨使用</small>
        </article>
      </section>

      <section class="surface-card panel">
        <header class="panel-header">
          <div>
            <p class="panel-eyebrow">IDLE ASSETS</p>
            <h2 class="panel-title">闲置资产清单</h2>
          </div>
          <span class="panel-meta">共 {{ formatInt(idlePage.total) }} 台</span>
        </header>
        <el-table v-loading="tableLoading" :data="idlePage.items" row-key="id">
          <el-table-column label="资产" min-width="180">
            <template #default="{ row }">
              <div class="stack-cell">
                <strong>{{ row.name }}</strong>
                <small class="mono">{{ row.asset_no }}</small>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="分类" min-width="130">
            <template #default="{ row }">{{ row.category_name || '未分类' }}</template>
          </el-table-column>
          <el-table-column label="部门 / 责任人" min-width="150">
            <template #default="{ row }">
              <div class="stack-cell">
                <span>{{ row.dept_name || '未分配部门' }}</span>
                <small>{{ row.custodian_name || '未指定' }}</small>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="90">
            <template #default="{ row }">
              <el-tag type="warning" effect="light">{{ row.status_label }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="进入闲置时间" width="150">
            <template #default="{ row }">{{ formatDate(row.idle_since) }}</template>
          </el-table-column>
          <el-table-column label="闲置天数" width="110" align="center">
            <template #default="{ row }">
              <span
                class="idle-days"
                :class="{ danger: row.idle_days >= 90, warning: row.idle_days >= 30 }"
              >
                {{ row.idle_days }} 天
              </span>
            </template>
          </el-table-column>
          <el-table-column label="购置金额" width="130" align="right">
            <template #default="{ row }">{{ formatMoney(row.purchase_price) }}</template>
          </el-table-column>
          <el-table-column label="存放位置" min-width="130">
            <template #default="{ row }">{{ row.location || '—' }}</template>
          </el-table-column>
          <template #empty>
            <el-empty :image-size="72" description="当前筛选范围内没有闲置资产" />
          </template>
        </el-table>
        <div class="table-footer">
          <el-pagination
            v-model:current-page="page"
            v-model:page-size="pageSize"
            :total="idlePage.total"
            :page-sizes="[10, 20, 50, 100]"
            layout="total, sizes, prev, pager, next"
            background
            @current-change="handlePageChange"
            @size-change="handleSizeChange"
          />
        </div>
      </section>
    </div>

    <div v-else class="tab-body">
      <section v-loading="summaryLoading" class="compliance-head">
        <div class="compliance-title-row">
          <div>
            <p class="panel-eyebrow">COMPLIANCE</p>
            <h2 class="panel-title">合规检查</h2>
          </div>
          <span class="compliance-total">
            {{ formatInt(complianceSummary?.asset_count ?? 0) }} 台资产存在合规问题
          </span>
        </div>
        <p class="compliance-note">
          <el-icon><InfoFilled /></el-icon>
          基于资产台账实时计算：责任人、位置、采购信息、序列号、保修状态与部门归属。
        </p>
        <div class="issue-strip">
          <button
            type="button"
            class="issue-card all"
            :class="{ active: !complianceIssue }"
            @click="selectIssue(undefined)"
          >
            <span class="issue-title">全部问题</span>
            <strong>{{ formatInt(complianceSummary?.asset_count ?? 0) }}</strong>
            <p>存在至少一项合规问题的资产</p>
          </button>
          <button
            v-for="issue in complianceSummary?.items ?? []"
            :key="issue.issue_type"
            type="button"
            class="issue-card"
            :class="issueCardClass(issue)"
            @click="selectIssue(issue.issue_type)"
          >
            <span class="issue-title">
              <el-tag :type="issueTagType(issue.severity)" size="small" effect="plain">
                {{ issue.severity === 'warning' ? '需关注' : '建议完善' }}
              </el-tag>
              {{ issue.label }}
            </span>
            <strong>{{ formatInt(issue.count) }}</strong>
            <p>{{ issue.suggestion }}</p>
          </button>
        </div>
      </section>

      <section class="surface-card panel">
        <header class="panel-header">
          <div>
            <p class="panel-eyebrow">ISSUE DETAILS</p>
            <h2 class="panel-title">
              {{ complianceIssue ? `问题明细 · ${complianceIssueLabel}` : '全部问题明细' }}
            </h2>
          </div>
          <el-button
            v-if="complianceIssue"
            link
            type="primary"
            @click="selectIssue(undefined)"
          >
            查看全部问题
          </el-button>
          <span v-else class="panel-meta">共 {{ formatInt(compliancePage.total) }} 台</span>
        </header>
        <el-table v-loading="tableLoading" :data="compliancePage.items" row-key="id">
          <el-table-column label="资产" min-width="180">
            <template #default="{ row }">
              <div class="stack-cell">
                <strong>{{ row.name }}</strong>
                <small class="mono">{{ row.asset_no }}</small>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="分类" min-width="130">
            <template #default="{ row }">{{ row.category_name || '未分类' }}</template>
          </el-table-column>
          <el-table-column label="部门 / 责任人" min-width="150">
            <template #default="{ row }">
              <div class="stack-cell">
                <span>{{ row.dept_name || '未分配部门' }}</span>
                <small>{{ row.custodian_name || '未指定' }}</small>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="90">
            <template #default="{ row }">
              <el-tag :type="statusTagType(row.status)" effect="light">
                {{ row.status_label }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="问题项" min-width="220">
            <template #default="{ row }">
              <div class="issue-tags">
                <el-tag
                  v-for="issue in row.issues"
                  :key="issue.issue_type"
                  :type="issueTagType(issue.severity)"
                  size="small"
                  effect="plain"
                >
                  {{ issue.label }}
                </el-tag>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="购置金额" width="130" align="right">
            <template #default="{ row }">{{ formatMoney(row.purchase_price) }}</template>
          </el-table-column>
          <el-table-column label="保修到期" width="115">
            <template #default="{ row }">{{ formatDate(row.warranty_end) }}</template>
          </el-table-column>
          <el-table-column label="存放位置" min-width="130">
            <template #default="{ row }">{{ row.location || '—' }}</template>
          </el-table-column>
          <template #empty>
            <el-empty :image-size="72" description="当前筛选范围内没有合规问题" />
          </template>
        </el-table>
        <div class="table-footer">
          <el-pagination
            v-model:current-page="page"
            v-model:page-size="pageSize"
            :total="compliancePage.total"
            :page-sizes="[10, 20, 50, 100]"
            layout="total, sizes, prev, pager, next"
            background
            @current-change="handlePageChange"
            @size-change="handleSizeChange"
          />
        </div>
      </section>
    </div>
  </section>
</template>

<style scoped>
.page-actions {
  display: flex;
  gap: 10px;
}

.panel {
  padding: 20px;
}

.filter-panel {
  margin-bottom: 4px;
}

.filter-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
}

.filter-keyword {
  width: 300px;
}

.filter-tree {
  width: 200px;
}

.filter-select {
  width: 150px;
}

.filter-date {
  width: 270px;
}

.filter-actions {
  display: flex;
  gap: 8px;
  margin-left: auto;
}

.report-tabs {
  margin-top: 10px;
}

.report-tabs :deep(.el-tabs__header) {
  margin-bottom: 14px;
}

.tab-body {
  min-height: 200px;
}

.overview-meta {
  display: flex;
  justify-content: flex-end;
  margin: -4px 0 10px;
  color: var(--text-3);
  font-size: 12px;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
  margin-bottom: 16px;
}

.metric-card {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 18px 20px;
  overflow: hidden;
}

.metric-card::before {
  content: '';
  position: absolute;
  inset: 0 auto 0 0;
  width: 4px;
  background: var(--brand);
  opacity: 0.85;
}

.metric-card.is-blue::before {
  background: var(--brand);
}

.metric-card.is-teal::before {
  background: #0d9488;
}

.metric-card.is-violet::before {
  background: #8b5cf6;
}

.metric-card.is-amber::before {
  background: #f59e0b;
}

.metric-card.is-orange::before {
  background: #f97316;
}

.metric-card.is-slate::before {
  background: #64748b;
}

.metric-card.is-danger::before {
  background: #dc2626;
}

.metric-card.clickable {
  cursor: pointer;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}

.metric-card.clickable:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-md);
}

.metric-label {
  color: var(--text-2);
  font-size: 12.5px;
}

.metric-value {
  color: var(--text-1);
  font-size: 26px;
  font-weight: 700;
  letter-spacing: -0.03em;
  line-height: 1.2;
}

.metric-card small {
  color: var(--text-3);
  font-size: 11.5px;
}

.chart-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
  margin-bottom: 16px;
}

.panel-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}

.panel-eyebrow {
  color: var(--brand);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.15em;
}

.panel-title {
  margin: 3px 0 0;
  color: var(--text-1);
  font-size: 16px;
  font-weight: 650;
}

.panel-meta {
  color: var(--text-3);
  font-size: 12px;
  white-space: nowrap;
}

.status-body {
  display: grid;
  grid-template-columns: minmax(220px, 1fr) minmax(180px, 1fr);
  align-items: center;
  gap: 12px;
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
  pointer-events: none;
}

.donut-center strong {
  color: var(--text-1);
  font-size: 24px;
  font-weight: 700;
}

.donut-center span {
  color: var(--text-3);
  font-size: 11px;
}

.status-legend {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.status-legend li {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--text-2);
  font-size: 12px;
}

.status-legend strong {
  color: var(--text-1);
  font-size: 12.5px;
}

.status-legend small {
  margin-left: auto;
  color: var(--text-3);
  font-size: 11px;
}

.legend-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.legend-label {
  white-space: nowrap;
}

.chart-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 200px;
}

.dept-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.dept-item {
  display: flex;
  align-items: center;
  gap: 10px;
}

.dept-rank {
  color: var(--text-3);
  font-size: 11px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

.dept-rank.top {
  color: var(--brand);
}

.dept-main {
  flex: 1;
  min-width: 0;
}

.dept-row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 5px;
}

.dept-name {
  color: var(--text-1);
  font-size: 12.5px;
  font-weight: 550;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dept-number {
  color: var(--text-2);
  font-size: 11.5px;
  white-space: nowrap;
}

.dept-number small {
  margin-left: 8px;
  color: var(--text-3);
}

.dept-track {
  height: 6px;
  border-radius: 999px;
  background: var(--surface-muted);
  overflow: hidden;
}

.dept-bar {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, var(--brand), var(--brand-cyan));
}

.mini-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
  margin-bottom: 16px;
}

.mini-card {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 18px 20px;
}

.mini-card span {
  color: var(--text-2);
  font-size: 12.5px;
}

.mini-card strong {
  color: var(--text-1);
  font-size: 24px;
  font-weight: 700;
}

.mini-card small {
  color: var(--text-3);
  font-size: 11.5px;
}

.mini-card.is-teal strong {
  color: #0f766e;
}

.idle-days {
  color: var(--text-2);
  font-weight: 600;
}

.idle-days.warning {
  color: #d97706;
}

.idle-days.danger {
  color: #dc2626;
}

.stack-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.stack-cell small {
  color: var(--text-3);
  font-size: 11.5px;
}

.mono {
  font-family: 'JetBrains Mono', 'SFMono-Regular', Consolas, monospace;
  font-size: 11.5px;
}

.table-footer {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}

.compliance-head {
  padding: 4px 0 18px;
}

.compliance-title-row {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}

.compliance-total {
  color: var(--text-2);
  font-size: 13px;
  white-space: nowrap;
}

.compliance-note {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 0 0 14px;
  color: var(--text-3);
  font-size: 12px;
}

.issue-strip {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(210px, 1fr));
  gap: 10px;
}

.issue-card {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 14px 16px;
  text-align: left;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  cursor: pointer;
  transition: border-color 0.2s ease, box-shadow 0.2s ease, transform 0.2s ease;
}

.issue-card:hover {
  border-color: var(--brand);
  box-shadow: var(--shadow-sm);
  transform: translateY(-1px);
}

.issue-card.active {
  border-color: var(--brand);
  box-shadow: 0 0 0 2px var(--brand-soft);
}

.issue-card.is-warning strong {
  color: #d97706;
}

.issue-card.is-info strong {
  color: var(--brand);
}

.issue-title {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--text-1);
  font-size: 12.5px;
  font-weight: 600;
}

.issue-card strong {
  color: var(--text-1);
  font-size: 22px;
  font-weight: 700;
  line-height: 1.2;
}

.issue-card p {
  margin: 0;
  color: var(--text-3);
  font-size: 11.5px;
  line-height: 1.5;
}

.issue-card.all {
  background: var(--gradient-brand-soft);
}

.issue-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

@media (max-width: 1280px) {
  .metric-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 1100px) {
  .chart-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 760px) {
  .filter-keyword,
  .filter-tree,
  .filter-select,
  .filter-date {
    width: 100%;
  }

  .filter-actions {
    width: 100%;
    margin-left: 0;
  }

  .metric-grid,
  .mini-grid {
    grid-template-columns: 1fr;
  }

  .status-body {
    grid-template-columns: 1fr;
  }

  .compliance-title-row {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
