/** 监管动态追踪接口。 */
import { request } from './request'
import type { Page, PaginationParams } from '@/types/api'
import type { ConfirmBody, ManualCreate, RegulationUpdate } from '@/types/regulationTrend'

export interface FetchSummary {
  sources: Record<
    string,
    { fetched: number; new: number; duplicate: number; in_db: number; error: string | null }
  >
  errors: string[]
}

export const listRegulationTrends = (
  params: PaginationParams & { status?: string; source?: string },
) => request<Page<RegulationUpdate>>({ url: '/regulatory-updates', method: 'get', params })

export const getRegulationTrend = (id: number) =>
  request<RegulationUpdate>({ url: `/regulatory-updates/${id}`, method: 'get' })

export const fetchRegulationTrends = () =>
  request<FetchSummary>({ url: '/regulatory-updates/fetch', method: 'post' })

export const confirmRegulationTrend = (id: number, body: ConfirmBody) =>
  request<{ regulation_id: number; regulation_name: string }>({
    url: `/regulatory-updates/${id}/confirm`,
    method: 'post',
    data: body,
  })

export const ignoreRegulationTrend = (id: number) =>
  request<null>({ url: `/regulatory-updates/${id}/ignore`, method: 'post' })

export const createRegulationTrend = (body: ManualCreate) =>
  request<RegulationUpdate>({ url: '/regulatory-updates', method: 'post', data: body })
