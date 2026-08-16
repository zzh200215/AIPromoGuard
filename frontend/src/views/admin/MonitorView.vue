<template>
  <div>
    <PageHeader title="系统监控">
      <el-button :loading="loading" @click="load">刷新</el-button>
    </PageHeader>

    <div v-loading="loading">
      <!-- 任务统计 -->
      <el-card class="section-card">
        <template #header><span>审查任务</span></template>
        <el-row :gutter="12">
          <el-col :span="6"><StatCard label="最近 24h" :value="monitor?.tasks.last_24h" /></el-col>
          <el-col :span="6">
            <StatCard label="平均耗时(s)" :value="avgDuration" />
          </el-col>
          <el-col v-for="(count, status) in taskStatusCounts" :key="status" :span="6">
            <StatCard :label="TASK_STATUS_LABELS[status] ?? status" :value="count" />
          </el-col>
        </el-row>
      </el-card>

      <!-- 数据层 -->
      <el-card class="section-card">
        <template #header><span>数据层</span></template>
        <el-row :gutter="12">
          <el-col :span="6">
            <StatCard label="数据库" :value="dbText" />
          </el-col>
          <el-col :span="6">
            <StatCard label="法规库" :value="monitor?.database.knowledge_base.regulations" />
          </el-col>
          <el-col :span="6">
            <StatCard label="规则库" :value="monitor?.database.knowledge_base.rules" />
          </el-col>
          <el-col :span="6">
            <StatCard label="用户数" :value="monitor?.database.knowledge_base.users" />
          </el-col>
        </el-row>
        <el-row :gutter="12" class="stat-row">
          <el-col :span="6">
            <StatCard label="条款向量" :value="monitor?.vector_store.legal_articles" />
          </el-col>
          <el-col :span="6">
            <StatCard label="案例向量" :value="monitor?.vector_store.legal_penalty_cases" />
          </el-col>
          <el-col :span="6">
            <StatCard label="图谱" :value="graphText" />
          </el-col>
          <el-col :span="6">
            <StatCard label="审计(24h)" :value="monitor?.audit.last_24h" />
          </el-col>
        </el-row>
      </el-card>

      <!-- 图谱详情 -->
      <el-card v-if="monitor?.graph" class="section-card">
        <template #header>
          <span>知识图谱节点 / 关系</span>
          <el-tag v-if="!monitor.graph.available" size="small" type="warning" style="margin-left: 8px">
            Neo4j 不可用
          </el-tag>
        </template>
        <el-descriptions :column="5" border size="small">
          <el-descriptions-item label="法规">
            {{ monitor.graph.nodes?.Regulation ?? '—' }}
          </el-descriptions-item>
          <el-descriptions-item label="条款">
            {{ monitor.graph.nodes?.Article ?? '—' }}
          </el-descriptions-item>
          <el-descriptions-item label="违规模式">
            {{ monitor.graph.nodes?.ViolationPattern ?? '—' }}
          </el-descriptions-item>
          <el-descriptions-item label="产品类型">
            {{ monitor.graph.nodes?.ProductType ?? '—' }}
          </el-descriptions-item>
          <el-descriptions-item label="处罚案例">
            {{ monitor.graph.nodes?.PenaltyCase ?? '—' }}
          </el-descriptions-item>
          <el-descriptions-item label="关系数">
            {{ monitor.graph.relationships ? Object.values(monitor.graph.relationships).reduce((a, b) => a + (b || 0), 0) : '—' }}
          </el-descriptions-item>
        </el-descriptions>
      </el-card>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { systemMonitor } from '@/api/monitor'
import { TASK_STATUS_LABELS } from '@/constants/enums'

const monitor = ref<Awaited<ReturnType<typeof systemMonitor>> | null>(null)
const loading = ref(false)

const avgDuration = computed(() => {
  const v = monitor.value?.tasks.avg_duration_seconds
  return v != null ? Math.round(v) : null
})

const dbText = computed(() => (monitor.value?.database.ok ? '正常' : '异常'))

const graphText = computed(() => {
  const g = monitor.value?.graph
  if (!g) return null
  return g.available ? '可用' : '不可用'
})

const taskStatusCounts = computed(() => {
  const t = monitor.value?.tasks ?? {}
  const statuses = ['pending', 'running', 'processing', 'completed', 'failed', 'cancelled']
  return Object.fromEntries(
    statuses.filter((s) => t[s] != null).map((s) => [s, t[s] as number]),
  )
})

async function load() {
  loading.value = true
  try {
    monitor.value = await systemMonitor()
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

.stat-row {
  margin-top: 12px;
}
</style>
