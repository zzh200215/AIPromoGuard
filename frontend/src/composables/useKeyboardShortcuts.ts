/**
 * 复核工作台键盘快捷键的判定逻辑（纯函数，独立于 DOM 事件机制以便测试）。
 * 语义：J/K 或 ↑/↓ 切换；C 确认违规方向；X 误报方向；已判定项按同方向键即翻案。
 */
import type { ResultStatus } from '@/types/result'

export type KeyAction = 'step-next' | 'step-prev' | 'confirm' | 'false-positive'

/** 键 → 动作。canConfirm=false 或无选中项时判定类按键不产生动作（切换类不受限）。 */
export function resolveKeyAction(
  key: string,
  current: { status: ResultStatus } | null,
  canConfirm: boolean,
): KeyAction | null {
  const k = key.toLowerCase()
  if (k === 'j' || k === 'arrowdown') return 'step-next'
  if (k === 'k' || k === 'arrowup') return 'step-prev'
  if (!canConfirm || !current) return null
  if (k === 'c' && current.status !== 'confirmed') return 'confirm'
  if (k === 'x' && current.status !== 'false_positive') return 'false-positive'
  return null
}

/** 事件是否应忽略：快捷键总开关关闭 / 输入控件聚焦 / 修饰键组合（Ctrl+K 等全局功能）。 */
export function shouldIgnoreKeydown(e: KeyboardEvent, shortcutsEnabled?: boolean): boolean {
  if (shortcutsEnabled === false) return true
  const t = e.target as HTMLElement | null
  if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) {
    return true
  }
  return e.metaKey || e.ctrlKey || e.altKey
}
