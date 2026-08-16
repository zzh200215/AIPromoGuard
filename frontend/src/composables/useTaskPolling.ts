/** 任务进度轮询：每 2s 拉取 GET /tasks/{id}，终态自动停表，组件卸载清理。 */
import { onBeforeUnmount, ref, type Ref } from 'vue'
import { getTask } from '@/api/tasks'
import type { TaskOut } from '@/types/task'

const POLL_INTERVAL = 2000
const TERMINAL = ['completed', 'failed', 'cancelled']

export function useTaskPolling(taskId: Ref<number | null>) {
  const task = ref<TaskOut | null>(null)
  const error = ref(false)
  let timer: ReturnType<typeof setInterval> | null = null

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
      if (TERMINAL.includes(task.value.status)) stop()
    } catch {
      error.value = true
      stop()
    }
  }

  const start = () => {
    if (timer) return
    void poll()
    timer = setInterval(poll, POLL_INTERVAL)
  }

  onBeforeUnmount(stop)

  return { task, error, start, stop }
}
