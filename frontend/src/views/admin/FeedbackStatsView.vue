<template>
  <div>
    <PageHeader
      title="反馈统计"
      description="人工复核结论回流：按检出来源统计确认率 / 误报率，并给出规则精调建议"
    />

    <div v-loading="loading">
      <!-- 按来源聚合 -->
      <el-card class="section-card">
        <template #header>
          <span>人工复核 · 按检出来源</span>
        </template>
        <el-empty
          v-if="!Object.keys(stats?.by_source ?? {}).length"
          description="暂无复核数据"
        />
        <el-table v-else :data="sourceRows">
          <el-table-column label="来源" width="120">
            <template #default="{ row }">
              <el-tag
                size="small"
                :type="row.key === 'rule' ? 'primary' : row.key === 'llm' ? 'warning' : 'success'"
              >
                {{ VIOLATION_SOURCE_LABELS[row.key] ?? row.key }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="confirmed" label="确认违规" width="110" />
          <el-table-column prop="false_positive" label="误报" width="110" />
          <el-table-column prop="pending_confirm" label="待复核" width="110" />
          <el-table-column label="确认率" width="110">
            <template #default="{ row }">{{ fmtRate(row.confirm_rate) }}</template>
          </el-table-column>
          <el-table-column label="误报率" width="110">
            <template #default="{ row }">
              <span :class="{ 'fp-high': (row.false_positive_rate ?? 0) > 0.2 }">
                {{ fmtRate(row.false_positive_rate) }}
              </span>
            </template>
          </el-table-column>
        </el-table>

        <el-descriptions :column="4" class="totals">
          <el-descriptions-item label="整体误报率">
            <b>{{ fmtRate(stats?.overall_false_positive_rate) }}</b>
          </el-descriptions-item>
          <el-descriptions-item label="确认违规">{{ stats?.totals?.confirmed ?? 0 }}</el-descriptions-item>
          <el-descriptions-item label="误报">{{ stats?.totals?.false_positive ?? 0 }}</el-descriptions-item>
          <el-descriptions-item label="待复核">{{ stats?.totals?.pending_confirm ?? 0 }}</el-descriptions-item>
        </el-descriptions>
      </el-card>

      <!-- 规则质量 -->
      <el-card class="section-card">
        <template #header><span>规则质量（已复核规则，按误报率降序）</span></template>
        <el-empty v-if="!quality.items?.length" description="暂无已复核的规则命中" />
        <el-table v-else :data="quality.items">
          <el-table-column prop="rule_name" label="规则名称" min-width="200" show-overflow-tooltip />
          <el-table-column prop="rule_id" label="ID" width="80" />
          <el-table-column prop="hits" label="命中" width="90" />
          <el-table-column prop="confirmed" label="确认" width="90" />
          <el-table-column prop="false_positive" label="误报" width="90" />
          <el-table-column label="误报率" width="110">
            <template #default="{ row }">
              <el-tag
                size="small"
                :type="row.false_positive_rate > 0.2 ? 'danger' : row.false_positive_rate > 0.05 ? 'warning' : 'success'"
              >
                {{ fmtRate(row.false_positive_rate) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="精调建议" min-width="240">
            <template #default="{ row }">
              <div v-if="suggestionMap[row.rule_id]" class="sug-cell">
                <el-tag
                  size="small"
                  :type="suggestionMap[row.rule_id].action === 'deactivate' ? 'danger' : 'warning'"
                >
                  {{ sugLabel(suggestionMap[row.rule_id]) }}
                </el-tag>
                <el-tooltip
                  :content="sugTip(suggestionMap[row.rule_id])"
                  placement="top"
                  :show-after="200"
                >
                  <el-button size="small" type="primary" link @click="applySuggestion(row.rule_id)">
                    应用
                  </el-button>
                </el-tooltip>
              </div>
              <span v-else>—</span>
            </template>
          </el-table-column>
        </el-table>
      </el-card>
    </div>
  </div>
</template>

<script setup lang="ts">
defineOptions({ name: 'feedback-stats' })
import { computed, onMounted, ref } from 'vue'
import {
  applyRuleSuggestion,
  feedbackStats,
  listRuleSuggestions,
  rulesQuality,
} from '@/api/results'
import { VIOLATION_SOURCE_LABELS } from '@/constants/enums'
import type { FeedbackStats, RuleQualityItem, RuleSuggestion, SourceStats } from '@/types/result'

const loading = ref(false)
const stats = ref<FeedbackStats | null>(null)
const quality = ref<{ total: number; items: RuleQualityItem[] }>({ total: 0, items: [] })
const suggestions = ref<RuleSuggestion[]>([])

const suggestionMap = computed<Record<number, RuleSuggestion>>(() =>
  Object.fromEntries(suggestions.value.map((s) => [s.rule_id, s])),
)

const sourceRows = computed(() =>
  Object.entries(stats.value?.by_source ?? {}).map(([key, v]: [string, SourceStats]) => ({
    key,
    ...v,
  })),
)

function fmtRate(v: number | null | undefined): string {
  if (v == null) return '—'
  return `${(v * 100).toFixed(1)}%`
}

function sugLabel(s: RuleSuggestion): string {
  return s.action === 'deactivate' ? '建议停用' : `移除关键词「${s.keyword}」`
}

function sugTip(s: RuleSuggestion): string {
  const samples = s.fp_samples?.length ? `\n误报样本: ${s.fp_samples.join('；')}` : ''
  return `${s.reason}${samples}`
}

async function applySuggestion(ruleId: number) {
  const sug = suggestionMap.value[ruleId]
  if (!sug) return
  const ok = await ElMessageBox.confirm(
    `${sug.reason}。\n应用后将立即修改规则，可在规则库中回退。`,
    `应用建议（${sugLabel(sug)}）`,
    { type: 'warning', confirmButtonText: '应用', cancelButtonText: '取消' },
  ).catch(() => false)
  if (!ok) return
  try {
    await applyRuleSuggestion(ruleId, {
      action: sug.action,
      condition_index: sug.condition_index,
      keyword: sug.keyword,
    })
    ElMessage.success('已应用建议')
    load()
  } catch {
    // 拦截器已提示
  }
}

async function load() {
  loading.value = true
  try {
    const [s, q, sugs] = await Promise.all([
      feedbackStats(),
      rulesQuality(),
      listRuleSuggestions(),
    ])
    stats.value = s
    quality.value = q
    suggestions.value = sugs.items
  } catch {
    // 拦截器已提示
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.section-card {
  margin-bottom: 16px;
}

.totals {
  margin-top: 16px;
}

.fp-high {
  color: #f56c6c;
  font-weight: 600;
}
</style>
