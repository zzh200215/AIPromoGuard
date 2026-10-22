import { describe, expect, it } from 'vitest'
import { SOURCE_TRUST, collectRegulationRefs, parseCitation } from '@/utils/regulationRefs'
import type { ViolationItem } from '@/types/report'

describe('utils/regulationRefs · 法规引用解析', () => {
  it('parseCitation：无书名号"名称 条款号"（LLM 路实际格式）', () => {
    expect(parseCitation('公开募集证券投资基金宣传推介材料管理暂行规定 第八条')).toEqual({
      name: '公开募集证券投资基金宣传推介材料管理暂行规定',
      articleNo: '第八条',
    })
  })

  it('parseCitation：书名号格式', () => {
    expect(parseCitation('《商业银行理财业务监督管理办法》第二十六条')).toEqual({
      name: '商业银行理财业务监督管理办法',
      articleNo: '第二十六条',
    })
  })

  it('parseCitation：条款号带"之X"后缀', () => {
    expect(parseCitation('《证券投资基金法》第一百零三条之三')).toEqual({
      name: '证券投资基金法',
      articleNo: '第一百零三条之三',
    })
  })

  it('parseCitation：泛引（无条款号）去尾缀', () => {
    expect(parseCitation('《证券投资基金销售管理办法》相关条款')).toEqual({
      name: '证券投资基金销售管理办法',
      articleNo: undefined,
    })
  })

  it('parseCitation：无效输入返回 null', () => {
    expect(parseCitation('')).toBeNull()
    expect(parseCitation('较短')).toBeNull()
  })

  it('collectRegulationRefs：自由文本 + 数组去重（保留首个条款号）', () => {
    const v = {
      regulation: '公开募集证券投资基金宣传推介材料管理暂行规定 第八条',
      related_regulations: ['《公开募集证券投资基金宣传推介材料管理暂行规定》第八条'],
    } as ViolationItem
    const refs = collectRegulationRefs(v)
    expect(refs).toHaveLength(1)
    expect(refs[0].articleNo).toBe('第八条')
  })

  it('collectRegulationRefs：单条引用时绑定 regulation_id；多条不猜测', () => {
    const single = {
      regulation: '《商业银行理财业务监督管理办法》第二十六条',
      related_regulations: [],
      regulation_id: 7,
    } as unknown as ViolationItem
    expect(collectRegulationRefs(single)[0].regulationId).toBe(7)

    const multi = {
      regulation: '',
      related_regulations: ['《商业银行理财业务监督管理办法》第二十六条', '《理财公司理财产品销售管理暂行办法》第三十一条'],
      regulation_id: 7,
    } as unknown as ViolationItem
    expect(collectRegulationRefs(multi)).toHaveLength(2)
    expect(collectRegulationRefs(multi).every((r) => r.regulationId == null)).toBe(true)
  })

  it('collectRegulationRefs：空数据 → []', () => {
    expect(collectRegulationRefs({} as ViolationItem)).toEqual([])
  })

  it('SOURCE_TRUST：四类引擎均有中文信任分级解释', () => {
    for (const key of ['rule', 'llm', 'hybrid', 'vlm']) {
      expect(SOURCE_TRUST[key]?.label).toBeTruthy()
      expect(SOURCE_TRUST[key]?.desc).toBeTruthy()
    }
  })
})
