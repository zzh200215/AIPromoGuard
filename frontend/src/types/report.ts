/** 审查报告类型（对齐 src/api/routers/reports.py 返回的 JSON 报告）。 */

export interface ReportSummary {
  total_violations: number
  high_risk: number
  medium_risk: number
  low_risk: number
  /** 待人工核验项数量（见 src/core/report/generator.py） */
  pending_verification?: number
}

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
  /** 未完成时存在：报告生成中占位 */
  message?: string
}
