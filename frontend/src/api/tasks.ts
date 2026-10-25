/** 审查任务接口。 */
import type { AxiosResponse } from 'axios'
import { request } from './request'
import type { Page, PaginationParams } from '@/types/api'
import type { TaskCreate, TaskOut } from '@/types/task'

export const createTask = (body: TaskCreate) =>
  request<{ task_id: number; status: string; progress: number }>({
    url: '/tasks',
    method: 'post',
    data: body,
  })

export const listTasks = (params: PaginationParams & { status?: string; search?: string }) =>
  request<Page<TaskOut>>({ url: '/tasks', method: 'get', params })

export const getTask = (taskId: number) =>
  request<TaskOut>({ url: `/tasks/${taskId}`, method: 'get' })

/** 审核签发：正式放行/驳回（门槛：任务完成且待复核清零，后端校验） */
export const signOffTask = (taskId: number, body: { decision: 'released' | 'rejected'; note?: string }) =>
  request<{
    task_id: number
    decision: 'released' | 'rejected'
    username: string
    note?: string | null
    created_at: string
  }>({ url: `/tasks/${taskId}/sign-off`, method: 'post', data: body })

/** 人工复核决策提交（HIL 续跑）：rejected_indexes = 标记为误报的 finding 下标 */
export const submitHumanReview = (taskId: number, rejectedIndexes: number[]) =>
  request<{ task_id: number; status: string; total_violations?: number }>({
    url: `/tasks/${taskId}/human-review`,
    method: 'post',
    data: { rejected_indexes: rejectedIndexes },
  })

/** 查询任务当前有效签发结论（最新一次），无则 data 为 null */
export const getSignOff = (taskId: number) =>
  request<{
    decision: 'released' | 'rejected'
    username: string
    note?: string | null
    created_at: string
  } | null>({ url: `/tasks/${taskId}/sign-off`, method: 'get' })

/** 文档解析原文块（带页/段位置，已脱敏；供复核对照视图） */
export interface DocumentBlock {
  text: string
  page?: number | null
  paragraph?: number | null
  heading?: boolean
}

export interface TaskDocumentContent {
  task_id: number
  document_name: string
  blocks: DocumentBlock[]
}

/** 按需解析任务文档原文（OCR 等慢解析只在打开对照视图时发生） */
export const getTaskDocumentContent = (taskId: number) =>
  request<TaskDocumentContent>({ url: `/tasks/${taskId}/document-content`, method: 'get' })

/**
 * 任务原始文件流（F2-2）：图片材料复核需看到原图。
 * 经 axios 带 token 取 blob 再转 objectURL——`<img src>` 无法携带认证头。
 * 调用方负责在组件卸载时 URL.revokeObjectURL 释放。
 */
export async function fetchTaskDocumentObjectUrl(taskId: number): Promise<string> {
  const res = await request<AxiosResponse<Blob>>({
    url: `/tasks/${taskId}/document-file`,
    method: 'get',
    responseType: 'blob',
    timeout: 120_000,
  })
  return URL.createObjectURL(res.data)
}

/** 可视文件类型判定（与后端 MEDIA_TYPES 的可视子集对齐） */
export const IMAGE_EXTS = ['png', 'jpg', 'jpeg', 'bmp']
export function isImageDocument(name?: string | null): boolean {
  if (!name) return false
  const dot = name.lastIndexOf('.')
  if (dot < 0) return false
  return IMAGE_EXTS.includes(name.slice(dot + 1).toLowerCase())
}

/** 重试失败任务：复位状态重新入队，返回复位后的任务状态（pending） */
export const retryTask = (taskId: number) =>
  request<{ task_id: number; status: string }>({
    url: `/tasks/${taskId}/retry`,
    method: 'post',
  })
