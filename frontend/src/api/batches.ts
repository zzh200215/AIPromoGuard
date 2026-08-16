/** 审查批次接口。 */
import type { AxiosResponse } from 'axios'
import { request } from './request'
import type { Page, PaginationParams } from '@/types/api'
import type { BatchDetail, BatchOut } from '@/types/batch'

export interface BatchCreateResult {
  batch_id: number
  batch_name: string
  total_count: number
  task_ids: number[]
}

export const createBatch = (files: File[], batchName: string) => {
  const form = new FormData()
  form.append('batch_name', batchName)
  files.forEach((f) => form.append('files', f))
  return request<BatchCreateResult>({
    url: '/batches',
    method: 'post',
    data: form,
    timeout: 120_000,
  })
}

export const listBatches = (params: PaginationParams) =>
  request<Page<BatchOut>>({ url: '/batches', method: 'get', params })

export const getBatch = (batchId: number) =>
  request<BatchDetail>({ url: `/batches/${batchId}`, method: 'get' })

/** 批量导出 zip 并触发浏览器保存。后端 Content-Disposition 为 filename*=UTF-8''<name>.zip */
export async function downloadBatchZip(batchId: number, batchName: string): Promise<void> {
  const res = await request<AxiosResponse<Blob>>({
    url: `/batches/${batchId}/export`,
    method: 'get',
    responseType: 'blob',
  })
  const blob = res.data
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${batchName}.zip`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}
