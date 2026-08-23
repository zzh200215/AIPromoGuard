/** 法规影响中心接口。 */
import { request } from './request'
import type { Page, PaginationParams } from '@/types/api'
import type {
  AssessmentDetail,
  AssessmentStatus,
  CreateBatchResult,
  ImpactAssessment,
} from '@/types/impact'

export const listAssessments = (params: PaginationParams & { status?: AssessmentStatus }) =>
  request<Page<ImpactAssessment>>({ url: '/impact/assessments', method: 'get', params })

export const createAssessment = (regulationUpdateId: number) =>
  request<ImpactAssessment>({
    url: '/impact/assessments',
    method: 'post',
    data: { regulation_update_id: regulationUpdateId },
  })

export const getAssessment = (id: number) =>
  request<AssessmentDetail>({ url: `/impact/assessments/${id}`, method: 'get' })

export const confirmAssessment = (
  id: number,
  body: { action: 'confirm' | 'dismiss'; rule_ids?: number[]; material_ids?: number[] },
) =>
  request<ImpactAssessment & { created_links: number }>({
    url: `/impact/assessments/${id}/confirm`,
    method: 'post',
    data: body,
  })

export const createAssessmentBatch = (id: number, materialIds: number[]) =>
  request<CreateBatchResult>({
    url: `/impact/assessments/${id}/batch`,
    method: 'post',
    data: { material_ids: materialIds },
  })
