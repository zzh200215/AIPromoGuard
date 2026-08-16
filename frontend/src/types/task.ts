/** 审查任务类型（对齐 src/api/schemas/task.py 与 review_service）。 */

/** task.status 枚举：DB 注释含 processing，实际写入 running，前端两种都兼容 */
export type TaskStatus =
  | 'pending'
  | 'running'
  | 'processing'
  | 'completed'
  | 'failed'
  | 'cancelled'

/** stages 结构：{ 节点名: {status, cost_ms} }（W14 状态追踪，见 src/core/agents/graph.py） */
export interface TaskStageDetail {
  status: string
  cost_ms: number
}

export interface TaskOut {
  id: number
  task_name: string
  document_name: string
  document_type?: string
  domain?: string
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
  base_document_id?: string
}
