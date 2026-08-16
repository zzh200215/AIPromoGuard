/** 用户管理接口（全部要求 manage_users）。 */
import { request } from './request'
import type { Page, PaginationParams } from '@/types/api'
import type { Role } from '@/types/auth'
import type { UserCreate, UserItem, UserUpdate } from '@/types/user'

export const listUsers = (params: PaginationParams & { role?: Role; status?: number }) =>
  request<Page<UserItem>>({ url: '/users', method: 'get', params })

export const createUser = (body: UserCreate) =>
  request<UserItem>({ url: '/users', method: 'post', data: body })

export const updateUser = (id: number, body: UserUpdate) =>
  request<UserItem>({ url: `/users/${id}`, method: 'put', data: body })

export const resetPassword = (id: number, password: string) =>
  request<{ reset: number }>({
    url: `/users/${id}/password`,
    method: 'post',
    data: { password },
  })

export const deleteUser = (id: number) =>
  request<{ deleted: number }>({ url: `/users/${id}`, method: 'delete' })
