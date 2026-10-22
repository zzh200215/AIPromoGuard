/** 合规洞察接口类型。 */
export interface InsightCount {
  key: string
  count: number
}

export interface InsightTopItem {
  name: string
  count: number
}

export interface InsightFunnelStep {
  label: string
  value: number
}

export interface InsightTrendPoint {
  date: string
  count: number
}

export interface InsightCards {
  tasks_total: number
  tasks_completed: number
  findings_total: number
  confirmed: number
  pending: number
  false_positive: number
  confirm_rate: number | null
  review_coverage: number | null
  materials_total: number
  materials_violation: number
  materials_clean: number
  batches_total: number
  batches_completed: number
}

export interface InsightOverview {
  cards: InsightCards
  risk: InsightCount[]
  sources: InsightCount[]
  rules_top: InsightTopItem[]
  regulations_top: InsightTopItem[]
  trend: InsightTrendPoint[]
  review_funnel: InsightFunnelStep[]
  remediation: {
    materials_total: number
    violation: number
    remediated: number
    clean: number
  }
  material_types: InsightTopItem[]
}
