import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/api/request', () => ({
  request: vi.fn(),
}))

import { request } from '@/api/request'
import {
  downloadEvidencePack,
  downloadReport,
} from '@/api/reports'
import { getResultTrail, listResults } from '@/api/results'
import { getVerdictAdvice } from '@/api/ai'
import { fetchTaskDocumentObjectUrl, isImageDocument } from '@/api/tasks'

const mockedRequest = vi.mocked(request)

beforeEach(() => {
  mockedRequest.mockReset()
})

describe('api/tasks · F2-2 原图', () => {
  it('isImageDocument 识别可视类型', () => {
    for (const n of ['海报.png', 'a.JPG', 'b.jpeg', 'c.bmp']) {
      expect(isImageDocument(n)).toBe(true)
    }
    for (const n of ['说明.pdf', '话术.docx', 'no-ext', '', null, undefined]) {
      expect(isImageDocument(n as string | null | undefined)).toBe(false)
    }
  })

  it('fetchTaskDocumentObjectUrl 走 blob 并转 objectURL', async () => {
    const blob = new Blob(['fake'], { type: 'image/png' })
    mockedRequest.mockResolvedValue({ data: blob } as never)
    const url = await fetchTaskDocumentObjectUrl(9)
    expect(mockedRequest).toHaveBeenCalledWith({
      url: '/tasks/9/document-file',
      method: 'get',
      responseType: 'blob',
      timeout: 120_000,
    })
    expect(url.startsWith('blob:')).toBe(true)
    URL.revokeObjectURL(url)
  })
})

describe('api · F2-3 / F1 断点参数拼装', () => {
  it('getResultTrail 指向结论轨迹端点', async () => {
    mockedRequest.mockResolvedValue({} as never)
    await getResultTrail(42)
    expect(mockedRequest).toHaveBeenCalledWith({
      url: '/results/42/trail',
      method: 'get',
    })
  })

  it('getVerdictAdvice 为静默预取（silent）', async () => {
    mockedRequest.mockResolvedValue({} as never)
    await getVerdictAdvice(7)
    expect(mockedRequest).toHaveBeenCalledWith(
      expect.objectContaining({ url: '/ai/results/7/verdict-advice', silent: true }),
    )
  })
})

describe('api/reports · 证据包下载', () => {
  it('downloadEvidencePack 走 evidence-pack 端点且为 blob', async () => {
    mockedRequest.mockResolvedValue({
      data: new Blob(['zip']),
      headers: { 'content-disposition': "attachment; filename*=UTF-8''%E5%8F%96%E8%AF%81%E5%8C%85.zip" },
    } as never)
    const spy = vi.fn()
    const origCreate = document.createElement.bind(document)
    vi.spyOn(document, 'createElement').mockImplementation(((tag: string) => {
      const el = origCreate(tag)
      if (tag === 'a') {
        el.click = spy
      }
      return el
    }) as never)
    await downloadEvidencePack(3)
    expect(mockedRequest).toHaveBeenCalledWith(
      expect.objectContaining({ url: '/tasks/3/evidence-pack', responseType: 'blob' }),
    )
    expect(spy).toHaveBeenCalled()
    vi.restoreAllMocks()
  })

  it('downloadReport 参数 format 透传', async () => {
    mockedRequest.mockResolvedValue({
      data: new Blob(['md']),
      headers: {},
    } as never)
    const origCreate = document.createElement.bind(document)
    const clickSpy = vi.fn()
    vi.spyOn(document, 'createElement').mockImplementation(((tag: string) => {
      const el = origCreate(tag)
      if (tag === 'a') el.click = clickSpy
      return el
    }) as never)
    await downloadReport(3, 'pdf')
    expect(mockedRequest).toHaveBeenCalledWith(
      expect.objectContaining({ url: '/tasks/3/report/download', params: { format: 'pdf' } }),
    )
    expect(clickSpy).toHaveBeenCalled()
    vi.restoreAllMocks()
  })
})

describe('api/results · 排序参数（F1-1）', () => {
  it('listResults 带 order=priority', async () => {
    mockedRequest.mockResolvedValue({} as never)
    await listResults(5, 'pending_confirm', 'priority')
    expect(mockedRequest).toHaveBeenCalledWith({
      url: '/tasks/5/results',
      method: 'get',
      params: { status: 'pending_confirm', order: 'priority' },
    })
  })
})
