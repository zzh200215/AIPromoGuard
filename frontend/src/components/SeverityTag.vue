<template>
  <el-tag :type="SEVERITY_TAG_TYPE[severity]" size="small">{{ SEVERITY_LABELS[severity] }}</el-tag>
</template>

<script setup lang="ts">
import { SEVERITY_LABELS, SEVERITY_TAG_TYPE } from '@/constants/enums'
import type { Severity } from '@/types/api'

defineProps<{ severity: Severity }>()
</script>
