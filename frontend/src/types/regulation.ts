/** 法规/条款类型（对齐 src/api/routers/regulations.py 与 schemas）。 */

export type RegulationStatus = 'effective' | 'amended' | 'repealed'

export interface Regulation {
  id: number
  domain: string
  regulation_name: string
  regulation_no?: string
  issuer?: string
  publish_date?: string
  effective_date?: string
  status: RegulationStatus
  created_at: string
}

export interface RegulationCreate {
  domain: string
  regulation_name: string
  regulation_no?: string
  issuer?: string
  publish_date?: string
  effective_date?: string
  status?: RegulationStatus
}

export type RegulationUpdate = Partial<RegulationCreate>

export interface Article {
  id: number
  regulation_id: number
  chapter_no?: string
  section_no?: string
  article_no?: string
  clause_no?: string
  item_no?: string
  content: string
  vector_id?: string
}

export interface ArticleCreate {
  chapter_no?: string
  section_no?: string
  article_no?: string
  clause_no?: string
  item_no?: string
  content: string
}

export type ArticleUpdate = Partial<ArticleCreate>

export type SearchType = 'keyword' | 'semantic' | 'hybrid'

export interface RegulationSearchRequest {
  query: string
  search_type?: SearchType
  domain?: Domain[]
  top_k?: number
}

export interface RegulationSearchHit {
  article_id: number
  regulation_id: number
  regulation_name: string
  article_no: string
  content: string
  status: string
  score: number
  /** 含 <em> 高亮标记，可安全渲染 */
  highlight: string
  /** 证据链：被多少条审查规则引用（rule_regulation_links） */
  cited_rules?: number
  /** 证据链：关联多少起真实处罚案例（penalty_cases.related_regulations） */
  cited_cases?: number
}
