import { defineStore } from 'pinia'
import { getMe, login as loginApi } from '@/api/auth'
import { ROLE_PERMISSIONS, type PermissionCode } from '@/constants/permission'
import type { LoginRequest, Role, UserInfo } from '@/types/auth'

const TOKEN_KEY = 'access_token'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: localStorage.getItem(TOKEN_KEY) as string | null,
    user: null as UserInfo | null,
  }),
  getters: {
    role: (state): Role | null => state.user?.role ?? null,
    hasPermission:
      (state) =>
      (code: PermissionCode): boolean => {
        if (!state.user) return false
        return (ROLE_PERMISSIONS[state.user.role] ?? []).includes(code)
      },
  },
  actions: {
    async login(payload: LoginRequest) {
      const data = await loginApi(payload)
      this.token = data.access_token
      this.user = data.user
      localStorage.setItem(TOKEN_KEY, data.access_token)
    },
    async fetchMe() {
      this.user = await getMe()
    },
    logout() {
      this.token = null
      this.user = null
      localStorage.removeItem(TOKEN_KEY)
    },
  },
})
