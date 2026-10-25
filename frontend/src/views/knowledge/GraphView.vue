<template>
  <div>
    <PageHeader
      title="知识图谱"
      description="违规模式 → 法规条款 → 处罚案例的关联网络，输入违规点即可查证历史处罚与法规依据"
    />

    <el-card v-if="stats" class="stats-card">
      <el-row :gutter="12">
        <el-col :span="6"><StatCard label="法规" :value="stats.nodes?.Regulation" /></el-col>
        <el-col :span="6"><StatCard label="条款" :value="stats.nodes?.Article" /></el-col>
        <el-col :span="6"><StatCard label="违规模式" :value="stats.nodes?.ViolationPattern" /></el-col>
        <el-col :span="6"><StatCard label="处罚案例" :value="stats.nodes?.PenaltyCase" /></el-col>
      </el-row>
    </el-card>

    <el-card class="query-card">
      <div class="search-bar">
        <el-input
          v-model="query"
          placeholder="输入违规点，如：保本保收益、承诺预期收益、免健康告知…"
          clearable
          style="flex: 1"
          @keyup.enter="doQuery"
        />
        <el-select v-model="domain" placeholder="领域" clearable style="width: 160px">
          <el-option
            v-for="d in DOMAIN_OPTIONS"
            :key="d.value"
            :label="d.label"
            :value="d.value"
          />
        </el-select>
        <el-button type="primary" :loading="querying" @click="doQuery">图谱查询</el-button>
      </div>
      <el-alert
        v-if="stats && stats.available === false"
        type="warning"
        :closable="false"
        show-icon
        title="Neo4j 图谱当前不可用，查询将返回空结果"
        class="graph-alert"
      />
    </el-card>

    <template v-if="result">
      <el-card v-if="result.total_matched > 0" class="force-card">
        <template #header><span>图谱关联视图</span></template>
        <GraphForceChart :result="result" />
      </el-card>
      <el-row :gutter="12" class="result-row">
        <el-col :span="8">
          <el-card class="panel-card">
            <template #header><span>违规模式（{{ result.patterns.length }}）</span></template>
            <el-empty v-if="!result.patterns.length" description="无匹配" :image-size="60" />
            <div v-for="p in result.patterns" :key="p.pattern_name" class="panel-item">
              <div class="item-title">{{ p.pattern_name }}</div>
              <div class="item-meta">
                <el-tag size="small" type="info">
                  {{ (DOMAIN_LABELS as Record<string, string>)[p.domain] ?? p.domain }}
                </el-tag>
                <SeverityTag :severity="p.severity as Severity" />
                <span class="item-score">相关度 {{ (p.similarity * 100).toFixed(0) }}%</span>
              </div>
            </div>
          </el-card>
        </el-col>
        <el-col :span="8">
          <el-card class="panel-card">
            <template #header><span>关联法规（{{ result.regulations.length }}）</span></template>
            <el-empty v-if="!result.regulations.length" description="无匹配" :image-size="60" />
            <div v-for="r in result.regulations" :key="r.regulation_name" class="panel-item">
              <div class="item-title">
                <router-link
                  v-if="r.regulation_id"
                  class="reg-link"
                  :to="`/knowledge/regulations/${r.regulation_id}`"
                >
                  {{ r.regulation_name }}
                </router-link>
                <template v-else>{{ r.regulation_name }}</template>
              </div>
              <div class="item-meta">
                <span class="item-sub">条款：{{ r.article_nos.join('、') || '—' }}</span>
              </div>
            </div>
          </el-card>
        </el-col>
        <el-col :span="8">
          <el-card class="panel-card">
            <template #header><span>历史处罚案例（{{ result.cases.length }}）</span></template>
            <el-empty v-if="!result.cases.length" description="无匹配" :image-size="60" />
            <div v-for="c in result.cases" :key="c.case_name" class="panel-item">
              <div class="item-title">{{ c.case_name }}</div>
              <div class="item-meta">
                <span class="item-sub">{{ [c.penalty_org, c.penalty_date].filter(Boolean).join(' · ') }}</span>
                <span class="item-score">{{ (c.similarity * 100).toFixed(0) }}%</span>
              </div>
            </div>
          </el-card>
        </el-col>
      </el-row>
    </template>

    <el-card class="recommend-card">
      <template #header><span>相似案例推荐</span></template>
      <div class="search-bar">
        <el-input
          v-model="caseText"
          placeholder="输入违规表述，推荐历史相似处罚案例"
          clearable
          style="flex: 1"
          @keyup.enter="recommend"
        />
        <el-button type="primary" plain :loading="recommending" @click="recommend">推荐</el-button>
      </div>
      <el-empty v-if="recommended && !recommendList.length" description="未找到相似案例" :image-size="60" />
      <el-table v-if="recommendList.length" :data="recommendList">
        <el-table-column prop="case_name" label="案例名称" min-width="200" />
        <el-table-column prop="penalty_org" label="处罚机关" min-width="120" />
        <el-table-column prop="penalty_date" label="处罚日期" width="110" />
        <el-table-column label="相似度" width="100">
          <template #default="{ row }">
            <el-tag size="small" type="success">{{ (row.similarity * 100).toFixed(0) }}%</el-tag>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
