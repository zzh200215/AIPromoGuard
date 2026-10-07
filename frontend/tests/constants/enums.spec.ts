import { describe, expect, it } from 'vitest'
import {
  SEVERITY_LABELS,
  TASK_STATUS_LABELS,
  VIOLATION_SOURCE_LABELS,
} from '@/constants/enums'

/**
 * 常量契约测试：枚举标签是 UI 渲染的数据源。
 * 维度/状态扩展时此测试强制同步标签，防止静默显示 undefined。
 */
describe('constants/enums · 契约', () => {
  it('violation_type 四来源标签齐全（含 vlm 视觉层）', () => {
    expect(VIOLATION_SOURCE_LABELS).toMatchObject({
      rule: expect.any(String),
      llm: expect.any(String),
      hybrid: expect.any(String),
      vlm: expect.any(String),
    })
  })

  it('severity 三级标签齐全', () => {
    expect(SEVERITY_LABELS).toMatchObject({
      high: expect.any(String),
      medium: expect.any(String),
      low: expect.any(String),
    })
  })

  it('task 终态与运行态标签齐全', () => {
    for (const s of ['completed', 'failed', 'cancelled', 'running', 'pending']) {
      expect(TASK_STATUS_LABELS[s]).toBeTruthy()
    }
  })
})
