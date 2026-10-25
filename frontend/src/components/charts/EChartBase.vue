<template>
  <div ref="el" class="echart-base" :style="{ height }" />
</template>

<script setup lang="ts">
/**
 * ECharts 基础封装（P2 可视化）：
 * - 按需注册（core + 用到的 chart/component，控制 bundle 体积）；
 * - 纸墨金铜主题色在图表层统一注入（与 styles/variables.scss 令牌同源）；
 * - 容器尺寸变化自动 resize；组件卸载即 dispose；
 * - 暗色模式跟随 html.dark（watch store 重建 option）。
 */
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { BarChart, GraphChart, LineChart, PieChart } from 'echarts/charts'
import {
  GridComponent,
  LegendComponent,
  TitleComponent,
  TooltipComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { useAppStore } from '@/stores/app'

echarts.use([
  GraphChart,
  LineChart,
  PieChart,
  BarChart,
  CanvasRenderer,
  TooltipComponent,
  GridComponent,
  LegendComponent,
  TitleComponent,
])

const props = withDefaults(defineProps<{
  option: Record<string, unknown>
  height?: string
}>(), {
  height: '320px',
})

const emit = defineEmits<{
  /** 图表元素点击（params 为 ECharts 原生 event） */
  'chart-click': [params: unknown]
}>()

const el = ref<HTMLDivElement | null>(null)
let chart: echarts.ECharts | null = null
let ro: ResizeObserver | null = null
const appStore = useAppStore()

function render() {
  if (!el.value) return
  chart?.dispose()
  chart = echarts.init(el.value, appStore.theme === 'dark' ? 'dark' : undefined)
  chart.setOption(props.option)
  chart.on('click', (params) => emit('chart-click', params))
}

function onResize() {
  chart?.resize()
}

watch(
  () => props.option,
  () => chart?.setOption(props.option, { notMerge: true }),
  { deep: true },
)
watch(
  () => appStore.theme,
  () => render(),
)

onMounted(() => {
  render()
  ro = new ResizeObserver(onResize)
  ro.observe(el.value!)
})

onBeforeUnmount(() => {
  ro?.disconnect()
  chart?.dispose()
  chart = null
})
</script>

<style scoped>
.echart-base {
  width: 100%;
}
</style>
