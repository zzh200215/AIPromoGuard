/** 人工复核结果接口。 */
import { request } from './request'
import type {
  ConfirmRequest,
  FeedbackStats,
  ReviewResult,
  ResultStatus,
  RuleQualityItem,
  RuleSuggestion,
} from '@/types/result'
import type { Rule } from '@/types/rule'

/**
 * 任务复核结论列表。
 * order='priority'（PR-2 起的默认）：低置信×高风险优先（R4-3 复核路由——AI 最拿不准
 * 且危害最大的排前）；order='id' 为检出顺序（自然序）。后端两种排序均受支持，
 * 组件内仍各自显式排序一次——开关切"检出顺序"时不依赖返回顺序，语义稳定。
 */
export const listResults = (
  taskId: number,
  status?: ResultStatus,
  order: 'id' | 'priority' = 'priority',
) =>
  request<{ task_id: number; total: number; items: ReviewResult[] }>({
    url: `/tasks/${taskId}/results`,
    method: 'get',
    params: { status, order },
  })

export const confirmResult = (resultId: number, body: ConfirmRequest) =>
  request<{
    result_id: number
    status: string
    confirmed_by: number
    confirmed_at: string
    auto_confirmed: boolean
  }>({
    url: `/results/${resultId}/confirm`,
    method: 'post',
    data: body,
  })

/** 批量人工判定（确认 / 剔除误报）；无权访问的条目在 skipped 中逐条说明 */
export const bulkConfirmResults = (body: {
  result_ids: number[]
  verdict: 'confirmed' | 'false_positive'
  note?: string
}) =>
  request<{ updated: number; skipped: Array<{ result_id: number; reason: string }> }>({
    url: '/results/bulk-confirm',
    method: 'post',
    data: body,
  })

/** 撤销人工判定：恢复为待复核（批量误操作的「撤销」用） */
export const revertResults = (body: { result_ids: number[]; note?: string }) =>
  request<{ updated: number; skipped: Array<{ result_id: number; reason: string }> }>({
    url: '/results/revert',
    method: 'post',
    data: body,
  })

export const feedbackStats = () =>
  request<FeedbackStats>({ url: '/results/feedback-stats', method: 'get' })

/** 结论生命周期时间线（F2-3）：检出 → 系统分流 → 人工判定/翻案 → 撤销 */
export interface TrailEvent {
  at: string
  type: 'detected' | 'auto_confirmed' | 'confirm' | 'overturn' | 'revert'
  actor: string
  detail: string
}

export const getResultTrail = (resultId: number) =>
  request<{ result_id: number; task_id: number; events: TrailEvent[] }>({
    url: `/results/${resultId}/trail`,
    method: 'get',
  })

export const rulesQuality = () =>
  request<{ total: number; items: RuleQualityItem[] }>({
    url: '/results/rules/quality',
    method: 'get',
  })

export const listRuleSuggestions = () =>
  request<{ total: number; items: RuleSuggestion[] }>({
    url: '/results/rules/suggestions',
    method: 'get',
  })

export const applyRuleSuggestion = (
  ruleId: number,
  body: { action: string; condition_index?: number; keyword?: string },
) =>
  request<Rule>({
    url: `/results/rules/${ruleId}/apply-suggestion`,
    method: 'post',
    data: body,
  })
