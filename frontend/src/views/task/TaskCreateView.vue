<template>
  <div class="app-page app-page--narrow">
    <PageHeader
      title="新建审查"
      description="上传营销材料，系统自动完成领域识别 → 法规召回 → 规则 + LLM 双引擎审查 → 报告生成"
    />

    <el-card>
      <el-steps :active="activeStep" finish-status="success" align-center class="create-steps">
        <el-step title="上传文档" />
        <el-step title="配置任务" />
        <el-step title="提交审查" />
      </el-steps>

      <div v-show="activeStep === 0" class="step-body">
        <el-radio-group v-model="form.compareMode" class="compare-mode">
          <el-radio-button v-for="m in COMPARE_MODES" :key="m.value" :value="m.value">
            {{ m.label }}
          </el-radio-button>
        </el-radio-group>

        <template v-if="form.compareMode === 'normal'">
          <el-radio-group v-model="form.sourceMode" size="small" class="source-mode">
            <el-radio-button value="upload">上传文件</el-radio-button>
            <el-radio-button value="paste">粘贴文本</el-radio-button>
          </el-radio-group>
          <AppUpload v-show="form.sourceMode === 'upload'" @uploaded="onUploaded" @reset="onUploadReset" />
          <div v-show="form.sourceMode === 'paste'" class="paste-box">
            <el-input
              v-model="form.pasteTitle"
              placeholder="文档名称（选填，默认「粘贴文本」）"
              maxlength="100"
              class="paste-title"
            />
            <el-input
              v-model="form.pasteText"
              type="textarea"
              :rows="10"
              maxlength="200000"
              show-word-limit
              placeholder="粘贴待审文本：网页片段、聊天记录、话术稿、产品说明段落等，粘贴后点击下一步即可送审"
            />
          </div>
        </template>
        <div v-else class="compare-uploads">
          <div class="compare-item">
            <h4 class="compare-title">旧版文档</h4>
            <AppUpload @uploaded="onBaseUploaded" @reset="onBaseUploadReset" />
          </div>
          <div class="compare-item">
            <h4 class="compare-title">新版文档</h4>
            <AppUpload @uploaded="onUploaded" @reset="onUploadReset" />
          </div>
        </div>
      </div>

      <div v-show="activeStep === 1" class="step-body">
        <el-form
          ref="formRef"
          :model="form"
          :rules="rules"
          label-width="100px"
          label-position="left"
          class="create-form"
        >
          <el-form-item label="已选文档">
            <template v-if="form.compareMode === 'compare'">
              <el-tag type="info" closable @close="goBackUpload">旧版：{{ form.baseFileName }}</el-tag>
              <el-tag type="success" closable @close="goBackUpload">新版：{{ form.fileName }}</el-tag>
            </template>
            <el-tag v-else type="success" closable @close="goBackUpload">{{ form.fileName }}</el-tag>
          </el-form-item>
          <el-form-item label="任务名称">
            <el-input v-model="form.taskName" placeholder="默认取文件名" maxlength="100" clearable />
          </el-form-item>
          <el-form-item label="文档类型">
            <el-select v-model="form.documentType" placeholder="选填" clearable>
              <el-option v-for="t in DOC_TYPES" :key="t" :label="t" :value="t" />
            </el-select>
          </el-form-item>
          <el-form-item label="产品领域">
            <el-select v-model="form.domain" placeholder="选填（系统可自动识别）" clearable>
              <el-option v-for="d in DOMAIN_OPTIONS" :key="d.value" :label="d.label" :value="d.value" />
            </el-select>
          </el-form-item>
          <el-form-item label="审查策略">
            <el-select v-model="form.profile" placeholder="默认常规审查">
              <el-option v-for="p in PROFILE_OPTIONS" :key="p.value" :label="p.label" :value="p.value" />
            </el-select>
            <div class="profile-tip">{{ PROFILE_TIP[form.profile] }}</div>
          </el-form-item>
        </el-form>
      </div>

      <div v-show="activeStep === 2" class="step-body">
        <el-alert
          title="即将提交审查"
          :description="
            form.compareMode === 'compare'
              ? `「${form.baseFileName}」→「${form.fileName}」 对比审查，提交后进入差异分析与报告生成`
              : `文档「${form.fileName}」→ 任务创建后进入审查队列`
          "
          type="info"
          show-icon
          :closable="false"
        />
        <p class="flow-tip">
          提交后系统自动执行：领域分类 → 法规召回 → 规则扫描 + LLM 审查（并行）→ 冲突融合 →
          风险评估 → 报告生成。
        </p>
      </div>

      <div class="step-actions">
        <el-button v-if="activeStep > 0" @click="activeStep--">上一步</el-button>
        <el-button
          v-if="activeStep < 2"
          type="primary"
          :disabled="!canNext"
          :loading="creatingDoc"
          @click="nextStep"
        >
          下一步
        </el-button>
        <el-button v-else type="primary" :loading="submitting" @click="submit">提交审查</el-button>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
defineOptions({ name: 'task-create' })
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { createTextDocument } from '@/api/documents'
import { createTask } from '@/api/tasks'
import { DOMAIN_OPTIONS, PROFILE_OPTIONS } from '@/constants/enums'
import type { Domain } from '@/types/api'
import type { ReviewProfile } from '@/types/task'

const DOC_TYPES = ['说明书', '协议', '宣传材料', '宣传图片']

const COMPARE_MODES = [
  { label: '普通审查', value: 'normal' },
  { label: '对比审查（旧版+新版）', value: 'compare' },
]

