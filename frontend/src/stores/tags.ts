import { defineStore } from 'pinia'
import type { RouteLocationNormalizedLoaded } from 'vue-router'

export interface TagItem {
  path: string
  title: string
  /** 路由名 = 视图组件名（defineOptions 同名），keep-alive include 依据 */
  name?: string
  /** 固定标签（工作台），不显示关闭按钮 */
  affix?: boolean
}

export const HOME_PATH = '/dashboard'

/** 从路由生成标签；详情页追加 #id，避免两个「任务详情」标签分不清 */
export function tagFromRoute(route: RouteLocationNormalizedLoaded): TagItem | null {
  const base = route.meta.title as string | undefined
  if (!base) return null
  const id = route.params.id
  const suffix = id ? ` #${Array.isArray(id) ? id.join('/') : id}` : ''
  return { path: route.path, title: `${base}${suffix}`, name: route.name as string | undefined }
}

export const useTagsStore = defineStore('tags', {
  state: () => ({
    tags: [{ path: HOME_PATH, title: '工作台', name: 'dashboard', affix: true }] as TagItem[],
    /** 自增键：MainLayout 绑在 router-view 的 key 上，自增一次 = 当前页强制重挂载（标签右键刷新） */
    refreshKey: 0,
    /** 刷新时短暂排除的组件名：让 keep-alive 剪掉旧缓存实例，下一个 tick 恢复 */
    evicting: [] as string[],
  }),
  actions: {
    /** 新登录会话开始时重置（TagsView 挂载时调用），避免看到上一个用户的标签 */
    resetToHome() {
      this.tags = [{ path: HOME_PATH, title: '工作台', name: 'dashboard', affix: true }]
      this.refreshKey = 0
      this.evicting = []
    },
    addRoute(route: RouteLocationNormalizedLoaded) {
      const tag = tagFromRoute(route)
      if (!tag || this.tags.some((t) => t.path === tag.path)) return
      this.tags.push(tag)
    },
    removeTag(path: string) {
      this.tags = this.tags.filter((t) => t.path !== path)
      // 关闭标签后 include 不再含该组件名，keep-alive 自动剪掉对应缓存
    },
    closeOthers(path: string) {
      this.tags = this.tags.filter((t) => t.affix || t.path === path)
    },
    bump() {
      this.refreshKey += 1
    },
    /** 短暂把组件名移出 include：旧实例被剪枝后下个 tick 恢复，新实例重新入缓存 */
    evictForRefresh(name: string) {
      if (name && !this.evicting.includes(name)) this.evicting.push(name)
    },
    restoreEvicted(name: string) {
      this.evicting = this.evicting.filter((n) => n !== name)
    },
  },
})
