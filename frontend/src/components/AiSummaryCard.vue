<template>
  <el-card shadow="never" class="section-card ai-summary-card">
    <template #header>
      <div class="card-header">
        <span class="card-title">
          <el-icon class="ai-icon" :size="15"><MagicStick /></el-icon>
          AI 风险综述
          <el-tag v-if="summary?.stale" size="small" type="warning" effect="plain">已过期</el-tag>
        </span>
        <el-button
          size="small"
          text
          type="primary"
          :loading="loading"
          @click="generate(true)"
        >
          {{ summary ? '重新生成' : '生成综述' }}
        </el-button>
      </div>
    </template>

    <div v-if="loading && !summary" class="placeholder">
      <el-skeleton :rows="2" animated />
    </div>

    <template v-else-if="summary?.text">
      <div class="summary-text">
        {{ displayText }}<span v-if="typing" class="type-cursor">▌</span>
      </div>
      <div v-if="!typing" class="meta">
        AI 生成，仅供参考 · 模型 {{ summary.model }} · {{ summary.generated_at }}
        <span v-if="summary.stale"> · 结论已变化，点击右上角重新生成</span>
      </div>
    </template>

    <el-empty v-else description="基于当前报告生成一份风险综述，供快速了解整体风险" :image-size="56">
      <el-button type="primary" plain @click="generate(true)">生成综述</el-button>
    </el-empty>
  </el-card>
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { MagicStick } from '@element-plus/icons-vue'
import { summarizeTask, type SummaryResponse } from '@/api/ai'
import { useTypewriter } from '@/composables/useTypewriter'

const props = defineProps<{
  taskId: number | null
}>()

const summary = ref<SummaryResponse | null>(null)
const loading = ref(false)
/** 打字机（伪流式）：主动生成时逐字呈现"AI 在说话"；缓存回看直接显示 */
const { text: displayText, typing, start: typewrite, set: setText } = useTypewriter()
/** 综述跟随任务：换任务即失效重新拉取（服务端按报告持久化，未过期不重复调用） */
let loadedFor: number | null = null

async function generate(force = false) {
  if (props.taskId == null || loading.value) return
  loading.value = true
  try {
    const res = await summarizeTask(props.taskId, force)
    summary.value = res
    loadedFor = props.taskId
    if (force) {
      // 用户主动生成/重新生成 → 逐字呈现
      typewrite(res.text ?? '')
    } else {
      // 自动加载（缓存命中回看）→ 直接显示，不做打字机
      setText(res.text ?? '')
    }
  } catch {
    // 静默请求：失败（如 AI 服务未配置）不弹全局提示，界面保持可手动重试
  } finally {
    loading.value = false
  }
}

// 切换任务后自动拉取该任务的综述（命中报告内缓存则即时返回）
watch(
  () => props.taskId,
  (id) => {
    if (id != null && loadedFor !== id) {
      setText('')
      summary.value = null
      void generate(false)
    }
  },
)

onMounted(() => {
  if (props.taskId != null) void generate(false)
})
</script>

<style scoped lang="scss">
.ai-summary-card {
  .card-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  .card-title {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 16px;
    font-weight: 600;

    .ai-icon {
      color: var(--el-color-primary);
    }
  }

  .summary-text {
    font-size: 14px;
    line-height: 1.7;
    color: var(--el-text-color-primary);
  }

  .type-cursor {
    display: inline-block;
    margin-left: 1px;
    color: var(--el-color-primary);
    animation: ai-cursor-blink 1s step-end infinite;
  }

  .meta {
    margin-top: 10px;
    font-size: 12px;
    color: var(--el-text-color-secondary);
  }

  .placeholder {
    padding: 4px 0;
  }
}

@keyframes ai-cursor-blink {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0;
  }
}
</style>