/** 策略说明：与 src/core/profiles.py 三档语义一致 */
const PROFILE_TIP: Record<string, string> = {
  standard: '跟随系统配置：规则/双引擎高置信自动确认，其余进人工复核队列',
  strict: '对外投放：全部结论强制人工确认，自动确认关闭',
  loose: '内部预检：跳过人工复核关卡，放宽自动确认，适合草稿快速过审',
}

const router = useRouter()
const route = useRoute()

const activeStep = ref(0)
const submitting = ref(false)
const creatingDoc = ref(false)
const form = reactive({
  documentId: '',
  baseDocumentId: '',
  fileName: '',
  baseFileName: '',
  compareMode: 'normal',
  sourceMode: 'upload' as 'upload' | 'paste',
  pasteText: '',
  pasteTitle: '',
  taskName: '',
  documentType: '',
  domain: '' as Domain | '',
  profile: 'standard' as ReviewProfile | '',
})

/** 下一步是否可用：普通模式需文档（已上传，或粘贴模式有文本可生成）；对比模式需旧版+新版 */
const canNext = computed(() => {
  if (form.compareMode === 'compare') return !!form.baseDocumentId && !!form.documentId
  return !!form.documentId || (form.sourceMode === 'paste' && !!form.pasteText.trim())
})

const rules = {
  taskName: [{ max: 100, message: '任务名称最长 100 字', trigger: 'blur' }],
}

function onUploaded(documentId: string, fileName: string) {
  form.documentId = documentId
  form.fileName = fileName
  if (!form.taskName) form.taskName = fileName
}

function onBaseUploaded(documentId: string, fileName: string) {
  form.baseDocumentId = documentId
  form.baseFileName = fileName
}

function onUploadReset() {
  form.documentId = ''
  form.fileName = ''
  activeStep.value = 0
}

function onBaseUploadReset() {
  form.baseDocumentId = ''
  form.baseFileName = ''
  activeStep.value = 0
}

function goBackUpload() {
  form.documentId = ''
  form.fileName = ''
  form.baseDocumentId = ''
  form.baseFileName = ''
  activeStep.value = 0
}

function nextStep() {
  if (form.compareMode === 'compare') {
    if (!form.baseDocumentId || !form.documentId) {
      ElMessage.warning('请同时上传旧版与新版文档')
      return
    }
  } else if (!form.documentId) {
    if (form.sourceMode === 'paste') {
      void createDocFromPaste()
      return
    }
    ElMessage.warning('请先上传文档')
    return
  }
  activeStep.value++
}

/** 粘贴文本 → 落成 .txt 文档（走同一解析管线），成功后进配置步骤 */
async function createDocFromPaste() {
  const text = form.pasteText.trim()
  if (!text) {
    ElMessage.warning('请先粘贴待审文本')
    return
  }
  if (creatingDoc.value) return
  creatingDoc.value = true
  try {
    const res = await createTextDocument(text, form.pasteTitle || undefined)
    form.documentId = res.document_id
    form.fileName = res.file_name
    if (!form.taskName) form.taskName = form.pasteTitle || '粘贴文本'
    activeStep.value++
  } catch {
    // 拦截器已提示
  } finally {
    creatingDoc.value = false
  }
}

async function submit() {
  if (!form.documentId || submitting.value) return
  submitting.value = true
  try {
    const res = await createTask({
      document_id: form.documentId,
      base_document_id: form.compareMode === 'compare' ? form.baseDocumentId : undefined,
      task_name: form.taskName || undefined,
      document_type: form.documentType || undefined,
      domain: form.domain || undefined,
      profile: form.profile || undefined,
    })
    ElMessage.success('任务已创建，开始审查')
    router.push(`/tasks/${res.task_id}`)
  } catch {
    // 拦截器已提示
  } finally {
    submitting.value = false
  }
}

// 材料台账「发起审查」直达：?document_id=doc_xx&material=名称 预填并跳过上传步骤
onMounted(() => {
  const docId = String(route.query.document_id || '')
  if (!docId) return
  form.compareMode = 'normal'
  form.documentId = docId
  form.fileName = String(route.query.material || docId)
  if (!form.taskName) form.taskName = form.fileName
  activeStep.value = 1
})
</script>

<style scoped lang="scss">
.create-steps {
  max-width: 680px;
  margin: 8px auto 24px;
}

.step-body {
  min-height: 240px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 16px 0;
}

.compare-mode {
  margin-bottom: 16px;
}

.source-mode {
  margin-bottom: 18px;
}

.paste-box {
  width: 100%;
  max-width: 640px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.paste-title {
  width: 100%;
}

.compare-uploads {
  display: flex;
  gap: 40px;
  justify-content: center;
  align-items: flex-start;
  flex-wrap: wrap;
}

.compare-item {
  display: flex;
  flex-direction: column;
  align-items: center;
}

.compare-title {
  margin: 0 0 10px;
  font-size: 14px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.step-body :deep(.el-upload-dragger) {
  width: 460px;
  border-radius: 12px;
  transition: border-color 0.15s;

  &:hover {
    border-color: var(--el-color-primary);
  }
}

.create-form {
  width: 100%;
  max-width: 520px;
}

.profile-tip {
  width: 100%;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.5;
  margin-top: 4px;
}

.flow-tip {
  color: var(--el-text-color-secondary);
  font-size: 13px;
  margin-top: 16px;
  max-width: 520px;
  text-align: center;
  line-height: 1.8;
}

.step-actions {
  display: flex;
  justify-content: center;
  gap: 12px;
  margin-top: 24px;
  padding-top: 20px;
  border-top: 1px solid var(--app-border-light);
}
</style>
