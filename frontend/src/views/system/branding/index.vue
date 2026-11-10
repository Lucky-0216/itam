<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { UploadRawFile, UploadRequestOptions } from 'element-plus'
import {
  Bell,
  Check,
  Monitor,
  Picture,
  Plus,
  Refresh,
} from '@element-plus/icons-vue'

import { brandingApi } from '@/api/branding'
import { useAuthStore } from '@/stores/auth'
import { useBrandingStore } from '@/stores/branding'
import type {
  Announcement,
  AnnouncementLevel,
  AnnouncementPayload,
  Branding,
  BrandingUpdate,
} from '@/types/branding'
import { formatDateTime } from '@/utils/format'

const auth = useAuthStore()
const brandingStore = useBrandingStore()
const canUpdate = computed(() => auth.hasPerm('system:settings:update'))
const currentYear = new Date().getFullYear()

const activeTab = ref<'login' | 'home'>('login')
const loading = ref(false)
const saving = ref(false)
const branding = ref<Branding>(brandingStore.branding)

const form = reactive<BrandingUpdate>({
  site_name: '',
  site_subtitle: '',
  brand_mark_text: '',
  login_footer_text: '',
  dashboard_welcome: '',
})

const announcements = ref<Announcement[]>([])
const dialogVisible = ref(false)
const submitting = ref(false)
const editingId = ref<number | null>(null)
const announcementForm = reactive({
  title: '',
  content: '',
  level: 'INFO' as AnnouncementLevel,
  is_active: true,
  start_at: '' as string | null,
  end_at: '' as string | null,
  sort: 0,
})

const LEVEL_OPTIONS: { value: AnnouncementLevel; label: string }[] = [
  { value: 'INFO', label: '通知' },
  { value: 'IMPORTANT', label: '重要' },
  { value: 'WARNING', label: '提醒' },
]

const previewStyle = computed(() =>
  branding.value.background_url
    ? {
        backgroundImage: `linear-gradient(160deg, rgba(7, 15, 29, 0.92), rgba(7, 15, 29, 0.74)), url(${branding.value.background_url})`,
        backgroundSize: 'cover',
        backgroundPosition: 'center',
      }
    : {},
)

function applyBranding(data: Branding): void {
  branding.value = data
  form.site_name = data.site_name
  form.site_subtitle = data.site_subtitle
  form.brand_mark_text = data.brand_mark_text
  form.login_footer_text = data.login_footer_text
  form.dashboard_welcome = data.dashboard_welcome
}

async function loadBranding(): Promise<void> {
  const data = await brandingApi.adminBranding()
  applyBranding(data)
  brandingStore.apply(data)
}

async function loadAnnouncements(): Promise<void> {
  announcements.value = await brandingApi.listAnnouncements()
}

async function loadAll(): Promise<void> {
  loading.value = true
  try {
    await Promise.all([loadBranding(), loadAnnouncements()])
  } finally {
    loading.value = false
  }
}

async function saveBranding(): Promise<void> {
  if (!canUpdate.value || saving.value) return
  if (!form.site_name.trim()) {
    ElMessage.warning('请填写系统名称')
    return
  }
  saving.value = true
  try {
    const data = await brandingApi.updateBranding({ ...form })
    applyBranding(data)
    brandingStore.apply(data)
    ElMessage.success('品牌与首页配置已保存')
  } finally {
    saving.value = false
  }
}

function beforeUpload(file: UploadRawFile, limitMb: number): boolean {
  const allowed = ['image/png', 'image/jpeg', 'image/webp']
  if (!allowed.includes(file.type)) {
    ElMessage.warning('仅支持 PNG、JPG、WEBP 格式的图片')
    return false
  }
  if (file.size > limitMb * 1024 * 1024) {
    ElMessage.warning(`图片不能超过 ${limitMb}MB`)
    return false
  }
  return true
}

