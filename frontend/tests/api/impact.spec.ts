import { beforeEach, describe, expect, it, vi } from 'vitest'

/** request 模块整体 mock：断言 impact api 的 url/method/params 拼装。 */
vi.mock('@/api/request', () => ({
  request: vi.fn(),
}))

import { request } from '@/api/request'
import { getPatrolDiff, syncStaleMaterials } from '@/api/impact'

const mockedRequest = vi.mocked(request)

beforeEach(() => {
  mockedRequest.mockReset()
  mockedRequest.mockResolvedValue({} as never)
})

describe('api/impact · PR-3 巡检差异与失效同步', () => {
  it('getPatrolDiff：GET /impact/materials/{id}/patrol-diff', async () => {
    await getPatrolDiff(42)
    expect(mockedRequest).toHaveBeenCalledWith({
      url: '/impact/materials/42/patrol-diff',
      method: 'get',
    })
  })

  it('syncStaleMaterials：POST 失效同步（响应含 highlight_ids 供整改清单高亮）', async () => {
    await syncStaleMaterials()
    expect(mockedRequest).toHaveBeenCalledWith({
      url: '/impact/materials/stale/sync',
      method: 'post',
    })
  })
})
