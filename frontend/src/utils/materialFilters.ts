/**
 * 材料台账筛选态 ↔ URL query 双向映射（PR-1 驾驶舱卡片下钻的统一交互模式）。
 *
 * 下钻别名：Dashboard「线上内容已变更 / 线上页面失联」卡片以
 * `?filter=patrol_changed` / `?filter=patrol_gone` 进入台账页；台账页内部筛选器
 * 以独立参数（product/status/review/patrol）维护——刷新可保持、链接可分享。
 * 解析时独立参数优先，`filter` 别名兜底。
 */

export interface MaterialFilters {
  product: string
  status: string
  review: string
  patrol: string
}

export const EMPTY_MATERIAL_FILTERS: MaterialFilters = {
  product: '',
  status: '',
  review: '',
  patrol: '',
}

/** 下钻别名表（值 → 筛选态片段）；新增卡片下钻时在此登记 */
const FILTER_ALIASES: Record<string, Partial<MaterialFilters>> = {
  patrol_changed: { patrol: 'changed' },
  patrol_gone: { patrol: 'gone' },
}

function asString(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

/** 解析 URL query 为筛选态；独立参数优先，`filter` 别名兜底 */
export function parseMaterialFilters(query: Record<string, unknown>): MaterialFilters {
  const alias = FILTER_ALIASES[asString(query.filter)] ?? {}
  const pick = (key: keyof MaterialFilters): string => asString(query[key]) || alias[key] || ''
  return {
    product: pick('product'),
    status: pick('status'),
    review: pick('review'),
    patrol: pick('patrol'),
  }
}

/** 筛选态 → URL query（空值不写入，URL 保持干净） */
export function buildMaterialQuery(filters: MaterialFilters): Record<string, string> {
  const query: Record<string, string> = {}
  if (filters.product) query.product = filters.product
  if (filters.status) query.status = filters.status
  if (filters.review) query.review = filters.review
  if (filters.patrol) query.patrol = filters.patrol
  return query
}

/** 是否存在任何生效筛选 */
export function hasActiveMaterialFilters(filters: MaterialFilters): boolean {
  return Boolean(filters.product || filters.status || filters.review || filters.patrol)
}
