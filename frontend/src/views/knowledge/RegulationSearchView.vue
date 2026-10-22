<template>
  <div>
    <PageHeader
      title="法规检索"
      description="按关键词、语义或混合方式检索法规条款，支持查看命中高亮与法规效力状态"
    />

    <el-card>
      <div class="search-bar">
        <el-input
          v-model="query"
          placeholder="输入检索内容，如：刚性兑付、适当性、宣传预期收益…"
          clearable
          style="flex: 1"
          @keyup.enter="doSearch"
        />
        <el-radio-group v-model="searchType">
          <el-radio-button value="hybrid">混合</el-radio-button>
          <el-radio-button value="keyword">关键词</el-radio-button>
          <el-radio-button value="semantic">语义</el-radio-button>
        </el-radio-group>
        <el-select
          v-model="domains"
          multiple
          placeholder="领域（选填）"
          clearable
          style="width: 200px"
        >
          <el-option
            v-for="d in DOMAIN_OPTIONS"
            :key="d.value"
            :label="d.label"
            :value="d.value"
          />
        </el-select>
        <el-button type="primary" :loading="loading" @click="doSearch">检索</el-button>
      </div>

      <div class="example-row">
        <span class="example-label">示例：</span>
        <el-tag
          v-for="ex in EXAMPLES"
          :key="ex"
          size="small"
          effect="plain"
          class="example-chip"
          @click="applyExample(ex)"
        >
          {{ ex }}
        </el-tag>
      </div>

      <div v-if="query || searched" class="result-count">
        共命中 <b>{{ total }}</b> 条条款
      </div>

      <div v-loading="loading" class="results">
        <el-empty
          v-if="searched && !results.length"
          description="未检索到相关条款——换个说法试试（如「刚性兑付」），或点击上方示例"
        />
        <div v-for="hit in results" :key="hit.article_id" class="hit-card">
          <div class="hit-head">
            <el-tag size="small" type="primary">{{ hit.regulation_name }}</el-tag>
            <el-tag size="small" type="info">{{ hit.article_no }}</el-tag>
            <span class="hit-score">相关度 {{ hit.score.toFixed(3) }}</span>
          </div>
          <p class="hit-content">
            <HighlightText :highlight="hit.highlight || hit.content" />
          </p>
          <div class="hit-foot">
            <span class="hit-status">
              状态：{{ REG_STATUS_LABELS[hit.status] ?? hit.status }}
            </span>
            <span v-if="hit.cited_rules" class="hit-link">
              被 {{ hit.cited_rules }} 条审查规则引用
            </span>
            <span v-if="hit.cited_cases" class="hit-link">
              关联 {{ hit.cited_cases }} 起真实处罚案例
            </span>
          </div>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
defineOptions({ name: 'regulation-search' })
import { ref } from 'vue'
import { searchRegulations } from '@/api/regulations'
import { DOMAIN_OPTIONS, REG_STATUS_LABELS } from '@/constants/enums'
import type { Domain } from '@/types/api'
import type { RegulationSearchHit } from '@/types/regulation'

const query = ref('')
const searchType = ref<'hybrid' | 'keyword' | 'semantic'>('hybrid')
const domains = ref<Domain[]>([])
const results = ref<RegulationSearchHit[]>([])
const loading = ref(false)
const total = ref(0)
const searched = ref(false)

/** 示例查询：覆盖六维审查的高频违规模式词（空态引导与首屏速览） */
const EXAMPLES = ['刚性兑付', '预期收益率', '适当性匹配', '保本保收益', '风险揭示', '收益承诺']

function applyExample(ex: string) {
  query.value = ex
  void doSearch()
}

async function doSearch() {
  const q = query.value.trim()
  if (!q) {
    ElMessage.warning('请输入检索内容')
    return
  }
  loading.value = true
  searched.value = true
  try {
    const res = await searchRegulations({
      query: q,
      search_type: searchType.value,
      domain: domains.value.length ? domains.value : undefined,
      top_k: 10,
    })
    results.value = res.results
    total.value = res.total
  } catch {
    // 拦截器已提示
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.search-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}

.example-row {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}

.example-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.example-chip {
  cursor: pointer;
  transition: all 0.15s;
}

.example-chip:hover {
  color: var(--el-color-primary);
  border-color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
}

.result-count {
  margin-bottom: 12px;
  color: #606266;
  font-size: 13px;
}

.hit-card {
  border: 1px solid var(--app-border);
  border-radius: 8px;
  padding: 12px 16px;
  margin-bottom: 12px;
  background: var(--app-surface);
}

.hit-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.hit-score {
  margin-left: auto;
  font-size: 12px;
  color: #909399;
}

.hit-content {
  margin: 0 0 8px;
  line-height: 1.7;
  color: #303133;
}

.hit-foot {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
  font-size: 12px;
  color: #909399;
}

.hit-link {
  color: var(--el-color-primary);
}
</style>
