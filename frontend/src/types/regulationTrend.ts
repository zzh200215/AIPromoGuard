/** 监管动态追踪类型（对齐 src/api/routers/trends.py 与 schemas/trend.py）。 */

export type RegulationUpdateStatus = 'pending' | 'imported' | 'ignored' | 'in_db'
export type UpdateSource = 'nfra' | 'csrc' | 'pbc'

export interface MatchedRegulation {
  regulation_id: number
  regulation_name: string
  article_no: string
  status: string
}

export interface RegulationUpdate {
  id: number
  source: UpdateSource
  title: string
  doc_no?: string
  publish_date?: string
  url?: string
  domain?: string
  doc_type?: string
  llm_summary?: string
  matched_regulations?: MatchedRegulation[]
  status: RegulationUpdateStatus
  match_type?: string
  created_at: string
}

export interface ConfirmBody {
  domain?: string
  effective_date?: string
}

export interface ManualCreate {
  source: UpdateSource
  title: string
  url?: string
  doc_no?: string
  publish_date?: string
}