defineOptions({ name: 'graph' })
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { graphStats, queryGraph, recommendCases } from '@/api/graph'
import GraphForceChart from '@/components/charts/GraphForceChart.vue'
import { DOMAIN_LABELS, DOMAIN_OPTIONS } from '@/constants/enums'
import type { Domain, Severity } from '@/types/api'
import type { GraphCase, GraphQueryResult, GraphStats } from '@/types/graph'

const route = useRoute()
const stats = ref<GraphStats | null>(null)
const query = ref('')
const domain = ref<Domain | ''>('')
const result = ref<GraphQueryResult | null>(null)
const querying = ref(false)

const caseText = ref('')
// 不能命名为 recommendCases：会遮蔽从 @/api/graph 导入的同名函数
const recommendList = ref<GraphCase[]>([])
const recommending = ref(false)
const recommended = ref(false)

async function doQuery() {
  const q = query.value.trim()
  if (!q) {
    ElMessage.warning('请输入违规点')
    return
  }
  querying.value = true
  try {
    result.value = await queryGraph({
      query: q,
      domain: domain.value || undefined,
      top_k: 10,
    })
  } catch {
    // 拦截器已提示
  } finally {
    querying.value = false
  }
}

async function recommend() {
  const t = caseText.value.trim()
  if (!t) {
    ElMessage.warning('请输入违规表述')
    return
  }
  recommending.value = true
  recommended.value = true
  try {
    const res = await recommendCases({ text: t, top_k: 10 })
    recommendList.value = res.cases
  } catch {
    // 拦截器已提示
  } finally {
    recommending.value = false
  }
}

onMounted(async () => {
  try {
    stats.value = await graphStats()
  } catch {
    // 拦截器已提示
  }
  // 法规详情页「在图谱中查看」直达：?q=法规名称 自动查询
  const q = String(route.query.q || '').trim()
  if (q) {
    query.value = q
    void doQuery()
  }
})
</script>

<style scoped>
.stats-card {
  margin-bottom: 16px;
}

.query-card {
  margin-bottom: 16px;
}

.search-bar {
  display: flex;
  align-items: center;
  gap: 10px;
}

.graph-alert {
  margin-top: 12px;
}

.force-card {
  margin-bottom: 16px;
}

.result-row {
  margin-bottom: 16px;
}

.panel-card {
  margin-bottom: 12px;
}

.panel-item {
  padding: 8px 4px;
  border-bottom: 1px dashed var(--app-border);
}

.panel-item:last-child {
  border-bottom: none;
}

.item-title {
  font-size: 14px;
  color: #303133;
  margin-bottom: 4px;
}

.reg-link {
  color: var(--el-color-primary);
  text-decoration: none;
}

.reg-link:hover {
  text-decoration: underline;
}

.item-meta {
  display: flex;
  align-items: center;
  gap: 6px;
}

.item-sub {
  font-size: 12px;
  color: #909399;
}

.item-score {
  margin-left: auto;
  font-size: 12px;
  color: #909399;
}

.recommend-card {
  margin-top: 4px;
}
</style>