function beforeLogoUpload(file: UploadRawFile): boolean {
  return beforeUpload(file, 2)
}

function beforeBackgroundUpload(file: UploadRawFile): boolean {
  return beforeUpload(file, 10)
}

async function handleUpload(
  kind: 'logo' | 'background',
  options: UploadRequestOptions,
): Promise<void> {
  try {
    const data = await brandingApi.uploadImage(kind, options.file)
    applyBranding(data)
    brandingStore.apply(data)
    ElMessage.success(kind === 'logo' ? 'Logo 已更新' : '登录背景图已更新')
  } catch {
    // 请求拦截器已提示具体错误
  }
}

function uploadLogo(options: UploadRequestOptions): Promise<void> {
  return handleUpload('logo', options)
}

function uploadBackground(options: UploadRequestOptions): Promise<void> {
  return handleUpload('background', options)
}

async function resetImage(kind: 'logo' | 'background'): Promise<void> {
  if (!canUpdate.value) return
  const label = kind === 'logo' ? 'Logo' : '登录背景图'
  try {
    await ElMessageBox.confirm(`确定恢复默认${label}吗？`, '恢复默认', {
      type: 'warning',
      confirmButtonText: '恢复默认',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  const data = await brandingApi.deleteImage(kind)
  applyBranding(data)
  brandingStore.apply(data)
  ElMessage.success(`${label}已恢复默认`)
}

function resetAnnouncementForm(): void {
  editingId.value = null
  announcementForm.title = ''
  announcementForm.content = ''
  announcementForm.level = 'INFO'
  announcementForm.is_active = true
  announcementForm.start_at = ''
  announcementForm.end_at = ''
  announcementForm.sort = 0
}

function openCreateDialog(): void {
  resetAnnouncementForm()
  dialogVisible.value = true
}

function openEditDialog(item: Announcement): void {
  editingId.value = item.id
  announcementForm.title = item.title
  announcementForm.content = item.content
  announcementForm.level = item.level
  announcementForm.is_active = item.is_active
  announcementForm.start_at = item.start_at ? item.start_at.slice(0, 19) : ''
  announcementForm.end_at = item.end_at ? item.end_at.slice(0, 19) : ''
  announcementForm.sort = item.sort
  dialogVisible.value = true
}

async function submitAnnouncement(): Promise<void> {
  if (!canUpdate.value || submitting.value) return
  if (!announcementForm.title.trim() || !announcementForm.content.trim()) {
    ElMessage.warning('请填写公告标题与内容')
    return
  }
  if (
    announcementForm.start_at &&
    announcementForm.end_at &&
    announcementForm.start_at > announcementForm.end_at
  ) {
    ElMessage.warning('生效时间不能晚于失效时间')
    return
  }
  const payload: AnnouncementPayload = {
    title: announcementForm.title.trim(),
    content: announcementForm.content.trim(),
    level: announcementForm.level,
    is_active: announcementForm.is_active,
    start_at: announcementForm.start_at || null,
    end_at: announcementForm.end_at || null,
    sort: announcementForm.sort,
  }
  submitting.value = true
  try {
    if (editingId.value) {
      await brandingApi.updateAnnouncement(editingId.value, payload)
      ElMessage.success('公告已更新')
    } else {
      await brandingApi.createAnnouncement(payload)
      ElMessage.success('公告已发布')
    }
    dialogVisible.value = false
    await loadAnnouncements()
  } finally {
    submitting.value = false
  }
}

async function deleteAnnouncement(item: Announcement): Promise<void> {
  if (!canUpdate.value) return
  try {
    await ElMessageBox.confirm(`确定删除公告「${item.title}」吗？`, '删除公告', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  await brandingApi.deleteAnnouncement(item.id)
  ElMessage.success('公告已删除')
  await loadAnnouncements()
}

function announcementStatus(
  item: Announcement,
): { text: string; type: 'success' | 'info' | 'warning' } {
  if (!item.is_active) return { text: '已停用', type: 'info' }
  const now = Date.now()
  if (item.start_at && new Date(item.start_at).getTime() > now) {
    return { text: '未生效', type: 'warning' }
  }
  if (item.end_at && new Date(item.end_at).getTime() < now) {
    return { text: '已过期', type: 'info' }
  }
  return { text: '生效中', type: 'success' }
}

onMounted(() => {
  void loadAll()
})
</script>

<template>
  <div v-loading="loading" class="page branding-page">
    <header class="page-header">
      <div>
        <p class="page-eyebrow">BRANDING & HOME</p>
        <h1 class="page-title">品牌与首页</h1>
        <p class="page-subtitle">
          自定义登录封面的 Logo、名称、背景图与页脚，维护工作台欢迎语与公告。
        </p>
      </div>
      <div class="page-actions">
        <el-button :icon="Refresh" @click="loadAll">刷新</el-button>
        <el-button
          v-if="activeTab === 'login'"
          type="primary"
          :icon="Check"
          :loading="saving"
          :disabled="!canUpdate"
          @click="saveBranding"
        >
          保存配置
        </el-button>
      </div>
    </header>

    <el-tabs v-model="activeTab" class="branding-tabs">
      <el-tab-pane name="login">
        <template #label>
          <span class="tab-label"><el-icon><Monitor /></el-icon> 登录封面</span>
        </template>

        <div class="brand-layout">
          <div class="form-column">
            <section class="surface-card form-card">
              <div class="panel-head">
                <div>
                  <p class="panel-eyebrow">BRAND</p>
                  <h2 class="panel-title">品牌信息</h2>
                </div>
              </div>

              <el-form label-position="top" :disabled="!canUpdate">
                <div class="form-grid">
                  <el-form-item label="系统名称">
                    <el-input v-model="form.site_name" maxlength="60" show-word-limit />
                  </el-form-item>
                  <el-form-item label="副标题">
                    <el-input v-model="form.site_subtitle" maxlength="80" show-word-limit />
                  </el-form-item>
                </div>
                <el-form-item label="图标文字（未上传 Logo 时显示）">
                  <el-input
                    v-model="form.brand_mark_text"
                    maxlength="8"
                    class="mark-input"
                    show-word-limit
                  />
                </el-form-item>
                <el-form-item label="页脚文案">
                  <el-input v-model="form.login_footer_text" maxlength="200" show-word-limit />
                </el-form-item>
              </el-form>

              <div class="image-grid">
                <div class="image-box">
                  <div class="image-head">
                    <span class="image-title"><el-icon><Picture /></el-icon> Logo</span>
                    <span class="field-hint">PNG / JPG / WEBP · ≤ 2MB</span>
                  </div>
                  <div class="logo-preview">
                    <img v-if="branding.logo_url" :src="branding.logo_url" alt="Logo" />
                    <span v-else>{{ form.brand_mark_text || 'IT' }}</span>
                  </div>
                  <div class="image-actions">
                    <el-upload
                      :show-file-list="false"
                      :http-request="uploadLogo"
                      :before-upload="beforeLogoUpload"
                      accept=".png,.jpg,.jpeg,.webp"
                    >
                      <el-button size="small" :disabled="!canUpdate">上传 Logo</el-button>
                    </el-upload>
                    <el-button
                      v-if="branding.logo_url"
                      size="small"
                      text
                      type="danger"
                      :disabled="!canUpdate"
                      @click="resetImage('logo')"
                    >
                      恢复默认
                    </el-button>
                  </div>
                </div>

                <div class="image-box">
                  <div class="image-head">
                    <span class="image-title"><el-icon><Picture /></el-icon> 登录背景图</span>
                    <span class="field-hint">PNG / JPG / WEBP · ≤ 10MB</span>
                  </div>
                  <div
                    class="background-preview"
                    :style="
                      branding.background_url
                        ? { backgroundImage: `url(${branding.background_url})` }
                        : {}
                    "
                  >
                    <span v-if="!branding.background_url">默认渐变背景</span>
                  </div>
                  <div class="image-actions">
                    <el-upload
                      :show-file-list="false"
                      :http-request="uploadBackground"
                      :before-upload="beforeBackgroundUpload"
                      accept=".png,.jpg,.jpeg,.webp"
                    >
                      <el-button size="small" :disabled="!canUpdate">上传背景图</el-button>
                    </el-upload>
                    <el-button
                      v-if="branding.background_url"
                      size="small"
                      text
                      type="danger"
                      :disabled="!canUpdate"
                      @click="resetImage('background')"
                    >
                      恢复默认
                    </el-button>
                  </div>
                </div>
              </div>
            </section>

          </div>

          <aside class="preview-column">
            <section class="surface-card preview-card">
              <div class="panel-head">
                <div>
                  <p class="panel-eyebrow">PREVIEW</p>
                  <h2 class="panel-title">封面预览</h2>
                </div>
              </div>
              <div class="login-preview" :style="previewStyle">
                <div class="preview-card">
                  <div class="preview-brand">
                    <img v-if="branding.logo_url" :src="branding.logo_url" alt="Logo" />
                    <span v-else class="preview-mark">{{ form.brand_mark_text || 'IT' }}</span>
                    <strong>{{ form.site_name || 'ITAM' }}</strong>
                    <small>{{ form.site_subtitle }}</small>
                  </div>
                  <div class="preview-hint">使用本地账号或域账号（AD / LDAP）登录</div>
                  <div class="preview-input" />
                  <div class="preview-input" />
                  <div class="preview-submit">登录</div>
                </div>
                <p class="preview-footer">
                  {{ form.login_footer_text || form.site_name || 'ITAM' }} · © {{ currentYear }}
                </p>
              </div>
            </section>
          </aside>
        </div>
      </el-tab-pane>

      <el-tab-pane name="home">
        <template #label>
          <span class="tab-label"><el-icon><Bell /></el-icon> 工作台首页</span>
        </template>

        <div class="home-column">
          <section class="surface-card form-card">
            <div class="panel-head">
              <div>
                <p class="panel-eyebrow">WELCOME</p>
                <h2 class="panel-title">欢迎语</h2>
              </div>
            </div>
            <el-form label-position="top" :disabled="!canUpdate">
              <el-form-item label="工作台欢迎语">
                <el-input
                  v-model="form.dashboard_welcome"
                  type="textarea"
                  :rows="3"
                  maxlength="300"
                  show-word-limit
                  placeholder="例如：欢迎回来，{name}！今天也要高效管理资产。"
                />
              </el-form-item>
              <p class="field-hint welcome-hint">
                支持占位符 <code>{name}</code>（当前用户姓名）与 <code>{greeting}</code>
                （早上好 / 下午好等）。留空则不显示欢迎语。
              </p>
              <div class="welcome-actions">
                <el-button
                  type="primary"
                  :icon="Check"
                  :loading="saving"
                  :disabled="!canUpdate"
                  @click="saveBranding"
                >
                  保存欢迎语
                </el-button>
              </div>
            </el-form>
          </section>

          <section class="surface-card form-card">
            <div class="panel-head announcement-head">
              <div>
                <p class="panel-eyebrow">ANNOUNCEMENTS</p>
                <h2 class="panel-title">公告栏</h2>
                <p class="panel-hint">
                  工作台仅展示启用且在有效期内的公告；按排序值从小到大展示。
                </p>
              </div>
              <el-button
                type="primary"
                :icon="Plus"
                :disabled="!canUpdate"
                @click="openCreateDialog"
              >
                新增公告
              </el-button>
            </div>

            <el-table :data="announcements" class="announcement-table" empty-text="暂无公告">
              <el-table-column prop="title" label="标题" min-width="180" show-overflow-tooltip />
              <el-table-column label="级别" width="90">
                <template #default="{ row }">
                  <el-tag
                    size="small"
                    effect="light"
                    :type="
                      row.level === 'IMPORTANT'
                        ? 'danger'
                        : row.level === 'WARNING'
                          ? 'warning'
                          : 'primary'
                    "
                  >
                    {{ row.level_label }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="状态" width="90">
                <template #default="{ row }">
                  <el-tag size="small" effect="plain" :type="announcementStatus(row).type">
                    {{ announcementStatus(row).text }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="content" label="内容" min-width="220" show-overflow-tooltip />
              <el-table-column label="有效期" min-width="200">
                <template #default="{ row }">
                  <span class="cell-muted">
                    {{ row.start_at ? formatDateTime(row.start_at) : '即时' }}
                    ~
                    {{ row.end_at ? formatDateTime(row.end_at) : '长期' }}
                  </span>
                </template>
              </el-table-column>
              <el-table-column prop="sort" label="排序" width="70" align="center" />
              <el-table-column label="操作" width="130" fixed="right">
                <template #default="{ row }">
                  <el-button text type="primary" :disabled="!canUpdate" @click="openEditDialog(row)">
                    编辑
                  </el-button>
                  <el-button
                    text
                    type="danger"
                    :disabled="!canUpdate"
                    @click="deleteAnnouncement(row)"
                  >
                    删除
                  </el-button>
                </template>
              </el-table-column>
            </el-table>
          </section>
        </div>
      </el-tab-pane>
    </el-tabs>

    <el-dialog
      v-model="dialogVisible"
      :title="editingId ? '编辑公告' : '新增公告'"
      width="640px"
      append-to-body
    >
      <el-form label-position="top" :disabled="!canUpdate">
        <el-form-item label="标题" required>
          <el-input v-model="announcementForm.title" maxlength="200" show-word-limit />
        </el-form-item>
        <div class="form-grid">
          <el-form-item label="级别">
            <el-select v-model="announcementForm.level" class="full-width">
              <el-option
                v-for="option in LEVEL_OPTIONS"
                :key="option.value"
                :label="option.label"
                :value="option.value"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="排序（数字越小越靠前）">
            <el-input-number
              v-model="announcementForm.sort"
              :min="-9999"
              :max="9999"
              class="full-width"
            />
          </el-form-item>
        </div>
        <div class="form-grid">
          <el-form-item label="生效时间">
            <el-date-picker
              v-model="announcementForm.start_at"
              type="datetime"
              value-format="YYYY-MM-DDTHH:mm:ss"
              placeholder="立即生效"
              clearable
              class="full-width"
            />
          </el-form-item>
          <el-form-item label="失效时间">
            <el-date-picker
              v-model="announcementForm.end_at"
              type="datetime"
              value-format="YYYY-MM-DDTHH:mm:ss"
              placeholder="长期有效"
              clearable
              class="full-width"
            />
          </el-form-item>
        </div>
        <el-form-item label="内容" required>
          <el-input
            v-model="announcementForm.content"
            type="textarea"
            :rows="5"
            maxlength="4000"
            show-word-limit
          />
        </el-form-item>
        <el-form-item label="状态">
          <el-switch
            v-model="announcementForm.is_active"
            active-text="启用"
            inactive-text="停用"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button
          type="primary"
          :loading="submitting"
          :disabled="!canUpdate"
          @click="submitAnnouncement"
        >
          保存
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.branding-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.branding-tabs :deep(.el-tabs__header) {
  margin-bottom: 16px;
}

.tab-label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.brand-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 360px;
  align-items: start;
  gap: 18px;
}

.form-column,
.home-column {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.form-card {
  padding: 22px 24px;
}

.form-card :deep(.el-form-item) {
  margin-bottom: 18px;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 16px;
}

.mark-input {
  max-width: 220px;
}

.image-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.image-box {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 14px;
  border: 1px solid var(--border);
  border-radius: 14px;
  background: var(--surface-muted);
}

.image-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.image-title {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: var(--text-1);
  font-size: 13px;
  font-weight: 600;
}

.logo-preview {
  display: grid;
  place-items: center;
  width: 64px;
  height: 64px;
  border-radius: 14px;
  background: var(--gradient-brand);
  color: var(--on-brand);
  font-size: 22px;
  font-weight: 800;
  overflow: hidden;
}

.logo-preview img {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
}

.background-preview {
  display: grid;
  place-items: center;
  height: 84px;
  border-radius: 10px;
  background:
    radial-gradient(120px 60px at 20% 20%, color-mix(in srgb, var(--brand) 35%, transparent), transparent 70%),
    #0b172a;
  background-size: cover;
  background-position: center;
  color: #7d92b0;
  font-size: 12px;
}

.image-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.preview-column {
  position: sticky;
  top: 16px;
}

.preview-card {
  padding: 20px;
}

.login-preview {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 14px;
  margin-top: 4px;
  padding: 26px 20px 20px;
  border-radius: 18px;
  background:
    radial-gradient(220px 140px at 0% 0%, color-mix(in srgb, var(--brand) 40%, transparent), transparent 70%),
    #07101f;
}

.preview-card {
  display: flex;
  flex-direction: column;
  width: 100%;
  max-width: 220px;
  padding: 18px 16px;
  border-radius: 14px;
  background: var(--surface);
  box-shadow: 0 18px 40px -20px rgba(2, 8, 23, 0.9);
}

.preview-brand {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
}

.preview-brand img {
  width: 30px;
  height: 30px;
  border-radius: 9px;
  object-fit: contain;
}

.preview-mark {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border-radius: 9px;
  background: var(--gradient-brand);
  color: var(--on-brand);
  font-size: 12px;
  font-weight: 800;
}

.preview-brand strong {
  margin-top: 8px;
  color: var(--text-1);
  font-size: 13px;
  letter-spacing: 0.02em;
}

.preview-brand small {
  margin-top: 2px;
  color: var(--text-3);
  font-size: 7.5px;
  letter-spacing: 0.14em;
}

.preview-hint {
  margin: 10px 0 8px;
  padding-top: 10px;
  border-top: 1px solid var(--border);
  color: var(--text-3);
  font-size: 8px;
  text-align: center;
}

.preview-input {
  height: 20px;
  margin-bottom: 6px;
  border-radius: 6px;
  background: var(--surface-muted);
  box-shadow: 0 0 0 1px var(--border) inset;
}

.preview-submit {
  display: grid;
  place-items: center;
  height: 22px;
  margin-top: 2px;
  border-radius: 6px;
  background: var(--gradient-brand);
  color: var(--on-brand);
  font-size: 9px;
  font-weight: 600;
  letter-spacing: 0.12em;
}

.preview-footer {
  color: rgba(226, 236, 250, 0.55);
  font-size: 9.5px;
  text-align: center;
}

.announcement-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.panel-hint {
  margin-top: 6px;
  color: var(--text-3);
  font-size: 12px;
}

.announcement-table {
  width: 100%;
}

.cell-muted {
  color: var(--text-3);
  font-size: 12px;
}

.welcome-hint code {
  padding: 1px 5px;
  border-radius: 5px;
  background: var(--surface-muted);
  color: var(--brand);
  font-size: 11.5px;
}

.welcome-actions {
  display: flex;
  justify-content: flex-end;
}

.full-width {
  width: 100%;
}

@media (max-width: 1280px) {
  .brand-layout {
    grid-template-columns: minmax(0, 1fr);
  }

  .preview-column {
    position: static;
  }
}

@media (max-width: 760px) {
  .form-grid,
  .image-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
