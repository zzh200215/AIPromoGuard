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
  vector_store: { legal_articles: number; legal_penalty_cases: number }
  graph: GraphStats
  audit: { last_24h: number; errors_last_24h: number }
}

export const systemMonitor = () =>
  request<SystemMonitor>({ url: '/system/monitor', method: 'get' })
