<template>
  <div>
    <PageHeader title="新建审查任务" />

    <el-card>
      <el-steps :active="activeStep" finish-status="success" align-center class="create-steps">
        <el-step title="上传文档" />
        <el-step title="配置任务" />
        <el-step title="提交审查" />
      </el-steps>

      <div v-show="activeStep === 0" class="step-body">
        <el-radio-group v-model="form.compareMode" class="compare-mode">
          <el-radio-button
            v-for="m in COMPARE_MODES"
            :key="m.value"
            :value="m.value"
          >
            {{ m.label }}
          </el-radio-button>
        </el-radio-group>

        <AppUpload
          v-if="form.compareMode === 'normal'"
          @uploaded="onUploaded"
          @reset="onUploadReset"
        />
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
          class="create-form"
        >
          <el-form-item label="已选文档">
            <template v-if="form.compareMode === 'compare'">
              <el-tag type="info" closable @close="goBackUpload">
                旧版：{{ form.baseFileName }}
              </el-tag>
              <el-tag type="success" closable @close="goBackUpload">
                新版：{{ form.fileName }}
              </el-tag>
            </template>
            <el-tag v-else type="success" closable @close="goBackUpload">
              {{ form.fileName }}
            </el-tag>
          </el-form-item>
          <el-form-item label="任务名称">
            <el-input
              v-model="form.taskName"
              placeholder="默认取文件名"
              maxlength="100"
              clearable
            />
          </el-form-item>
          <el-form-item label="文档类型">
            <el-select v-model="form.documentType" placeholder="选填" clearable>
              <el-option v-for="t in DOC_TYPES" :key="t" :label="t" :value="t" />
            </el-select>
          </el-form-item>
          <el-form-item label="产品领域">
            <el-select v-model="form.domain" placeholder="选填（系统可自动识别）" clearable>
              <el-option
                v-for="d in DOMAIN_OPTIONS"
                :key="d.value"
                :label="d.label"
                :value="d.value"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="审查策略">
            <el-select v-model="form.profile" placeholder="默认常规审查">
              <el-option
                v-for="p in PROFILE_OPTIONS"
                :key="p.value"
                :label="p.label"
                :value="p.value"
              />
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
          提交后系统自动执行：领域分类 → 法规召回 → 规则扫描 + LLM 审查（并行）→ 冲突融合 → 风险评估 → 报告生成。
        </p>
      </div>

      <div class="step-actions">
        <el-button v-if="activeStep > 0" @click="activeStep--">上一步</el-button>
        <el-button
          v-if="activeStep < 2"
          type="primary"
          :disabled="!canNext"
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
import { computed, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { createTask } from '@/api/tasks'
import { DOMAIN_OPTIONS, PROFILE_OPTIONS } from '@/constants/enums'
import type { Domain } from '@/types/api'
import type { ReviewProfile } from '@/types/task'

const DOC_TYPES = ['说明书', '协议', '宣传材料']

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

const activeStep = ref(0)
const submitting = ref(false)
const form = reactive({
  documentId: '',
  baseDocumentId: '',
  fileName: '',
  baseFileName: '',
  compareMode: 'normal',
  taskName: '',
  documentType: '',
  domain: '' as Domain | '',
  profile: 'standard' as ReviewProfile | '',
})

/** 下一步是否可用：普通模式需新版文档；对比模式需旧版+新版 */
const canNext = computed(() => {
  if (form.compareMode === 'compare') return !!form.baseDocumentId && !!form.documentId
  return !!form.documentId
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
    ElMessage.warning('请先上传文档')
    return
  }
  activeStep.value++
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
</script>

<style scoped>
.create-steps {
  max-width: 720px;
  margin: 8px auto 24px;
}

.step-body {
  min-height: 200px;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 16px 0;
}

.compare-mode {
  margin-bottom: 20px;
}

.compare-uploads {
  display: flex;
  gap: 32px;
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
  margin: 0 0 8px;
  font-size: 14px;
  font-weight: 600;
  color: #303133;
}

.step-body :deep(.el-upload-dragger) {
  width: 420px;
}

.create-form {
  width: 100%;
  max-width: 520px;
}

.profile-tip {
  color: #909399;
  font-size: 12px;
  line-height: 1.5;
  margin-top: 4px;
}

.flow-tip {
  color: #909399;
  font-size: 13px;
  margin-top: 12px;
  max-width: 480px;
  text-align: center;
}

.step-actions {
  display: flex;
  justify-content: center;
  gap: 12px;
  margin-top: 24px;
}
</style>
