<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage, type UploadFile, type UploadUserFile } from 'element-plus'
import { Download, UploadFilled } from '@element-plus/icons-vue'

import { importApi } from '@/api/imports'
import VirtualList from '@/components/VirtualList.vue'
import type { ImportKind, ImportResult } from '@/types/imports'

const props = defineProps<{
  modelValue: boolean
  kind: ImportKind
  title?: string
  hint?: string
}>()

const emit = defineEmits<{
  (event: 'update:modelValue', value: boolean): void
  (event: 'imported', result: ImportResult): void
}>()

const KIND_LABELS: Record<ImportKind, string> = {
  users: '用户',
  assets: '资产',
  categories: '资产分类',
}

const TEMPLATE_NAMES: Record<ImportKind, string> = {
  users: '用户导入模板.xlsx',
  assets: '资产导入模板.xlsx',
  categories: '资产分类导入模板.xlsx',
}

const file = ref<File | null>(null)
const fileList = ref<UploadUserFile[]>([])
const submitting = ref(false)
const downloading = ref(false)
const result = ref<ImportResult | null>(null)

const dialogTitle = computed(() => props.title || `导入${KIND_LABELS[props.kind]}`)
const hint = computed(
  () =>
    props.hint ||
    `请先下载模板，按表头填写后上传；支持 .xlsx 格式，单次最多 1000 行，文件不超过 10MB。`,
)

function close(): void {
  emit('update:modelValue', false)
}

function reset(): void {
  file.value = null
  fileList.value = []
  result.value = null
  submitting.value = false
  downloading.value = false
}

watch(
  () => props.modelValue,
  (visible) => {
    if (visible) reset()
  },
)

function handleFileChange(uploadFile: UploadFile): void {
  const raw = uploadFile.raw
  if (!raw) return
  if (!raw.name.toLowerCase().endsWith('.xlsx')) {
    ElMessage.error('仅支持 .xlsx 格式的 Excel 文件')
    fileList.value = []
    file.value = null
    return
  }
  if (raw.size > 10 * 1024 * 1024) {
    ElMessage.error('文件不能超过 10MB')
    fileList.value = []
    file.value = null
    return
  }
  file.value = raw
  fileList.value = [uploadFile]
  result.value = null
}

function handleFileRemove(): void {
  file.value = null
  fileList.value = []
}

async function downloadTemplate(): Promise<void> {
  downloading.value = true
  try {
    const blob = await importApi.downloadTemplate(props.kind)
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = TEMPLATE_NAMES[props.kind]
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(url)
  } finally {
    downloading.value = false
  }
}

