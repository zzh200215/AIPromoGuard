<template>
  <div class="task-progress">
    <el-progress
      :percentage="progress"
      :status="status === 'failed' ? 'exception' : undefined"
      :stroke-width="14"
    />
    <div v-if="task?.stages && stageEntries.length" class="stages">
      <el-tooltip
        v-for="[name, detail] in stageEntries"
        :key="name"
        :content="`${STAGE_LABELS[name] ?? name}：${detail.status} · ${(detail.cost_ms / 1000).toFixed(1)}s`"
        placement="top"
      >
        <el-tag
          size="small"
          :type="detail.status === 'completed' ? 'success' : 'info'"
          class="stage-tag"
        >
          {{ STAGE_LABELS[name] ?? name }}
        </el-tag>
      </el-tooltip>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { TaskOut } from '@/types/task'

const props = defineProps<{ status: string; progress: number; task?: TaskOut | null }>()

const STAGE_LABELS: Record<string, string> = {
  classify: '领域分类',
  regulation_match: '法规召回',
  rule_scan: '规则扫描',
  llm_scan: 'LLM 审查',
  conflict_resolve: '冲突融合',
  risk_assess: '风险评估',
  report: '报告生成',
}

const stageEntries = computed(() => Object.entries(props.task?.stages ?? {}))
</script>

<style scoped>
.task-progress {
  padding: 8px 0;
}

.stages {
  margin-top: 12px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.stage-tag {
  cursor: default;
}
</style>
