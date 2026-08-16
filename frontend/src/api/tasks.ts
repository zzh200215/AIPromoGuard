/** 审查任务接口。 */
import { request } from './request'
import type { Page, PaginationParams } from '@/types/api'
import type { TaskCreate, TaskOut } from '@/types/task'

export const createTask = (body: TaskCreate) =>
  request<{ task_id: number; status: string; progress: number }>({
    url: '/tasks',
    method: 'post',
    data: body,
  })

export const listTasks = (params: PaginationParams & { status?: string }) =>
  request<Page<TaskOut>>({ url: '/tasks', method: 'get', params })

export const getTask = (taskId: number) =>
  request<TaskOut>({ url: `/tasks/${taskId}`, method: 'get' })
