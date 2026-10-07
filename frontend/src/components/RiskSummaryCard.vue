<template>
  <div class="risk-summary">
    <div class="risk-stats">
      <div class="stat">
        <div class="stat-num num">{{ summary.total_violations }}</div>
        <div class="stat-label">违规总数</div>
      </div>
      <div class="divider" />
      <div class="stat">
        <div class="stat-num num danger">{{ summary.high_risk }}</div>
        <div class="stat-label">高风险</div>
      </div>
      <div class="divider" />
      <div class="stat">
        <div class="stat-num num warning">{{ summary.medium_risk }}</div>
        <div class="stat-label">中风险</div>
      </div>
      <div class="divider" />
      <div class="stat">
        <div class="stat-num num muted">{{ summary.low_risk }}</div>
        <div class="stat-label">低风险</div>
      </div>
    </div>

    <!-- 风险分布占比条：一眼看出这份材料的风险构成 -->
    <div v-if="summary.total_violations > 0" class="ratio-bar">
      <span
        v-for="seg in segments"
        :key="seg.key"
        class="seg"
        :class="`seg-${seg.key}`"
        :style="{ width: seg.pct + '%' }"
        :title="`${seg.label} ${seg.count} 条（${Math.round(seg.pct)}%）`"
      />
    </div>
    <div v-else class="clean-tip">
      <el-icon><CircleCheck /></el-icon>
      未检出违规
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { CircleCheck } from '@element-plus/icons-vue'
import type { ReportSummary } from '@/types/report'

const props = defineProps<{ summary: ReportSummary }>()

const segments = computed(() => {
  const total = props.summary.total_violations || 1
  return [
    {
      key: 'high',
      label: '高风险',
      count: props.summary.high_risk,
      pct: (props.summary.high_risk / total) * 100,
    },
    {
      key: 'medium',
      label: '中风险',
      count: props.summary.medium_risk,
      pct: (props.summary.medium_risk / total) * 100,
    },
    {
      key: 'low',
      label: '低风险',
      count: props.summary.low_risk,
      pct: (props.summary.low_risk / total) * 100,
    },
  ].filter((s) => s.count > 0)
})
</script>

<style scoped lang="scss">
.risk-summary {
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  border-radius: 12px;
  padding: 18px 20px;
}

.risk-stats {
  display: flex;
  align-items: center;
}

.stat {
  flex: 1;
  text-align: center;
}

.divider {
  width: 1px;
  height: 36px;
  background: var(--app-border-light);
}

.stat-num {
  font-size: 28px;
  font-weight: 700;
  line-height: 1.2;
  color: var(--el-text-color-primary);

  &.danger {
    color: var(--el-color-danger);
  }

  &.warning {
    color: var(--el-color-warning);
  }

  &.muted {
    color: var(--el-text-color-secondary);
  }
}

.stat-label {
  margin-top: 4px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.ratio-bar {
  display: flex;
  height: 6px;
  border-radius: 3px;
  overflow: hidden;
  margin-top: 16px;
  background: var(--el-fill-color);

  .seg {
    height: 100%;

    &.seg-high {
      background: var(--el-color-danger);
    }

    &.seg-medium {
      background: var(--el-color-warning);
    }

    &.seg-low {
      background: var(--el-color-info-light-5);
    }
  }
}

.clean-tip {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 14px;
  color: var(--el-color-success);
  font-size: 13px;
  font-weight: 500;
}
</style>
