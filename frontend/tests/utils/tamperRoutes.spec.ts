import { describe, expect, it } from 'vitest'
import { parseTamperRoutes } from '@/utils/tamperRoutes'

describe('utils/tamperRoutes · 疑似篡改两路数字对照', () => {
  it('changed 分支：同位置不一致，两路各自带值', () => {
    const r = parseTamperRoutes('年化收益率 图片：9.85 ｜ 文字：3.85')
    expect(r).toEqual({ label: '年化收益率', vlm: '9.85', text: '3.85', unverified: false })
  })

  it('unverified 分支：文字侧"未读到"→ text=null 且标记待人工核验', () => {
    const r = parseTamperRoutes('年化收益率 图片：9.85 ｜ 文字：未读到')
    expect(r).toEqual({ label: '年化收益率', vlm: '9.85', text: null, unverified: true })
  })

  it('半角竖线与半角冒号也接受（兼容历史/手工数据）', () => {
    const r = parseTamperRoutes('最低认购金额 图片:100,000 | 文字:50,000')
    expect(r).toEqual({
      label: '最低认购金额',
      vlm: '100,000',
      text: '50,000',
      unverified: false,
    })
  })

  it('无标签时 label 为 null，仍能解析出两路值', () => {
    const r = parseTamperRoutes('图片：9.85 ｜ 文字：3.85')
    expect(r).toEqual({ label: null, vlm: '9.85', text: '3.85', unverified: false })
  })

  it('聚合条目（整档核对）不带两路格式 → null，按普通结论渲染', () => {
    expect(parseTamperRoutes('未读到：9.85（年化收益率）、1000（认购金额）')).toBeNull()
  })

  it('空输入与普通结论 → null（不误伤其他维度渲染）', () => {
    expect(parseTamperRoutes('')).toBeNull()
    expect(parseTamperRoutes(undefined)).toBeNull()
    expect(parseTamperRoutes('本产品保本保息，稳赚不赔')).toBeNull()
  })
})
