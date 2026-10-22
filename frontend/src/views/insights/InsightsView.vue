<template>
  <div class="app-page">
    <PageHeader
      title="合规洞察"
      description="把审查运行数据汇成一屏：检出与复核质量、规则与法规命中、整改闭环进度（纯聚合，无 LLM 参与）"
    />

    <el-row :gutter="12" class="stat-row">
      <el-col :span="6">
        <el-card shadow="never">
          <div class="stat-label">审查任务</div>
          <div class="stat-value">{{ c.tasks_completed }}<small> / {{ c.tasks_total }}</small></div>
          <div class="stat-hint">已完成 / 总数</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never">
          <div class="stat-label">检出总数</div>
          <div class="stat-value">{{ c.findings_total }}</div>
          <div class="stat-hint">规则 + 语义 + 混合</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never">
          <div class="stat-label">复核覆盖率</div>
          <div class="stat-value">{{ coverageText }}</div>
          <div class="stat-hint">采纳率 {{ rateText }} · 待复核 {{ c.pending }}</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never">
          <div class="stat-label">在用材料</div>
          <div class="stat-value">{{ c.materials_total }}</div>
          <div class="stat-hint">存在违规 {{ c.materials_violation }} · 干净 {{ c.materials_clean }}</div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="12">
      <el-col :span="12">
        <el-card>
          <template #header><span class="card-title">近 30 天检出趋势</span></template>
          <svg viewBox="0 0 600 140" class="spark" preserveAspectRatio="none">
            <polyline :points="sparkPoints" fill="none" stroke="var(--el-color-primary)" stroke-width="2" />
            <polygon :points="sparkArea" fill="var(--el-color-primary)" opacity="0.12" />
          </svg>
          <div class="spark-axis">
            <span>{{ trendFirst }}</span>
            <span>峰值 {{ trendPeak }}</span>
            <span>{{ trendLast }}</span>
          </div>
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card>
          <template #header><span class="card-title">复核漏斗</span></template>
          <div v-for="(step, idx) in overview?.review_funnel ?? []" :key="step.label" class="funnel-row">
            <span class="funnel-label">{{ step.label }}</span>
            <div class="funnel-bar">
              <div class="funnel-fill" :style="{ width: funnelWidth(step.value), opacity: 1 - idx * 0.18 }" />
            </div>
            <span class="funnel-value">{{ step.value }}</span>
          </div>
          <div class="funnel-note">口径：采纳 = 人工确认；采纳率分母不含未复核条目</div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="12">
      <el-col :span="8">
        <el-card>
          <template #header><span class="card-title">风险分布</span></template>
          <div v-for="item in sortedRisk" :key="item.key" class="bar-row">
            <span class="bar-label">{{ RISK_LABELS[item.key] ?? item.key }}</span>
            <div class="bar-track"><div class="bar-fill" :style="{ width: pct(item.count, maxRisk), background: RISK_COLORS[item.key] ?? '#909399' }" /></div>
            <span class="bar-value">{{ item.count }}</span>
          </div>
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card>
          <template #header><span class="card-title">检出来源</span></template>
          <div v-for="item in sortedSources" :key="item.key" class="bar-row">
            <span class="bar-label">{{ SOURCE_LABELS[item.key] ?? item.key }}</span>
            <div class="bar-track"><div class="bar-fill" :style="{ width: pct(item.count, maxSource) }" /></div>
            <span class="bar-value">{{ item.count }}</span>
          </div>
          <div class="funnel-note">规则=确定性引擎 · 语义=LLM · 混合=双路一致</div>
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card>
          <template #header><span class="card-title">材料类型分布</span></template>
          <div v-for="item in overview?.material_types ?? []" :key="item.name" class="bar-row">
            <span class="bar-label">{{ item.name }}</span>
            <div class="bar-track"><div class="bar-fill" :style="{ width: pct(item.count, maxType) }" /></div>
            <span class="bar-value">{{ item.count }}</span>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="12">
      <el-col :span="12">
        <el-card>
          <template #header><span class="card-title">规则命中 Top 8</span></template>
          <el-table :data="overview?.rules_top ?? []" size="small" empty-text="暂无规则命中">
            <el-table-column prop="name" label="规则" min-width="220" show-overflow-tooltip />
            <el-table-column prop="count" label="命中" width="80" align="right" />
          </el-table>
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card>
          <template #header><span class="card-title">法规引用 Top 8</span></template>
          <el-table :data="overview?.regulations_top ?? []" size="small" empty-text="暂无法规引用">
            <el-table-column prop="name" label="法规" min-width="220" show-overflow-tooltip />
            <el-table-column prop="count" label="引用" width="80" align="right" />
          </el-table>
        </el-card>
      </el-col>
    </el-row>

    <el-card class="remediation-card">
      <template #header><span class="card-title">整改闭环</span></template>
      <div class="remedy-steps">
        <div class="remedy-step">
          <div class="remedy-num">{{ overview?.remediation.materials_total ?? 0 }}</div>
          <div class="remedy-label">台账材料</div>
        </div>
        <div class="remedy-arrow">→</div>
        <div class="remedy-step">
          <div class="remedy-num danger">{{ overview?.remediation.violation ?? 0 }}</div>
          <div class="remedy-label">检出违规</div>
        </div>
        <div class="remedy-arrow">→</div>
        <div class="remedy-step">
          <div class="remedy-num warning">{{ overview?.remediation.remediated ?? 0 }}</div>
          <div class="remedy-label">提交整改版</div>
        </div>
        <div class="remedy-arrow">→</div>
        <div class="remedy-step">
          <div class="remedy-num success">{{ overview?.remediation.clean ?? 0 }}</div>
          <div class="remedy-label">当前干净</div>
        </div>
      </div>
      <div class="funnel-note">数据来源：材料台账状态与版本；复测通过由整改复测批次回写</div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import PageHeader from '@/components/PageHeader.vue'
