/** 认证相关类型（对齐 src/api/routers/auth.py）。 */

export type Role = 'admin' | 'reviewer' | 'viewer'

export interface LoginRequest {
  username: string
  password: string
}

export interface UserInfo {
  id: number
  username: string
  role: Role
  department?: string
}

export interface LoginResult {
  access_token: string
  token_type: string
  user: UserInfo
}
