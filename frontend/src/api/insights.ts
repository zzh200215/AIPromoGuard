/** 合规洞察接口。 */
import { request } from './request'
import type { InsightOverview } from '@/types/insights'

export const insightsOverview = () =>
  request<InsightOverview>({ url: '/insights/overview', method: 'get' })
