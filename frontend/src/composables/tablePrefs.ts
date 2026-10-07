import { ref, watch } from 'vue'

export type TableDensity = 'small' | 'default' | 'large'

const DENSITY_KEY = 'app-table-density'
const DENSITY_VALUES: TableDensity[] = ['small', 'default', 'large']

/**
 * 表格个性化偏好（列显隐 + 密度），localStorage 持久化。
 * 密度是全局偏好（所有表格共用），列显隐按 storageKey 每张表独立。
 * 存储里出现已不存在的列（列定义变更）会被过滤；全空则回退默认。
 */
export function useTablePrefs(storageKey: string, defaultKeys: string[]) {
  function loadKeys(): string[] {
    try {
      const raw = localStorage.getItem(storageKey)
      if (raw) {
        const parsed: unknown = JSON.parse(raw)
        if (Array.isArray(parsed)) {
          const valid = parsed.filter(
            (k): k is string => typeof k === 'string' && defaultKeys.includes(k),
          )
          if (valid.length > 0) return valid
        }
      }
    } catch {
      // 本地配置损坏时按默认处理
    }
    return [...defaultKeys]
  }

  const visibleKeys = ref<string[]>(loadKeys())
  watch(
    visibleKeys,
    (keys) => {
      try {
        localStorage.setItem(storageKey, JSON.stringify(keys))
      } catch {
        // 隐私模式等写入失败不影响使用
      }
    },
    { deep: true },
  )

  function loadDensity(): TableDensity {
    const raw = localStorage.getItem(DENSITY_KEY)
    return DENSITY_VALUES.includes(raw as TableDensity) ? (raw as TableDensity) : 'default'
  }

  const density = ref<TableDensity>(loadDensity())
  watch(density, (value) => {
    try {
      localStorage.setItem(DENSITY_KEY, value)
    } catch {
      // 同上
    }
  })

  return { visibleKeys, density }
}
