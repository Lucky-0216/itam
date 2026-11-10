<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch, type Component } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  AlarmClock,
  ArrowRight,
  Bell,
  Files,
  FirstAidKit,
  Memo,
  Refresh,
  Search,
  Tickets,
} from '@element-plus/icons-vue'

import { reminderApi } from '@/api/reminder'
import { useAuthStore } from '@/stores/auth'
import type {
  ReminderCategorySummary,
  ReminderItem,
  ReminderPage,
  ReminderScanResult,
  ReminderSummary,
} from '@/types/reminder'
import { formatDateTime } from '@/utils/format'

type TagType = 'primary' | 'success' | 'info' | 'warning' | 'danger'

const CATEGORY_OPTIONS = [
  { value: 'WARRANTY', label: '保修到期' },
  { value: 'CONTRACT', label: '合同到期' },
  { value: 'BORROW', label: '借用归还' },
  { value: 'INVENTORY', label: '盘点任务' },
]

const LEVEL_OPTIONS = [
  { value: 'danger', label: '紧急' },
  { value: 'warning', label: '预警' },
  { value: 'info', label: '关注' },
]

const CATEGORY_META: Record<
  string,
  { icon: Component; tone: string; hint: string }
> = {
  WARRANTY: { icon: FirstAidKit, tone: 'blue', hint: '保修即将到期或已经过保' },
  CONTRACT: { icon: Memo, tone: 'violet', hint: '合同临近结束或已经到期' },
  BORROW: { icon: Tickets, tone: 'teal', hint: '借用资产临近或已过归还日' },
  INVENTORY: { icon: Files, tone: 'amber', hint: '盘点任务临近或已经逾期' },
}

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const canScan = computed(() => auth.hasPerm('asset:reminder:scan'))

const summary = ref<ReminderSummary | null>(null)
const pageData = ref<ReminderPage>({ items: [], total: 0, page: 1, page_size: 10 })
const summaryLoading = ref(false)
const loading = ref(false)
const scanning = ref(false)
const scanDialog = ref(false)
const scanResult = ref<ReminderScanResult | null>(null)
const page = ref(1)
const pageSize = ref(10)

const query = reactive({
  keyword: '',
  category: undefined as string | undefined,
  level: undefined as string | undefined,
})

const activeCategory = computed(() =>
  summary.value?.categories.find((item) => item.category === query.category),
)
const generatedText = computed(() =>
  summary.value ? formatDateTime(summary.value.generated_at) : '—',
)
const emailHint = computed(() =>
  summary.value?.email_enabled
    ? '每日汇总邮件已启用'
    : '系统消息提醒中 · 邮件汇总未启用',
)

function levelTagType(level: string): TagType {
  if (level === 'danger') return 'danger'
  if (level === 'warning') return 'warning'
  return 'info'
}

function categoryMeta(category: string) {
  return CATEGORY_META[category] ?? { icon: Bell, tone: 'slate', hint: '' }
}

function daysText(item: ReminderItem): string {
  if (item.days_left === null || item.days_left === undefined) return '—'
  if (item.days_left < 0) return `已逾期 ${-item.days_left} 天`
  if (item.days_left === 0) return '今天到期'
  return `剩余 ${item.days_left} 天`
}

function daysClass(item: ReminderItem): string {
  if (item.days_left === null || item.days_left === undefined) return ''
  if (item.days_left < 0) return 'is-overdue'
  if (item.days_left <= 7) return 'is-soon'
  return 'is-safe'
}

function categoryBreakdown(item: ReminderCategorySummary): string {
  if (!item.count) return '暂无待处理事项'
  const parts: string[] = []
  if (item.danger_count) parts.push(`${item.danger_count} 项紧急`)
  if (item.warning_count) parts.push(`${item.warning_count} 项预警`)
  if (item.info_count) parts.push(`${item.info_count} 项提醒`)
  return parts.join(' · ')
}

function emailStatusLabel(status: string): string {
  return (
    {
      SENT: '邮件已发送',
      FAILED: '邮件发送失败',
      SKIPPED: '邮件未启用或无需发送',
    }[status] ?? status
  )
}

