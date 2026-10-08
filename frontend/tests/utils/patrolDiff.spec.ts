import { describe, expect, it } from 'vitest'
import { CHANGE_LABELS, similarityText } from '@/utils/patrolDiff'

describe('utils/patrolDiff · 展示派生值', () => {
  it('similarityText：0~1 转百分比（保留一位小数）', () => {
    expect(similarityText(0.873)).toBe('87.3%')
    expect(similarityText(1)).toBe('100.0%')
    expect(similarityText(0)).toBe('0.0%')
  })

  it('similarityText：无快照时为占位符（不显示 0%，避免误导为"零保留"）', () => {
    expect(similarityText(null)).toBe('—')
    expect(similarityText(undefined)).toBe('—')
  })

  it('CHANGE_LABELS：三类片段均有中文标签（批准版/线上版语义）', () => {
    expect(CHANGE_LABELS.modified).toBe('内容修改')
    expect(CHANGE_LABELS.added).toBe('线上新增')
    expect(CHANGE_LABELS.removed).toBe('批准版内容被删')
  })
})
