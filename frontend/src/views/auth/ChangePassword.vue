<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormItemRule, type FormRules } from 'element-plus'
import { ArrowLeft, CircleCheck, Key, Lock, Warning } from '@element-plus/icons-vue'

import { authApi } from '@/api/auth'
import { useAuthStore } from '@/stores/auth'
import { saveTokenBundle } from '@/utils/token'

interface PasswordForm {
  old_password: string
  new_password: string
  confirm_password: string
}

const auth = useAuthStore()
const router = useRouter()
const formRef = ref<FormInstance>()
const loading = ref(false)

const form = reactive<PasswordForm>({
  old_password: '',
  new_password: '',
  confirm_password: '',
})

const forced = computed(() => Boolean(auth.profile?.must_change_password))
const isDomainUser = computed(() => auth.profile?.source === 'ldap')

const strength = computed(() => {
  const value = form.new_password
  if (!value) {
    return { level: 0, label: '待输入', color: 'var(--border-strong)' }
  }
  let score = 0
  if (value.length >= 8) score += 1
  if (value.length >= 12) score += 1
  if (/[a-z]/.test(value) && /[A-Z]/.test(value)) score += 1
  if (/\d/.test(value)) score += 1
  if (/[^A-Za-z0-9]/.test(value)) score += 1
  if (score <= 2) return { level: 1, label: '较弱', color: '#ef4444' }
  if (score <= 3) return { level: 2, label: '中等', color: '#f59e0b' }
  return { level: 3, label: '较强', color: '#10b981' }
})

const checks = computed(() => ({
  length: form.new_password.length >= 8,
  mixed: /[A-Za-z]/.test(form.new_password) && /\d/.test(form.new_password),
  complex: /[^A-Za-z0-9]/.test(form.new_password) || (form.new_password.length >= 12 && /[A-Z]/.test(form.new_password)),
  different: Boolean(form.new_password) && form.new_password !== form.old_password,
}))

const validateNewPassword: FormItemRule['validator'] = (_rule, value: string, callback) => {
  if (!value) {
    callback(new Error('请输入新密码'))
    return
  }
  if (value.length < 8 || value.length > 64) {
    callback(new Error('密码长度需为 8-64 位'))
    return
  }
  if (!/[A-Za-z]/.test(value) || !/\d/.test(value)) {
    callback(new Error('密码需同时包含字母和数字'))
    return
  }
  if (value === form.old_password) {
    callback(new Error('新密码不能与当前密码相同'))
    return
  }
  if (form.confirm_password) {
    void formRef.value?.validateField('confirm_password').catch(() => undefined)
  }
  callback()
}

const validateConfirm: FormItemRule['validator'] = (_rule, value: string, callback) => {
  if (!value) {
    callback(new Error('请再次输入新密码'))
    return
  }
  if (value !== form.new_password) {
    callback(new Error('两次输入的密码不一致'))
    return
  }
  callback()
}

const rules: FormRules<PasswordForm> = {
  old_password: [{ required: true, message: '请输入当前密码', trigger: 'blur' }],
  new_password: [{ validator: validateNewPassword, trigger: 'blur' }],
  confirm_password: [{ validator: validateConfirm, trigger: ['blur', 'change'] }],
}

async function handleSubmit(): Promise<void> {
  if (!formRef.value || loading.value) return
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return

  loading.value = true
  try {
    const bundle = await authApi.changePassword({
      old_password: form.old_password,
      new_password: form.new_password,
    })
    saveTokenBundle(bundle)
    await auth.fetchProfile()
    ElMessage.success('密码修改成功，其他设备上的登录状态已失效')
    void router.replace('/dashboard')
  } finally {
    loading.value = false
  }
}

function goBack(): void {
  void router.replace('/dashboard')
}
</script>

