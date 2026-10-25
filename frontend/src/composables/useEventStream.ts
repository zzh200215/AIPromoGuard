/**
 * SSE 事件流连接器（P1 实时推送）：单例 EventSource + 类型订阅分发。
 *
 * - 认证：EventSource 不能带 Authorization 头，token 走 ?token= 查询参数；
 * - 重连：EventSource 原生自动重连（服务端 retry: 3000）；401 关闭后由
 *   useAuthStore 重新登录流程兜底，此处不再无限重试坏 token；
 * - 兜底：connected === false 时调用方应回退轮询（各页面已有轮询实现）。
 */
import { readonly, ref } from 'vue'
import { useAuthStore } from '@/stores/auth'

export type ServerEvent = {
  type: string
  task_id: number | null
  batch_id: number | null
  user_id: number | null
  data: Record<string, unknown>
  ts: number
}

type Handler = (e: ServerEvent) => void

const status = ref<'connecting' | 'open' | 'closed'>('closed')
const handlers = new Map<string, Set<Handler>>() // type -> handlers；'*' = 全部
let source: EventSource | null = null

function dispatch(raw: MessageEvent) {
  let event: ServerEvent
  try {
    event = JSON.parse(raw.data) as ServerEvent
  } catch {
    return
  }
  handlers.get(event.type)?.forEach((h) => h(event))
  handlers.get('*')?.forEach((h) => h(event))
}

function connect() {
  if (typeof EventSource === 'undefined') return // jsdom/SSR 无实现：保持 closed，调用方走轮询兜底
  const auth = useAuthStore()
  if (!auth.token || source) return
  status.value = 'connecting'
  const es = new EventSource(`/api/v1/events?token=${encodeURIComponent(auth.token)}`)
  source = es
  es.onopen = () => {
    status.value = 'open'
  }
  es.onmessage = dispatch
  es.onerror = () => {
    // EventSource 会自动重连；readyState CLOSED 表示无法恢复（如 401）
    if (es.readyState === EventSource.CLOSED) {
      status.value = 'closed'
      source = null
    } else {
      status.value = 'connecting'
    }
  }
}

/** 订阅事件；'*' 订阅全部。返回退订函数。 */
export function onServerEvent(type: string, handler: Handler): () => void {
  if (!source) connect()
  let set = handlers.get(type)
  if (!set) {
    set = new Set()
    handlers.set(type, set)
  }
  set.add(handler)
  return () => {
    set?.delete(handler)
  }
}

/** 当前连接状态（只读）。'open' 才可信；否则调用方应保留轮询兜底。 */
export function eventStreamStatus() {
  return readonly(status)
}

/** 测试专用：清空单例连接与订阅（生产代码勿用）。 */
export function resetEventStreamForTest() {
  source = null
  status.value = 'closed'
  handlers.clear()
}
