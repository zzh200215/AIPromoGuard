/** 系统监控接口。 */
import { request } from './request'
import type { GraphStats } from '@/types/graph'

export interface SystemMonitor {
  timestamp: string
  tasks: {
    [status: string]: number
    last_24h: number
    avg_duration_seconds?: number
  }
  database: {
    ok: boolean
    knowledge_base: { regulations: number; rules: number; users: number }
  }
  /** 知识库飞轮动态：最近入库/发布（驱动舱侧栏"看起来在长"） */
  recent_activity?: {
    regulations: Array<{ id: number; name: string; created_at?: string | null }>
    rules: Array<{ id: number; name: string; status?: string; updated_at?: string | null }>
    penalty_cases: Array<{ id: number; name: string; penalty_date?: string | null }>
  }
  vector_store: { legal_articles: number; legal_penalty_cases: number }
  graph: GraphStats
  /** 未启用队列模式或 Redis 不可用时 available=false，queue_depth=-1 */
  celery?: {
    available: boolean
    queue_depth: number
    workers_alive: string[]
  }
  audit: { last_24h: number; errors_last_24h: number }
}

export const systemMonitor = () =>
  request<SystemMonitor>({ url: '/system/monitor', method: 'get' })
