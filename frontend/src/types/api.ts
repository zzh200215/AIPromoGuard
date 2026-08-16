/** 后端统一响应与分页结构（对齐 src/utils/response.py 与各 router）。 */

/** 统一响应外壳：{code, message, data, trace_id}，code=0 成功 */
export interface ApiResult<T> {
  code: number
  message: string
  data: T
  trace_id: string
}

/** 分页返回：{total, page, page_size, items} */
export interface Page<T> {
  total: number
  page: number
  page_size: number
  items: T[]
}

/** 分页请求参数 */
export interface PaginationParams {
  page?: number
  page_size?: number
}

/** 产品领域（configs/app.yaml domains 键驱动） */
export type Domain = 'banking' | 'fund' | 'insurance'

/** 风险等级 */
export type Severity = 'high' | 'medium' | 'low'
