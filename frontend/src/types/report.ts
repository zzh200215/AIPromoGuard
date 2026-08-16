/** 审查报告类型（对齐 src/api/routers/reports.py 返回的 JSON 报告）。 */

export interface ReportSummary {
  total_violations: number
  high_risk: number
  medium_risk: number
  low_risk: number
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

export interface ReportData {
  report_version: string
  task_id: number
  document_name: string
  domain?: string
  generated_at: string
  summary: ReportSummary
  violations: ViolationItem[]
  /** 未完成时存在：报告生成中占位 */
  message?: string
}
