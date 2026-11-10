<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowRight,
  CircleCheck,
  Finished,
  Refresh,
  SortDown,
  SortUp,
} from '@element-plus/icons-vue'

import { todoApi } from '@/api/todo'
import { useTodoStore } from '@/stores/todo'
import type { TodoCategoryGroup, TodoItem, TodoTypeCount } from '@/types/todo'
import { formatDateTime } from '@/utils/format'

const CATEGORY_TONES: Record<string, string> = {
  APPROVAL: 'blue',
  CONFIRM: 'cyan',
  HANDLE: 'violet',
  MINE: 'amber',
  DUE: 'rose',
}

type TagType = 'primary' | 'success' | 'info' | 'warning' | 'danger'

const router = useRouter()
const route = useRoute()
const store = useTodoStore()

const KNOWN_CATEGORIES = ['APPROVAL', 'CONFIRM', 'HANDLE', 'MINE', 'DUE']

function queryValue(key: string): string {
  const value = route.query[key]
  return typeof value === 'string' ? value : ''
}

const initialCategory = queryValue('category')
const category = ref(KNOWN_CATEGORIES.includes(initialCategory) ? initialCategory : '')

const items = ref<TodoItem[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 12
const todoType = ref(queryValue('type'))
const sort = ref<'asc' | 'desc'>('desc')
const loading = ref(false)
const loadedOnce = ref(false)

const categoryTabs = computed(() => [
  { value: '', label: '全部待办', count: store.total, tone: 'all' },
  ...store.categories.map((group: TodoCategoryGroup) => ({
    value: group.category,
    label: group.label,
    count: group.count,
    tone: toneOf(group.category),
  })),
])

const typeOptions = computed<TodoTypeCount[]>(() => {
  const groups = category.value
    ? store.categories.filter((group) => group.category === category.value)
    : store.categories
  return groups.flatMap((group) => group.types)
})

const maxPage = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))
const hasFilter = computed(() => Boolean(category.value || todoType.value))

function toneOf(value: string): string {
  return CATEGORY_TONES[value] || 'blue'
}

function statusTag(status: string): TagType {
  if (status === 'COMPLETED') return 'success'
  if (status === 'REJECTED') return 'danger'
  if (status === 'CANCELLED') return 'info'
  if (status.startsWith('PENDING') || status === 'WAITING') return 'warning'
  if (status === 'BORROWED' || status === 'REPAIRING' || status === 'IN_PROGRESS') return 'primary'
  return 'info'
}

function dueText(item: TodoItem): string {
  if (item.is_overdue) {
    return item.days_to_due === null ? '已逾期' : `已逾期 ${Math.abs(item.days_to_due)} 天`
  }
  if (item.days_to_due === null) return ''
  if (item.days_to_due === 0) return '今天到期'
  return `剩 ${item.days_to_due} 天到期`
}

function showDue(item: TodoItem): boolean {
  return Boolean(item.due_date) && item.days_to_due !== null && item.days_to_due <= 3
}

async function loadList(): Promise<void> {
  loading.value = true
  try {
    const result = await todoApi.list({
      category: category.value || undefined,
      todo_type: todoType.value || undefined,
      page: page.value,
      page_size: pageSize,
      sort: sort.value,
    })
    items.value = result.items
    total.value = result.total
    const limit = Math.max(1, Math.ceil(result.total / pageSize))
    if (page.value > limit) {
      page.value = limit
      loading.value = false
      await loadList()
    }
  } finally {
    loading.value = false
    loadedOnce.value = true
  }
}

async function refreshAll(): Promise<void> {
  await Promise.all([store.refresh(), loadList()])
}

function selectCategory(value: string): void {
  if (category.value === value) return
  category.value = value
  todoType.value = ''
  page.value = 1
  void loadList()
}

function handleTypeChange(value: string): void {
  todoType.value = value || ''
  page.value = 1
  void loadList()
}

function toggleSort(): void {
  sort.value = sort.value === 'desc' ? 'asc' : 'desc'
  page.value = 1
  void loadList()
}

function handlePageChange(next: number): void {
  if (next === page.value) return
  page.value = next
  void loadList()
}

function openItem(item: TodoItem): void {
  void router.push(item.link)
}

onMounted(() => {
  void store.start()
  void loadList()
})
</script>