import { insightsOverview } from '@/api/insights'
import type { InsightCount, InsightOverview } from '@/types/insights'

const RISK_LABELS: Record<string, string> = { high: '高风险', medium: '中风险', low: '低风险', unknown: '未分级' }
const RISK_COLORS: Record<string, string> = { high: '#f56c6c', medium: '#e6a23c', low: '#909399', unknown: '#c0c4cc' }
const SOURCE_LABELS: Record<string, string> = { rule: '规则引擎', llm: '语义引擎', hybrid: '双路一致', vision: '视觉核验' }
const RISK_ORDER = ['high', 'medium', 'low', 'unknown']
const SOURCE_ORDER = ['rule', 'hybrid', 'llm', 'vision']

const overview = ref<InsightOverview | null>(null)

onMounted(async () => {
  overview.value = await insightsOverview()
})

const c = computed(() => overview.value?.cards ?? {
  tasks_total: 0, tasks_completed: 0, findings_total: 0, confirmed: 0, pending: 0,
  false_positive: 0, confirm_rate: null, materials_total: 0, materials_violation: 0,
  materials_clean: 0, batches_total: 0, batches_completed: 0,
})
const rateText = computed(() =>
  c.value.confirm_rate == null ? '—' : `${(c.value.confirm_rate * 100).toFixed(1)}%`,
)
const coverageText = computed(() =>
  c.value.review_coverage == null ? '—' : `${(c.value.review_coverage * 100).toFixed(1)}%`,
)

