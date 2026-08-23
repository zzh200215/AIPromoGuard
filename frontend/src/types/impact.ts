/** 法规影响中心类型（对齐 src/api/routers/impact.py 与 schemas/impact.py）。 */

export type AssessmentStatus = 'draft' | 'pending_review' | 'confirmed' | 'dismissed'

export interface ImpactRuleItem {
  rule_id: number
  rule_name: string
  domain: string
  severity: string
  matched_by: 'link' | 'keyword'
  confirm_status: string
}

export interface ImpactMaterialItem {
  material_id: number
  name: string
  product_type: string
  material_type: string
  owner?: string | null
  document_id?: string | null
  last_review_status?: string | null
  matched_rules: number[]
  risk_score: number
  risk_level: 'high' | 'medium' | 'low'
  reason: string
  evidence_penalty_case_ids: number[]
  confirm_status: string
}

export interface ImpactItems {
  rules: ImpactRuleItem[]
  materials: ImpactMaterialItem[]
}

export interface ImpactAssessment {
  id: number
  regulation_update_id?: number | null
  title: string
  summary?: string | null
  status: AssessmentStatus
  items?: ImpactItems | null
  high_count: number
  medium_count: number
  low_count: number
  created_by?: number | null
  confirmed_by?: number | null
  confirmed_at?: string | null
  created_at: string
  update_title?: string
}

export interface AssessmentUpdateInfo {
  id: number
  title: string
  source: string
  publish_date?: string | null
}

export interface AssessmentBatchSummary {
  id: number
  batch_name: string
  status: string
  total_count: number
  completed_count: number
}

export interface AssessmentDetail extends ImpactAssessment {
  update?: AssessmentUpdateInfo | null
  batches: AssessmentBatchSummary[]
}

export interface CreateBatchResult {
  batch_id: number
  batch_name: string
  total_count: number
  task_ids: number[]
  skipped: Array<{ material_id?: number; name?: string; reason: string }>
}