<template>
  <div class="page todo-page">
    <header class="page-header">
      <div>
        <p class="page-eyebrow">MY WORK QUEUE</p>
        <h1 class="page-title">我的待办</h1>
        <p class="page-subtitle">
          审批、确认、处理、我发起的单据与借用到期统一汇总，处理完成后自动消失
        </p>
      </div>
      <div class="head-actions">
        <div class="total-chip">
          <span class="total-icon"><el-icon><Finished /></el-icon></span>
          <div class="total-copy">
            <strong>{{ store.total }}</strong>
            <span>项未完成</span>
          </div>
        </div>
        <el-button :icon="Refresh" :loading="loading || store.loading" @click="refreshAll">
          刷新
        </el-button>
      </div>
    </header>

    <section class="category-strip">
      <button
        v-for="tab in categoryTabs"
        :key="tab.value || 'all'"
        type="button"
        class="category-chip"
        :class="[`tone-${tab.tone}`, { active: category === tab.value }]"
        @click="selectCategory(tab.value)"
      >
        <span class="chip-label">{{ tab.label }}</span>
        <span class="chip-count">{{ tab.count }}</span>
      </button>
    </section>

    <section class="todo-toolbar surface-card">
      <div class="toolbar-left">
        <el-select
          :model-value="todoType"
          class="type-select"
          placeholder="全部类型"
          clearable
          @update:model-value="handleTypeChange"
        >
          <el-option
            v-for="option in typeOptions"
            :key="option.todo_type"
            :label="`${option.label}（${option.count}）`"
            :value="option.todo_type"
          />
        </el-select>
        <span class="toolbar-hint">
          当前筛选 <strong>{{ total }}</strong> 项
          <template v-if="category || todoType"> · 共 {{ store.total }} 项未完成</template>
        </span>
      </div>
      <el-button text :icon="sort === 'desc' ? SortDown : SortUp" @click="toggleSort">
        {{ sort === 'desc' ? '最新在前' : '最早在前' }}
      </el-button>
    </section>

    <section v-loading="loading" class="todo-list">
      <button
        v-for="item in items"
        :key="item.key"
        type="button"
        class="todo-row surface-card"
        @click="openItem(item)"
      >
        <span class="type-badge" :class="`tone-${toneOf(item.category)}`">
          {{ item.todo_type_label }}
        </span>

        <span class="row-main">
          <span class="row-top">
            <strong class="row-title">{{ item.title }}</strong>
            <el-tag :type="statusTag(item.status)" size="small" effect="light" round>
              {{ item.status_label }}
            </el-tag>
            <span
              v-if="showDue(item)"
              class="due-flag"
              :class="{ overdue: item.is_overdue }"
            >
              {{ dueText(item) }}
            </span>
          </span>
          <span class="row-meta">
            <span class="doc-no">{{ item.doc_no }}</span>
            <span v-if="item.subtitle" class="meta-item">{{ item.subtitle }}</span>
            <span v-if="item.related_name" class="meta-item">
              相关人：{{ item.related_name }}
            </span>
            <span v-if="item.dept_name" class="meta-item">{{ item.dept_name }}</span>
          </span>
        </span>

        <span class="row-side">
          <span class="row-category">{{ item.category_label }}</span>
          <span class="row-time">{{ formatDateTime(item.occurred_at) }}</span>
          <el-icon class="row-arrow"><ArrowRight /></el-icon>
        </span>
      </button>

      <div v-if="!loading && loadedOnce && !items.length" class="todo-empty surface-card">
        <el-empty :image-size="76" :description="hasFilter ? '当前筛选下暂无待办' : '暂无未完成事项'">
          <template #image>
            <span class="empty-badge"><el-icon><CircleCheck /></el-icon></span>
          </template>
          <p class="empty-tip">
            {{ hasFilter ? '试试切换分类或清除类型筛选' : '所有事项都已处理完成，保持这个节奏' }}
          </p>
        </el-empty>
      </div>

      <div v-if="total > pageSize" class="todo-pagination">
        <el-pagination
          layout="prev, pager, next"
          :total="total"
          :page-size="pageSize"
          :current-page="page"
          :pager-count="7"
          background
          @current-change="handlePageChange"
        />
        <span class="pagination-hint">第 {{ page }} / {{ maxPage }} 页</span>
      </div>
    </section>
  </div>
</template>

<style scoped>
.todo-page {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.head-actions {
  display: flex;
  align-items: center;
  gap: 14px;
}

.total-chip {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 16px 8px 10px;
  border: 1px solid var(--border);
  border-radius: 14px;
  background: var(--surface);
  box-shadow: var(--shadow-sm);
}

.total-icon {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  border-radius: 11px;
  background: var(--gradient-brand);
  color: var(--on-brand);
}

.total-copy {
  display: flex;
  align-items: baseline;
  gap: 6px;
}

.total-copy strong {
  color: var(--text-1);
  font-size: 20px;
  font-weight: 700;
  letter-spacing: -0.02em;
}

.total-copy span {
  color: var(--text-3);
  font-size: 11.5px;
}

.category-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.category-chip {
  display: inline-flex;
  align-items: center;
  gap: 9px;
  padding: 9px 14px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--surface);
  color: var(--text-2);
  font: inherit;
  font-size: 12.8px;
  cursor: pointer;
  transition: border-color 0.18s ease, color 0.18s ease, background-color 0.18s ease,
    transform 0.18s ease;
}

.category-chip:hover {
  transform: translateY(-1px);
  border-color: var(--border-strong);
}

.category-chip.active {
  border-color: var(--brand);
  color: var(--brand);
  background: var(--gradient-brand-soft);
  box-shadow: 0 10px 24px -18px var(--brand-glow);
}

.chip-count {
  min-width: 22px;
  padding: 1px 7px;
  border-radius: 999px;
  background: var(--surface-muted);
  color: var(--text-2);
  font-size: 11px;
  font-weight: 700;
  text-align: center;
}

