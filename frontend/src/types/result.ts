/** 人工复核结果类型（对齐 src/api/routers/results.py）。 */

export type ResultStatus = 'pending_confirm' | 'confirmed' | 'false_positive'

export interface ReviewResult {
  result_id: number
  violation_type: 'rule' | 'llm' | 'hybrid' | 'vlm'
  /**
   * 内置维度身份（F1-2）：pii=敏感信息 / consistency=数字勾稽 / tamper=疑似篡改 /
   * visual=视觉层其余发现；null=普通规则/LLM 命中（来源看 violation_type）。
   * 后端由落库 description 头部的 [rule_name] 前缀派生。
   */
  finding_kind?: 'pii' | 'consistency' | 'tamper' | 'visual' | null
  risk_level: Severity
  original_text: string
  location_page?: number
  location_paragraph?: number
  rule_id?: number
  confidence_score: number
  description?: string
  suggestion?: string
  status: ResultStatus
  confirmed_at?: string
  confirmed_by?: number
  /** 系统自动确认（方向②分流，confirmed_by=0）；人工复核/翻案后为 false */
  auto_confirmed?: boolean
  /** 法规溯源：规则-法规关联反查的结构化依据（无关联时为 null） */
  regulation_id?: number | null
  article_id?: number | null
  regulation_name?: string | null
  regulation_no?: string | null
  article_no?: string | null
  article_excerpt?: string | null
}

export interface ConfirmRequest {
  verdict: 'confirmed' | 'false_positive'
  note?: string
}

export interface SourceStats {
  confirmed: number
  false_positive: number
  pending_confirm: number
  confirm_rate: number | null
  false_positive_rate: number | null
}

export interface FeedbackStats {
  by_source: Record<string, SourceStats>
  totals: Record<ResultStatus, number>
  overall_false_positive_rate: number | null
}

export interface RuleQualityItem {
  rule_id: number
  rule_name?: string
  hits: number
  confirmed: number
  false_positive: number
  pending_confirm: number
  confirm_rate: number
  false_positive_rate: number
}

/** 规则精调建议（方向③，src/services/rule_tuning.py） */
export interface RuleSuggestion {
  rule_id: number
  rule_name: string
  domain: string
  severity: Severity
  action: 'deactivate' | 'remove_keyword'
  keyword?: string
  condition_index?: number
  reason: string
  confirmed: number
  false_positive: number
  fp_rate: number
  fp_samples: string[]
}
