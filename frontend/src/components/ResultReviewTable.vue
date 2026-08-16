<template>
  <el-table :data="results" border>
    <el-table-column label="原文" prop="original_text" min-width="240" show-overflow-tooltip />
    <el-table-column label="来源" width="100">
      <template #default="{ row }">{{ VIOLATION_SOURCE_LABELS[row.violation_type] }}</template>
    </el-table-column>
    <el-table-column label="风险" width="90">
      <template #default="{ row }"><SeverityTag :severity="row.risk_level" /></template>
    </el-table-column>
    <el-table-column label="置信度" width="90">
      <template #default="{ row }">{{ (row.confidence_score * 100).toFixed(0) }}%</template>
    </el-table-column>
    <el-table-column label="定位" width="120">
      <template #default="{ row }">
        第{{ row.location_page ?? '—' }}页 · 段{{ row.location_paragraph ?? '—' }}
      </template>
    </el-table-column>
    <el-table-column label="状态" width="130">
      <template #default="{ row }">
        <el-tooltip
          v-if="row.status === 'confirmed' && row.auto_confirmed"
          content="规则/双引擎高置信命中，系统自动确认，可翻案"
          placement="top"
        >
          <el-tag size="small" type="success">自动确认</el-tag>
        </el-tooltip>
        <el-tag
          v-else
          size="small"
          :type="
            row.status === 'confirmed' ? 'success' : row.status === 'false_positive' ? 'danger' : 'info'
          "
        >
          {{ RESULT_STATUS_LABELS[row.status] }}
        </el-tag>
      </template>
    </el-table-column>
    <el-table-column v-if="canConfirm" label="操作" width="200" fixed="right">
      <template #default="{ row }">
        <template v-if="row.status === 'pending_confirm'">
          <el-button size="small" type="success" @click="emit('confirm', row)">确认违规</el-button>
          <el-button size="small" type="danger" @click="emit('false-positive', row)">误报</el-button>
        </template>
        <el-tooltip
          v-else
          :content="`翻案为${row.status === 'confirmed' ? '误报' : '确认违规'}（计入人工复核）`"
          placement="top"
        >
          <el-button size="small" plain @click="overturn(row)">翻案</el-button>
        </el-tooltip>
      </template>
    </el-table-column>
  </el-table>
</template>

<script setup lang="ts">
import { RESULT_STATUS_LABELS, VIOLATION_SOURCE_LABELS } from '@/constants/enums'
import type { ReviewResult } from '@/types/result'

defineProps<{ results: ReviewResult[]; canConfirm: boolean }>()

const emit = defineEmits<{
  (e: 'confirm', row: ReviewResult): void
  (e: 'false-positive', row: ReviewResult): void
}>()

function overturn(row: ReviewResult) {
  // 翻案：目标 verdict 取当前状态相反值（confirmed→误报 / false_positive→确认违规）
  emit(row.status === 'confirmed' ? 'false-positive' : 'confirm', row)
}
</script>

<style scoped></style>
