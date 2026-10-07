/**
 * 判定说明的维度前缀解析（F2-4 配套 F1-2）。
 *
 * 后端落库时给内置维度命中（PII/勾稽/篡改/视觉层）的 description 头部
 * 写入 "[rule_name] " 前缀——它是数据身份标记，但直接展示会与正文重复
 * （"[数字勾稽：演示表算术不一致] 勾稽检查发现：…"）。此处拆成
 * 身份标签 + 正文两段，前端分别渲染：标签用弱化样式，正文为主文本。
 */

export interface ParsedFindingDescription {
  /** 身份标签（去掉方括号），无前缀时为 null */
  prefixLabel: string | null
  /** 正文（不含前缀与紧随空格） */
  body: string
}

export function parseFindingDescription(desc?: string | null): ParsedFindingDescription {
  if (!desc) return { prefixLabel: null, body: '' }
  const m = /^\[([^\]]{1,80})\]\s*/.exec(desc)
  if (!m) return { prefixLabel: null, body: desc }
  return { prefixLabel: m[1], body: desc.slice(m[0].length) }
}
