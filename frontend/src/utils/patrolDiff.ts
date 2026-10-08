/** 巡检差异（批准版 vs 线上快照）的展示派生值——纯函数，供材料台账差异抽屉消费。 */

/** 变更片段类型标签（diff_service 块级比对：old=批准版，new=线上版）。 */
export const CHANGE_LABELS: Record<string, string> = {
  modified: '内容修改',
  added: '线上新增',
  removed: '批准版内容被删',
}

/** 内容保留率展示：0~1 → "87.3%"；无快照（null/undefined）→ "—"。 */
export function similarityText(value: number | null | undefined): string {
  return value == null ? '—' : `${(value * 100).toFixed(1)}%`
}