const sortedRisk = computed<InsightCount[]>(() =>
  [...(overview.value?.risk ?? [])].sort(
    (a, b) => RISK_ORDER.indexOf(a.key) - RISK_ORDER.indexOf(b.key),
  ),
)
const sortedSources = computed<InsightCount[]>(() =>
  [...(overview.value?.sources ?? [])].sort(
    (a, b) => SOURCE_ORDER.indexOf(a.key) - SOURCE_ORDER.indexOf(b.key),
  ),
)
const maxRisk = computed(() => Math.max(1, ...sortedRisk.value.map((i) => i.count)))
const maxSource = computed(() => Math.max(1, ...sortedSources.value.map((i) => i.count)))
const maxType = computed(() => Math.max(1, ...(overview.value?.material_types ?? []).map((i) => i.count)))
const pct = (value: number, max: number) => `${Math.round((value / max) * 100)}%`

// 30 天折线：把计数映射到 0..130 的 SVG 坐标
const sparkPoints = computed(() => {
  const data = overview.value?.trend ?? []
  if (!data.length) return ''
  const max = Math.max(1, ...data.map((d) => d.count))
  return data
    .map((d, i) => {
      const x = (i / (data.length - 1 || 1)) * 600
      const y = 130 - (d.count / max) * 120
      return `${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')
})
const sparkArea = computed(() => (sparkPoints.value ? `0,140 ${sparkPoints.value} 600,140` : ''))
const trendFirst = computed(() => overview.value?.trend[0]?.date.slice(5) ?? '')
const trendLast = computed(() => overview.value?.trend.at(-1)?.date.slice(5) ?? '')
const trendPeak = computed(() => Math.max(0, ...(overview.value?.trend ?? []).map((d) => d.count)))

const funnelMax = computed(() => Math.max(1, ...(overview.value?.review_funnel ?? []).map((s) => s.value)))
const funnelWidth = (value: number) => `${Math.max(4, Math.round((value / funnelMax.value) * 100))}%`
</script>

<style scoped>
.stat-row { margin-bottom: 12px; }
.stat-label { color: var(--el-text-color-secondary); font-size: 13px; }
.stat-value { font-size: 26px; font-weight: 600; margin-top: 4px; }
.stat-value small { font-size: 14px; color: var(--el-text-color-secondary); font-weight: 400; }
.stat-hint { color: var(--el-text-color-secondary); font-size: 12px; margin-top: 2px; }
.card-title { font-weight: 600; }
.spark { width: 100%; height: 140px; display: block; }
.spark-axis { display: flex; justify-content: space-between; color: var(--el-text-color-secondary); font-size: 12px; }
.bar-row { display: flex; align-items: center; gap: 8px; margin: 10px 0; }
.bar-label { width: 76px; color: var(--el-text-color-regular); font-size: 13px; }
.bar-track { flex: 1; height: 10px; background: var(--el-fill-color-light); border-radius: 5px; overflow: hidden; }
.bar-fill { height: 100%; background: var(--el-color-primary); border-radius: 5px; }
.bar-value { width: 36px; text-align: right; font-variant-numeric: tabular-nums; }
.funnel-row { display: flex; align-items: center; gap: 8px; margin: 10px 0; }
.funnel-label { width: 56px; color: var(--el-text-color-regular); font-size: 13px; }
.funnel-bar { flex: 1; height: 14px; background: var(--el-fill-color-light); border-radius: 7px; overflow: hidden; }
.funnel-fill { height: 100%; background: var(--el-color-primary); border-radius: 7px; }
.funnel-value { width: 40px; text-align: right; font-variant-numeric: tabular-nums; }
.funnel-note { color: var(--el-text-color-secondary); font-size: 12px; margin-top: 6px; }
.remediation-card { margin-top: 12px; }
.remedy-steps { display: flex; align-items: center; justify-content: center; gap: 18px; padding: 6px 0; }
.remedy-step { text-align: center; min-width: 110px; }
.remedy-num { font-size: 28px; font-weight: 600; }
.remedy-num.danger { color: var(--el-color-danger); }
.remedy-num.warning { color: var(--el-color-warning); }
.remedy-num.success { color: var(--el-color-success); }
.remedy-label { color: var(--el-text-color-secondary); font-size: 13px; }
.remedy-arrow { color: var(--el-text-color-placeholder); font-size: 18px; }
</style>
