import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { useTaskPolling } from '@/composables/useTaskPolling'
import { getTask } from '@/api/tasks'

vi.mock('@/api/tasks', () => ({
  getTask: vi.fn(),
}))

const mockedGetTask = vi.mocked(getTask)

function taskOf(status: string) {
  return { task_id: 1, task_name: 't', status, domain: 'fund' } as never
}

beforeEach(() => {
  vi.useFakeTimers()
  mockedGetTask.mockReset()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('useTaskPolling', () => {
  it('start 后立即拉取一次并更新 task', async () => {
    mockedGetTask.mockResolvedValue(taskOf('completed'))
    const taskId = ref<number | null>(1)
    const { task, start } = useTaskPolling(taskId)
    start()
    // start 内首个 poll 是 async，先让出微任务
    await vi.advanceTimersByTimeAsync(0)
    expect(mockedGetTask).toHaveBeenCalledWith(1)
    expect(task.value?.status).toBe('completed')
  })

  it('终态（completed/failed/cancelled）自动停表', async () => {
    mockedGetTask.mockResolvedValue(taskOf('completed'))
    const taskId = ref<number | null>(1)
    const { start, task } = useTaskPolling(taskId)
    start()
    await vi.advanceTimersByTimeAsync(0)
    expect(task.value?.status).toBe('completed')
    // 再走 10 个轮询周期，不应有新请求
    await vi.advanceTimersByTimeAsync(20_000)
    expect(mockedGetTask).toHaveBeenCalledTimes(1)
  })

  it('非终态持续轮询，每 2s 一次', async () => {
    mockedGetTask.mockResolvedValue(taskOf('running'))
    const taskId = ref<number | null>(1)
    const { start } = useTaskPolling(taskId)
    start()
    await vi.advanceTimersByTimeAsync(6_000)
    // 首次立即 + 2s/4s/6s 三次周期 = 4 次
    expect(mockedGetTask).toHaveBeenCalledTimes(4)
  })

  it('拉取失败置 error 并停表', async () => {
    mockedGetTask.mockRejectedValue(new Error('boom'))
    const taskId = ref<number | null>(1)
    const { start, error } = useTaskPolling(taskId)
    start()
    await vi.advanceTimersByTimeAsync(0)
    expect(error.value).toBe(true)
    await vi.advanceTimersByTimeAsync(10_000)
    expect(mockedGetTask).toHaveBeenCalledTimes(1)
  })

  it('taskId 为 null 时轮询静默跳过', async () => {
    const taskId = ref<number | null>(null)
    const { start } = useTaskPolling(taskId)
    start()
    await vi.advanceTimersByTimeAsync(10_000)
    expect(mockedGetTask).not.toHaveBeenCalled()
  })

  it('stop 手动停表后不再轮询', async () => {
    mockedGetTask.mockResolvedValue(taskOf('running'))
    const taskId = ref<number | null>(1)
    const { start, stop } = useTaskPolling(taskId)
    start()
    await vi.advanceTimersByTimeAsync(0)
    stop()
    await vi.advanceTimersByTimeAsync(20_000)
    expect(mockedGetTask).toHaveBeenCalledTimes(1)
  })
})
