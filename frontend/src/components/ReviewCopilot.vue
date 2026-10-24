<template>
  <el-drawer
    :model-value="modelValue"
    title="审查问答助手"
    size="440px"
    append-to-body
    :close-on-click-modal="false"
    @update:model-value="emit('update:modelValue', $event)"
    @open="onOpen"
  >
    <div class="copilot" ref="scrollRef">
      <!-- 欢迎语 + 建议问题：第一次打开时引导，不需要用户猜能问什么 -->
      <div v-if="!messages.length && !loading" class="copilot-welcome">
        <div class="welcome-title">基于本任务报告与法规知识库回答</div>
        <div class="welcome-sub">结论均附法规出处，可点击跳转原文</div>
        <button
          v-for="s in SUGGESTIONS"
          :key="s"
          type="button"
          class="suggestion"
          @click="send(s)"
        >
          {{ s }}
        </button>
      </div>

      <div
        v-for="(m, i) in messages"
        :key="i"
        class="msg"
        :class="m.role"
      >
        <div class="bubble">
          <span v-for="(line, li) in m.content.split('\n')" :key="li" class="line">{{ line }}</span>
          <div v-if="m.refs?.length" class="refs">
            <div class="refs-title">依据：</div>
            <component
              :is="ref.regulation_id != null ? 'router-link' : 'span'"
              v-for="(ref, ri) in m.refs"
              :key="ri"
              class="ref-chip"
              :to="ref.regulation_id != null ? `/knowledge/regulations/${ref.regulation_id}` : undefined"
            >
              《{{ ref.name }}》{{ ref.article_no ?? '' }}
            </component>
          </div>
        </div>
      </div>

      <div v-if="loading" class="msg assistant">
        <div class="bubble thinking"><span /><span /><span /></div>
      </div>
    </div>

    <div class="copilot-input">
      <el-input
        v-model="draft"
        type="textarea"
        :rows="2"
        resize="none"
        maxlength="500"
        placeholder="就本任务提问，Enter 发送（Shift+Enter 换行）"
        :disabled="loading"
        @keydown.enter.exact.prevent="onEnter"
      />
      <el-button type="primary" :loading="loading" :disabled="!draft.trim()" @click="onEnter">
        发送
      </el-button>
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { askTask, askTaskHistory, type AskResponse, type CopilotRef } from '@/api/ai'

interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  refs?: CopilotRef[]
}

const props = defineProps<{
  modelValue: boolean
  taskId: number | null
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
}>()

const SUGGESTIONS = [
  '本材料最主要的合规风险是什么？',
  '哪些表述违反了收益承诺规定？',
  '给出三条最重要的整改建议',
]

const messages = ref<ChatMessage[]>([])
const draft = ref('')
const loading = ref(false)
const scrollRef = ref<HTMLElement | null>(null)

function onOpen() {
  // 每次打开回到当前任务语境：换任务后旧对话不再展示，避免答非所问
  if (messages.value.length && loading.value) return
}

/** 从服务端恢复当前任务的持久化问答历史（多轮记忆的可见落点） */
async function restoreHistory(taskId: number) {
  try {
    const res = await askTaskHistory(taskId)
    messages.value = res.messages.map((m) => ({
      role: m.role,
      content: m.content,
      refs: m.refs?.length ? m.refs : undefined,
    }))
  } catch {
    // 历史拉取失败静默降级为空会话（问答功能不受影响）
    messages.value = []
  }
  await scrollToBottom()
}

async function send(text: string) {
  const question = text.trim()
  if (!question || loading.value || props.taskId == null) return
  messages.value.push({ role: 'user', content: question })
  draft.value = ''
  loading.value = true
  await scrollToBottom()
  try {
    const res: AskResponse = await askTask(props.taskId, question)
    messages.value.push({ role: 'assistant', content: res.answer, refs: res.refs })
  } catch {
    // 拦截器已 toast 具体错误（如 AI 服务未配置）；会话内保留失败痕迹
    messages.value.push({ role: 'assistant', content: '本次回答调用失败，请稍后重试或检查 AI 服务配置。' })
  } finally {
    loading.value = false
    await scrollToBottom()
  }
}

function onEnter() {
  void send(draft.value)
}

async function scrollToBottom() {
  await nextTick()
  scrollRef.value?.scrollTo({ top: scrollRef.value.scrollHeight })
}

// 切换任务时从服务端恢复该任务的持久化会话（历史随任务落库，关抽屉不丢）
watch(
  () => props.taskId,
  (id) => {
    if (id != null) {
      void restoreHistory(id)
    } else {
      messages.value = []
    }
  },
  { immediate: true },
)
</script>

<style scoped lang="scss">
.copilot {
  display: flex;
  flex-direction: column;
  gap: 12px;
  height: 100%;
  overflow-y: auto;
  padding: 4px 4px 12px;
}

.copilot-welcome {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 24px;

  .welcome-title {
    font-size: 15px;
    font-weight: 600;
    color: var(--el-text-color-primary);
  }

  .welcome-sub {
    font-size: 13px;
    color: var(--el-text-color-secondary);
    margin-bottom: 8px;
  }

  .suggestion {
    padding: 8px 12px;
    border: 1px solid var(--app-border);
    border-radius: 8px;
    background: var(--app-surface-2);
    color: var(--el-text-color-regular);
    font-size: 13px;
    text-align: left;
    cursor: pointer;
    transition: border-color 0.15s, color 0.15s;

    &:hover {
      border-color: var(--el-color-primary);
      color: var(--el-color-primary);
    }
  }
}

.msg {
  display: flex;

  &.user {
    justify-content: flex-end;

    .bubble {
      background: var(--el-color-primary-light-9);
      border-color: var(--el-color-primary-light-7);
    }
  }

  &.assistant .bubble {
    background: var(--app-surface-2);
  }
}

.bubble {
  max-width: 92%;
  padding: 10px 12px;
  border: 1px solid var(--app-border-light);
  border-radius: 10px;
  font-size: 13.5px;
  line-height: 1.65;
  color: var(--el-text-color-primary);
  white-space: normal;

  .line {
    display: block;
    min-height: 4px;
  }
}

.refs {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed var(--app-border);

  .refs-title {
    font-size: 12px;
    color: var(--el-text-color-secondary);
    margin-bottom: 4px;
  }

  .ref-chip {
    display: inline-block;
    margin: 0 6px 4px 0;
    padding: 1px 8px;
    border-radius: 4px;
    background: var(--el-color-primary-light-9);
    color: var(--el-color-primary);
    font-size: 12px;
    text-decoration: none;
  }
}

.thinking {
  display: inline-flex;
  gap: 4px;
  align-items: center;

  span {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--el-text-color-secondary);
    animation: blink 1.2s infinite ease-in-out;

    &:nth-child(2) {
      animation-delay: 0.2s;
    }

    &:nth-child(3) {
      animation-delay: 0.4s;
    }
  }
}

@keyframes blink {
  0%,
  80%,
  100% {
    opacity: 0.25;
  }

  40% {
    opacity: 1;
  }
}

.copilot-input {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  padding-top: 10px;
  border-top: 1px solid var(--app-border-light);
}
</style>

<style>
/* 抽屉体改为纵向 flex，让输入区固定底部、会话区滚动 */
.el-drawer__body:has(.copilot) {
  display: flex;
  flex-direction: column;
  padding: 12px 16px 16px;
}

.el-drawer__body:has(.copilot) .copilot {
  flex: 1;
}
</style>
