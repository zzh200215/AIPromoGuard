/** 规则类型（对齐 scripts/init_data/rules.json 的 DSL 与 src/core/rule_engine/matchers）。 */

export type RuleType = 'regex' | 'keyword' | 'condition' | 'composite'

export type RuleOperator = 'OR' | 'AND'

/** 单个条件：regex 或 keyword 二选一（见 matchers） */
export interface RuleCondition {
  type: 'regex' | 'keyword'
  pattern?: string
  keywords?: string[]
  match_mode?: 'any' | 'all'
  context_window?: number
  /** 否定语境抑制窗口，0 关闭 */
  negation_window?: number
}

export interface RuleContent {
  operator: RuleOperator
  conditions: RuleCondition[]
  related_regulations?: string[]
}

export interface Rule {
  id: number
  domain: string
  rule_name: string
  rule_type: RuleType
  rule_content: RuleContent
  severity: Severity
  description?: string
  /** 0/1 布尔存储 */
  is_active: number
  version: number
  created_at: string
  updated_at: string
}

export interface RuleCreate {
  domain: string
  rule_name: string
  rule_type: RuleType
  rule_content: RuleContent
  severity?: Severity
  description?: string
  is_active?: boolean
}

export type RuleUpdate = Partial<RuleCreate>
