/** 审查任务类型（对齐 src/api/schemas/task.py 与 review_service）。 */

/** task.status 枚举：DB 注释含 processing，实际写入 running，前端两种都兼容 */
export type TaskStatus =
  | 'pending'
  | 'running'
  | 'processing'
  | 'completed'
  | 'failed'
  | 'cancelled'

/** stages 结构：{ 节点名: {status, cost_ms, detail?} }
 * （W14 状态追踪 + 审查轨迹明细，见 src/core/agents/graph.py _stage_detail） */
export interface TaskStageDetail {
  status: string
  cost_ms: number
  /** 节点过程明细（审查轨迹面板数据源；enrich 上线前的旧任务无此字段） */
  detail?: StageNodeDetail
}

/** 各节点的过程明细字段（按节点名选用；全部来自 state 已有数据） */
export interface StageNodeDetail {
  /** classify */
  domain?: string | null
  /** regulation_match */
  article_count?: number
  top_articles?: Array<{ name: string; article_no?: string | null }>
  agentic_rounds?: number
  agentic_added?: number
  /** rule_scan */
  hit_count?: number
  /** llm_scan */
  finding_count?: number
  tokens?: number | null
  failed_blocks?: number | null
  model?: string | null
  /** conflict_resolve */
  merged_count?: number
  by_source?: Record<string, number>
  /** human_review */
  enabled?: boolean
  required?: boolean
  reviewed_count?: number
  rejected_count?: number
  /** risk_assess */
  by_risk?: Record<string, number>
  with_cases?: number
  /** report */
  total_violations?: number | null
}

/** 审查策略：strict=对外投放(全量人工复核) / standard=常规 / loose=内部预检 */
export type ReviewProfile = 'strict' | 'standard' | 'loose'

export interface TaskOut {
  id: number
  task_name: string
  document_name: string
  document_type?: string
  domain?: string
  profile?: ReviewProfile
  status: string
  progress: number
  stages?: Record<string, TaskStageDetail>
  created_at: string
  started_at?: string
  completed_at?: string
  batch_id?: number
  base_document_name?: string
}

export interface TaskCreate {
  document_id: string
  task_name?: string
  document_type?: string
  domain?: string
  profile?: ReviewProfile
  base_document_id?: string
}
