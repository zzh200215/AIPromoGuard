<template>
  <div class="table-toolbar">
    <div class="toolbar-left">
      <slot name="left" />
    </div>

    <div class="toolbar-right">
      <el-tooltip content="刷新列表" placement="top">
        <button class="tool-btn" type="button" aria-label="刷新列表" @click="emit('refresh')">
          <el-icon :size="14"><Refresh /></el-icon>
        </button>
      </el-tooltip>

      <el-dropdown trigger="click" @command="onDensity">
        <button class="tool-btn" type="button" title="表格密度">
          <el-icon :size="14"><Operation /></el-icon>
          <span class="tool-text">{{ densityLabel }}</span>
          <el-icon :size="11" class="caret"><ArrowDown /></el-icon>
        </button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item
              v-for="opt in DENSITY_OPTIONS"
              :key="opt.value"
              :command="opt.value"
              :class="{ 'is-active': opt.value === density }"
            >
              {{ opt.label }}
            </el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>

      <el-popover trigger="click" :width="220" placement="bottom-end">
        <template #reference>
          <button class="tool-btn" type="button" title="列设置">
            <el-icon :size="14"><Setting /></el-icon>
            <span class="tool-text">列设置</span>
          </button>
        </template>
        <div class="col-panel">
          <div class="col-panel-head">
            <span class="col-panel-title">显示字段</span>
            <el-button link type="primary" size="small" @click="resetColumns">恢复默认</el-button>
          </div>
          <el-checkbox-group v-model="visibleKeys" class="col-list">
            <el-checkbox
              v-for="col in columns"
              :key="col.key"
              :value="col.key"
              :disabled="visibleKeys.length <= 1 && visibleKeys.includes(col.key)"
            >
              {{ col.label }}
            </el-checkbox>
          </el-checkbox-group>
        </div>
      </el-popover>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { ArrowDown, Operation, Refresh, Setting } from '@element-plus/icons-vue'
import type { TableDensity } from '@/composables/tablePrefs'

interface ToolbarColumn {
  key: string
  label: string
}

const props = defineProps<{
  /** 可隐藏列的候选清单（操作/多选/展开列由表格自身保留，不在此列） */
  columns: ToolbarColumn[]
}>()

const emit = defineEmits<{
  refresh: []
}>()

const visibleKeys = defineModel<string[]>('visibleKeys', { required: true })
const density = defineModel<TableDensity>('density', { required: true })

const DENSITY_OPTIONS: { value: TableDensity; label: string }[] = [
  { value: 'small', label: '紧凑' },
  { value: 'default', label: '默认' },
  { value: 'large', label: '宽松' },
]

const densityLabel = computed(
  () => DENSITY_OPTIONS.find((o) => o.value === density.value)?.label ?? '默认',
)

function onDensity(value: TableDensity) {
  density.value = value
}

function resetColumns() {
  visibleKeys.value = props.columns.map((c) => c.key)
}
</script>

<style scoped lang="scss">
.table-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 28px;
  margin-bottom: 12px;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: 2px;
  flex-shrink: 0;
}

.tool-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 26px;
  padding: 0 8px;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: var(--el-text-color-regular);
  font-size: 13px;
  font-family: inherit;
  cursor: pointer;
  transition: background 0.15s, color 0.15s;

  &:hover {
    background: var(--el-color-primary-light-9);
    color: var(--el-color-primary);
  }
}

.caret {
  color: var(--el-text-color-secondary);
}

.col-panel {
  .col-panel-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 4px;
  }

  .col-panel-title {
    font-size: 13px;
    font-weight: 600;
    color: var(--el-text-color-primary);
  }

  .col-list {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 2px;
  }
}
</style>
