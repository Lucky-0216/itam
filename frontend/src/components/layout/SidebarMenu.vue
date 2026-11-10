<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import MenuTreeItem from './MenuTreeItem.vue'
import { useAuthStore } from '@/stores/auth'
import type { MenuNode } from '@/types/api'

defineProps<{ collapsed: boolean }>()

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

function normalizeMenus(nodes: MenuNode[]): MenuNode[] {
  return nodes
    .filter((node) => node.type !== 'BUTTON')
    .map((node) => ({ ...node, children: normalizeMenus(node.children ?? []) }))
    .filter((node) => node.type === 'MENU' || node.children.length > 0)
}

function flatten(nodes: MenuNode[]): MenuNode[] {
  return nodes.flatMap((node) => [node, ...flatten(node.children ?? [])])
}

const navMenus = computed(() => normalizeMenus(auth.menus))

const activePath = computed(() => {
  const candidates = flatten(navMenus.value).filter(
    (node) =>
      node.type === 'MENU' &&
      Boolean(node.path) &&
      (route.path === node.path || route.path.startsWith(`${node.path}/`)),
  )
  candidates.sort((a, b) => (b.path?.length ?? 0) - (a.path?.length ?? 0))
  return candidates[0]?.path ?? route.path
})

function handleSelect(index: string): void {
  if (!index.startsWith('/') || index === route.path) return
  void router.push(index)
}
</script>

<template>
  <el-scrollbar class="sidebar-menu-wrap">
    <el-menu
      :default-active="activePath"
      :collapse="collapsed"
      :collapse-transition="false"
      unique-opened
      class="sidebar-menu"
      @select="handleSelect"
    >
      <MenuTreeItem v-for="item in navMenus" :key="item.id" :item="item" />
    </el-menu>
    <div v-if="!navMenus.length" class="sidebar-empty">
      <span>暂无可用菜单</span>
      <small>请联系管理员分配角色权限</small>
    </div>
  </el-scrollbar>
</template>

<style scoped>
.sidebar-menu-wrap {
  flex: 1;
  min-height: 0;
}

:deep(.el-scrollbar__wrap) {
  overflow-x: hidden;
}

.sidebar-empty {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 26px 18px;
  color: var(--sidebar-status);
  font-size: 12.5px;
  text-align: center;
}

.sidebar-empty small {
  color: var(--sidebar-brand-sub);
  font-size: 11px;
}

:deep(.el-menu--collapse) {
  width: 100%;
}
</style>
