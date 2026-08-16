/** 报告查看与下载（markdown/pdf 为文件流）。 */
import type { AxiosResponse } from 'axios'
import { request } from './request'
import type { ReportData } from '@/types/report'

export const getReport = (taskId: number) =>
  request<ReportData>({ url: `/tasks/${taskId}/report`, method: 'get' })

/** 解析 RFC 5987 filename*=UTF-8'' 中文文件名 */
function parseFilename(disposition: string | null, fallback: string): string {
  if (!disposition) return fallback
  const star = disposition.match(/filename\*=UTF-8''([^;]+)/i)
  if (star) return decodeURIComponent(star[1])
  const plain = disposition.match(/filename="?([^";]+)"?/i)
  return plain ? plain[1] : fallback
}

/** 下载报告并触发浏览器保存。format: markdown | pdf */
export async function downloadReport(
  taskId: number,
  format: 'markdown' | 'pdf' = 'markdown',
): Promise<void> {
  const res = await request<AxiosResponse<Blob>>({
    url: `/tasks/${taskId}/report/download`,
    method: 'get',
    params: { format },
    responseType: 'blob',
  })
  const blob = res.data
  const filename = parseFilename(
    res.headers['content-disposition'] as string | null,
    format === 'pdf' ? `report_${taskId}.pdf` : `report_${taskId}.md`,
  )
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}
