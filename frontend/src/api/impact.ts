/** 法规影响中心接口。 */
import { request } from './request'
import type { Page, PaginationParams } from '@/types/api'
import type {
  AssessmentDetail,
  AssessmentStatus,
  CreateBatchResult,
  ImpactAssessment,
  ImpactOverview,
  ImpactPenaltyCase,
  RemediationItem,
} from '@/types/impact'
import type { Rule } from '@/types/rule'

export const impactOverview = () =>
  request<ImpactOverview>({ url: '/impact/overview', method: 'get' })

export const listImpactPenaltyCases = (page = 1, pageSize = 10) =>
  request<{ total: number; items: ImpactPenaltyCase[] }>({
    url: '/impact/penalty-cases',
    method: 'get',
    params: { page, page_size: pageSize },
  })

export const minePenaltyRules = (caseId: number) =>
  request<{ items: Rule[] }>({
    url: `/impact/penalty-cases/${caseId}/mine-rules`,
    method: 'post',
  })

export const listAssessments = (params: PaginationParams & { status?: AssessmentStatus }) =>
  request<Page<ImpactAssessment>>({ url: '/impact/assessments', method: 'get', params })

export const createAssessment = (source: {
  regulation_update_id?: number
  penalty_case_id?: number
}) =>
  request<ImpactAssessment>({ url: '/impact/assessments', method: 'post', data: source })

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

export const listRemediation = (id: number) =>
  request<{ items: RemediationItem[] }>({
    url: `/impact/assessments/${id}/remediation`,
    method: 'get',
  })

export const decideRemediation = (
  id: number,
  taskId: number,
  decision: 'remediate' | 'reject' | 'done',
) =>
  request<{ items: RemediationItem[] }>({
    url: `/impact/assessments/${id}/remediation`,
    method: 'post',
    data: { task_id: taskId, decision },
  })
