import { describe, expect, it } from 'vitest'
import {
  EMPTY_MATERIAL_FILTERS,
  buildMaterialQuery,
  hasActiveMaterialFilters,
  parseMaterialFilters,
} from '@/utils/materialFilters'

describe('parseMaterialFilters（PR-1 卡片下钻）', () => {
  it('空 query → 全部空筛选态', () => {
    expect(parseMaterialFilters({})).toEqual(EMPTY_MATERIAL_FILTERS)
  })

  it('下钻别名 filter=patrol_changed → patrol=changed', () => {
    expect(parseMaterialFilters({ filter: 'patrol_changed' })).toEqual({
      ...EMPTY_MATERIAL_FILTERS,
      patrol: 'changed',
    })
  })

  it('下钻别名 filter=patrol_gone → patrol=gone', () => {
    expect(parseMaterialFilters({ filter: 'patrol_gone' })).toEqual({
      ...EMPTY_MATERIAL_FILTERS,
      patrol: 'gone',
    })
  })

  it('未知别名安全降级为空态（不误筛）', () => {
    expect(parseMaterialFilters({ filter: 'nonexistent' })).toEqual(EMPTY_MATERIAL_FILTERS)
  })

  it('独立参数全部解析', () => {
    expect(
      parseMaterialFilters({ product: 'fund', status: 'active', review: 'violation', patrol: 'drift' }),
    ).toEqual({ product: 'fund', status: 'active', review: 'violation', patrol: 'drift' })
  })

  it('独立参数优先于别名（同时存在时）', () => {
    const r = parseMaterialFilters({ filter: 'patrol_changed', patrol: 'gone' })
    expect(r.patrol).toBe('gone')
  })

  it('非字符串值安全忽略（数组/数字等）', () => {
    expect(parseMaterialFilters({ patrol: ['a', 'b'], product: 123 })).toEqual(EMPTY_MATERIAL_FILTERS)
  })

  it('空字符串参数不生效', () => {
    expect(parseMaterialFilters({ patrol: '', product: '' })).toEqual(EMPTY_MATERIAL_FILTERS)
  })
})

describe('buildMaterialQuery', () => {
  it('空值不写入（URL 干净）', () => {
    expect(buildMaterialQuery(EMPTY_MATERIAL_FILTERS)).toEqual({})
  })

  it('有值项写入', () => {
    expect(buildMaterialQuery({ product: 'fund', status: '', review: '', patrol: 'changed' })).toEqual({
      product: 'fund',
      patrol: 'changed',
    })
  })

  it('往返一致：build → parse 还原筛选态', () => {
    const filters = { product: 'insurance', status: 'active', review: 'clean', patrol: 'ok' }
    expect(parseMaterialFilters(buildMaterialQuery(filters))).toEqual(filters)
  })
})

describe('hasActiveMaterialFilters', () => {
  it('全空 → false', () => {
    expect(hasActiveMaterialFilters(EMPTY_MATERIAL_FILTERS)).toBe(false)
  })

  it('任一有值 → true', () => {
    expect(hasActiveMaterialFilters({ ...EMPTY_MATERIAL_FILTERS, patrol: 'changed' })).toBe(true)
  })
})
