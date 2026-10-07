import { describe, expect, it } from 'vitest'
import { usePagination } from '@/composables/usePagination'

describe('usePagination', () => {
  it('默认 page=1 / pageSize=20 / total=0', () => {
    const p = usePagination()
    expect(p.page.value).toBe(1)
    expect(p.pageSize.value).toBe(20)
    expect(p.total.value).toBe(0)
  })

  it('自定义 defaultPageSize 生效', () => {
    const p = usePagination(50)
    expect(p.pageSize.value).toBe(50)
  })

  it('params 响应式跟随 page/pageSize', () => {
    const p = usePagination()
    p.page.value = 3
    p.pageSize.value = 10
    expect(p.params.value).toEqual({ page: 3, page_size: 10 })
  })

  it('reset 回到第一页但保留 pageSize 与 total', () => {
    const p = usePagination()
    p.page.value = 7
    p.total.value = 123
    p.reset()
    expect(p.page.value).toBe(1)
    expect(p.total.value).toBe(123)
  })
})
