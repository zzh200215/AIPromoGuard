/** AI Copilot：审查问答与合规改写。 */
import { request } from './request'

export interface CopilotRef {
  regulation_id: number | null
  name: string
  article_no?: string | null
  quote?: string | null
}

export interface AskResponse {
  answer: string
  refs: CopilotRef[]
  /** 本次回答实际使用的工具调用次数（0 = 未触发工具） */
  tools_used?: number
}

export interface RewriteResponse {
  rewritten: string
  changes: string[]
}

/** 任务审查问答：回答附法规引用（regulation_id 已过服务端校验，可直接跳转） */
export const askTask = (taskId: number, question: string) =>
  request<AskResponse>({ url: `/ai/tasks/${taskId}/ask`, method: 'post', data: { question } })

export interface HistoryMessage {
  id: number
  role: 'user' | 'assistant'
  content: string
  refs: CopilotRef[]
  created_at: string | null
}

/** 任务问答历史（时间正序）：抽屉打开时恢复服务端持久化会话 */
export const askTaskHistory = (taskId: number) =>
  request<{ messages: HistoryMessage[] }>({ url: `/ai/tasks/${taskId}/ask-history`, method: 'get', silent: true })

/** 单条违规的合规改写：返回改写文案与逐条修改说明 */
export const rewriteResult = (resultId: number) =>
  request<RewriteResponse>({ url: `/ai/results/${resultId}/rewrite`, method: 'post' })

export interface SummaryResponse {
  text: string
  model: string
  generated_at: string
  /** 报告结论变化后标记过期（服务端会在下次访问时自动重算） */
  stale: boolean
}

export interface VerdictAdvice {
  suggested_verdict: 'confirmed' | 'false_positive'
  confidence: number
  reasons: string[]
}

/** 报告风险综述：随报告落盘进导出留档链路；force=true 强制重新生成 */
export const summarizeTask = (taskId: number, force = false) =>
  request<SummaryResponse>({
    url: `/ai/tasks/${taskId}/summary`,
    method: 'post',
    data: { force },
    silent: true,
  })

/** 判定辅助：AI 预判成立/误报与理由（自动预取，失败静默） */
export const getVerdictAdvice = (resultId: number) =>
  request<VerdictAdvice>({
    url: `/ai/results/${resultId}/verdict-advice`,
    method: 'post',
    silent: true,
  })