async function loadSummary(): Promise<void> {
  summaryLoading.value = true
  try {
    summary.value = await reminderApi.summary()
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    summaryLoading.value = false
  }
}

async function loadList(): Promise<void> {
  loading.value = true
  try {
    pageData.value = await reminderApi.list({
      keyword: query.keyword.trim() || undefined,
      category: query.category,
      level: query.level,
      page: page.value,
      page_size: pageSize.value,
    })
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    loading.value = false
  }
}

function refreshAll(): void {
  void loadSummary()
  void loadList()
}

function handleQuery(): void {
  page.value = 1
  void loadList()
}

function handleReset(): void {
  query.keyword = ''
  query.category = undefined
  query.level = undefined
  page.value = 1
  if (Object.keys(route.query).length) {
    void router.replace({ path: route.path, query: {} })
  }
  void loadList()
}

function focusLevel(level: string): void {
  query.level = query.level === level ? undefined : level
  page.value = 1
  void loadList()
}

function focusCategory(category: string): void {
  query.category = query.category === category ? undefined : category
  page.value = 1
  void loadList()
}

function handleOpen(item: ReminderItem): void {
  if (!item.link) return
  void router.push(item.link)
}

function handleSizeChange(size: number): void {
  pageSize.value = size
  page.value = 1
  void loadList()
}

function handlePageChange(value: number): void {
  page.value = value
  void loadList()
}

async function handleScan(): Promise<void> {
  if (scanning.value) return
  try {
    await ElMessageBox.confirm(
      '系统将立即汇总保修、合同、借用与盘点数据，并写入当日提醒审计记录。同一天内重复扫描不会重复写入。',
      '执行到期提醒扫描',
      {
        confirmButtonText: '开始扫描',
        cancelButtonText: '取消',
        type: 'info',
      },
    )
  } catch {
    return
  }
  scanning.value = true
  try {
    scanResult.value = await reminderApi.scan()
    scanDialog.value = true
    if (scanResult.value.already_scanned) {
      ElMessage.info('今日扫描已完成，本次未重复写入提醒记录')
    } else {
      ElMessage.success(`扫描完成，新增 ${scanResult.value.created} 条提醒审计`)
    }
    refreshAll()
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    scanning.value = false
  }
}

function applyRouteQuery(): boolean {
  const rawCategory =
    typeof route.query.category === 'string' ? route.query.category.toUpperCase() : ''
  const rawLevel =
    typeof route.query.level === 'string' ? route.query.level.toLowerCase() : ''
  const rawKeyword = typeof route.query.keyword === 'string' ? route.query.keyword : ''
  const category = CATEGORY_OPTIONS.some((item) => item.value === rawCategory)
    ? rawCategory
    : undefined
  const level = LEVEL_OPTIONS.some((item) => item.value === rawLevel)
    ? rawLevel
    : undefined
  query.category = category
  query.level = level
  if (rawKeyword) query.keyword = rawKeyword
  return Boolean(category || level || rawKeyword)
}

watch(
  () => route.query,
  () => {
    if (!applyRouteQuery()) return
    page.value = 1
    void loadList()
  },
)

onMounted(() => {
  applyRouteQuery()
  void loadSummary()
  void loadList()
})
</script>

