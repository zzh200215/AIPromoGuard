/** 文档上传接口（公开，multipart 字段 file）。 */
import { request } from './request'

export interface UploadResult {
  document_id: string
  file_name: string
  file_size: number
  status: string
}

export const uploadDocument = (file: File) => {
  const form = new FormData()
  form.append('file', file)
  return request<UploadResult>({
    url: '/documents/upload',
    method: 'post',
    data: form,
    // 不手动设 Content-Type，让浏览器带 boundary
    timeout: 120_000,
  })
}
