/** 用户管理类型（对齐 src/api/routers/users.py）。 */

import type { Role } from './auth'

export interface UserItem {
  id: number
  username: string
  role: Role
  department?: string
  status: number
  created_at: string
}

export interface UserCreate {
  username: string
  password: string
  role?: Role
  department?: string
}

export interface UserUpdate {
  role?: Role
  department?: string
  status?: number
}
