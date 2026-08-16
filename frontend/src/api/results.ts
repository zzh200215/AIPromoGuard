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

export const listResults = (taskId: number, status?: ResultStatus) =>
  request<{ task_id: number; total: number; items: ReviewResult[] }>({
    url: `/tasks/${taskId}/results`,
    method: 'get',
    params: status ? { status } : undefined,
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

export const feedbackStats = () =>
  request<FeedbackStats>({ url: '/results/feedback-stats', method: 'get' })

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
