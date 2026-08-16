/** 认证接口：登录 / 当前用户。 */
import { request } from './request'
import type { LoginRequest, LoginResult, UserInfo } from '@/types/auth'

export const login = (body: LoginRequest) =>
  request<LoginResult>({ url: '/auth/login', method: 'post', data: body })

export const getMe = () => request<UserInfo>({ url: '/auth/me', method: 'get' })
