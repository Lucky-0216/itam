<script setup lang="ts">
import { useRouter } from 'vue-router'
import { ArrowLeft, Lock, SwitchButton } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const auth = useAuthStore()

function goHome(): void {
  void router.replace('/dashboard')
}

async function switchAccount(): Promise<void> {
  await auth.logout()
  ElMessage.success('已退出当前账号')
  void router.replace('/login')
}
</script>

<template>
  <div class="page forbidden-page">
    <section class="surface-card forbidden-card">
      <div class="forbidden-visual" aria-hidden="true">
        <span class="code-shadow">403</span>
        <span class="code-foreground">403</span>
        <span class="lock-badge"><el-icon><Lock /></el-icon></span>
      </div>

      <p class="forbidden-eyebrow">ACCESS DENIED</p>
      <h1>没有访问该页面的权限</h1>
      <p class="forbidden-desc">
        当前账号缺少访问此页面所需的操作权限。你可以返回工作台，或联系管理员为你的角色补充授权。
      </p>

      <div class="forbidden-actions">
        <el-button type="primary" :icon="ArrowLeft" @click="goHome">返回工作台</el-button>
        <el-button :icon="SwitchButton" @click="switchAccount">切换账号</el-button>
      </div>

      <p class="forbidden-foot">
        权限由后端接口层与查询层双重校验，前端菜单仅作为展示过滤。
      </p>
    </section>
  </div>
</template>

<style scoped>
.forbidden-page {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: calc(100vh - var(--header-height) - 90px);
  padding: 20px 0;
}

.forbidden-card {
  width: 100%;
  max-width: 620px;
  padding: 44px 46px 36px;
  text-align: center;
}

.forbidden-visual {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 230px;
  height: 120px;
  margin-bottom: 8px;
}

.code-shadow,
.code-foreground {
  font-family: var(--font-number);
  font-size: 108px;
  font-weight: 800;
  letter-spacing: -0.06em;
  line-height: 1;
}

.code-shadow {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  color: var(--surface-muted);
  transform: translate(5px, 5px);
}

.code-foreground {
  position: relative;
  background: linear-gradient(120deg, color-mix(in srgb, var(--brand) 45%, #ffffff), var(--brand) 45%, var(--brand-cyan));
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}

.lock-badge {
  position: absolute;
  right: 14px;
  bottom: 6px;
  display: grid;
  place-items: center;
  width: 46px;
  height: 46px;
  border: 3px solid var(--surface);
  border-radius: 50%;
  background: var(--gradient-brand);
  color: var(--on-brand);
  box-shadow: 0 14px 30px -12px var(--brand-glow);
}

.lock-badge .el-icon {
  font-size: 20px;
}

.forbidden-eyebrow {
  color: var(--brand);
  font-size: 10.5px;
  font-weight: 700;
  letter-spacing: 0.22em;
}

.forbidden-card h1 {
  margin: 10px 0 10px;
  color: var(--text-1);
  font-size: 25px;
  font-weight: 700;
  letter-spacing: -0.025em;
}

.forbidden-desc {
  max-width: 440px;
  margin: 0 auto;
  color: var(--text-2);
  font-size: 13px;
  line-height: 1.75;
}

.forbidden-actions {
  display: flex;
  justify-content: center;
  gap: 10px;
  margin-top: 26px;
}

.forbidden-foot {
  margin-top: 26px;
  padding-top: 18px;
  border-top: 1px dashed var(--border);
  color: var(--text-3);
  font-size: 11px;
}

@media (max-width: 640px) {
  .forbidden-card {
    padding: 34px 22px 28px;
  }

  .forbidden-visual {
    width: 190px;
    height: 100px;
  }

  .code-shadow,
  .code-foreground {
    font-size: 84px;
  }

  .forbidden-actions {
    flex-direction: column;
  }

  .forbidden-actions :deep(.el-button) {
    width: 100%;
    margin-left: 0;
  }
}
</style>
