<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowLeft, HomeFilled } from '@element-plus/icons-vue'

import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()

const homePath = computed(() => (auth.isAuthenticated ? '/dashboard' : '/login'))
const homeLabel = computed(() => (auth.isAuthenticated ? '返回工作台' : '前往登录'))

function goHome(): void {
  void router.replace(homePath.value)
}
</script>

<template>
  <div class="notfound-screen">
    <div class="nf-grid" aria-hidden="true" />
    <div class="nf-glow nf-glow-a" aria-hidden="true" />
    <div class="nf-glow nf-glow-b" aria-hidden="true" />

    <div class="notfound-content">
      <div class="nf-brand">
        <div class="brand-mark">IT</div>
        <div>
          <span class="brand-name">ITAM</span>
          <span class="brand-sub">IT ASSET CONTROL</span>
        </div>
      </div>

      <p class="nf-eyebrow">PAGE NOT FOUND</p>
      <h1 class="nf-code">404</h1>
      <h2 class="nf-title">页面不存在或已被移动</h2>
      <p class="nf-desc">
        你访问的地址没有对应的页面。请检查链接是否完整，或返回工作台继续操作。
      </p>

      <div class="nf-actions">
        <el-button type="primary" size="large" :icon="HomeFilled" @click="goHome">
          {{ homeLabel }}
        </el-button>
        <el-button size="large" :icon="ArrowLeft" @click="router.back()">返回上一页</el-button>
      </div>

      <p class="nf-foot">ITAM · IT 资产管理系统 <span>v0.1.0</span></p>
    </div>
  </div>
</template>

<style scoped>
.notfound-screen {
  position: relative;
  display: grid;
  place-items: center;
  min-height: 100vh;
  overflow: hidden;
  padding: 40px 20px;
  background:
    radial-gradient(800px 420px at 80% 0%, color-mix(in srgb, var(--brand) 22%, transparent), transparent 62%),
    radial-gradient(700px 460px at 10% 100%, color-mix(in srgb, var(--brand-cyan) 14%, transparent), transparent 60%),
    #070f1d;
}

.nf-grid {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(148, 178, 224, 0.05) 1px, transparent 1px),
    linear-gradient(90deg, rgba(148, 178, 224, 0.05) 1px, transparent 1px);
  background-size: 52px 52px;
  mask-image: radial-gradient(ellipse 60% 60% at 50% 40%, #000 20%, transparent 75%);
  pointer-events: none;
}

.nf-glow {
  position: absolute;
  border-radius: 50%;
  filter: blur(90px);
  pointer-events: none;
}

.nf-glow-a {
  width: 380px;
  height: 380px;
  top: -140px;
  left: 16%;
  background: color-mix(in srgb, var(--brand) 28%, transparent);
}

.nf-glow-b {
  width: 320px;
  height: 320px;
  bottom: -140px;
  right: 12%;
  background: color-mix(in srgb, var(--brand-cyan) 18%, transparent);
}

.notfound-content {
  position: relative;
  z-index: 2;
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 100%;
  max-width: 560px;
  text-align: center;
}

.nf-brand {
  display: flex;
  align-items: center;
  gap: 11px;
  margin-bottom: 40px;
}

.brand-mark {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  border-radius: 12px;
  background: var(--gradient-brand);
  color: var(--on-brand);
  font-family: var(--font-number);
  font-size: 15px;
  font-weight: 800;
  letter-spacing: -0.06em;
  box-shadow: 0 14px 30px -12px var(--brand-glow);
}

.nf-brand > div:last-child {
  display: flex;
  flex-direction: column;
  text-align: left;
  line-height: 1.2;
}

.brand-name {
  color: #f5f8ff;
  font-size: 16px;
  font-weight: 700;
  letter-spacing: 0.04em;
}

.brand-sub {
  margin-top: 3px;
  color: #6f83a0;
  font-size: 9.5px;
  letter-spacing: 0.18em;
}

.nf-eyebrow {
  color: var(--hero-accent);
  font-size: 10.5px;
  font-weight: 700;
  letter-spacing: 0.24em;
}

.nf-code {
  margin: 2px 0 -6px;
  background: linear-gradient(120deg, color-mix(in srgb, var(--brand) 30%, #ffffff) 0%, var(--hero-accent) 45%, var(--brand-cyan) 100%);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  font-family: var(--font-number);
  font-size: clamp(108px, 18vw, 168px);
  font-weight: 800;
  line-height: 1;
  letter-spacing: -0.07em;
  filter: drop-shadow(0 24px 44px var(--hero-glow-b));
}

.nf-title {
  margin: 18px 0 10px;
  color: #f2f7ff;
  font-size: 24px;
  font-weight: 650;
  letter-spacing: -0.02em;
}

.nf-desc {
  max-width: 400px;
  color: #8ba0bd;
  font-size: 13.5px;
  line-height: 1.75;
}

.nf-actions {
  display: flex;
  gap: 10px;
  margin-top: 28px;
}

.nf-actions :deep(.el-button:not(.el-button--primary)) {
  border-color: rgba(150, 180, 225, 0.22);
  background: rgba(255, 255, 255, 0.05);
  color: #d7e4f7;
}

.nf-actions :deep(.el-button:not(.el-button--primary):hover) {
  border-color: rgba(150, 180, 225, 0.4);
  background: rgba(255, 255, 255, 0.1);
  color: #fff;
}

.nf-foot {
  margin-top: 44px;
  color: #526883;
  font-size: 11px;
}

.nf-foot span {
  color: #7f95b2;
}

@media (max-width: 520px) {
  .nf-actions {
    flex-direction: column;
    width: 100%;
  }

  .nf-actions :deep(.el-button) {
    width: 100%;
    margin-left: 0;
  }
}
</style>
