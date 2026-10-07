import { beforeEach, describe, expect, it } from 'vitest'
import { useTablePrefs } from '@/composables/tablePrefs'

const KEY = 'test-table'
const DEFAULTS = ['name', 'owner', 'status', 'extra']

beforeEach(() => {
  localStorage.clear()
})

describe('useTablePrefs · 列显隐', () => {
  it('无存储时回退默认列', () => {
    const { visibleKeys } = useTablePrefs(KEY, DEFAULTS)
    expect(visibleKeys.value).toEqual(DEFAULTS)
  })

  it('存储的有效列被加载', () => {
    localStorage.setItem(KEY, JSON.stringify(['name', 'status']))
    const { visibleKeys } = useTablePrefs(KEY, DEFAULTS)
    expect(visibleKeys.value).toEqual(['name', 'status'])
  })

  it('存储含已删除列（列定义变更）被过滤', () => {
    localStorage.setItem(KEY, JSON.stringify(['name', 'ghost_col', 'status']))
    const { visibleKeys } = useTablePrefs(KEY, DEFAULTS)
    expect(visibleKeys.value).toEqual(['name', 'status'])
  })

  it('存储 JSON 损坏时回退默认', () => {
    localStorage.setItem(KEY, '{broken json')
    const { visibleKeys } = useTablePrefs(KEY, DEFAULTS)
    expect(visibleKeys.value).toEqual(DEFAULTS)
  })

  it('存储为非数组时回退默认', () => {
    localStorage.setItem(KEY, JSON.stringify({ not: 'array' }))
    const { visibleKeys } = useTablePrefs(KEY, DEFAULTS)
    expect(visibleKeys.value).toEqual(DEFAULTS)
  })

  it('修改 visibleKeys 持久化到 localStorage', () => {
    const { visibleKeys } = useTablePrefs(KEY, DEFAULTS)
    visibleKeys.value = ['owner']
    // watch deep 是异步 flush（pre）——等一个 tick
    return Promise.resolve().then(() => {
      expect(JSON.parse(localStorage.getItem(KEY) ?? '[]')).toEqual(['owner'])
    })
  })

  it('不同 storageKey 互不影响', () => {
    localStorage.setItem('other-table', JSON.stringify(['extra']))
    const a = useTablePrefs(KEY, DEFAULTS)
    const b = useTablePrefs('other-table', DEFAULTS)
    expect(a.visibleKeys.value).toEqual(DEFAULTS)
    expect(b.visibleKeys.value).toEqual(['extra'])
  })
})

describe('useTablePrefs · 密度', () => {
  it('无存储默认 default 密度', () => {
    const { density } = useTablePrefs(KEY, DEFAULTS)
    expect(density.value).toBe('default')
  })

  it('存储的合法密度被加载', () => {
    localStorage.setItem('app-table-density', 'small')
    const { density } = useTablePrefs(KEY, DEFAULTS)
    expect(density.value).toBe('small')
  })

  it('存储的非法密度回退 default', () => {
    localStorage.setItem('app-table-density', 'huge')
    const { density } = useTablePrefs(KEY, DEFAULTS)
    expect(density.value).toBe('default')
  })
})
