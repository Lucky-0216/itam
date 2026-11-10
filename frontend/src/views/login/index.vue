<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { Lock, User } from '@element-plus/icons-vue'

import { useAuthStore } from '@/stores/auth'
import { useBrandingStore } from '@/stores/branding'
import type { LoginPayload } from '@/types/api'

const REMEMBER_KEY = 'itam_remember_username'

const auth = useAuthStore()
const brandingStore = useBrandingStore()
const branding = computed(() => brandingStore.branding)
const router = useRouter()
const route = useRoute()

const formRef = ref<FormInstance>()
const loading = ref(false)
const remember = ref(true)
const form = reactive<LoginPayload>({ username: '', password: '' })
const year = new Date().getFullYear()

const rules: FormRules<LoginPayload> = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

onMounted(() => {
  void brandingStore.load()
  const saved = localStorage.getItem(REMEMBER_KEY)
  if (saved) {
    form.username = saved
    remember.value = true
  }
})

function redirectTarget(): string {
  const value = route.query.redirect
  const target = (typeof value === 'string' ? value : '/dashboard').split('#')[0]
  if (!target.startsWith('/') || target.startsWith('//')) return '/dashboard'
  const resolved = router.resolve(target)
  return resolved.matched.length ? resolved.fullPath : '/dashboard'
}

