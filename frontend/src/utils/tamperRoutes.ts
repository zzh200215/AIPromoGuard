/**
 * 疑似篡改结论的两路数字对照解析（PR-6）。
 *
 * 后端 tamper_check 把两路数字写进 original_text（稳定格式，改动会被
 * 前后端两侧测试同时拦截）：
 *   `{标签} 图片：{值} ｜ 文字：{值|未读到}`
 * 其中"文字：未读到"= 降级分支（OCR 未读到该数字 → 待人工核验）；
 * 文字侧给了具体数字 = 同位置不一致（一票 changed，疑似 P 图）。
 *
 * 聚合条目（整档核对）不带该格式 → 解析返回 null，按普通结论渲染。
 */

export interface TamperRoutes {
  /** 紧邻标签（如"年化收益率"），可空 */
  label: string | null
  /** 图片（视觉模型）读到的数字 */
  vlm: string
  /** 文字材料同位置数字；null = 未读到 */
  text: string | null
  /** true = 文字材料未读到（降级"待人工核验"分支） */
  unverified: boolean
}

/** 全角/半角竖线都接受；数字值不含空格（后端渲染时已保证） */
const ROUTE_RE = /图片[：:]\s*(\S+?)\s*[｜|]\s*文字[：:]\s*(\S+)/

export function parseTamperRoutes(originalText?: string | null): TamperRoutes | null {
  const src = (originalText ?? '').trim()
  if (!src) return null
  const m = ROUTE_RE.exec(src)
  if (!m) return null
  const vlm = m[1]
  const textRaw = m[2]
  const unverified = textRaw === '未读到'
  const label = src.slice(0, m.index).trim() || null
  return { label, vlm, text: unverified ? null : textRaw, unverified }
}
