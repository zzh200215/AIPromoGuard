/** 知识图谱查询与统计接口。 */
import { request } from './request'
import type { Domain } from '@/types/api'
import type { GraphCase, GraphQueryResult, GraphStats } from '@/types/graph'

export const queryGraph = (body: { query: string; domain?: Domain; top_k?: number }) =>
  request<GraphQueryResult>({ url: '/graph/query', method: 'post', data: body })

export const recommendCases = (body: { text: string; domain?: Domain; top_k?: number }) =>
  request<{ total: number; cases: GraphCase[] }>({
    url: '/graph/cases/recommend',
    method: 'post',
    data: body,
  })

export const graphStats = () => request<GraphStats>({ url: '/graph/stats', method: 'get' })
