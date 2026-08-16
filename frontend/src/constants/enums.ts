/** 领域/状态/枚举的中文标签映射。 */
import type { Domain, Severity } from '@/types/api'
import type { Role } from '@/types/auth'
import type { ResultStatus } from '@/types/result'

export const DOMAIN_LABELS: Record<Domain, string> = {
  banking: '银行理财',
  fund: '基金销售',
  insurance: '保险产品',
}

export const DOMAIN_OPTIONS: Array<{ value: Domain; label: string }> = [
  { value: 'banking', label: DOMAIN_LABELS.banking },
  { value: 'fund', label: DOMAIN_LABELS.fund },
  { value: 'insurance', label: DOMAIN_LABELS.insurance },
]

export const SEVERITY_LABELS: Record<Severity, string> = {
  high: '高',
  medium: '中',
  low: '低',
}

export const SEVERITY_TAG_TYPE: Record<Severity, 'danger' | 'warning' | 'info'> = {
  high: 'danger',
  medium: 'warning',
  low: 'info',
}

export const TASK_STATUS_LABELS: Record<string, string> = {
  pending: '待处理',
  running: '审查中',
  processing: '审查中',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
}

export const TASK_STATUS_TAG_TYPE: Record<string, 'info' | 'warning' | 'success' | 'danger'> = {
  pending: 'info',
  running: 'warning',
  processing: 'warning',
  completed: 'success',
  failed: 'danger',
  cancelled: 'info',
}

export const RESULT_STATUS_LABELS: Record<ResultStatus, string> = {
  pending_confirm: '待复核',
  confirmed: '确认违规',
  false_positive: '误报',
}

export const REG_STATUS_LABELS: Record<string, string> = {
  effective: '现行有效',
  amended: '已修订',
  repealed: '已废止',
}

export const RULE_TYPE_LABELS: Record<string, string> = {
  regex: '正则',
  keyword: '关键词',
  condition: '条件',
  composite: '复合',
}

export const VIOLATION_SOURCE_LABELS: Record<string, string> = {
  rule: '规则引擎',
  llm: 'LLM',
  hybrid: '混合',
}

export const ROLE_LABELS: Record<Role, string> = {
  admin: '管理员',
  reviewer: '审查员',
  viewer: '只读用户',
}