<template>
  <section class="page reminder-page">
    <header class="page-header">
      <div>
        <p class="page-eyebrow">EXPIRY REMINDERS</p>
        <h1 class="page-title">到期提醒</h1>
        <p class="page-subtitle">
          汇总保修、合同、借用归还与盘点任务的临近及逾期事项，按数据权限实时计算。
        </p>
      </div>
      <div class="page-actions">
        <span class="email-chip" :class="{ 'is-on': summary?.email_enabled }">
          <el-icon><Bell /></el-icon>
          {{ emailHint }}
        </span>
        <el-button
          :icon="Refresh"
          :loading="summaryLoading || loading"
          @click="refreshAll"
        >
          刷新
        </el-button>
        <el-button
          v-if="canScan"
          type="primary"
          :icon="AlarmClock"
          :loading="scanning"
          @click="handleScan"
        >
          立即扫描
        </el-button>
      </div>
    </header>

    <section v-loading="summaryLoading" class="hero surface-card">
      <div class="hero-main">
        <div class="hero-copy">
          <p class="hero-eyebrow">TODAY'S FOCUS</p>
          <div class="hero-number">
            <strong>{{ summary?.total ?? 0 }}</strong>
            <span>项待处理提醒</span>
          </div>
          <p class="hero-desc">
            数据每日 09:10 自动扫描，也可随时手动执行；统计时间 {{ generatedText }}。
          </p>
        </div>
        <div class="hero-orbit" aria-hidden="true">
          <span class="orbit-ring" />
          <span class="orbit-core">
            <el-icon><AlarmClock /></el-icon>
          </span>
        </div>
      </div>

      <div class="hero-levels">
        <button
          type="button"
          class="level-chip is-danger"
          :class="{ active: query.level === 'danger' }"
          @click="focusLevel('danger')"
        >
          <span class="level-dot" />
          <span class="level-label">紧急</span>
          <strong>{{ summary?.danger_count ?? 0 }}</strong>
        </button>
        <button
          type="button"
          class="level-chip is-warning"
          :class="{ active: query.level === 'warning' }"
          @click="focusLevel('warning')"
        >
          <span class="level-dot" />
          <span class="level-label">预警</span>
          <strong>{{ summary?.warning_count ?? 0 }}</strong>
        </button>
        <button
          type="button"
          class="level-chip is-info"
          :class="{ active: query.level === 'info' }"
          @click="focusLevel('info')"
        >
          <span class="level-dot" />
          <span class="level-label">关注</span>
          <strong>{{ summary?.info_count ?? 0 }}</strong>
        </button>
      </div>
    </section>

    <section class="category-grid">
      <button
        v-for="item in summary?.categories ?? []"
        :key="item.category"
        type="button"
        class="category-card surface-card"
        :class="[
          `tone-${categoryMeta(item.category).tone}`,
          { active: query.category === item.category },
        ]"
        @click="focusCategory(item.category)"
      >
        <span class="category-icon">
          <el-icon><component :is="categoryMeta(item.category).icon" /></el-icon>
        </span>
        <span class="category-body">
          <span class="category-top">
            <span class="category-name">{{ item.label }}</span>
            <el-icon class="category-arrow"><ArrowRight /></el-icon>
          </span>
          <span class="category-count">{{ item.count }}<small>项</small></span>
          <span class="category-hint">{{ categoryBreakdown(item) }}</span>
          <span class="category-desc">{{ categoryMeta(item.category).hint }}</span>
        </span>
      </button>
    </section>

    <section class="surface-card panel">
      <header class="panel-header">
        <div>
          <p class="panel-eyebrow">REMINDER LIST</p>
          <h2 class="panel-title">
            {{ activeCategory ? activeCategory.label : '全部提醒' }}
            <span v-if="activeCategory" class="panel-count">{{ activeCategory.count }}</span>
          </h2>
        </div>
        <span class="panel-meta">共 {{ pageData.total }} 条 · 到期日按紧急程度排序</span>
      </header>

      <div class="filter-bar">
        <el-input
          v-model="query.keyword"
          :prefix-icon="Search"
          placeholder="搜索编号 / 名称 / 负责人"
          clearable
          class="filter-keyword"
          @keyup.enter="handleQuery"
          @clear="handleQuery"
        />
        <el-select
          v-model="query.category"
          placeholder="提醒类型"
          clearable
          class="filter-select"
          @change="handleQuery"
        >
          <el-option
            v-for="item in CATEGORY_OPTIONS"
            :key="item.value"
            :label="item.label"
            :value="item.value"
          />
        </el-select>
        <el-select
          v-model="query.level"
          placeholder="紧急程度"
          clearable
          class="filter-select"
          @change="handleQuery"
        >
          <el-option
            v-for="item in LEVEL_OPTIONS"
            :key="item.value"
            :label="item.label"
            :value="item.value"
          />
        </el-select>
        <div class="filter-actions">
          <el-button type="primary" :icon="Search" @click="handleQuery">查询</el-button>
          <el-button @click="handleReset">重置</el-button>
        </div>
      </div>

      <el-table
        v-loading="loading"
        :data="pageData.items"
        row-key="id"
        class="reminder-table"
      >
        <el-table-column label="级别" width="84">
          <template #default="{ row }">
            <el-tag :type="levelTagType(row.level)" effect="light" size="small">
              {{ row.level_label }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="类型" width="108">
          <template #default="{ row }">
            <span class="type-cell">
              <el-icon
                class="type-icon"
                :class="`tone-${categoryMeta(row.category).tone}`"
              >
                <component :is="categoryMeta(row.category).icon" />
              </el-icon>
              {{ row.category_label }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="提醒内容" min-width="360">
          <template #default="{ row }">
            <div class="content-cell">
              <strong class="content-title">{{ row.title }}</strong>
              <span class="content-desc">{{ row.description }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="来源编号" width="150">
          <template #default="{ row }">
            <span class="mono">{{ row.source_no || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="负责人" width="100">
          <template #default="{ row }">{{ row.owner || '—' }}</template>
        </el-table-column>
        <el-table-column label="到期日期" width="168">
          <template #default="{ row }">
            <div class="due-cell">
              <span class="mono">{{ row.due_date || '—' }}</span>
              <span class="due-days" :class="daysClass(row)">{{ daysText(row) }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="104" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="handleOpen(row)">前往处理</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty :image-size="70" description="当前筛选条件下没有到期提醒" />
        </template>
      </el-table>

      <div class="table-footer">
        <el-pagination
          :current-page="page"
          :page-size="pageSize"
          :page-sizes="[10, 20, 50]"
          :total="pageData.total"
          layout="total, sizes, prev, pager, next"
          background
          @current-change="handlePageChange"
          @size-change="handleSizeChange"
        />
      </div>
    </section>

    <el-dialog v-model="scanDialog" title="提醒扫描结果" width="480px">
      <div v-if="scanResult" class="scan-result">
        <div class="scan-total">
          <strong>{{ scanResult.total }}</strong>
          <span>项提醒</span>
        </div>
        <ul class="scan-list">
          <li>
            <span>保修到期</span>
            <strong>{{ scanResult.warranty }}</strong>
          </li>
          <li>
            <span>合同到期</span>
            <strong>{{ scanResult.contract }}</strong>
          </li>
          <li>
            <span>借用归还</span>
            <strong>{{ scanResult.borrow }}</strong>
          </li>
          <li>
            <span>盘点任务</span>
            <strong>{{ scanResult.inventory }}</strong>
          </li>
        </ul>
        <div class="scan-meta">
          <p>
            {{
              scanResult.already_scanned
                ? '今日已完成扫描，本次未重复写入提醒审计记录。'
                : `本次新增 ${scanResult.created} 条提醒审计记录。`
            }}
          </p>
          <p>
            邮件状态：
            <el-tag size="small" effect="plain">{{ emailStatusLabel(scanResult.email_status) }}</el-tag>
          </p>
          <p>扫描时间：{{ formatDateTime(scanResult.generated_at) }}</p>
        </div>
      </div>
      <template #footer>
        <el-button type="primary" @click="scanDialog = false">知道了</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.page-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.email-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 11px;
  border: 1px dashed var(--border);
  border-radius: 999px;
  color: var(--text-3);
  font-size: 11.5px;
}

.email-chip.is-on {
  border-style: solid;
  border-color: rgba(16, 185, 129, 0.35);
  background: rgba(16, 185, 129, 0.08);
  color: #0f9f6e;
}

.hero {
  display: flex;
  flex-wrap: wrap;
  align-items: stretch;
  gap: 22px;
  padding: 24px 26px;
  margin-bottom: 16px;
  background:
    radial-gradient(520px 220px at 88% 10%, color-mix(in srgb, var(--brand) 10%, transparent), transparent 62%),
    var(--surface);
}

.hero-main {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex: 1 1 420px;
  min-width: 0;
  gap: 18px;
}

.hero-eyebrow {
  margin: 0;
  color: var(--brand);
  font-size: 10.5px;
  font-weight: 700;
  letter-spacing: 0.14em;
}

.hero-number {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin: 6px 0 4px;
}

.hero-number strong {
  color: var(--text-1);
  font-size: 46px;
  font-weight: 750;
  line-height: 1;
  letter-spacing: -0.04em;
}

.hero-number span {
  color: var(--text-2);
  font-size: 13px;
}

.hero-desc {
  margin: 0;
  color: var(--text-3);
  font-size: 12px;
}

.hero-orbit {
  position: relative;
  display: grid;
  place-items: center;
  width: 104px;
  height: 104px;
  flex-shrink: 0;
}

.orbit-ring {
  position: absolute;
  inset: 0;
  border: 1px dashed color-mix(in srgb, var(--brand) 30%, transparent);
  border-radius: 50%;
  animation: orbit-spin 18s linear infinite;
}

.orbit-ring::after {
  content: '';
  position: absolute;
  top: -4px;
  left: 50%;
  width: 8px;
  height: 8px;
  margin-left: -4px;
  border-radius: 50%;
  background: var(--brand);
  box-shadow: 0 0 0 4px var(--brand-soft);
}

.orbit-core {
  display: grid;
  place-items: center;
  width: 66px;
  height: 66px;
  border-radius: 50%;
  background: var(--gradient-brand);
  color: var(--on-brand);
  box-shadow: 0 12px 26px var(--brand-glow);
}

.orbit-core .el-icon {
  font-size: 27px;
}

@keyframes orbit-spin {
  to {
    transform: rotate(360deg);
  }
}

.hero-levels {
  display: flex;
  align-items: stretch;
  gap: 10px;
  flex: 0 0 auto;
}

.level-chip {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  justify-content: center;
  gap: 2px;
  min-width: 92px;
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: 14px;
  background: var(--surface-muted);
  cursor: pointer;
  transition:
    border-color 0.18s ease,
    transform 0.18s ease,
    background-color 0.18s ease;
}

.level-chip:hover {
  transform: translateY(-2px);
}

.level-chip.active {
  border-color: var(--brand);
  background: var(--surface);
  box-shadow: 0 6px 18px -10px var(--brand-glow);
}

.level-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
}

.level-chip.is-danger .level-dot {
  background: #dc2626;
}

.level-chip.is-warning .level-dot {
  background: #f59e0b;
}

.level-chip.is-info .level-dot {
  background: #0ea5e9;
}

.level-label {
  color: var(--text-3);
  font-size: 11px;
}

.level-chip strong {
  color: var(--text-1);
  font-size: 22px;
  font-weight: 700;
  line-height: 1.1;
}

.category-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
  margin-bottom: 16px;
}

.category-card {
  display: flex;
  align-items: flex-start;
  gap: 13px;
  padding: 17px 18px;
  border: 1px solid var(--border);
  text-align: left;
  cursor: pointer;
  transition:
    transform 0.2s cubic-bezier(0.22, 1, 0.36, 1),
    box-shadow 0.2s ease,
    border-color 0.2s ease;
}

.category-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-md);
}

.category-card.active {
  border-color: var(--brand);
  box-shadow: 0 0 0 3px var(--brand-soft);
}

.category-icon {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  flex-shrink: 0;
  border-radius: 12px;
  background: var(--brand-soft);
  color: var(--brand);
}

.category-icon .el-icon {
  font-size: 19px;
}

.tone-violet .category-icon,
.type-icon.tone-violet {
  background: rgba(139, 92, 246, 0.1);
  color: #7c3aed;
}

.tone-teal .category-icon,
.type-icon.tone-teal {
  background: rgba(13, 148, 136, 0.1);
  color: #0d9488;
}

.tone-amber .category-icon,
.type-icon.tone-amber {
  background: rgba(245, 158, 11, 0.12);
  color: #d97706;
}

.tone-slate .category-icon,
.type-icon.tone-slate {
  background: rgba(100, 116, 139, 0.12);
  color: #64748b;
}

.category-body {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  flex: 1;
}

.category-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
}

