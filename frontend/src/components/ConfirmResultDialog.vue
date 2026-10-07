<template>
  <el-dialog
    v-model="visible"
    :title="verdict === 'confirmed' ? '确认违规' : '标记误报'"
    width="480px"
  >
    <el-alert
      :type="verdict === 'confirmed' ? 'success' : 'warning'"
      :closable="false"
      show-icon
      class="dialog-alert"
    >
      <template #title>
        <div class="dialog-alert-text">{{ row?.original_text }}</div>
      </template>
    </el-alert>

    <el-alert
      v-if="row && row.status !== 'pending_confirm'"
      type="warning"
      :closable="false"
      show-icon
      class="dialog-alert"
      title="翻案：将覆盖原判定并计入人工复核统计"
    />

    <!-- AI 判定辅助：自动预取，失败静默；采纳仅预填结论，最终以人工提交为准 -->
    <el-alert
      v-if="adviceLoading"
      type="info"
      :closable="false"
      class="dialog-alert"
      title="AI 判定建议生成中…"
    />
    <el-alert
      v-else-if="advice && !adviceDismissed"
      type="info"
      :closable="false"
      show-icon
      class="dialog-alert"
    >
      <template #title>
        <div class="advice-head">
          <span>
            AI 建议：{{ advice.suggested_verdict === 'confirmed' ? '确认违规' : '剔除误报' }}
            （置信 {{ Math.round(advice.confidence * 100) }}%）
          </span>
          <span class="advice-actions">
            <el-button
              v-if="advice.suggested_verdict !== verdict"
              size="small"
              link
              type="primary"
              @click="adoptAdvice"
            >
              采纳
            </el-button>
            <el-button size="small" link @click="adviceDismissed = true">忽略</el-button>
          </span>
        </div>
      </template>
      <ol class="advice-reasons">
        <li v-for="(r, i) in advice.reasons" :key="i">{{ r }}</li>
      </ol>
    </el-alert>

    <el-form
      label-width="60px"
      label-position="left"
      class="dialog-form"
      @keydown.ctrl.enter.prevent="submit"
    >
      <el-form-item label="备注">
        <el-input
          v-model="note"
          type="textarea"
          :rows="3"
          placeholder="选填：复核意见（会追加到结果描述），Ctrl+Enter 提交"
        />
      </el-form-item>
    </el-form>

    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="submit">提交</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { confirmResult } from '@/api/results'
import { getVerdictAdvice, type VerdictAdvice } from '@/api/ai'
import type { ReviewResult } from '@/types/result'

const props = defineProps<{
  modelValue: boolean
  row: ReviewResult | null
  verdict: 'confirmed' | 'false_positive'
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', v: boolean): void
  (e: 'submitted'): void
  (e: 'adopt', verdict: 'confirmed' | 'false_positive'): void
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

const note = ref('')
const submitting = ref(false)

// ---- AI 判定辅助：每次打开按 result_id 预取，失败静默 ----
const advice = ref<VerdictAdvice | null>(null)
const adviceLoading = ref(false)
const adviceDismissed = ref(false)
let adviceFor: number | null = null

watch(
  () => props.modelValue,
  async (v) => {
    if (!v) return
    note.value = ''
    adviceDismissed.value = false
    const rid = props.row?.result_id ?? null
    if (rid == null || adviceFor === rid) return
    advice.value = null
    adviceLoading.value = true
    try {
      advice.value = await getVerdictAdvice(rid)
      adviceFor = rid
    } catch {
      advice.value = null
    } finally {
      adviceLoading.value = false
    }
  },
)

function adoptAdvice() {
  if (!advice.value) return
  emit('adopt', advice.value.suggested_verdict)
}

async function submit() {
  if (!props.row) return
  submitting.value = true
  try {
    await confirmResult(props.row.result_id, {
      verdict: props.verdict,
      note: note.value || undefined,
    })
    ElMessage.success('已提交复核')
    visible.value = false
    emit('submitted')
  } catch {
    // 拦截器已提示
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.dialog-alert {
  margin-bottom: 16px;
}

.dialog-alert-text {
  max-height: 96px;
  overflow-y: auto;
  line-height: 1.5;
}

.advice-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  width: 100%;
}

.advice-actions {
  flex-shrink: 0;
}

.advice-reasons {
  margin: 0;
  padding-left: 18px;
  font-size: 12.5px;
  line-height: 1.7;
}
</style>
