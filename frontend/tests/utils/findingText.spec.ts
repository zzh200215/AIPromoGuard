import { describe, expect, it } from 'vitest'
import { parseFindingDescription } from '@/utils/findingText'

describe('parseFindingDescription（F2-4）', () => {
  it('拆出内置维度前缀与正文', () => {
    const r = parseFindingDescription('[数字勾稽：演示表算术不一致] 勾稽检查发现：期末金额 ≠ 本金 + 收益')
    expect(r.prefixLabel).toBe('数字勾稽：演示表算术不一致')
    expect(r.body).toBe('勾稽检查发现：期末金额 ≠ 本金 + 收益')
  })

  it('PII 命中同样拆分', () => {
    const r = parseFindingDescription('[敏感信息：手机号] 材料包含疑似真实客户手机号')
    expect(r.prefixLabel).toBe('敏感信息：手机号')
    expect(r.body).toBe('材料包含疑似真实客户手机号')
  })

  it('无前缀的普通命中原样返回', () => {
    const r = parseFindingDescription('LLM 判定该表述构成收益承诺')
    expect(r.prefixLabel).toBeNull()
    expect(r.body).toBe('LLM 判定该表述构成收益承诺')
  })

  it('空值安全', () => {
    expect(parseFindingDescription(null)).toEqual({ prefixLabel: null, body: '' })
    expect(parseFindingDescription('')).toEqual({ prefixLabel: null, body: '' })
    expect(parseFindingDescription(undefined)).toEqual({ prefixLabel: null, body: '' })
  })

  it('正文含方括号不会被误拆（只认行首前缀）', () => {
    const r = parseFindingDescription('引用《办法》第十二条[注] 的表述')
    expect(r.prefixLabel).toBeNull()
    expect(r.body).toBe('引用《办法》第十二条[注] 的表述')
  })

  it('超长方括号不作为前缀（防误吞正文）', () => {
    const long = `[${'x'.repeat(120)}] 正文`
    const r = parseFindingDescription(long)
    expect(r.prefixLabel).toBeNull()
    expect(r.body).toBe(long)
  })
})
