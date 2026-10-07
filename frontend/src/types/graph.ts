/** 知识图谱类型（对齐 src/api/routers/graph.py）。 */

export interface GraphPattern {
  pattern_name: string
  domain: string
  severity: string
  similarity: number
}

export interface GraphRegulation {
  /** 与法规库同源（Neo4j Regulation.id = MySQL regulations.id），用于跳法规详情 */
  regulation_id?: number | null
  regulation_name: string
  domain: string
  article_nos: string[]
}

export interface GraphCase {
  case_name: string
  penalty_org?: string
  penalty_date?: string
  penalty_result?: string
  summary?: string
  similarity: number
}

export interface GraphQueryResult {
  query: string
  domain?: string
  total_matched: number
  patterns: GraphPattern[]
  regulations: GraphRegulation[]
  cases: GraphCase[]
}

export interface GraphStats {
  nodes: {
    Regulation: number
    Article: number
    ViolationPattern: number
    ProductType: number
    PenaltyCase: number
  }
  relationships: {
    HAS_ARTICLE: number
    VIOLATES: number
    APPLIES_TO: number
    BASED_ON_REGULATION: number
    INVOLVES_VIOLATION: number
  }
  available: boolean
}
