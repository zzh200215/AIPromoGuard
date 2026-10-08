import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { nextTick } from 'vue'
import ReviewWorkbench from '@/components/ReviewWorkbench.vue'
import type { ReviewResult } from '@/types/result'

/**
 * 组件行为测试（渲染/选中/过滤）。键盘判定语义在 useKeyboardShortcuts.spec.ts
 * 纯函数层覆盖；此文件不依赖 window keydown 事件机制（jsdom 下该机制不稳定）。
 */
function resultOf(
  id: number,
  status: ReviewResult['status'],
  risk_level: ReviewResult['risk_level'] = 'high',
  confidence = 0.9,
): ReviewResult {
  return {
    result_id: id,
    violation_type: 'rule',
    risk_level,
    original_text: `违规片段${id}`,
    confidence_score: confidence,
    status,
  }
}

describe('ReviewWorkbench · 渲染与选中', () => {
  const results = [
    resultOf(1, 'pending_confirm'),
    resultOf(2, 'pending_confirm', 'medium'),
    resultOf(3, 'pending_confirm', 'low'),
    resultOf(4, 'confirmed'),
  ]

  it('默认待复核分组，队列条目数正确', () => {
    const wrapper = mount(ReviewWorkbench, { props: { results, canConfirm: true } })
    expect(wrapper.findAll('.queue-item').length).toBe(3)
  })

  it('默认选中第一条待复核', () => {
    const wrapper = mount(ReviewWorkbench, { props: { results, canConfirm: true } })
    expect(wrapper.findAll('.queue-item')[0].classes()).toContain('active')
  })

  it('原文条目渲染 original_text', () => {
    const wrapper = mount(ReviewWorkbench, { props: { results, canConfirm: true } })
    expect(wrapper.find('.queue-item').text()).toContain('违规片段1')
  })

  it('待复核清空时显示空态文案', () => {
    const wrapper = mount(ReviewWorkbench, {
      props: { results: [resultOf(9, 'confirmed')], canConfirm: true },
    })
    expect(wrapper.text()).toContain('待复核已清空')
  })

  it('上一条/下一条按钮驱动选中切换（step 逻辑）', async () => {
    const wrapper = mount(ReviewWorkbench, { props: { results, canConfirm: true } })
    const buttons = wrapper.findAll('button')
    // nav 区两个按钮：上一条（禁用，index=0）/ 下一条
    const nextBtn = buttons.find((b) => b.text().includes('下一条'))
    expect(nextBtn).toBeTruthy()
    await nextBtn!.trigger('click')
    expect(wrapper.findAll('.queue-item')[1].classes()).toContain('active')
  })

  it('队列底部显示复核进度', () => {
    const wrapper = mount(ReviewWorkbench, { props: { results, canConfirm: true } })
    expect(wrapper.find('.queue-foot').text()).toContain('1 / 4')
  })
})

describe('ReviewWorkbench · a11y（F3-2）', () => {
  const results = [resultOf(1, 'pending_confirm'), resultOf(2, 'pending_confirm')]

  it('队列为 listbox，条目为 option 且标记选中态', () => {
    const wrapper = mount(ReviewWorkbench, { props: { results, canConfirm: true } })
    expect(wrapper.find('[role="listbox"]').exists()).toBe(true)
    const options = wrapper.findAll('[role="option"]')
    expect(options.length).toBe(2)
    expect(options[0].attributes('aria-selected')).toBe('true')
    expect(options[1].attributes('aria-selected')).toBe('false')
  })

  it('条目可聚焦（选中项 tabindex=0，其余 -1）且带 aria-label', () => {
    const wrapper = mount(ReviewWorkbench, { props: { results, canConfirm: true } })
    const options = wrapper.findAll('[role="option"]')
    expect(options[0].attributes('tabindex')).toBe('0')
    expect(options[1].attributes('tabindex')).toBe('-1')
    expect(options[0].attributes('aria-label')).toContain('风险')
  })

  it('详情面板为带标签的 region', () => {
    const wrapper = mount(ReviewWorkbench, { props: { results, canConfirm: true } })
    const region = wrapper.find('[role="region"]')
    expect(region.exists()).toBe(true)
    expect(region.attributes('aria-label')).toBe('结论详情')
  })

  it('状态筛选组有可访问名称', () => {
    const wrapper = mount(ReviewWorkbench, { props: { results, canConfirm: true } })
    expect(wrapper.find('[role="group"]').attributes('aria-label')).toBe('按复核状态筛选')
  })
})

describe('ReviewWorkbench · 复核路由（PR-2）', () => {
  // 排序键 (1-c)×weight：id1=0.05 / id2=2.1 / id3=0.3 / id4=1.2
  // → 风险序 2 > 4 > 3 > 1；检出序（id 升序）1 > 2 > 3 > 4
  const results = [
    resultOf(1, 'pending_confirm', 'low', 0.95),
    resultOf(2, 'pending_confirm', 'high', 0.3),
    resultOf(3, 'pending_confirm', 'high', 0.9),
    resultOf(4, 'pending_confirm', 'medium', 0.4),
  ]

  it('默认风险优先：低置信×高风险（id=2）排首位且带 urgent 高亮', () => {
    const wrapper = mount(ReviewWorkbench, { props: { results, canConfirm: true } })
    const first = wrapper.findAll('.queue-item')[0]
    expect(first.text()).toContain('违规片段2')
    expect(first.classes()).toContain('queue-item--urgent')
  })

  it('默认选中与视觉队列首条一致（风险序，非数据原始序）', () => {
    const wrapper = mount(ReviewWorkbench, { props: { results, canConfirm: true } })
    // 详情区（current）展示排序首条 id=2；数据原始序首条 id=1 不应被选中
    expect(wrapper.find('.detail').text()).toContain('违规片段2')
  })

  it('切到检出顺序：按 result_id 升序（不依赖接口返回顺序）', async () => {
    const wrapper = mount(ReviewWorkbench, { props: { results, canConfirm: true } })
    const sw = wrapper.findComponent({ name: 'ElSwitch' })
    expect(sw.exists()).toBe(true)
    await sw.vm.$emit('update:modelValue', false)
    await nextTick()
    expect(wrapper.findAll('.queue-item')[0].text()).toContain('违规片段1')
  })

  it('低置信×高风险行带 urgent 高亮，其余行不标', () => {
    const wrapper = mount(ReviewWorkbench, { props: { results, canConfirm: true } })
    const urgent = wrapper.findAll('.queue-item--urgent')
    expect(urgent.length).toBe(1)
    expect(urgent[0].text()).toContain('违规片段2')
  })
})
