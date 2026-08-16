/** <em> 高亮安全渲染：先 DOM 转义防 XSS，再还原 em 标签。 */

export function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

/** 输入可能含 <em> 标记（后端 highlight），转义后还原为可安全 v-html 的串。 */
export function safeHighlightHtml(input: string): string {
  return escapeHtml(input)
    .replace(/&lt;em&gt;/g, '<em>')
    .replace(/&lt;\/em&gt;/g, '</em>')
}