<template>
  <div class="page password-page">
    <header class="password-header">
      <p class="page-eyebrow">ACCOUNT SECURITY</p>
      <h1 class="page-title">修改登录密码</h1>
      <p class="page-subtitle">密码修改后，所有已签发的旧令牌将立即失效，需要重新登录其他设备。</p>
    </header>

    <div class="password-grid">
      <section class="surface-card password-card">
        <div v-if="forced && !isDomainUser" class="force-banner">
          <el-icon><Warning /></el-icon>
          <div>
            <strong>当前使用的是初始密码</strong>
            <p>为确保账号安全，请先完成密码修改后再继续使用系统。</p>
          </div>
        </div>

        <div v-if="isDomainUser" class="domain-banner">
          <span class="domain-icon"><el-icon><Lock /></el-icon></span>
          <div>
            <strong>域账号密码由 AD 域统一管理</strong>
            <p>当前账号来自域控同步，无法在 ITAM 系统中修改密码。如需重置，请联系域管理员在 Active Directory 中操作。</p>
            <el-button class="domain-back" :icon="ArrowLeft" @click="goBack">返回工作台</el-button>
          </div>
        </div>

        <div v-if="!isDomainUser" class="card-heading">
          <span class="heading-icon"><Key /></span>
          <div>
            <h2>更新登录凭据</h2>
            <p>新密码需满足系统的密码强度策略</p>
          </div>
        </div>

        <el-form
          v-if="!isDomainUser"
          ref="formRef"
          :model="form"
          :rules="rules"
          label-position="top"
          size="large"
          class="password-form"
          @submit.prevent="handleSubmit"
        >
          <el-form-item label="当前密码" prop="old_password">
            <el-input
              v-model="form.old_password"
              :prefix-icon="Lock"
              type="password"
              placeholder="请输入当前登录密码"
              autocomplete="current-password"
              show-password
            />
          </el-form-item>

          <el-form-item label="新密码" prop="new_password">
            <el-input
              v-model="form.new_password"
              :prefix-icon="Key"
              type="password"
              placeholder="8-64 位，同时包含字母和数字"
              autocomplete="new-password"
              show-password
            />
            <div class="strength-row">
              <div class="strength-bars">
                <span
                  v-for="index in 3"
                  :key="index"
                  class="strength-bar"
                  :style="{
                    background: index <= strength.level ? strength.color : 'var(--border)',
                  }"
                />
              </div>
              <span class="strength-label" :style="{ color: strength.color }">
                {{ strength.label }}
              </span>
            </div>
          </el-form-item>

          <el-form-item label="确认新密码" prop="confirm_password">
            <el-input
              v-model="form.confirm_password"
              :prefix-icon="Lock"
              type="password"
              placeholder="请再次输入新密码"
              autocomplete="new-password"
              show-password
              @keyup.enter="handleSubmit"
            />
          </el-form-item>

          <div class="form-actions">
            <el-button v-if="!forced" :icon="ArrowLeft" @click="goBack">返回工作台</el-button>
            <el-button type="primary" :loading="loading" class="submit-btn" @click="handleSubmit">
              {{ loading ? '正在更新' : '确认修改密码' }}
            </el-button>
          </div>
        </el-form>
      </section>

      <aside v-if="!isDomainUser" class="password-aside">
        <section class="surface-card tip-card">
          <h3>密码策略</h3>
          <ul class="check-list">
            <li :class="{ passed: checks.length }">
              <el-icon><CircleCheck /></el-icon>
              至少 8 位字符
            </li>
            <li :class="{ passed: checks.mixed }">
              <el-icon><CircleCheck /></el-icon>
              同时包含字母与数字
            </li>
            <li :class="{ passed: checks.complex }">
              <el-icon><CircleCheck /></el-icon>
              建议包含大小写与特殊符号
            </li>
            <li :class="{ passed: checks.different }">
              <el-icon><CircleCheck /></el-icon>
              不与当前密码相同
            </li>
          </ul>
        </section>

        <section class="surface-card tip-card security-tip">
          <h3>安全建议</h3>
          <p>
            请勿将密码告知他人，也不要在多个系统间复用。若怀疑账号泄露，请立即修改密码并联系系统管理员查看审计日志。
          </p>
          <div class="tip-footer">
            <el-icon><Lock /></el-icon>
            密码以 scrypt 加盐哈希存储，系统不会保存明文。
          </div>
        </section>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.password-header {
  max-width: 640px;
  margin-bottom: 24px;
}

.password-grid {
  display: grid;
  grid-template-columns: minmax(0, 620px) minmax(260px, 340px);
  gap: 18px;
  align-items: start;
}

.password-card {
  padding: 28px 30px 30px;
}

.force-banner {
  display: flex;
  align-items: flex-start;
  gap: 11px;
  margin-bottom: 22px;
  padding: 13px 15px;
  border: 1px solid rgba(245, 158, 11, 0.28);
  border-radius: 13px;
  background: rgba(245, 158, 11, 0.08);
  color: #b45309;
}

