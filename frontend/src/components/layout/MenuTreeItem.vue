<script setup lang="ts">
import { computed } from 'vue'

import { useTodoStore } from '@/stores/todo'
import type { MenuNode } from '@/types/api'
import { resolveMenuIcon } from '@/utils/icons'

const props = defineProps<{ item: MenuNode }>()

const todoStore = useTodoStore()
const icon = computed(() => resolveMenuIcon(props.item.icon))
const hasChildren = computed(() => props.item.type === 'DIR' || (props.item.children?.length ?? 0) > 0)
const isTodoEntry = computed(() => props.item.path === '/todos')
const showTodoBadge = computed(() => isTodoEntry.value && todoStore.total > 0)
const todoBadgeText = computed(() => (todoStore.total > 99 ? '99+' : String(todoStore.total)))
</script>

<template>
  <el-sub-menu v-if="hasChildren" :index="`dir-${item.id}`">
    <template #title>
      <el-icon><component :is="icon" /></el-icon>
      <span>{{ item.name }}</span>
    </template>
    <MenuTreeItem v-for="child in item.children" :key="child.id" :item="child" />
  </el-sub-menu>
  <el-menu-item v-else-if="item.path" :index="item.path" :class="{ 'todo-entry': isTodoEntry }">
    <el-icon><component :is="icon" /></el-icon>
    <template #title>
      <span class="menu-item-title">{{ item.name }}</span>
      <span v-if="showTodoBadge" class="sidebar-todo-badge">{{ todoBadgeText }}</span>
    </template>
    <span v-if="showTodoBadge" class="sidebar-todo-badge sidebar-todo-badge-float">
      {{ todoBadgeText }}
    </span>
  </el-menu-item>
</template>

<style scoped>
.menu-item-title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sidebar-todo-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  margin-left: auto;
  border-radius: 999px;
  background: var(--brand);
  color: var(--on-brand);
  font-size: 10.5px;
  font-weight: 700;
  line-height: 1;
  flex-shrink: 0;
}

.sidebar-todo-badge-float {
  display: none;
}

.todo-entry {
  position: relative;
}

:global(.el-menu--collapse) .sidebar-todo-badge-float {
  position: absolute;
  top: 4px;
  right: 6px;
  display: inline-flex;
  margin-left: 0;
}

:global(.el-menu--collapse) .sidebar-todo-badge:not(.sidebar-todo-badge-float) {
  display: none;
}
</style>
