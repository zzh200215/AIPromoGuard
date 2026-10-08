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

export interface RemediationItem {
  batch_id?: number
  task_id?: number
  task_status?: string
  material_id: number | null
  material_name: string
  violation_count?: number
  requires_remediation: boolean
  decision: 'pending' | 'remediate' | 'reject' | 'done'
  /** 本条为整改复测结果条目（针对 retest_for_task_id 指向的原整改项） */
  retest?: boolean
  retest_for_task_id?: number
  /** 原整改项发起的复测任务 id（复测完成前可据此显示"复测中"） */
  retest_task_id?: number
  /** R3-2 v2：依据失效待更新条目（无审查任务，按 material_id 定位决策） */
  kind?: 'stale'
  /** stale 条目的失效依据清单（规则停用/法规废止） */
  reasons?: string[]
  /** stale 条目的材料版本号 */
  version?: string
  last_review_status?: string | null
  /** 依据恢复被系统自动关闭时的说明（存在即表示系统关闭，非人工） */
  resolved?: string
}

export interface RetestResult {
  batch_id: number
  task_id: number
  version: string
  material_id: number
  document_id: string
}

export interface ImpactItems {
  rules: ImpactRuleItem[]
  materials: ImpactMaterialItem[]
  remediation?: RemediationItem[]
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

export interface ImpactOverview {
  pending_updates: number
  updates_to_analyze: number
  pending_assessments: number
  assessments_by_status: Record<string, number>
  high_risk_materials: number
  running_batches: number
  remediation_total: number
  remediation_pending: number
  remediation_done: number
  rules_pending_publish: number
  active_rules: number
  /** R3-2 时效性告警：规则停用/法规废止反向定位的在用材料 */
  stale_materials: {
    checked: number
    stale_count: number
    materials: Array<{
      material_id: number
      name: string
      version: string
      last_review_status?: string | null
      reasons: string[]
    }>
  }
  /** R3-1 巡检动态：线上内容被改/页面失联的在用材料计数 */
  patrol_counts: Record<string, number>
  patrol_changed: number
  patrol_gone: number
}

export interface ImpactPenaltyCase {
  id: number
  case_name: string
  penalty_org?: string | null
  penalty_date?: string | null
  violation_summary?: string | null
  related_regulation_count: number
}

export interface MaterialLedger {
  id: number
  name: string
  product_type: string
  material_type: string
  version: string
  owner?: string | null
  document_id?: string | null
  status: string
  last_review_status?: string | null
  last_reviewed_at?: string | null
  /** R3-1 发布后巡检：已授权自有渠道的线上地址 */
  publish_url?: string | null
  /** 发布渠道：web / wechat / douyin 等 */
  channel?: string | null
  /** 巡检结论：ok / drift / changed / gone / error（null=未巡检） */
  patrol_status?: string | null
  patrol_checked_at?: string | null
  created_at: string
}

export interface MaterialCreateBody {
  name: string
  product_type: 'fund' | 'insurance' | 'wealth'
  material_type: string
  version?: string
  owner?: string
  document_id?: string
  publish_url?: string
  channel?: string
}

/** 巡检差异片段（批准版 → 线上版，来自 diff_service 块级比对）。 */
export interface PatrolDiffChange {
  change_type: 'added' | 'removed' | 'modified'
  change_id: string
  /** 批准版文本（added 时为空） */
  old_text: string
  /** 线上版文本（removed 时为空） */
  new_text: string
  block_index?: number | null
  block_count?: number
}

/** 巡检差异详情（GET /impact/materials/{id}/patrol-diff）：批准版 vs 线上存档快照。 */
export interface PatrolDiff {
  material_id: number
  name: string
  version: string
  patrol_status?: string | null
  patrol_checked_at?: string | null
  /** 有线上快照且批准版可解析时为 true；否则看 reason */
  available: boolean
  reason?: string | null
  /** 批准版内容在线上快照中的保留率（containment，0~1） */
  similarity?: number | null
  /** 批准版中消失的关键数字（被删/被改的高危信号） */
  missing_numbers: string[]
  changes: PatrolDiffChange[]
  change_count: number
  approved_file?: string | null
  online_file?: string | null
  online_archived_at?: string | null
  /** changed 时自动创建的复审任务（无则 null） */
  review_task_id?: number | null
}

/** 依据失效同步结果：highlight_ids = 本轮新增/刷新/重开的待办条目（整改清单高亮）。 */
export interface StaleSyncResult {
  assessment_id: number
  checked: number
  stale_count: number
  added: number
  refreshed: number
  resolved: number
  reopened: number
  total: number
  highlight_ids: number[]
}
