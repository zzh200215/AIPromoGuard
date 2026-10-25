<template>
  <div class="graph-force">
    <EChartBase :option="option" height="420px" @chart-click="onNodeClick" />
    <div class="graph-legend">
      <span class="legend-item"><i class="dot dot--center" />查询违规点</span>
      <span class="legend-item"><i class="dot dot--pattern" />违规模式</span>
      <span class="legend-item"><i class="dot dot--reg" />关联法规（点击跳详情）</span>
      <span class="legend-item"><i class="dot dot--case" />处罚案例</span>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 图谱查询结果力导向图（P2-1）：
 * 中心节点=查询违规点，三环=违规模式（红）/关联法规（金铜，可点击跳法规库）/
 * 处罚案例（琥珀）。边为中心辐射——API 返回的是三张相关清单而非原始边，
 * 视觉呈现"违规点的一跳邻域"，不虚构模式↔法规连线。
 */
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import EChartBase from '@/components/charts/EChartBase.vue'
import { CHART_COLORS } from '@/components/charts/colors'
import type { GraphQueryResult } from '@/types/graph'

const props = defineProps<{ result: GraphQueryResult }>()
const emit = defineEmits<{ 'regulation-click': [regulationId: number] }>()
const router = useRouter()

interface ForceNode {
  id: string
  name: string
  category: number
  symbolSize: number
  value?: string
  regulationId?: number
}
interface ForceLink {
  source: string
  target: string
}

const option = computed(() => {
  const nodes: ForceNode[] = [
    {
      id: '__center__',
      name: props.result.query.slice(0, 12) || '查询',
      category: 0,
      symbolSize: 46,
    },
  ]
  const links: ForceLink[] = []

  for (const p of props.result.patterns) {
    nodes.push({
      id: `p:${p.pattern_name}`,
      name: p.pattern_name,
      category: 1,
      symbolSize: 18 + Math.round(p.similarity * 22),
      value: `相关度 ${(p.similarity * 100).toFixed(0)}%`,
    })
    links.push({ source: '__center__', target: `p:${p.pattern_name}` })
  }
  for (const r of props.result.regulations) {
    nodes.push({
      id: `r:${r.regulation_name}`,
      name: r.regulation_name,
      category: 2,
      symbolSize: 16 + Math.min(r.article_nos.length, 6) * 3,
      value: `条款 ${r.article_nos.join('、') || '—'}`,
      regulationId: r.regulation_id ?? undefined,
    })
    links.push({ source: '__center__', target: `r:${r.regulation_name}` })
  }
  for (const c of props.result.cases) {
    nodes.push({
      id: `c:${c.case_name}`,
      name: c.case_name,
      category: 3,
      symbolSize: 14 + Math.round(c.similarity * 20),
      value: c.penalty_org ?? '',
    })
    links.push({ source: '__center__', target: `c:${c.case_name}` })
  }

  return {
    backgroundColor: 'transparent',
    tooltip: {
      formatter: (p: { data?: { name?: string; value?: string; category?: number } }) =>
        p.data?.value ? `${p.data.name}<br/>${p.data.value}` : (p.data?.name ?? ''),
    },
    series: [
      {
        type: 'graph',
        layout: 'force',
        roam: true,
        draggable: true,
        data: nodes,
        links,
        categories: [
          { name: '查询', itemStyle: { color: CHART_COLORS.ink } },
          { name: '违规模式', itemStyle: { color: CHART_COLORS.danger } },
          { name: '法规', itemStyle: { color: CHART_COLORS.accent } },
          { name: '案例', itemStyle: { color: CHART_COLORS.warning } },
        ],
        label: { show: true, position: 'right', fontSize: 11, color: '#909399' },
        force: { repulsion: 220, edgeLength: [60, 140], gravity: 0.08 },
        emphasis: { focus: 'adjacency', lineStyle: { width: 3 } },
        lineStyle: { color: '#c0c4cc', width: 1, curveness: 0.1 },
      },
    ],
  }
})

/** 力导向图节点点击：法规节点 → 法规库详情（其余类型无落地页，忽略） */
function onNodeClick(raw: unknown) {
  const p = raw as { dataType?: string; data?: { regulationId?: number } }
  const rid = p?.data?.regulationId
  if (p?.dataType === 'node' && rid) {
    emit('regulation-click', rid)
    void router.push(`/knowledge/regulations/${rid}`)
  }
}
</script>

<style scoped>
.graph-force {
  position: relative;
}

.graph-legend {
  display: flex;
  gap: 16px;
  justify-content: center;
  padding: 4px 0 8px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.legend-item {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
}

.dot--center {
  background: #14110d;
}

.dot--pattern {
  background: #e5484d;
}

.dot--reg {
  background: #c8963c;
}

.dot--case {
  background: #d97706;
}
</style>
