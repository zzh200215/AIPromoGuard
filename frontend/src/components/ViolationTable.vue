<template>
  <div class="violation-table">
    <TableToolbar
      v-if="toolbar"
      v-model:visible-keys="visibleKeys"
      v-model:density="density"
      :columns="VIOLATION_COLUMNS"
      @refresh="emit('refresh')"
    />
    <el-table
      ref="tableRef"
      :data="violations"
      :size="density"
      @selection-change="onSelectionChange"
    >
      <el-table-column v-if="selectable" type="selection" width="42" :selectable="rowSelectable" />
      <el-table-column type="expand">
        <template #default="{ row }">
          <div class="violation-detail">
            <p><b>规则：</b>{{ row.rule_name || '—' }}</p>
            <p v-if="row.description"><b>说明：</b>{{ row.description }}</p>
            <p v-if="row.suggestion"><b>建议：</b>{{ row.suggestion }}</p>
            <p v-if="row.risk_reason"><b>风险依据：</b>{{ row.risk_reason }}</p>
            <p v-if="row.related_regulations?.length">
              <b>相关法规：</b>{{ row.related_regulations.join('；') }}
              <router-link
                v-if="row.regulation_id"
                class="reg-jump"
                :to="`/knowledge/regulations/${row.regulation_id}`"
              >
                查看法规 →
              </router-link>
            </p>
            <p v-if="row.related_cases?.length">
              <b>关联处罚案例：</b>
              <span v-for="c in row.related_cases" :key="c.case_name" class="case-chip">
                {{ c.case_name }}（相似度 {{ (c.similarity * 100).toFixed(0) }}%）
              </span>
            </p>
            <el-button
              v-if="rewriteable && row.result_id != null"
              size="small"
              type="primary"
              plain
              :icon="MagicStick"
              class="rewrite-btn"
              @click="emit('rewrite', row)"
            >
              AI 合规改写
            </el-button>
          </div>
        </template>
      </el-table-column>

      <el-table-column v-if="colOn('original_text')" label="原文" prop="original_text" min-width="220" show-overflow-tooltip />
      <el-table-column v-if="colOn('source')" label="来源" width="100">
        <template #default="{ row }">
          <el-tag
            size="small"
            :type="
              row.source === 'rule'
                ? 'primary'
                : row.source === 'llm'
                  ? 'warning'
                  : 'success'
            "
            effect="light"
          >
            {{ VIOLATION_SOURCE_LABELS[row.source] }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column v-if="colOn('type')" label="违规类型" width="100">
        <template #default="{ row }">{{ row.type || '—' }}</template>
      </el-table-column>
      <el-table-column v-if="colOn('risk_level')" label="风险" width="90">
        <template #default="{ row }"><SeverityTag :severity="row.risk_level" /></template>
      </el-table-column>
      <el-table-column v-if="hasHumanStatus && colOn('human')" label="人工" width="90">
        <template #default="{ row }">
          <el-tag
            v-if="row.human_status"
            size="small"
            effect="light"
            :type="HUMAN_TAG[row.human_status] ?? 'info'"
          >
            {{ row.human_status === 'confirmed' && row.human_auto_confirmed ? '已确认（自动）' : HUMAN_LABEL[row.human_status] ?? row.human_status }}
          </el-tag>
          <span v-else>—</span>
        </template>
      </el-table-column>
      <el-table-column v-if="colOn('confidence')" label="置信度" width="90">
        <template #default="{ row }">{{ (row.confidence * 100).toFixed(0) }}%</template>
      </el-table-column>
      <el-table-column v-if="colOn('location')" label="定位" width="120">
        <template #default="{ row }">
          第{{ row.page ?? '—' }}页 · 段{{ row.paragraph ?? '—' }}
        </template>
      </el-table-column>
      <el-table-column v-if="colOn('flag')" label="标记" width="100">
        <template #default="{ row }">
          <el-tag v-if="row.flag" size="small" type="warning" effect="light">{{ row.flag }}</el-tag>
          <span v-else>—</span>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { MagicStick } from '@element-plus/icons-vue'
import TableToolbar from '@/components/TableToolbar.vue'
import { VIOLATION_SOURCE_LABELS } from '@/constants/enums'
import { useTablePrefs } from '@/composables/tablePrefs'
import type { HumanStatus, ViolationItem } from '@/types/report'

const props = defineProps<{
  violations: ViolationItem[]
  /** 报告页批量判定：显示多选列（仅报告与 results 合并后可用） */
  selectable?: boolean
  /** 显示工具栏（列显隐 / 密度 / 刷新） */
  toolbar?: boolean
  /** 展开区显示「AI 合规改写」入口（有 result_id 的行） */
  rewriteable?: boolean
}>()

const emit = defineEmits<{
  selectionChange: [rows: ViolationItem[]]
  refresh: []
  rewrite: [row: ViolationItem]
}>()

// 列显隐候选（展开详情与多选列始终保留）
const VIOLATION_COLUMNS = [
  { key: 'original_text', label: '原文' },
  { key: 'source', label: '来源' },
  { key: 'type', label: '违规类型' },
  { key: 'risk_level', label: '风险' },
  { key: 'human', label: '人工' },
  { key: 'confidence', label: '置信度' },
  { key: 'location', label: '定位' },
  { key: 'flag', label: '标记' },
]
const { visibleKeys, density } = useTablePrefs(
  'app-table-cols.violations',
  VIOLATION_COLUMNS.map((c) => c.key),
)
const colOn = (key: string) => visibleKeys.value.includes(key)

const tableRef = ref()

/** 只有能关联到 results 记录的行才可批量判定 */
function rowSelectable(row: ViolationItem) {
  return row.result_id != null
}

function onSelectionChange(rows: ViolationItem[]) {
  emit('selectionChange', rows)
}

/** 供父组件在批量操作后清空选择 */
function clearSelection() {
  tableRef.value?.clearSelection()
}

defineExpose({ clearSelection })

const HUMAN_LABEL: Record<HumanStatus, string> = {
  pending_confirm: '待复核',
  confirmed: '已确认',
  false_positive: '误报剔除',
}
const HUMAN_TAG: Record<HumanStatus, string> = {
  pending_confirm: 'info',
  confirmed: 'success',
  false_positive: 'danger',
}

// 报告数据合并了人工结论后才显示该列（与其他使用 ViolationTable 的场景兼容）
const hasHumanStatus = computed(() => props.violations.some((v) => v.human_status))
</script>

<style scoped>
.violation-detail {
  padding: 4px 16px;
}

.violation-detail p {
  margin: 6px 0;
  line-height: 1.6;
  color: #606266;
}

.case-chip {
  display: inline-block;
  margin: 2px 4px 2px 0;
  padding: 1px 8px;
  background: var(--el-color-success-light-9);
  border: 1px solid var(--el-color-success-light-7);
  border-radius: 4px;
  color: var(--el-color-success-dark-2);
  font-size: 12px;
}

.reg-jump {
  margin-left: 8px;
  color: var(--el-color-primary);
  font-size: 12px;
  text-decoration: none;
}

.reg-jump:hover {
  text-decoration: underline;
}

.rewrite-btn {
  margin-top: 8px;
}
</style>
