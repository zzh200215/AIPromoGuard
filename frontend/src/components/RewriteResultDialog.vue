<template>
  <el-dialog
    :model-value="modelValue && !!result"
    title="AI 合规改写"
    width="640px"
    append-to-body
    @update:model-value="emit('update:modelValue', $event)"
    @open="start"
  >
    <div v-if="result" v-loading="loading" class="rewrite-body">
      <div class="block">
        <div class="block-title">原文（检出违规）</div>
        <blockquote class="original">{{ result.original_text }}</blockquote>
      </div>

      <template v-if="rewritten">
        <div class="block">
          <div class="block-title">改写后文案</div>
          <div class="rewritten">{{ rewritten }}</div>
        </div>

        <div v-if="changes.length" class="block">
          <div class="block-title">改动说明</div>
          <ul class="changes">
            <li v-for="(c, i) in changes" :key="i">{{ c }}</li>
          </ul>
        </div>

        <div class="notice">
          AI 生成内容仅供参考，采用前请人工复核其合规性与事实准确性。
        </div>
      </template>
    </div>

    <template #footer>
      <el-button
        v-if="rewritten"
        type="primary"
        plain
        @click="copyResult"
      >
        复制改写文案
      </el-button>
      <el-button @click="emit('update:modelValue', false)">关闭</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { rewriteResult } from '@/api/ai'
import type { ViolationItem } from '@/types/report'

const props = defineProps<{
  modelValue: boolean
  result: ViolationItem | null
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
}>()

const loading = ref(false)
const rewritten = ref('')
const changes = ref<string[]>([])
/** 记录已加载过的 result_id：同一行重复打开不重复计费调用 */
let loadedId: number | null = null

const rewrittenText = computed(() => rewritten.value)

async function start() {
  const row = props.result
  if (!row?.result_id) return
  if (loadedId === row.result_id && rewritten.value) return
  loading.value = true
  rewritten.value = ''
  changes.value = []
  try {
    const res = await rewriteResult(row.result_id)
    rewritten.value = res.rewritten
    changes.value = res.changes
    loadedId = row.result_id
  } catch {
    // 拦截器已提示（如 AI 服务未配置）；弹窗内保留原文供人工处理
  } finally {
    loading.value = false
  }
}

async function copyResult() {
  try {
    await navigator.clipboard.writeText(rewrittenText.value)
    ElMessage.success('已复制改写文案')
  } catch {
    ElMessage.error('复制失败，请手动选择文本复制')
  }
}

// 关闭弹窗不保留上一次结果：换行打开时 start() 会按 result_id 判断是否复用
watch(
  () => props.result?.result_id,
  () => {
    rewritten.value = ''
    changes.value = []
    loadedId = null
  },
)
</script>

<style scoped lang="scss">
.rewrite-body {
  min-height: 160px;
}

.block {
  margin-bottom: 16px;
}

.block-title {
  margin-bottom: 6px;
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-secondary);
}

.original {
  margin: 0;
  padding: 10px 12px;
  border-left: 3px solid var(--el-color-danger);
  border-radius: 4px;
  background: var(--el-color-danger-light-9);
  color: var(--el-text-color-primary);
  font-size: 13.5px;
  line-height: 1.65;
}

.rewritten {
  padding: 10px 12px;
  border-left: 3px solid var(--el-color-success);
  border-radius: 4px;
  background: var(--el-color-success-light-9);
  color: var(--el-text-color-primary);
  font-size: 13.5px;
  line-height: 1.65;
}

.changes {
  margin: 0;
  padding-left: 18px;
  font-size: 13px;
  line-height: 1.8;
  color: var(--el-text-color-regular);
}

.notice {
  padding: 8px 12px;
  border-radius: 4px;
  background: var(--el-color-warning-light-9);
  color: var(--el-color-warning-dark-2);
  font-size: 12.5px;
}
</style>
