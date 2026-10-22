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
      :data="rows"
      :size="density"
      row-key="_rowKey"
      :expand-row-keys="expandedKeys"
      @selection-change="onSelectionChange"
      @row-click="onRowClick"
    >
      <el-table-column v-if="selectable" type="selection" width="42" :selectable="rowSelectable" />
      <el-table-column type="expand">
        <template #default="{ row }">
          <ViolationEvidence
            :violation="row"
            :rewriteable="rewriteable"
            @rewrite="emit('rewrite', $event)"
          />
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
import TableToolbar from '@/components/TableToolbar.vue'
import ViolationEvidence from '@/components/ViolationEvidence.vue'
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

/** 行标识：优先 result_id，缺失时按下标——供整行展开用 */
type Row = ViolationItem & { _rowKey: string }
const rows = computed<Row[]>(() =>
  props.violations.map((v, i) => ({
    ...v,
    _rowKey: v.result_id != null ? `r-${v.result_id}` : `i-${i}`,
  })),
)
const expandedKeys = ref<string[]>([])

/**
 * 整行点击即展开/收起证据卡（2026-10-19 演示实操：展开箭头热区太小，现场易点空）。
 * 行内按钮/链接/表单控件的点击不触发展开，避免误操作。
 */
function onRowClick(row: Row, _column: unknown, event: MouseEvent) {
  const target = event.target as HTMLElement | null
  if (
    target?.closest(
      'button, a, input, textarea, .el-button, .el-checkbox, .el-radio, .el-select, .el-switch',
    )
  ) {
    return
  }
  const idx = expandedKeys.value.indexOf(row._rowKey)
  if (idx >= 0) expandedKeys.value.splice(idx, 1)
  else expandedKeys.value.push(row._rowKey)
}

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
/* expand 区由 ViolationEvidence 组件承载（证据卡样式在其内部） */
/* 整行可点：给正文行一个手型光标，暗示可展开 */
.violation-table :deep(.el-table__body > tbody > tr:not(.el-table__expanded-cell)) {
  cursor: pointer;
}
</style>
