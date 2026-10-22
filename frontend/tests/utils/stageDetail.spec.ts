import { describe, expect, it } from 'vitest'
import { STAGE_ORDER, describeStage } from '@/utils/stageDetail'

describe('utils/stageDetail · 审查轨迹展示派生值', () => {
  it('STAGE_ORDER：8 个节点按执行顺序（human_review 在融合之后）', () => {
    expect(STAGE_ORDER.map((s) => s.name)).toEqual([
      'classify',
      'regulation_match',
      'rule_scan',
      'llm_scan',
      'conflict_resolve',
      'human_review',
      'risk_assess',
      'report',
    ])
  })

  it('无 detail（enrich 前的旧任务）或未知节点：返回空串优雅降级', () => {
    expect(describeStage('classify', undefined)).toBe('')
    expect(describeStage('conflict_resolve', undefined)).toBe('')
    expect(describeStage('unknown-node', { hit_count: 3 })).toBe('')
  })

  it('classify：识别成功显示领域名；未识别显示兜底语义', () => {
    expect(describeStage('classify', { domain: 'fund' })).toContain('基金')
    expect(describeStage('classify', { domain: null })).toContain('通用兜底')
  })

  it('regulation_match：条款数 + 首条名称（全字段缺失返回空串）', () => {
    const desc = describeStage('regulation_match', {
      article_count: 5,
      top_articles: [{ name: '公开募集证券投资基金销售机构监督管理办法', article_no: '第二十一条' }],
    })
    expect(desc).toContain('召回 5 条条款')
    expect(desc).toContain('《公开募集证券投资基金销售机构监督管理办法》第二十一条')
    expect(describeStage('regulation_match', {})).toBe('')
  })

  it('regulation_match：agentic 补检（可选字段）出现时附带轮次', () => {
    const desc = describeStage('regulation_match', {
      article_count: 7,
      top_articles: [],
      agentic_rounds: 2,
      agentic_added: 2,
    })
    expect(desc).toContain('补检 2 条（2 轮）')
  })

  it('llm_scan：判定数 + token；降级路径（tokens=null 且零判定）显式说明', () => {
    expect(describeStage('llm_scan', { finding_count: 4, tokens: 12345 })).toContain('12,345 tokens')
    const degraded = describeStage('llm_scan', { finding_count: 0, tokens: null })
    expect(degraded).toContain('未启用或全部失败')
    expect(describeStage('llm_scan', {})).toBe('')
  })

  it('conflict_resolve：融合总数 + 来源分布（只列非零来源）', () => {
    const desc = describeStage('conflict_resolve', {
      merged_count: 8,
      by_source: { rule: 3, llm: 4, hybrid: 1 },
    })
    expect(desc).toContain('融合 8 条')
    expect(desc).toContain('规则 3 / LLM 4 / 交叉 1')
  })

  it('human_review：未启用 / 无需复核 / 复核结果 三种语义区分', () => {
    expect(describeStage('human_review', { enabled: false })).toContain('关卡未启用')
    expect(describeStage('human_review', { enabled: true, required: false })).toContain(
      '无需人工复核',
    )
    const reviewed = describeStage('human_review', {
      enabled: true,
      required: true,
      reviewed_count: 5,
      rejected_count: 2,
    })
    expect(reviewed).toContain('复核 5 条')
    expect(reviewed).toContain('驳回 2 条')
  })

  it('risk_assess：高风险数缺省 0 不显示 undefined（by_risk 无 high 键）', () => {
    const desc = describeStage('risk_assess', {
      by_risk: { medium: 2, low: 1 },
      with_cases: 3,
    })
    expect(desc).toContain('高 0 / 中 2 / 低 1')
    expect(desc).toContain('3 条关联处罚案例')
  })

  it('report：违规结论总数', () => {
    expect(describeStage('report', { total_violations: 7 })).toContain('共 7 条违规结论')
  })
})