.category-name {
  color: var(--text-2);
  font-size: 12.5px;
  font-weight: 600;
}

.category-arrow {
  color: var(--text-3);
  font-size: 12px;
}

.category-count {
  color: var(--text-1);
  font-size: 26px;
  font-weight: 720;
  line-height: 1.15;
  letter-spacing: -0.02em;
}

.category-count small {
  margin-left: 3px;
  color: var(--text-3);
  font-size: 11px;
  font-weight: 500;
}

.category-hint {
  color: var(--text-2);
  font-size: 11.5px;
}

.category-desc {
  color: var(--text-3);
  font-size: 10.8px;
}

.panel {
  padding: 20px;
}

.panel-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}

.panel-eyebrow {
  margin: 0;
  color: var(--text-3);
  font-size: 10.5px;
  letter-spacing: 0.1em;
}

.panel-title {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin: 3px 0 0;
  color: var(--text-1);
  font-size: 16px;
  font-weight: 650;
}

.panel-count {
  color: var(--brand);
  font-size: 12px;
  font-weight: 600;
}

.panel-meta {
  color: var(--text-3);
  font-size: 11.5px;
  line-height: 1.9;
}

.filter-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  padding-bottom: 14px;
  border-bottom: 1px dashed var(--border);
  margin-bottom: 6px;
}

