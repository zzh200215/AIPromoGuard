<template>
  <div class="review-timeline">
    <el-progress
      v-if="showProgress"
      class="tl-progress"
      :percentage="progress"
      :status="status === 'failed' ? 'exception' : undefined"
      :stroke-width="10"
    />
    <div class="tl-list">
      <div
        v-for="(item, idx) in steps"
        :key="item.name"
        class="tl-item"
        :class="`st-${item.state}`"
      >
        <div class="tl-rail">
          <div class="tl-dot">
            <el-icon v-if="item.state === 'done'" :size="11"><Check /></el-icon>
            <el-icon v-else-if="item.state === 'active'" :size="11" class="tl-spin">
              <Loading />
            </el-icon>
          </div>
          <div v-if="idx < steps.length - 1" class="tl-line" />
        </div>
        <div class="tl-body">
          <div class="tl-head">
            <span class="tl-label">{{ item.label }}</span>
            <span v-if="item.costMs != null" class="tl-cost num">
              {{ (item.costMs / 1000).toFixed(1) }}s
            </span>
          </div>
          <div v-if="item.desc" class="tl-desc">{{ item.desc }}</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 审查轨迹面板（原 TaskProgressBar 升级）：进度条 + 节点级过程明细。
 *
 * 明细数据来自 stage_log.detail（后端 graph.py _stage_detail enrich）——
 * 节点完成即增量落库（stage_sink）：运行中轨迹逐节点实时点亮，
 * 完成后成为永久的审查轨迹（审计证据的一部分，报告页复用本组件）；
 * 增量落库失败时静默降级为完成时一次性写入（面板退回步骤骨架）。
 *
 * 旧任务（enrich 上线前）无 detail 字段：各节点只显示状态与耗时，优雅降级。
 */
import { computed } from 'vue'
import { Check, Loading } from '@element-plus/icons-vue'
import { STAGE_ORDER, describeStage } from '@/utils/stageDetail'
import type { TaskOut } from '@/types/task'

const props = withDefaults(
  defineProps<{
    status: string
    progress: number
    task?: TaskOut | null
    /** 顶部总进度条（运行中视图展示；报告页回看轨迹时传 false） */
    showProgress?: boolean
  }>(),
  { showProgress: true },
)

type StepState = 'done' | 'active' | 'pending'

const steps = computed(() => {
  const stages = props.task?.stages ?? {}
  const running = ['pending', 'running', 'processing'].includes(props.status)
  // 串行近似：运行中第一个未完成的节点标记为 active（并行分支不做精确进度）
  let activeAssigned = false
  return STAGE_ORDER.map(({ name, label }) => {
    const entry = stages[name]
    let state: StepState = 'pending'
    let desc = ''

    if (entry?.status === 'completed') {
      state = 'done'
      desc = describeStage(name, entry.detail)
    } else if (entry?.status === 'awaiting') {
      // 人工复核 interrupt 暂停中（review_service 写入 awaiting + pending 列表）
      state = 'active'
      activeAssigned = true
      desc = '等待人工复核'
    } else if (running && !activeAssigned) {
      state = 'active'
      activeAssigned = true
    }

    return { name, label, state, desc, costMs: entry?.cost_ms }
  })
})
</script>

<style scoped>
.tl-progress {
  margin-bottom: 14px;
}

.tl-list {
  display: flex;
  flex-direction: column;
}

.tl-item {
  display: flex;
  gap: 10px;
  min-height: 34px;
}

.tl-rail {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 18px;
  flex-shrink: 0;
}

.tl-dot {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  border: 1.5px solid var(--el-border-color);
  background: var(--app-surface, #fff);
  color: #fff;
  flex-shrink: 0;
  margin-top: 1px;
}

.st-done .tl-dot {
  background: var(--el-color-primary);
  border-color: var(--el-color-primary);
}

.st-active .tl-dot {
  border-color: var(--el-color-primary);
  color: var(--el-color-primary);
}

.tl-spin {
  animation: tl-rotating 1.2s linear infinite;
}

@keyframes tl-rotating {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

.tl-line {
  flex: 1;
  width: 1.5px;
  background: var(--el-border-color-lighter);
  margin: 2px 0;
}

.st-done .tl-line {
  background: var(--el-color-primary-light-5);
}

.tl-body {
  flex: 1;
  min-width: 0;
  padding-bottom: 12px;
}

.tl-head {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.tl-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.st-pending .tl-label {
  color: var(--el-text-color-secondary);
  font-weight: 400;
}

.tl-cost {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.tl-desc {
  margin-top: 2px;
  font-size: 12px;
  line-height: 1.6;
  color: var(--el-text-color-secondary);
}

.st-active .tl-desc {
  color: var(--el-color-primary);
}
</style>
