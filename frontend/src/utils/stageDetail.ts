/**
 * 审查轨迹（stage_log.detail）的展示派生值——纯函数，供轨迹面板消费。
 *
 * 数据来源：src/core/agents/graph.py 的 _stage_detail（后端把各节点增量结果
 * 搬进 stage_log.detail）。旧任务无 detail 字段时各函数返回空串，面板优雅降级。
 */

import { DOMAIN_LABELS } from '@/constants/enums'
import type { StageNodeDetail } from '@/types/task'

/** 节点顺序与中文名（与后端 _NODES 一致；human_review 在融合之后） */
export const STAGE_ORDER: Array<{ name: string; label: string }> = [
  { name: 'classify', label: '领域识别' },
  { name: 'regulation_match', label: '法规召回' },
  { name: 'rule_scan', label: '规则扫描' },
  { name: 'llm_scan', label: 'LLM 语义审查' },
  { name: 'conflict_resolve', label: '双引擎融合' },
  { name: 'human_review', label: '人工复核' },
  { name: 'risk_assess', label: '风险定级' },
  { name: 'report', label: '报告生成' },
]

function num(v: unknown): number {
  return typeof v === 'number' && Number.isFinite(v) ? v : 0
}

/**
 * 单个节点的明细文案（中文短句）。
 * 返回空串表示无明细可显示（旧数据 / 该节点无 detail）。
 */
export function describeStage(name: string, detail?: StageNodeDetail): string {
  if (!detail) return ''

  switch (name) {
    case 'classify': {
      if (detail.domain === undefined) return ''
      return detail.domain
        ? `识别为「${DOMAIN_LABELS[detail.domain] ?? detail.domain}」领域`
        : '未识别领域，走通用兜底'
    }

    case 'regulation_match': {
      if (detail.article_count === undefined) return ''
      const parts = [`召回 ${num(detail.article_count)} 条条款`]
      const top = detail.top_articles?.[0]
      if (top?.name) {
        parts.push(`含《${top.name}》${top.article_no ?? ''}`)
      }
      if (detail.agentic_rounds) {
        parts.push(`agentic 补检 ${num(detail.agentic_added)} 条（${num(detail.agentic_rounds)} 轮）`)
      }
      return parts.join(' · ')
    }

    case 'rule_scan': {
      if (detail.hit_count === undefined) return ''
      return `命中 ${num(detail.hit_count)} 条规则`
    }

    case 'llm_scan': {
      if (detail.finding_count === undefined) return ''
      const parts = [`${num(detail.finding_count)} 条语义判定`]
      if (detail.tokens) parts.push(`${num(detail.tokens).toLocaleString()} tokens`)
      if (detail.failed_blocks) parts.push(`${num(detail.failed_blocks)} 块降级`)
      if (!detail.tokens && !detail.finding_count) parts.push('未启用或全部失败')
      return parts.join(' · ')
    }

    case 'conflict_resolve': {
      if (detail.merged_count === undefined) return ''
      const by = detail.by_source ?? {}
      const parts = [`融合 ${num(detail.merged_count)} 条`]
      const seg: string[] = []
      if (by.rule) seg.push(`规则 ${by.rule}`)
      if (by.llm) seg.push(`LLM ${by.llm}`)
      if (by.hybrid) seg.push(`交叉 ${by.hybrid}`)
      if (by.vlm) seg.push(`视觉 ${by.vlm}`)
      if (seg.length) parts.push(seg.join(' / '))
      return parts.join(' · ')
    }

    case 'human_review': {
      if (detail.enabled === undefined) return ''
      if (!detail.enabled) return '关卡未启用（直通）'
      if (detail.required) {
        return `复核 ${num(detail.reviewed_count)} 条 · 驳回 ${num(detail.rejected_count)} 条`
      }
      return '无需人工复核'
    }

    case 'risk_assess': {
      if (!detail.by_risk) return ''
      const by = detail.by_risk
      const parts = [`高 ${num(by.high)} / 中 ${num(by.medium)} / 低 ${num(by.low)}`]
      if (detail.with_cases) parts.push(`${num(detail.with_cases)} 条关联处罚案例`)
      return parts.join(' · ')
    }

    case 'report': {
      if (detail.total_violations === undefined) return ''
      return `共 ${num(detail.total_violations)} 条违规结论`
    }

    default:
      return ''
  }
}
