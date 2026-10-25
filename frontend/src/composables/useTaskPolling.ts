/**
 * 任务进度刷新：SSE 事件驱动（P1），2s 轮询作断线兜底。
 *
 * - SSE open：订阅 task_status / task_stage 事件，事件到达即拉取一次
 *   （500ms 防抖合并事件风暴），不跑定时器；
 * - SSE 未 open：回退 2s 轮询（与历史行为一致）；
 * - 终态自动停表，组件卸载清理。
 */
import { onBeforeUnmount, ref, watch, type Ref } from 'vue'
import { getTask } from '@/api/tasks'
import { eventStreamStatus, onServerEvent } from '@/composables/useEventStream'
import type { TaskOut } from '@/types/task'

const POLL_INTERVAL = 2000
const EVENT_DEBOUNCE = 500
const TERMINAL = ['completed', 'failed', 'cancelled']

export function useTaskPolling(taskId: Ref<number | null>) {
  const task = ref<TaskOut | null>(null)
  const error = ref(false)
  let timer: ReturnType<typeof setInterval> | null = null
  let debounceTimer: ReturnType<typeof setTimeout> | null = null
  const streamStatus = eventStreamStatus()

  const stop = () => {
    if (timer) {
      clearInterval(timer)
      timer = null
    }
  }

  const poll = async () => {
    if (taskId.value == null) return
    try {
      task.value = await getTask(taskId.value)
      error.value = false
      if (TERMINAL.includes(task.value.status)) stop()
    } catch {
      error.value = true
      stop()
    }
  }

  const pollDebounced = () => {
    if (debounceTimer) return
    debounceTimer = setTimeout(() => {
      debounceTimer = null
      void poll()
    }, EVENT_DEBOUNCE)
  }

  // SSE 事件 → 防抖拉取；无事件时由 SSE 自身保活，无需定时器
  const offStatus = onServerEvent('task_status', (e) => {
    if (e.task_id === taskId.value) pollDebounced()
  })
  const offStage = onServerEvent('task_stage', (e) => {
    if (e.task_id === taskId.value && !TERMINAL.includes(task.value?.status ?? '')) pollDebounced()
  })

  // 连接状态兜底：SSE 断开时启用轮询，恢复时停掉
  const ensureInterval = () => {
    if (!timer && !TERMINAL.includes(task.value?.status ?? '')) {
      timer = setInterval(poll, POLL_INTERVAL)
    }
  }
  watch(
    () => streamStatus.value,
    (s) => {
      if (s === 'open') stop()
      else ensureInterval()
    },
    { immediate: false },
  )

  const start = () => {
    if (streamStatus.value === 'open') {
      void poll()
      return
    }
    if (timer) return
    void poll()
    timer = setInterval(poll, POLL_INTERVAL)
  }

  onBeforeUnmount(() => {
    stop()
    if (debounceTimer) clearTimeout(debounceTimer)
    offStatus()
    offStage()
  })

  return { task, error, start, stop }
}
