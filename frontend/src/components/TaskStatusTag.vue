<template>
  <el-tag :type="TASK_STATUS_TAG_TYPE[status] ?? 'info'" size="small">
    {{ TASK_STATUS_LABELS[status] ?? status }}
  </el-tag>
</template>

<script setup lang="ts">
import { TASK_STATUS_LABELS, TASK_STATUS_TAG_TYPE } from '@/constants/enums'

defineProps<{ status: string }>()
</script>
