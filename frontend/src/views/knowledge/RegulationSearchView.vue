<template>
  <div>
    <PageHeader title="法规检索" />

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

      <div v-if="query || searched" class="result-count">
        共命中 <b>{{ total }}</b> 条条款
      </div>

      <div v-loading="loading" class="results">
        <el-empty v-if="searched && !results.length" description="未检索到相关条款" />
        <div v-for="hit in results" :key="hit.article_id" class="hit-card">
          <div class="hit-head">
            <el-tag size="small" type="primary">{{ hit.regulation_name }}</el-tag>
            <el-tag size="small" type="info">{{ hit.article_no }}</el-tag>
            <span class="hit-score">相关度 {{ hit.score.toFixed(3) }}</span>
          </div>
          <p class="hit-content">
            <HighlightText :highlight="hit.highlight || hit.content" />
          </p>
          <div class="hit-status">
            状态：{{ REG_STATUS_LABELS[hit.status] ?? hit.status }}
          </div>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
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
  margin-bottom: 16px;
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
  background: #fff;
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

.hit-status {
  font-size: 12px;
  color: #909399;
}
</style>
