/** 审查报告类型（对齐 src/api/routers/reports.py 返回的 JSON 报告）。 */

export interface ReportSummary {
  total_violations: number
  high_risk: number
  medium_risk: number
  low_risk: number
  /** 待人工核验项数量（见 src/core/report/generator.py） */
  pending_verification?: number
}

/** 人工复核结论状态（与 review_results.status 对齐） */
export type HumanStatus = 'pending_confirm' | 'confirmed' | 'false_positive'

/** 相似处罚案例（图谱推荐，risk_assess 注入） */
export interface RelatedCase {
  case_name: string
  penalty_org?: string
  penalty_date?: string
  penalty_result?: string
  summary?: string
  similarity: number
}

/** 单条违规（conflict_resolve + risk_assess 融合结果） */
export interface ViolationItem {
  source: 'rule' | 'llm' | 'hybrid'
  violation_type: 'rule' | 'llm' | 'hybrid'
  /** LLM 违规类型：禁止性/限制性/披露性 */
  type?: '禁止性' | '限制性' | '披露性'
  rule_id?: number
  rule_name?: string
  original_text: string
  page?: number
  paragraph?: number
  confidence: number
  severity: Severity
  description?: string
  related_regulations: string[]
  regulation?: string
  suggestion?: string
  /** LLM 单独检出的标记 */
  flag?: string
  risk_level: Severity
  risk_reason?: string
  related_cases: RelatedCase[]
  /** 人工复核结论（report_service 合并，与 results 表同序对齐） */
  human_status?: HumanStatus
  /** confirmed_by=0 表示系统自动确认 */
  human_confirmed_by?: number | null
  /** 关联审查结果 id（报告页批量判定用；未合并 results 时缺省） */
  result_id?: number
  regulation_id?: number | null
  article_id?: number | null
}

/** LLM 用量与预估成本（成本归因，随报告落盘；无 LLM 调用时省略） */
export interface LlmUsage {
  prompt_tokens?: number
  completion_tokens?: number
  total_tokens?: number
  calls?: number
  model?: string
  failed_blocks?: number
  /** 牌价预估（元）；未收录模型 priced=false 时为 null */
  estimated_cost_cny?: number | null
  priced?: boolean
}

/** 待人工核验项：机器无法闭环背书的存疑项（证据未命中/无引用/适当性需材料） */
export interface PendingVerificationItem {
  risk_level?: Severity
  original_text: string
  description?: string
  page?: number
  paragraph?: number
  reasons: string[]
}

/** 人工复核汇总（剔除误报后的 final_* 为对外口径） */
export interface HumanReviewSummary {
  pending_confirm: number
  confirmed: number
  false_positive: number
  auto_confirmed: number
  manual_reviewed: number
  final_total: number
  final_high: number
  final_medium: number
  final_low: number
  last_confirmed_at: string | null
}

/** 任务引用的法规（结构化，可点跳法规详情） */
export interface RegulationRef {
  id: number
  regulation_name: string
  regulation_no?: string | null
}

/** 审核签发：报告定稿后的正式放行/驳回结论（最新一次有效） */
export interface SignOffInfo {
  decision: 'released' | 'rejected'
  username: string
  note?: string | null
  created_at: string
}

export interface ReportData {
  report_version: string
  task_id: number
  document_name: string
  domain?: string
  generated_at: string
  summary: ReportSummary
  violations: ViolationItem[]
  llm_usage?: LlmUsage
  pending_verification?: PendingVerificationItem[]
  /** 人工复核结论汇总（报告已与最新判定同步） */
  human_review?: HumanReviewSummary
  /** 任务引用的法规（结构化，供前端可点跳转） */
  regulations?: RegulationRef[]
  /** 审核签发状态（实时合并；未签发为 null/缺省） */
  sign_off?: SignOffInfo | null
  /** 未完成时存在：报告生成中占位 */
  message?: string
}
