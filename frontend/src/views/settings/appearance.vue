<script setup lang="ts">
import { computed } from 'vue'
import { Check, RefreshLeft } from '@element-plus/icons-vue'

import { useAppStore, type ThemePrimary } from '@/stores/app'

const appStore = useAppStore()

const modes: {
  value: 'light' | 'dark'
  label: string
  hint: string
  bg: string
  surface: string
}[] = [
  { value: 'light', label: '舒适白', hint: '默认 · 微冷灰底 + 近白表面', bg: '#f5f6f8', surface: '#fcfcfd' },
  { value: 'dark', label: '深色', hint: '中性深色 · 低光环境', bg: '#0e1218', surface: '#161c25' },
]

const primaries: {
  value: ThemePrimary
  label: string
  hint: string
  hex: string
  swatch: string
}[] = [
  { value: 'blue', label: '雾蓝', hint: '沉静 · 默认', hex: '#4A6DA8', swatch: 'linear-gradient(120deg, #47679d, #5b82b6)' },
  { value: 'teal', label: '青瓷', hint: '松绿 · 温和', hex: '#4C8078', swatch: 'linear-gradient(120deg, #3f6f68, #5d968c)' },
  { value: 'violet', label: '黛紫', hint: '雅致 · 克制', hex: '#6A5A99', swatch: 'linear-gradient(120deg, #57497f, #7b6aa9)' },
  { value: 'white', label: '纯白', hint: '单色 · 极简', hex: '#FFFFFF', swatch: 'linear-gradient(120deg, #ffffff, #e9edf3)' },
]

const currentPrimary = computed(
  () => primaries.find((item) => item.value === appStore.primary) ?? primaries[0],
)

function resetAppearance(): void {
  appStore.resetTheme()
}
</script>

<template>
  <div class="page appearance-page">
    <header class="page-header">
      <div>
        <p class="page-eyebrow">APPEARANCE</p>
        <h1 class="page-title">外观设置</h1>
        <p class="page-subtitle">
          以舒适白为默认基底，主色单独配置。设置仅保存在当前浏览器，切换后立即生效，不影响权限与业务数据。
        </p>
      </div>
      <div class="page-actions">
        <el-button :icon="RefreshLeft" @click="resetAppearance">恢复默认</el-button>
      </div>
    </header>

    <section class="card">
      <div class="card-head">
        <h2>外观模式</h2>
        <p>默认舒适白：背景为轻微冷灰，表面为近白而非纯白，文字与边框柔和可辨。</p>
      </div>
      <div class="choice-grid">
        <button
          v-for="item in modes"
          :key="item.value"
          type="button"
          class="choice"
          :class="{ active: appStore.theme === item.value }"
          @click="appStore.setTheme(item.value)"
        >
          <span class="mode-chip" :style="{ background: item.bg }">
            <span class="mode-surface" :style="{ background: item.surface }" />
          </span>
          <span class="choice-copy">
            <strong>{{ item.label }}</strong>
            <small>{{ item.hint }}</small>
          </span>
          <el-icon v-if="appStore.theme === item.value" class="choice-check"><Check /></el-icon>
        </button>
      </div>
    </section>

    <section class="card">
      <div class="card-head">
        <h2>主色</h2>
        <p>
          主色用于主按钮、链接、选中态与高亮，不改变页面底色。「纯白」在亮色下以白瓷面 + 墨色字呈现，保证可读。
        </p>
      </div>
      <div class="primary-grid">
        <button
          v-for="item in primaries"
          :key="item.value"
          type="button"
          class="primary-item"
          :class="{ active: appStore.primary === item.value }"
          @click="appStore.setPrimary(item.value)"
        >
          <span class="primary-swatch" :style="{ background: item.swatch }">
            <el-icon v-if="appStore.primary === item.value"><Check /></el-icon>
          </span>
          <span class="primary-copy">
            <strong>{{ item.label }}</strong>
            <small>{{ item.hint }}</small>
            <code>{{ item.hex }}</code>
          </span>
        </button>
      </div>
    </section>

    <section class="card">
      <div class="card-head">
        <h2>实时预览</h2>
        <p>当前：{{ appStore.isDark ? '深色' : '舒适白' }} · 主色「{{ currentPrimary.label }}」。</p>
      </div>
      <div class="preview">
        <div class="preview-bar">
          <span class="preview-dot" />
          <span class="preview-dot" />
          <span class="preview-dot" />
          <span class="preview-title">资产台账</span>
        </div>
        <div class="preview-body">
          <aside class="preview-nav">
            <span class="preview-nav-item">工作台</span>
            <span class="preview-nav-item active">资产台账</span>
            <span class="preview-nav-item">领用申请</span>
            <span class="preview-nav-item">盘点任务</span>
          </aside>
          <div class="preview-main">
            <div class="preview-toolbar">
              <el-button type="primary" size="small">新建资产</el-button>
              <el-button size="small">导出</el-button>
              <el-tag effect="light" size="small" round>在用</el-tag>
              <span class="preview-link">查看详情</span>
            </div>
            <div class="preview-table">
              <div class="preview-row head">
                <span>资产编号</span>
                <span>资产名称</span>
                <span>状态</span>
              </div>
              <div class="preview-row">
                <span>IT-2026-0001</span>
                <span>ThinkPad X1 Carbon</span>
                <span class="preview-status">在用</span>
              </div>
              <div class="preview-row">
                <span>IT-2026-0002</span>
                <span>Dell U2723QE</span>
                <span class="preview-status muted">闲置</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <p class="footnote">
      系统默认：舒适白 + 雾蓝；你的选择会覆盖默认值并在刷新后保持。恢复默认会同时回到舒适白与雾蓝。
    </p>
  </div>
