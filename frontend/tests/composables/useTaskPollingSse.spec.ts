import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { ref } from 'vue'
import { useTaskPolling } from '@/composables/useTaskPolling'
import { eventStreamStatus, onServerEvent, resetEventStreamForTest } from '@/composables/useEventStream'
import { useAuthStore } from '@/stores/auth'
import { getTask } from '@/api/tasks'

vi.mock('@/api/tasks', () => ({
  getTask: vi.fn(),
}))

const mockedGetTask = vi.mocked(getTask)

function taskOf(status: string) {
  return { task_id: 1, task_name: 't', status, domain: 'fund' } as never
}

// 最小 EventSource 桩：可手动派发 message、报告状态
class FakeEventSource {
  static instances: FakeEventSource[] = []
  static CONNECTING = 0
  static OPEN = 1
  static CLOSED = 2
  readyState = FakeEventSource.CONNECTING
  onopen: (() => void) | null = null
  onmessage: ((e: { data: string }) => void) | null = null
  onerror: (() => void) | null = null
  constructor(public url: string) {
    FakeEventSource.instances.push(this)
  }
  emit(data: unknown) {
    this.readyState = FakeEventSource.OPEN
    this.onopen?.()
    this.onmessage?.({ data: JSON.stringify(data) })
  }
}

beforeEach(() => {
  vi.useFakeTimers()
  mockedGetTask.mockReset()
  FakeEventSource.instances = []
  vi.stubGlobal('EventSource', FakeEventSource as never)
  setActivePinia(createPinia())
  useAuthStore().token = 'test-token' // connect() 需要 token 才建连
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  resetEventStreamForTest()
})

describe('useTaskPolling × SSE', () => {
  it('SSE open 时 start 不建定时器，事件到达触发防抖拉取', async () => {
    mockedGetTask.mockResolvedValue(taskOf('running'))
    const taskId = ref<number | null>(1)
    const { start, task } = useTaskPolling(taskId)
    start()
    expect(eventStreamStatus().value).toBe('connecting')
    const es = FakeEventSource.instances[0]
    es.emit({ type: 'hello', data: {} })
    expect(eventStreamStatus().value).toBe('open')
    expect(mockedGetTask).toHaveBeenCalledTimes(1) // start 的立即拉取

    // task_status 事件 → 500ms 防抖后拉取一次（风暴合并）
    es.emit({ type: 'task_status', task_id: 1, data: { status: 'running' } })
    es.emit({ type: 'task_status', task_id: 1, data: { status: 'running' } })
    await vi.advanceTimersByTimeAsync(499)
    expect(mockedGetTask).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(10)
    expect(mockedGetTask).toHaveBeenCalledTimes(2)
    expect(task.value?.status).toBe('running')
  })

  it('SSE 事件只响应匹配的 taskId', async () => {
    mockedGetTask.mockResolvedValue(taskOf('running'))
    const taskId = ref<number | null>(1)
    const { start } = useTaskPolling(taskId)
    start()
    const es = FakeEventSource.instances[0]
    es.emit({ type: 'hello', data: {} })
    es.emit({ type: 'task_status', task_id: 999, data: {} })
    await vi.advanceTimersByTimeAsync(1_000)
    expect(mockedGetTask).toHaveBeenCalledTimes(1) // 仅 start 那次
  })

  it('终态事件后不再响应后续事件', async () => {
    mockedGetTask.mockResolvedValueOnce(taskOf('running'))
    mockedGetTask.mockResolvedValue(taskOf('completed'))
    const taskId = ref<number | null>(1)
    const { start } = useTaskPolling(taskId)
    start()
    const es = FakeEventSource.instances[0]
    es.emit({ type: 'hello', data: {} })
    es.emit({ type: 'task_status', task_id: 1, data: { status: 'completed' } })
    await vi.advanceTimersByTimeAsync(600)
    const calls = mockedGetTask.mock.calls.length
    es.emit({ type: 'task_stage', task_id: 1, data: {} })
    await vi.advanceTimersByTimeAsync(1_000)
    expect(mockedGetTask.mock.calls.length).toBe(calls) // 终态停表，stage 不再拉取
  })

  it('onServerEvent 返回退订函数', () => {
    const off = onServerEvent('task_status', () => {})
    expect(typeof off).toBe('function')
    off()
  })
})