.force-banner .el-icon {
  margin-top: 2px;
  font-size: 17px;
  flex-shrink: 0;
}

.force-banner strong {
  display: block;
  font-size: 12.5px;
  font-weight: 600;
}

.force-banner p {
  margin-top: 2px;
  font-size: 11.5px;
  line-height: 1.6;
}

.domain-banner {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  padding: 20px 18px;
  border: 1px solid color-mix(in srgb, var(--brand) 28%, transparent);
  border-radius: 14px;
  background: var(--gradient-brand-soft);
}

.domain-icon {
  display: grid;
  place-items: center;
  width: 42px;
  height: 42px;
  flex-shrink: 0;
  border-radius: 12px;
  background: var(--surface);
  color: var(--brand);
}

.domain-icon svg {
  width: 19px;
  height: 19px;
}

.domain-banner strong {
  color: var(--text-1);
  font-size: 14px;
  font-weight: 650;
}

.domain-banner p {
  max-width: 460px;
  margin-top: 6px;
  color: var(--text-2);
  font-size: 12.5px;
  line-height: 1.7;
}

.domain-back {
  margin-top: 16px;
}

.card-heading {
  display: flex;
  align-items: center;
  gap: 13px;
  margin-bottom: 24px;
}

.heading-icon {
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  flex-shrink: 0;
  border-radius: 13px;
  background: var(--gradient-brand-soft);
  color: var(--brand);
}

.heading-icon svg {
  width: 20px;
  height: 20px;
}

.card-heading h2 {
  color: var(--text-1);
  font-size: 17px;
  font-weight: 650;
  letter-spacing: -0.015em;
}

.card-heading p {
  margin-top: 2px;
  color: var(--text-3);
  font-size: 12px;
}

.password-form :deep(.el-form-item) {
  margin-bottom: 20px;
}

.password-form :deep(.el-form-item__label) {
  color: var(--text-2);
  font-size: 12.5px;
  font-weight: 500;
  padding-bottom: 6px;
}

.password-form :deep(.el-input__wrapper) {
  height: 46px;
  border-radius: 11px;
  background: var(--surface-muted);
  box-shadow: 0 0 0 1px var(--border) inset;
}

.password-form :deep(.el-input__wrapper.is-focus) {
  background: var(--surface);
}

.strength-row {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  margin-top: 8px;
}

.strength-bars {
  display: flex;
  flex: 1;
  gap: 5px;
}

.strength-bar {
  height: 4px;
  flex: 1;
  border-radius: 999px;
  transition: background-color 0.25s ease;
}

.strength-label {
  font-size: 11px;
  min-width: 30px;
  text-align: right;
}

.form-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 26px;
  padding-top: 20px;
  border-top: 1px dashed var(--border);
}

.submit-btn {
  min-width: 148px;
}

.password-aside {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.tip-card {
  padding: 22px 22px 20px;
}

.tip-card h3 {
  margin: 0 0 14px;
  color: var(--text-1);
  font-size: 14px;
  font-weight: 650;
}

.check-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.check-list li {
  display: flex;
  align-items: center;
  gap: 9px;
  color: var(--text-3);
  font-size: 12px;
  transition: color 0.2s ease;
}

.check-list li .el-icon {
  font-size: 15px;
  color: var(--border-strong);
  transition: color 0.2s ease;
}

.check-list li.passed {
  color: var(--text-1);
}

.check-list li.passed .el-icon {
  color: var(--success);
}

.security-tip p {
  color: var(--text-2);
  font-size: 12px;
  line-height: 1.75;
}

.tip-footer {
  display: flex;
  align-items: flex-start;
  gap: 7px;
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px dashed var(--border);
  color: var(--text-3);
  font-size: 11px;
  line-height: 1.55;
}

.tip-footer .el-icon {
  margin-top: 2px;
  flex-shrink: 0;
}

@media (max-width: 1100px) {
  .password-grid {
    grid-template-columns: 1fr;
  }

  .password-aside {
    display: grid;
    grid-template-columns: 1fr 1fr;
    align-items: stretch;
  }
}

@media (max-width: 640px) {
  .password-card {
    padding: 22px 18px 24px;
  }

  .password-aside {
    grid-template-columns: 1fr;
  }

  .form-actions {
    flex-direction: column-reverse;
  }

  .form-actions :deep(.el-button) {
    width: 100%;
    margin-left: 0;
  }
}
</style>
