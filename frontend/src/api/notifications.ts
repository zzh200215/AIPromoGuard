/** 站内通知接口。 */
import { request } from './request'
import type { Page, PaginationParams } from '@/types/api'

export interface NotificationItem {
  id: number
  type: 'task_failed' | 'batch_completed' | 'batch_failed' | string
  title: string
  body?: string | null
  link?: string | null
  is_read: number
  created_at?: string | null
}

export const listNotifications = (params: PaginationParams & { unread_only?: boolean }) =>
  request<Page<NotificationItem> & { unread: number }>({
    url: '/notifications',
    method: 'get',
    params,
  })

export const markNotificationRead = (id: number) =>
  request<{ id: number; is_read: number }>({
    url: `/notifications/${id}/read`,
    method: 'post',
  })

export const markAllNotificationsRead = () =>
  request<{ updated: number }>({ url: '/notifications/read-all', method: 'post' })
