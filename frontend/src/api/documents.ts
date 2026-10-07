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

/** 粘贴文本直接审查：落成 .txt 文档（无需先有文件） */
export const createTextDocument = (text: string, title?: string) =>
  request<UploadResult>({
    url: '/documents/text',
    method: 'post',
    data: { text, title: title || undefined },
  })
