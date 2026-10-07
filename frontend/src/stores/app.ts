import { defineStore } from 'pinia'

export type ThemeMode = 'light' | 'dark'

const THEME_KEY = 'app-theme'

function readTheme(): ThemeMode {
  try {
    return localStorage.getItem(THEME_KEY) === 'dark' ? 'dark' : 'light'
  } catch {
    return 'light'
  }
}

export const useAppStore = defineStore('app', {
  state: () => ({
    sidebarCollapsed: false,
    /** 主题：index.html 内联脚本已在挂载前挂好 dark 类，这里保持一致 */
    theme: readTheme() as ThemeMode,
    /** 合规水印：内容区叠加用户名/时间水印（默认开） */
    watermark: true,
  }),
  actions: {
    toggleSidebar() {
      this.sidebarCollapsed = !this.sidebarCollapsed
    },
    applyTheme() {
      document.documentElement.classList.toggle('dark', this.theme === 'dark')
    },
    toggleTheme() {
      this.theme = this.theme === 'dark' ? 'light' : 'dark'
      try {
        localStorage.setItem(THEME_KEY, this.theme)
      } catch {
        // 隐私模式等场景下持久化失败不影响本次会话
      }
      this.applyTheme()
    },
  },
})
