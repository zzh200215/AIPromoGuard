/**
 * 违规条目的法规引用解析——纯函数，供报告证据卡消费。
 *
 * 数据形态（实测两种并存）：
 * - LLM 路：`regulation` 自由文本，如 "公开募集证券投资基金宣传推介材料管理暂行规定 第八条"
 *   或 "《商业银行理财业务监督管理办法》第二十六条"（无结构化 ID）；
 * - 规则路 / 报告级：`related_regulations` 文本数组（规则-法规关联）+
 *   `regulation_id`（可结构化跳转/展开条款）。
 *
 * 解析产物不做"唯一正确"承诺（泛引/简写均属可能），仅作为展示归组：
 * 名称 + 可选条款号；同名去重后按出现顺序返回。
 */

import type { ViolationItem } from '@/types/report'

export interface RegulationRef {
  /** 法规名称（去书名号） */
  name: string
  /** 条款号（如"第二十六条"；泛引时为 undefined） */
  articleNo?: string
  /** 结构化法规 ID（规则路/回填存在时；LLM 自由文本通常为 null） */
  regulationId?: number | null
}

/** 条款号：第X条（含中文数字/阿拉伯数字，允许后随"第X款/项"等后缀） */
const ARTICLE_RE = /第[一二三四五六七八九十百零0-9]{1,6}条(?:之[一二三四五六七八九十]{1,3})?/

/** 书名号包裹的名称（4~60 字，容忍 LLM 引用格式） */
const QUOTED_RE = /《([^》]{4,60})》/

/** 去掉条款号后缀与首尾噪声后的法规名（清洗用） */
function _cleanName(raw: string): string {
  return raw
    .replace(/^[《\s]+|[》\s、，。；:：]+$/g, '')
    .replace(/\s+/g, '')
    .trim()
}

/** 解析单条引用文本 → { name, articleNo }；无法识别返回 null */
export function parseCitation(raw: string): { name: string; articleNo?: string } | null {
  const text = (raw || '').trim()
  if (!text) return null

  const quoted = QUOTED_RE.exec(text)
  if (quoted) {
    const name = _cleanName(quoted[1])
    if (name.length < 4) return null
    const art = ARTICLE_RE.exec(text.replace(quoted[0], ''))
    return { name, articleNo: art?.[0] }
  }

  // 无书名号：条款号前的部分即名称（"名称 第八条" / "名称第二十六条"）
  const art = ARTICLE_RE.exec(text)
  if (art) {
    const name = _cleanName(text.slice(0, art.index))
    if (name.length >= 4) return { name, articleNo: art[0] }
    return null
  }

  // 无条款号：整段视为名称（含"相关条款"式泛引时去尾缀）
  const name = _cleanName(text.replace(/相关条款$|相关$/, ''))
  return name.length >= 4 ? { name } : null
}

/**
 * 汇总条目全部法规引用（regulation 自由文本 + related_regulations 数组），
 * 名称去重（保留首个条款号），并可注入结构化 regulation_id（仅单条引用时绑定，
 * 多条引用无法判断归属，不猜测）。
 */
export function collectRegulationRefs(v: ViolationItem): RegulationRef[] {
  const raws: string[] = []
  if (v.regulation) raws.push(v.regulation)
  for (const r of v.related_regulations ?? []) raws.push(r)

  const refs: RegulationRef[] = []
  const seen = new Map<string, RegulationRef>()
  for (const raw of raws) {
    const parsed = parseCitation(raw)
    if (!parsed) continue
    const key = parsed.name
    const existing = seen.get(key)
    if (existing) {
      if (!existing.articleNo && parsed.articleNo) existing.articleNo = parsed.articleNo
      continue
    }
    const ref: RegulationRef = { name: parsed.name, articleNo: parsed.articleNo }
    seen.set(key, ref)
    refs.push(ref)
  }

  // 结构化 ID 只在"单条引用且条目带 ID"时绑定（多条无法可靠归属）
  if (refs.length === 1 && v.regulation_id != null) {
    refs[0].regulationId = v.regulation_id
  }
  return refs
}

/** 信任分级解释（source → 中文口径，报告页与复核台一致） */
export const SOURCE_TRUST: Record<string, { label: string; desc: string }> = {
  rule: {
    label: '规则命中',
    desc: '确定性规则直接采信 —— 字面红线，零成本、可复现',
  },
  llm: {
    label: 'AI 疑似',
    desc: 'LLM 单独检出，标注「建议关注」—— 需人工复核确认',
  },
  hybrid: {
    label: '交叉确认',
    desc: '规则与 LLM 双引擎交叉命中 —— 置信度升级',
  },
  vlm: {
    label: '视觉关注',
    desc: '视觉层检出（排版强调/图形暗示）—— 文字引擎盲区补充',
  },
}