.filter-keyword {
  width: 280px;
}

.filter-select {
  width: 148px;
}

.filter-actions {
  display: flex;
  gap: 8px;
  margin-left: auto;
}

.reminder-table {
  width: 100%;
}

.type-cell {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  color: var(--text-2);
  font-size: 12.5px;
}

.type-icon {
  display: grid;
  place-items: center;
  width: 24px;
  height: 24px;
  border-radius: 8px;
  background: var(--brand-soft);
  color: var(--brand);
  font-size: 13px;
}

.content-cell {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.content-title {
  color: var(--text-1);
  font-size: 13px;
  font-weight: 600;
  line-height: 1.45;
}

.content-desc {
  color: var(--text-3);
  font-size: 11.8px;
  line-height: 1.55;
}

.due-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.due-days {
  font-size: 11.5px;
  font-weight: 600;
}

.due-days.is-overdue {
  color: #dc2626;
}

.due-days.is-soon {
  color: #d97706;
}

.due-days.is-safe {
  color: #0f9f6e;
}

.table-footer {
  display: flex;
  justify-content: flex-end;
  padding-top: 16px;
}

.scan-result {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.scan-total {
  display: flex;
  align-items: baseline;
  justify-content: center;
  gap: 8px;
  padding: 14px;
  border-radius: 14px;
  background: var(--gradient-brand-soft);
}

.scan-total strong {
  color: var(--brand);
  font-size: 38px;
  font-weight: 750;
  line-height: 1;
}

.scan-total span {
  color: var(--text-2);
  font-size: 13px;
}

.scan-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.scan-list li {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 13px;
  border: 1px solid var(--border);
  border-radius: 10px;
  color: var(--text-2);
  font-size: 12.5px;
}

.scan-list strong {
  color: var(--text-1);
  font-size: 16px;
}

.scan-meta {
  display: flex;
  flex-direction: column;
  gap: 5px;
  color: var(--text-2);
  font-size: 12.5px;
}

.scan-meta p {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 0;
}

.mono {
  font-family: 'JetBrains Mono', 'SFMono-Regular', Consolas, monospace;
  font-size: 11.5px;
  color: var(--text-2);
}

@media (max-width: 1200px) {
  .category-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 900px) {
  .hero-levels {
    width: 100%;
  }

  .level-chip {
    flex: 1;
  }

  .category-grid {
    grid-template-columns: 1fr;
  }

  .filter-keyword {
    width: 100%;
  }

  .page-actions {
    flex-wrap: wrap;
  }
}
</style>