.category-chip.active .chip-count {
  background: var(--brand);
  color: var(--on-brand);
}

.category-chip.tone-cyan.active {
  border-color: #0891b2;
  color: #0891b2;
  background: rgba(6, 182, 212, 0.1);
}

.category-chip.tone-cyan.active .chip-count {
  background: #0891b2;
}

.category-chip.tone-violet.active {
  border-color: #7c3aed;
  color: #7c3aed;
  background: rgba(124, 58, 237, 0.09);
}

.category-chip.tone-violet.active .chip-count {
  background: #7c3aed;
}

.category-chip.tone-amber.active {
  border-color: #d97706;
  color: #b45309;
  background: rgba(245, 158, 11, 0.12);
}

.category-chip.tone-amber.active .chip-count {
  background: #d97706;
}

.category-chip.tone-rose.active {
  border-color: #e11d48;
  color: #e11d48;
  background: rgba(225, 29, 72, 0.08);
}

.category-chip.tone-rose.active .chip-count {
  background: #e11d48;
}

.todo-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 12px 16px;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 14px;
  min-width: 0;
}

.type-select {
  width: 220px;
}

.toolbar-hint {
  color: var(--text-3);
  font-size: 12px;
}

.toolbar-hint strong {
  color: var(--text-1);
}

.todo-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 220px;
}

.todo-row {
  display: flex;
  align-items: center;
  gap: 16px;
  width: 100%;
  padding: 14px 18px;
  text-align: left;
  font: inherit;
  cursor: pointer;
  transition: transform 0.18s ease, border-color 0.18s ease, box-shadow 0.18s ease;
}

.todo-row:hover {
  transform: translateY(-2px);
  border-color: var(--brand);
  box-shadow: var(--shadow-md);
}

.type-badge {
  flex-shrink: 0;
  min-width: 96px;
  padding: 7px 10px;
  border-radius: 10px;
  font-size: 11.8px;
  font-weight: 650;
  text-align: center;
}

.type-badge.tone-blue {
  background: var(--brand-soft);
  color: var(--brand);
}

.type-badge.tone-cyan {
  background: rgba(6, 182, 212, 0.12);
  color: #0891b2;
}

.type-badge.tone-violet {
  background: rgba(124, 58, 237, 0.1);
  color: #7c3aed;
}

.type-badge.tone-amber {
  background: rgba(245, 158, 11, 0.13);
  color: #b45309;
}

.type-badge.tone-rose {
  background: rgba(225, 29, 72, 0.09);
  color: #e11d48;
}

.row-main {
  display: flex;
  flex-direction: column;
  gap: 5px;
  flex: 1;
  min-width: 0;
}

.row-top {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.row-title {
  color: var(--text-1);
  font-size: 13.5px;
  font-weight: 600;
  line-height: 1.45;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
}

.due-flag {
  padding: 1px 7px;
  border-radius: 999px;
  background: rgba(245, 158, 11, 0.14);
  color: #b45309;
  font-size: 10.8px;
  font-weight: 600;
}

.due-flag.overdue {
  background: rgba(239, 68, 68, 0.12);
  color: #dc2626;
}

.row-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 14px;
  color: var(--text-3);
  font-size: 11.8px;
}

.doc-no {
  color: var(--text-2);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 11.5px;
}

.meta-item {
  position: relative;
}

.meta-item::before {
  content: '';
  position: absolute;
  left: -8px;
  top: 50%;
  width: 3px;
  height: 3px;
  border-radius: 50%;
  background: var(--border-strong);
  transform: translateY(-50%);
}

.row-side {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-shrink: 0;
}

.row-category {
  padding: 2px 9px;
  border-radius: 999px;
  background: var(--surface-muted);
  color: var(--text-3);
  font-size: 10.8px;
}

.row-time {
  color: var(--text-3);
  font-size: 11.5px;
  font-variant-numeric: tabular-nums;
}

.row-arrow {
  color: var(--text-3);
  transition: color 0.18s ease, transform 0.18s ease;
}

.todo-row:hover .row-arrow {
  color: var(--brand);
  transform: translateX(2px);
}

.todo-empty {
  padding: 30px 16px;
}

.empty-badge {
  display: grid;
  place-items: center;
  width: 64px;
  height: 64px;
  margin: 0 auto;
  border-radius: 20px;
  background: var(--gradient-brand-soft);
  color: var(--brand);
}

.empty-badge .el-icon {
  font-size: 30px;
}

.empty-tip {
  margin: 4px 0 0;
  color: var(--text-3);
  font-size: 12px;
}

.todo-pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 14px;
  padding: 10px 0 4px;
}

.pagination-hint {
  color: var(--text-3);
  font-size: 11.5px;
}

@media (max-width: 960px) {
  .page-header {
    flex-direction: column;
    align-items: flex-start;
  }

  .todo-row {
    flex-wrap: wrap;
    gap: 10px;
  }

  .row-side {
    width: 100%;
    justify-content: flex-end;
  }

  .type-select {
    width: 170px;
  }

  .toolbar-left {
    flex-wrap: wrap;
    gap: 8px;
  }
}
</style>
