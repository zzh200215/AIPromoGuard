import { beforeEach, describe, expect, it, vi } from 'vitest'

/** request 模块整体 mock：断言各 api 函数的 url/method/params/data 拼装。 */
vi.mock('@/api/request', () => ({
  request: vi.fn(),
}))

import { request } from '@/api/request'
import {
  bulkConfirmResults,
  listResults,
  revertResults,
} from '@/api/results'
import { summarizeTask } from '@/api/ai'

const mockedRequest = vi.mocked(request)

beforeEach(() => {
  mockedRequest.mockReset()
  mockedRequest.mockResolvedValue({} as never)
})

describe('api/results · 参数拼装', () => {
  it('listResults 无 status/order 时参数为空对象（axios 忽略 undefined 字段）', async () => {
    await listResults(7)
    expect(mockedRequest).toHaveBeenCalledWith({
      url: '/tasks/7/results',
      method: 'get',
      params: { status: undefined, order: undefined },
    })
  })

  it('listResults 支持 order=priority（R4-3 复核路由）', async () => {
    await listResults(7, 'pending_confirm', 'priority')
    expect(mockedRequest).toHaveBeenCalledWith({
      url: '/tasks/7/results',
      method: 'get',
      params: { status: 'pending_confirm', order: 'priority' },
    })
  })

  it('listResults 带 status 时进 params', async () => {
    await listResults(7, 'pending_confirm')
    expect(mockedRequest).toHaveBeenCalledWith({
      url: '/tasks/7/results',
      method: 'get',
      params: { status: 'pending_confirm' },
    })
  })

  it('bulkConfirmResults body 透传（批量判定）', async () => {
    const body = { result_ids: [1, 2], verdict: 'confirmed' as const, note: 'ok' }
    await bulkConfirmResults(body)
    expect(mockedRequest).toHaveBeenCalledWith({
      url: '/results/bulk-confirm',
      method: 'post',
      data: body,
    })
  })

  it('revertResults body 透传（撤销误操作）', async () => {
    const body = { result_ids: [3], note: '误点' }
    await revertResults(body)
    expect(mockedRequest).toHaveBeenCalledWith({
      url: '/results/revert',
      method: 'post',
      data: body,
    })
  })
})

describe('api/ai · 参数拼装', () => {
  it('summarizeTask 默认 force=false 且 silent', async () => {
    await summarizeTask(5)
    expect(mockedRequest).toHaveBeenCalledWith({
      url: '/ai/tasks/5/summary',
      method: 'post',
      data: { force: false },
      silent: true,
    })
  })

  it('summarizeTask force=true 透传', async () => {
    await summarizeTask(5, true)
    expect(mockedRequest).toHaveBeenCalledWith(
      expect.objectContaining({ data: { force: true } }),
    )
  })
})
