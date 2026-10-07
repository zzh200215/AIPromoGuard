import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useAppStore } from '@/stores/app'

/**
 * F3-1 主题状态：持久化 + DOM 类切换。
 * index.html 的防闪烁内联脚本同样读 'app-theme' 键——键名变更需同步该脚本。
 */
const THEME_KEY = 'app-theme'

beforeEach(() => {
  localStorage.clear()
  document.documentElement.classList.remove('dark')
  setActivePinia(createPinia())
})

describe('appStore · 主题', () => {
  it('默认浅色', () => {
    const app = useAppStore()
    expect(app.theme).toBe('light')
  })

  it('本地偏好为 dark 时初始即暗色', () => {
    localStorage.setItem(THEME_KEY, 'dark')
    const app = useAppStore()
    expect(app.theme).toBe('dark')
  })

  it('非法存储值回退浅色', () => {
    localStorage.setItem(THEME_KEY, 'blue')
    const app = useAppStore()
    expect(app.theme).toBe('light')
  })

  it('toggleTheme 切换并持久化 + 挂载 dark 类', () => {
    const app = useAppStore()
    app.toggleTheme()
    expect(app.theme).toBe('dark')
    expect(localStorage.getItem(THEME_KEY)).toBe('dark')
    expect(document.documentElement.classList.contains('dark')).toBe(true)

    app.toggleTheme()
    expect(app.theme).toBe('light')
    expect(localStorage.getItem(THEME_KEY)).toBe('light')
    expect(document.documentElement.classList.contains('dark')).toBe(false)
  })

  it('applyTheme 按当前状态幂等设置类（构造上是 remove 再 toggle）', () => {
    const app = useAppStore()
    app.theme = 'dark'
    app.applyTheme()
    expect(document.documentElement.classList.contains('dark')).toBe(true)
    app.applyTheme()
    expect(document.documentElement.classList.contains('dark')).toBe(true)
  })

  it('localStorage 不可写时不抛错（隐私模式）', () => {
    const app = useAppStore()
    const spy = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('QuotaExceededError')
    })
    expect(() => app.toggleTheme()).not.toThrow()
    expect(app.theme).toBe('dark') // 本次会话仍生效，只是不持久化
    spy.mockRestore()
  })
})