async function submit(): Promise<void> {
  if (!file.value) {
    ElMessage.warning('请选择要导入的 Excel 文件')
    return
  }
  submitting.value = true
  try {
    const data = await importApi.run(props.kind, file.value)
    result.value = data
    if (data.success > 0) {
      emit('imported', data)
    }
    if (data.failed === 0) {
      ElMessage.success(`导入完成，共 ${data.success} 条`)
      close()
      return
    }
    ElMessage.warning(`导入完成：成功 ${data.success} 条，失败 ${data.failed} 条`)
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    :title="dialogTitle"
    width="640px"
    destroy-on-close
    @update:model-value="emit('update:modelValue', $event)"
  >
    <p class="import-hint">{{ hint }}</p>

    <div class="import-steps">
      <section class="import-step">
        <div class="import-step-head">
          <span class="import-step-index">01</span>
          <span>下载模板</span>
        </div>
        <p class="import-step-desc">模板包含示例数据与填写说明，请勿修改表头。</p>
        <el-button :icon="Download" :loading="downloading" @click="downloadTemplate">
          下载模板
        </el-button>
      </section>

      <section class="import-step">
        <div class="import-step-head">
          <span class="import-step-index">02</span>
          <span>上传文件</span>
        </div>
        <el-upload
          v-model:file-list="fileList"
          class="import-upload"
          drag
          accept=".xlsx"
          :auto-upload="false"
          :on-change="handleFileChange"
          :on-remove="handleFileRemove"
        >
          <el-icon class="import-upload-icon"><UploadFilled /></el-icon>
          <div class="import-upload-text">
            将 Excel 拖到此处，或 <em>点击选择文件</em>
          </div>
          <template #tip>
            <div class="import-upload-tip">仅支持 .xlsx，单文件不超过 10MB</div>
          </template>
        </el-upload>
      </section>
    </div>

    <div v-if="result" class="import-result">
      <el-alert
        :type="result.failed === 0 ? 'success' : 'warning'"
        :closable="false"
        show-icon
        :title="`共 ${result.total} 行：成功 ${result.success} 行，失败 ${result.failed} 行`"
      />
      <div v-if="result.errors.length" class="import-error-list">
        <div class="import-error-head">
          <span class="import-error-no">行号</span>
          <span>失败原因</span>
        </div>
        <VirtualList :items="result.errors" :item-height="34" :height="220">
          <template #default="{ item }">
            <div class="import-error-row">
              <span class="import-error-no">{{ item.row }}</span>
              <span class="import-error-msg" :title="item.message">{{ item.message }}</span>
            </div>
          </template>
        </VirtualList>
      </div>
      <p v-if="result.errors.length" class="import-error-tip">
        可修正失败行后重新上传，已成功的行不会重复导入。
      </p>
    </div>

    <template #footer>
      <el-button @click="close">关闭</el-button>
      <el-button
        type="primary"
        :loading="submitting"
        :disabled="!file || submitting"
        @click="submit"
      >
        开始导入
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.import-hint {
  color: var(--text-2);
  font-size: 13px;
  line-height: 1.7;
  margin-bottom: 16px;
}

.import-steps {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.import-step {
  padding: 14px 16px;
  border-radius: 14px;
  border: 1px solid var(--border);
  background: var(--surface-muted);
}

.import-step-head {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  color: var(--text-1);
}

.import-step-index {
  font-family: var(--font-number);
  font-size: 12px;
  color: var(--text-3);
  letter-spacing: 0.08em;
}

.import-step-desc {
  margin: 6px 0 10px;
  color: var(--text-3);
  font-size: 12.5px;
}

.import-upload :deep(.el-upload) {
  width: 100%;
}

.import-upload :deep(.el-upload-dragger) {
  width: 100%;
  padding: 18px 12px;
  border-radius: 12px;
}

.import-upload-icon {
  font-size: 26px;
  color: var(--text-3);
}

.import-upload-text {
  margin-top: 6px;
  color: var(--text-2);
  font-size: 13px;
}

.import-upload-text em {
  color: var(--brand, #4a6da8);
  font-style: normal;
}

.import-upload-tip {
  color: var(--text-3);
  font-size: 12px;
  margin-top: 6px;
}

.import-result {
  margin-top: 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.import-error-list {
  border: 1px solid var(--border);
  border-radius: 10px;
  overflow: hidden;
  background: var(--surface);
}

.import-error-head {
  display: grid;
  grid-template-columns: 72px minmax(0, 1fr);
  align-items: center;
  height: 34px;
  padding: 0 12px;
  background: var(--surface-muted);
  border-bottom: 1px solid var(--border);
  font-size: 12px;
  color: var(--text-3);
}

.import-error-row {
  display: grid;
  grid-template-columns: 72px minmax(0, 1fr);
  align-items: center;
  height: 34px;
  padding: 0 12px;
  font-size: 12.5px;
  box-shadow: inset 0 -1px 0 var(--border);
}

.import-error-no {
  font-family: var(--font-number);
  color: var(--text-3);
}

.import-error-msg {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-1);
}

.import-error-tip {
  color: var(--text-3);
  font-size: 12px;
}
</style>
