<template>
  <el-row :gutter="12" class="risk-summary">
    <el-col :span="6">
      <div class="card total">
        <div class="num">{{ summary.total_violations }}</div>
        <div class="label">违规总数</div>
      </div>
    </el-col>
    <el-col :span="6">
      <div class="card high">
        <div class="num">{{ summary.high_risk }}</div>
        <div class="label">高风险</div>
      </div>
    </el-col>
    <el-col :span="6">
      <div class="card medium">
        <div class="num">{{ summary.medium_risk }}</div>
        <div class="label">中风险</div>
      </div>
    </el-col>
    <el-col :span="6">
      <div class="card low">
        <div class="num">{{ summary.low_risk }}</div>
        <div class="label">低风险</div>
      </div>
    </el-col>
  </el-row>
</template>

<script setup lang="ts">
import type { ReportSummary } from '@/types/report'

defineProps<{ summary: ReportSummary }>()
</script>

<style scoped>
.card {
  background: #fff;
  border: 1px solid var(--app-border);
  border-radius: 8px;
  padding: 16px;
  text-align: center;
}

.num {
  font-size: 28px;
  font-weight: 700;
}

.label {
  margin-top: 4px;
  font-size: 13px;
  color: #909399;
}

.total .num {
  color: #303133;
}

.high .num {
  color: #f56c6c;
}

.medium .num {
  color: #e6a23c;
}

.low .num {
  color: #909399;
}
</style>
