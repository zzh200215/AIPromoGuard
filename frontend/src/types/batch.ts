/** 审查批次类型（对齐 src/api/schemas/batch.py 与 batches router）。 */
import type { TaskOut } from '@/types/task'

export interface BatchOut {
  id: number
  batch_name: string
  status: string
  total_count: number
  completed_count: number
  failed_count: number
  created_at: string
  completed_at?: string
}

export interface BatchDetail {
  batch: BatchOut
  tasks: TaskOut[]
}
