/** 全局导航守卫：登录校验 + 权限校验。
 * 注意：由 main.ts 副作用引入（import './router/guards'），避免与 index.ts 循环依赖。 */
import router from './index'
import { useAuthStore } from '@/stores/auth'

router.beforeEach(async (to) => {
  const auth = useAuthStore()

  if (to.path === '/login') {
    return auth.token ? { path: '/' } : true
  }

  if (!auth.token) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }

  if (!auth.user) {
    try {
      await auth.fetchMe()
    } catch {
      auth.logout()
      return { path: '/login' }
    }
  }

  if (to.meta.requiredPermission && !auth.hasPermission(to.meta.requiredPermission)) {
    return { path: '/403' }
  }

  return true
})

export default router
