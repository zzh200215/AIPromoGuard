<template>
  <el-tag size="small" effect="light" :type="TAG_TYPE[status] ?? 'info'">
    {{ LABEL }}
  </el-tag>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { RESULT_STATUS_LABELS } from '@/constants/enums'
import type { ResultStatus } from '@/types/result'

const props = defineProps<{ status: ResultStatus; autoConfirmed?: boolean }>()

const TAG_TYPE: Record<ResultStatus, 'success' | 'danger' | 'warning'> = {
  confirmed: 'success',
  false_positive: 'danger',
  pending_confirm: 'warning',
}

const LABEL = computed(() => {
  if (props.status === 'confirmed' && props.autoConfirmed) return '自动确认'
  return RESULT_STATUS_LABELS[props.status]
})
</script>
