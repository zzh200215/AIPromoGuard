import { describe, expect, it } from 'vitest'
import {
  resolveKeyAction,
  shouldIgnoreKeydown,
} from '@/composables/useKeyboardShortcuts'
import type { ReviewResult, ResultStatus } from '@/types/result'

const PENDING: ResultStatus = 'pending_confirm'

function fakeKeydown(key: string, opts: Partial<KeyboardEvent> = {}) {
  return {
    key,
    metaKey: false,
    ctrlKey: false,
    altKey: false,
    target: null,
    ...opts,
  } as KeyboardEvent
}

describe('useKeyboardShortcuts · resolveKeyAction', () => {
  const current = { status: PENDING }

  it('j / arrowdown → step-next；k / arrowup → step-prev', () => {
    expect(resolveKeyAction('j', current, true)).toBe('step-next')
    expect(resolveKeyAction('ArrowDown', current, true)).toBe('step-next')
    expect(resolveKeyAction('k', current, true)).toBe('step-prev')
    expect(resolveKeyAction('ArrowUp', current, true)).toBe('step-prev')
  })

  it('c → confirm（待复核项）', () => {
    expect(resolveKeyAction('c', current, true)).toBe('confirm')
  })

  it('x → false-positive（待复核项）', () => {
    expect(resolveKeyAction('x', current, true)).toBe('false-positive')
  })

  it('已确认项按 C 不重复确认（无动作），按 X 走翻案方向', () => {
    const confirmed = { status: 'confirmed' as ResultStatus }
    expect(resolveKeyAction('c', confirmed, true)).toBeNull()
    expect(resolveKeyAction('x', confirmed, true)).toBe('false-positive')
  })

  it('已标记误报项按 X 不重复标记，按 C 走翻案方向', () => {
    const fp = { status: 'false_positive' as ResultStatus }
    expect(resolveKeyAction('x', fp, true)).toBeNull()
    expect(resolveKeyAction('c', fp, true)).toBe('confirm')
  })

  it('canConfirm=false 时判定类按键不产生动作（切换类不受限）', () => {
    expect(resolveKeyAction('c', current, false)).toBeNull()
    expect(resolveKeyAction('x', current, false)).toBeNull()
    expect(resolveKeyAction('j', current, false)).toBe('step-next')
  })

  it('无选中项时判定类按键不产生动作', () => {
    expect(resolveKeyAction('c', null, true)).toBeNull()
    expect(resolveKeyAction('x', null, true)).toBeNull()
  })

  it('无关按键返回 null', () => {
    expect(resolveKeyAction('a', current, true)).toBeNull()
    expect(resolveKeyAction('Enter', current, true)).toBeNull()
  })
})

describe('useKeyboardShortcuts · shouldIgnoreKeydown', () => {
  it('shortcutsEnabled=false 时全部忽略（弹窗打开场景）', () => {
    expect(shouldIgnoreKeydown(fakeKeydown('j'), false)).toBe(true)
  })

  it('输入控件聚焦时忽略（防误触）', () => {
    const input = { tagName: 'INPUT' } as HTMLElement
    const evt = fakeKeydown('j', { target: input })
    expect(shouldIgnoreKeydown(evt, true)).toBe(true)
    const textarea = { tagName: 'TEXTAREA' } as HTMLElement
    expect(shouldIgnoreKeydown(fakeKeydown('j', { target: textarea }), true)).toBe(true)
    const editable = { isContentEditable: true } as unknown as HTMLElement
    expect(shouldIgnoreKeydown(fakeKeydown('j', { target: editable }), true)).toBe(true)
  })

  it('修饰键组合忽略（Ctrl+K 是全局命令面板）', () => {
    expect(shouldIgnoreKeydown(fakeKeydown('k', { ctrlKey: true }), true)).toBe(true)
    expect(shouldIgnoreKeydown(fakeKeydown('j', { metaKey: true }), true)).toBe(true)
    expect(shouldIgnoreKeydown(fakeKeydown('j', { altKey: true }), true)).toBe(true)
  })

  it('普通按键不忽略', () => {
    expect(shouldIgnoreKeydown(fakeKeydown('j'), true)).toBe(false)
    expect(shouldIgnoreKeydown(fakeKeydown('j'), undefined)).toBe(false)
  })
})
