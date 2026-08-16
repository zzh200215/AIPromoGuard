<template>
  <el-table :data="violations" border>
    <el-table-column type="expand">
      <template #default="{ row }">
        <div class="violation-detail">
          <p><b>规则：</b>{{ row.rule_name || '—' }}</p>
          <p v-if="row.description"><b>说明：</b>{{ row.description }}</p>
          <p v-if="row.suggestion"><b>建议：</b>{{ row.suggestion }}</p>
          <p v-if="row.risk_reason"><b>风险依据：</b>{{ row.risk_reason }}</p>
          <p v-if="row.related_regulations?.length">
            <b>相关法规：</b>{{ row.related_regulations.join('；') }}
          </p>
          <p v-if="row.related_cases?.length">
            <b>关联处罚案例：</b>
            <span v-for="c in row.related_cases" :key="c.case_name" class="case-chip">
              {{ c.case_name }}（相似度 {{ (c.similarity * 100).toFixed(0) }}%）
            </span>
          </p>
        </div>
      </template>
    </el-table-column>

    <el-table-column label="原文" prop="original_text" min-width="220" show-overflow-tooltip />
    <el-table-column label="来源" width="100">
      <template #default="{ row }">
        <el-tag
          size="small"
          :type="
            row.source === 'rule'
              ? 'primary'
              : row.source === 'llm'
                ? 'warning'
                : 'success'
          "
        >
          {{ VIOLATION_SOURCE_LABELS[row.source] }}
        </el-tag>
      </template>
    </el-table-column>
    <el-table-column label="违规类型" width="100">
      <template #default="{ row }">{{ row.type || '—' }}</template>
    </el-table-column>
    <el-table-column label="风险" width="90">
      <template #default="{ row }"><SeverityTag :severity="row.risk_level" /></template>
    </el-table-column>
    <el-table-column label="置信度" width="90">
      <template #default="{ row }">{{ (row.confidence * 100).toFixed(0) }}%</template>
    </el-table-column>
    <el-table-column label="定位" width="120">
      <template #default="{ row }">
        第{{ row.page ?? '—' }}页 · 段{{ row.paragraph ?? '—' }}
      </template>
    </el-table-column>
    <el-table-column label="标记" width="100">
      <template #default="{ row }">
        <el-tag v-if="row.flag" size="small" type="warning">{{ row.flag }}</el-tag>
        <span v-else>—</span>
      </template>
    </el-table-column>
  </el-table>
</template>

<script setup lang="ts">
import { VIOLATION_SOURCE_LABELS } from '@/constants/enums'
import type { ViolationItem } from '@/types/report'

defineProps<{ violations: ViolationItem[] }>()
</script>

<style scoped>
.violation-detail {
  padding: 4px 16px;
}

.violation-detail p {
  margin: 6px 0;
  line-height: 1.6;
  color: #606266;
}

.case-chip {
  display: inline-block;
  margin: 2px 4px 2px 0;
  padding: 1px 8px;
  background: #f0f9eb;
  border: 1px solid #e1f3d8;
  border-radius: 4px;
  color: #529b2e;
  font-size: 12px;
}
</style>
