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

    <el-form label-width="60px" class="dialog-form">
      <el-form-item label="备注">
        <el-input
          v-model="note"
          type="textarea"
          :rows="3"
          placeholder="选填：复核意见（会追加到结果描述）"
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
import type { ReviewResult } from '@/types/result'

const props = defineProps<{
  modelValue: boolean
  row: ReviewResult | null
  verdict: 'confirmed' | 'false_positive'
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', v: boolean): void
  (e: 'submitted'): void
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

const note = ref('')
const submitting = ref(false)

watch(
  () => props.modelValue,
  (v) => {
    if (v) note.value = ''
  },
)

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
</style>