</template>

<style scoped>
.appearance-page {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.card {
  padding: 20px 22px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--surface);
  box-shadow: var(--shadow-sm);
}

.card-head {
  margin-bottom: 16px;
}

.card-head h2 {
  margin: 0 0 4px;
  color: var(--text-1);
  font-size: 15px;
  font-weight: 650;
}

.card-head p {
  margin: 0;
  color: var(--text-3);
  font-size: 12.5px;
}

.choice-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.choice {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface-muted);
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.18s ease, background-color 0.18s ease;
}

.choice:hover {
  border-color: var(--border-strong);
}

.choice.active {
  border-color: var(--brand);
  background: var(--brand-soft);
}

.mode-chip {
  position: relative;
  width: 64px;
  height: 40px;
  flex-shrink: 0;
  border-radius: 8px;
  box-shadow: inset 0 0 0 1px rgba(15, 23, 42, 0.12);
  overflow: hidden;
}

.mode-surface {
  position: absolute;
  inset: 8px 10px 8px 22px;
  border-radius: 5px;
  box-shadow: 0 2px 8px -4px rgba(15, 23, 42, 0.4);
}

.choice-copy {
  display: flex;
  flex-direction: column;
  gap: 2px;
  line-height: 1.35;
}

.choice-copy strong {
  color: var(--text-1);
  font-size: 13px;
  font-weight: 600;
}

.choice-copy small {
  color: var(--text-3);
  font-size: 11.5px;
}

.choice-check {
  margin-left: auto;
  color: var(--brand);
  font-size: 15px;
}

.primary-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
}

.primary-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface-muted);
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.18s ease, background-color 0.18s ease;
}

.primary-item:hover {
  border-color: var(--border-strong);
}

.primary-item.active {
  border-color: var(--brand);
  background: var(--brand-soft);
}

.primary-swatch {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  flex-shrink: 0;
  border-radius: 10px;
  color: var(--on-brand);
  font-size: 15px;
  box-shadow: inset 0 0 0 1px rgba(15, 23, 42, 0.16);
}

.primary-copy {
  display: flex;
  flex-direction: column;
  gap: 1px;
  line-height: 1.35;
}

.primary-copy strong {
  color: var(--text-1);
  font-size: 13px;
  font-weight: 600;
}

.primary-copy small {
  color: var(--text-3);
  font-size: 11.5px;
}

.primary-copy code {
  color: var(--text-3);
  font-family: var(--font-number);
  font-size: 10.5px;
  letter-spacing: 0.04em;
}

.preview {
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--page-bg);
  overflow: hidden;
}

.preview-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 9px 14px;
  border-bottom: 1px solid var(--border);
  background: var(--surface);
}

.preview-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--border-strong);
}

.preview-title {
  margin-left: 8px;
  color: var(--text-3);
  font-size: 11.5px;
  font-weight: 600;
  letter-spacing: 0.04em;
}

.preview-body {
  display: grid;
  grid-template-columns: 168px minmax(0, 1fr);
  min-height: 210px;
}

.preview-nav {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 12px 10px;
  background: var(--sidebar-bg);
}

.preview-nav-item {
  padding: 7px 10px;
  border-radius: 8px;
  color: var(--sidebar-text);
  font-size: 11.5px;
}

.preview-nav-item.active {
  background: var(--sidebar-active-bg);
  color: var(--sidebar-active-text);
  box-shadow: var(--sidebar-active-shadow);
}

.preview-main {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px 18px;
}

.preview-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.preview-link {
  margin-left: auto;
  color: var(--brand);
  font-size: 12px;
  font-weight: 600;
}

.preview-table {
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--surface);
  overflow: hidden;
}

.preview-row {
  display: grid;
  grid-template-columns: 1.1fr 1.6fr 0.6fr;
  gap: 10px;
  padding: 8px 14px;
  border-top: 1px solid var(--border);
  color: var(--text-2);
  font-size: 11.5px;
}

.preview-row:first-child {
  border-top: 0;
}

.preview-row.head {
  background: var(--surface-muted);
  color: var(--text-3);
  font-weight: 600;
}

.preview-status {
  color: var(--brand);
  font-weight: 600;
}

.preview-status.muted {
  color: var(--text-3);
  font-weight: 500;
}

.footnote {
  margin: 0;
  color: var(--text-3);
  font-size: 12px;
}

@media (max-width: 900px) {
  .primary-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .choice-grid {
    grid-template-columns: 1fr;
  }

  .preview-body {
    grid-template-columns: 1fr;
  }

  .preview-nav {
    flex-direction: row;
    flex-wrap: wrap;
  }
}
</style>
