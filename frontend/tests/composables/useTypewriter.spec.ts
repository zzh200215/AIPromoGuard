import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'
import { mount } from '@vue/test-utils'
import { useTypewriter } from '@/composables/useTypewriter'

function mountTypewriter(options?: { step?: number; intervalMs?: number }) {
  let api!: ReturnType<typeof useTypewriter>
  const Comp = defineComponent({
    setup() {
      api = useTypewriter(options)
      return () => h('div')
    },
  })
  const wrapper = mount(Comp)
  return { api, wrapper }
}

describe('composables/useTypewriter · 打字机（伪流式）', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('start：逐字追加，打完 typing=false', () => {
    const { api } = mountTypewriter({ step: 2, intervalMs: 10 })
    api.start('abcdef')
    expect(api.text.value).toBe('')
    expect(api.typing.value).toBe(true)

    vi.advanceTimersByTime(10)
    expect(api.text.value).toBe('ab')
    vi.advanceTimersByTime(10)
    expect(api.text.value).toBe('abcd')
    vi.advanceTimersByTime(10)
    expect(api.text.value).toBe('abcdef')
    expect(api.typing.value).toBe(false)
  })

  it('set：直接显示、不打字（回看场景）', () => {
    const { api } = mountTypewriter({ step: 1, intervalMs: 10 })
    api.start('abc')
    api.set('完整文本')
    expect(api.text.value).toBe('完整文本')
    expect(api.typing.value).toBe(false)
    // 旧定时器已被清理：推进时间不再变化
    vi.advanceTimersByTime(100)
    expect(api.text.value).toBe('完整文本')
  })

  it('start 空文本：直接结束，不启动定时器', () => {
    const { api } = mountTypewriter({ step: 1, intervalMs: 10 })
    api.start('')
    expect(api.text.value).toBe('')
    expect(api.typing.value).toBe(false)
  })

  it('重复 start：重置旧动画（不叠加）', () => {
    const { api } = mountTypewriter({ step: 1, intervalMs: 10 })
    api.start('aaaa')
    vi.advanceTimersByTime(10)
    expect(api.text.value).toBe('a')
    api.start('bb') // 重启
    expect(api.text.value).toBe('')
    vi.advanceTimersByTime(10)
    expect(api.text.value).toBe('b')
    vi.advanceTimersByTime(10)
    expect(api.text.value).toBe('bb')
  })

  it('卸载组件：定时器被清理（无泄漏）', () => {
    const { api, wrapper } = mountTypewriter({ step: 1, intervalMs: 10 })
    api.start('abcd')
    vi.advanceTimersByTime(10)
    expect(api.text.value).toBe('a')
    wrapper.unmount()
    vi.advanceTimersByTime(100)
    // 停止推进（卸载时 stop 清掉定时器）
    expect(api.text.value).toBe('a')
    expect(api.typing.value).toBe(false)
  })
})