async function handleSubmit(): Promise<void> {
  if (!formRef.value || loading.value) return
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return

  loading.value = true
  try {
    const username = form.username.trim()
    const result = await auth.login({ username, password: form.password })
    if (remember.value) {
      localStorage.setItem(REMEMBER_KEY, username)
    } else {
      localStorage.removeItem(REMEMBER_KEY)
    }
    ElMessage.success(`欢迎回来，${result.user.real_name}`)
    const destination = result.must_change_password ? '/change-password' : redirectTarget()
    await router.replace(destination)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-screen" :class="{ 'has-bg': !!branding.background_url }">
    <div class="login-decor" aria-hidden="true">
      <div
        v-if="branding.background_url"
        class="login-bg"
        :style="{ backgroundImage: `url(${branding.background_url})` }"
      />
      <div class="login-glow glow-a" />
      <div class="login-glow glow-b" />
    </div>

    <main class="login-stage">
      <section class="login-card" aria-labelledby="login-brand-name">
        <header class="login-brand">
          <img v-if="branding.logo_url" :src="branding.logo_url" alt="Logo" class="brand-logo" />
          <span v-else class="brand-mark">{{ branding.brand_mark_text }}</span>
          <h1 id="login-brand-name" class="brand-name">{{ branding.site_name }}</h1>
          <p v-if="branding.site_subtitle" class="brand-sub">{{ branding.site_subtitle }}</p>
        </header>

        <p class="login-hint">使用本地账号或域账号（AD / LDAP）登录</p>

        <el-form
          ref="formRef"
          :model="form"
          :rules="rules"
          size="large"
          class="login-form"
          @submit.prevent="handleSubmit"
        >
          <el-form-item prop="username">
            <el-input
              v-model="form.username"
              :prefix-icon="User"
              placeholder="用户名"
              autocomplete="username"
              clearable
            />
          </el-form-item>
          <el-form-item prop="password">
            <el-input
              v-model="form.password"
              :prefix-icon="Lock"
              type="password"
              placeholder="密码"
              autocomplete="current-password"
              show-password
              @keyup.enter="handleSubmit"
            />
          </el-form-item>

          <div class="login-options">
            <el-checkbox v-model="remember">记住用户名</el-checkbox>
          </div>

          <el-button class="login-submit" type="primary" :loading="loading" @click="handleSubmit">
            {{ loading ? '正在登录' : '登录' }}
          </el-button>
        </el-form>
      </section>

      <footer class="login-footer">
        {{ branding.login_footer_text || branding.site_name }}
        <span class="footer-sep">·</span>
        © {{ year }}
      </footer>
    </main>
  </div>
</template>

<style scoped>
.login-screen {
  position: relative;
  display: grid;
  place-items: center;
  min-height: 100vh;
  padding: 40px 16px;
  overflow: auto;
  background:
    radial-gradient(900px 520px at 18% 10%, color-mix(in srgb, var(--brand) 26%, transparent), transparent 62%),
    radial-gradient(760px 480px at 84% 90%, color-mix(in srgb, var(--brand-cyan) 16%, transparent), transparent 60%),
    #060f1e;
}

.login-decor {
  position: absolute;
  inset: 0;
  overflow: hidden;
  pointer-events: none;
}

.login-bg {
  position: absolute;
  inset: 0;
  background-position: center;
  background-size: cover;
}

.login-bg::after {
  content: '';
  position: absolute;
  inset: 0;
  background:
    radial-gradient(
      120% 100% at 50% 38%,
      rgba(4, 10, 20, 0) 0%,
      rgba(4, 10, 20, 0.22) 58%,
      rgba(4, 10, 20, 0.5) 100%
    ),
    linear-gradient(180deg, rgba(4, 10, 20, 0.12) 0%, rgba(4, 10, 20, 0.28) 100%);
}

.login-screen.has-bg .login-glow {
  display: none;
}

.login-glow {
  position: absolute;
  border-radius: 50%;
  filter: blur(110px);
  pointer-events: none;
}

.glow-a {
  width: 420px;
  height: 420px;
  top: -180px;
  left: -120px;
  background: color-mix(in srgb, var(--brand) 25%, transparent);
}

.glow-b {
  width: 380px;
  height: 380px;
  right: -140px;
  bottom: -180px;
  background: color-mix(in srgb, var(--brand-cyan) 14%, transparent);
}

.login-stage {
  position: relative;
  z-index: 1;
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 20px;
  width: min(100%, 408px);
}

.login-card {
  padding: 40px 36px 34px;
  border-radius: 24px;
  background: var(--surface);
  box-shadow:
    0 36px 90px -36px rgba(2, 8, 23, 0.85),
    0 2px 12px rgba(2, 8, 23, 0.18);
  animation: card-in 0.45s ease-out;
}

.login-screen.has-bg .login-card {
  border: 1px solid color-mix(in srgb, var(--surface) 52%, transparent);
  background: var(--surface);
  background: color-mix(in srgb, var(--surface) 80%, transparent);
  box-shadow:
    0 32px 80px -32px rgba(2, 8, 23, 0.5),
    0 2px 10px rgba(2, 8, 23, 0.1);
  backdrop-filter: blur(28px) saturate(150%);
  -webkit-backdrop-filter: blur(28px) saturate(150%);
}

@supports not ((backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px))) {
  .login-screen.has-bg .login-card {
    background: var(--surface);
  }
}

@keyframes card-in {
  from {
    opacity: 0;
    transform: translateY(14px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.login-brand {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
}

.brand-logo {
  width: 56px;
  height: 56px;
  border-radius: 16px;
  object-fit: contain;
}

.brand-mark {
  display: grid;
  place-items: center;
  width: 56px;
  height: 56px;
  border-radius: 16px;
  background: var(--gradient-brand);
  color: var(--on-brand);
  font-family: var(--font-number);
  font-size: 20px;
  font-weight: 800;
  letter-spacing: -0.04em;
  box-shadow: 0 16px 34px -14px var(--brand-glow);
}

.brand-name {
  margin: 16px 0 0;
  color: var(--text-1);
  font-size: 24px;
  font-weight: 750;
  letter-spacing: -0.01em;
  line-height: 1.2;
}

.brand-sub {
  margin-top: 7px;
  color: var(--text-3);
  font-size: 10.5px;
  font-weight: 600;
  letter-spacing: 0.2em;
  text-transform: uppercase;
}

.login-hint {
  margin: 22px 0 24px;
  padding-top: 20px;
  border-top: 1px solid var(--border);
  color: var(--text-3);
  font-size: 12.5px;
  text-align: center;
}

.login-screen.has-bg .login-hint {
  border-top-color: var(--border);
  color: var(--text-3);
}

.login-form :deep(.el-form-item) {
  margin-bottom: 16px;
}

.login-form :deep(.el-input__wrapper) {
  height: 48px;
  padding: 0 14px;
  border-radius: 12px;
  background: var(--surface-muted);
  box-shadow: 0 0 0 1px var(--border) inset;
}

.login-form :deep(.el-input__wrapper.is-focus) {
  background: var(--surface);
  box-shadow: 0 0 0 1px var(--brand) inset;
}

.login-form :deep(.el-input__inner) {
  font-size: 14px;
}

.login-form :deep(.el-input__prefix) {
  margin-right: 4px;
  color: var(--text-3);
}

.login-options {
  display: flex;
  align-items: center;
  margin: 2px 0 22px;
}

.login-options :deep(.el-checkbox__label) {
  color: var(--text-2);
  font-size: 13px;
}

.login-submit {
  width: 100%;
  height: 48px;
  border: none;
  border-radius: 12px;
  background: var(--gradient-brand);
  color: var(--on-brand);
  font-size: 15px;
  font-weight: 600;
  letter-spacing: 0.08em;
  box-shadow: 0 18px 34px -18px var(--brand-glow);
}

.login-submit:hover,
.login-submit:focus {
  filter: brightness(1.08);
}

.login-footer {
  color: rgba(226, 236, 250, 0.55);
  font-size: 11.5px;
  text-align: center;
  letter-spacing: 0.02em;
}

.login-screen.has-bg .login-footer {
  color: rgba(236, 244, 255, 0.78);
  text-shadow: 0 1px 3px rgba(2, 8, 23, 0.6);
}

.footer-sep {
  margin: 0 6px;
}

@media (max-width: 480px) {
  .login-screen {
    padding: 20px 14px;
  }

  .login-card {
    padding: 32px 22px 28px;
    border-radius: 20px;
  }

  .brand-logo,
  .brand-mark {
    width: 50px;
    height: 50px;
  }

  .brand-name {
    font-size: 22px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .login-card {
    animation: none;
  }
}
</style>
