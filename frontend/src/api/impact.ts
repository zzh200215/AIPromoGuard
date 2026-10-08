/** 法规影响中心接口。 */
import type { AxiosResponse } from 'axios'
import { request } from './request'
import type { Page, PaginationParams } from '@/types/api'
import type {
  AssessmentDetail,
  AssessmentStatus,
  CreateBatchResult,
  ImpactAssessment,
  ImpactOverview,
  ImpactPenaltyCase,
  MaterialCreateBody,
  MaterialLedger,
  PatrolDiff,
  RemediationItem,
  RetestResult,
  StaleSyncResult,
} from '@/types/impact'
import type { Rule } from '@/types/rule'

export const impactOverview = () =>
  request<ImpactOverview>({ url: '/impact/overview', method: 'get' })

export const listMaterials = (
  params: {
    page?: number
    page_size?: number
    product_type?: string
    status?: string
    last_review_status?: string
    patrol_status?: string
  },
) =>
  request<{ total: number; items: MaterialLedger[] }>({
    url: '/impact/materials',
    method: 'get',
    params,
  })

export const createMaterial = (body: MaterialCreateBody) =>
  request<MaterialLedger>({ url: '/impact/materials', method: 'post', data: body })

export const updateMaterial = (
  id: number,
  body: Partial<MaterialCreateBody> & { status?: string },
) => request<MaterialLedger>({ url: `/impact/materials/${id}`, method: 'patch', data: body })

/** R3-1 发布后巡检：批量抓取已登记 publish_url 的在用材料，与批准版比对（mock fetcher 供测试注入在后端） */
export const patrolMaterials = (materialIds?: number[]) =>
  request<{
    checked: number
    counts: Record<string, number>
    outcomes: Array<{
      material_id: number
      name: string
      status: string
      detail?: string
      review_task_id?: number | null
    }>
  }>({
    url: '/impact/materials/patrol',
    method: 'post',
    data: { material_ids: materialIds ?? null },
    timeout: 180_000,
  })

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
  decision: 'remediate' | 'reject' | 'done',
  identifier: { taskId?: number; materialId?: number },
) =>
  request<{ items: RemediationItem[] }>({
    url: `/impact/assessments/${id}/remediation`,
    method: 'post',
    // 审查整改项传 task_id；stale 待更新项（无审查任务）传 material_id
    data: {
      task_id: identifier.taskId ?? null,
      material_id: identifier.taskId == null ? (identifier.materialId ?? null) : null,
      decision,
    },
  })

/** 依据失效材料写入系统整改清单（R3-2 v2）：返回增量计数、容器评估 id 与高亮条目。 */
export const syncStaleMaterials = () =>
  request<StaleSyncResult>({
    url: '/impact/materials/stale/sync',
    method: 'post',
  })

/** 巡检差异详情（材料台账「差异详情」抽屉）：批准版 vs 线上存档快照。 */
export const getPatrolDiff = (materialId: number) =>
  request<PatrolDiff>({
    url: `/impact/materials/${materialId}/patrol-diff`,
    method: 'get',
  })

/** 上传整改版材料并发起复测（multipart：file + assessment_id）。 */
export const retestMaterial = (materialId: number, assessmentId: number, file: File) => {
  const form = new FormData()
  form.append('assessment_id', String(assessmentId))
  form.append('file', file)
  return request<RetestResult>({
    url: `/impact/materials/${materialId}/retest`,
    method: 'post',
    data: form,
    timeout: 120_000,
  })
}

/** 整改清单导出 Excel（blob 下载，文件名取自 Content-Disposition）。 */
export async function exportRemediation(assessmentId: number): Promise<void> {
  const res = await request<AxiosResponse<Blob>>({
    url: `/impact/assessments/${assessmentId}/remediation/export`,
    method: 'get',
    responseType: 'blob',
  })
  const disposition = res.headers['content-disposition'] as string | null
  const match = disposition?.match(/filename\*=UTF-8''([^;]+)/)
  const filename = match ? decodeURIComponent(match[1]) : `整改清单-${assessmentId}.xlsx`
  const url = URL.createObjectURL(res.data)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}
