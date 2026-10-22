<template>
  <div class="evidence-card">
    <!-- 1) 原文与定位 -->
    <section class="ev-section">
      <div class="ev-label">原文定位</div>
      <blockquote class="ev-original">{{ violation.original_text }}</blockquote>
      <div class="ev-orig-meta">
        <span class="ev-loc">
          第{{ violation.page ?? '—' }}页 · 第{{ violation.paragraph ?? '—' }}段
        </span>
        <el-button
          v-if="rewriteable && violation.result_id != null"
          size="small"
          type="primary"
          plain
          :icon="MagicStick"
          @click="emit('rewrite', violation)"
        >
          AI 合规改写
        </el-button>
      </div>
      <div v-if="violation.suggestion" class="ev-suggestion">
        <span class="ev-suggestion-tag">修改建议</span>{{ violation.suggestion }}
      </div>
      <div v-else-if="violation.description" class="ev-suggestion">
        <span class="ev-suggestion-tag">判定说明</span>{{ violation.description }}
      </div>
    </section>

    <!-- 2) 法规依据 -->
    <section v-if="refs.length" class="ev-section">
      <div class="ev-label">法规依据（{{ refs.length }}）</div>
      <div v-for="ref in refs" :key="ref.name" class="reg-item">
        <div class="reg-head">
          <span class="reg-name">《{{ ref.name }}》</span>
          <el-tag v-if="ref.articleNo" size="small" type="info" effect="plain">
            {{ ref.articleNo }}
          </el-tag>
          <el-button
            v-if="ref.regulationId"
            text
            size="small"
            type="primary"
            class="reg-toggle"
            :loading="loadingKeys.has(ref.name)"
            @click="toggleArticle(ref)"
          >
            {{ expandedKeys.has(ref.name) ? '收起条款原文' : '查看条款原文' }}
          </el-button>
        </div>
        <div v-if="expandedKeys.has(ref.name)" class="reg-article">
          <template v-if="articleCache.get(ref.name)?.length">
            <div
              v-for="a in articleCache.get(ref.name)"
              :key="a.id"
              class="reg-article-item"
              :class="{ hit: ref.articleNo && a.article_no === ref.articleNo }"
            >
              <span class="reg-article-no">{{ a.article_no || '条款' }}</span>
              <span class="reg-article-text">{{ a.content }}</span>
            </div>
          </template>
          <div v-else class="reg-article-empty">
            未在法规库中定位到该条款（可在知识库中查看全文）
          </div>
        </div>
      </div>
    </section>

    <!-- 3) 相似处罚案例（图谱推荐，Neo4j 在线时注入） -->
    <section v-if="cases.length" class="ev-section">
      <div class="ev-label">相似处罚案例（{{ cases.length }}）</div>
      <div v-for="(c, i) in cases" :key="i" class="case-item">
        <div class="case-name" :title="c.case_name">{{ c.case_name }}</div>
        <div class="case-meta">
          <span v-if="c.penalty_org" class="case-org">{{ c.penalty_org }}</span>
          <span v-if="c.penalty_date" class="case-date">{{ c.penalty_date }}</span>
          <span class="case-sim">相似度 {{ (c.similarity * 100).toFixed(0) }}%</span>
        </div>
        <div v-if="c.penalty_result" class="case-result">{{ c.penalty_result }}</div>
      </div>
    </section>

    <!-- 4) 引擎判定与信任分级 -->
    <section class="ev-section ev-section--last">
      <div class="ev-label">引擎判定</div>
      <div class="trust-row">
        <el-tag size="small" :type="trustTagType" effect="light" class="trust-tag">
          {{ trust?.label ?? violation.source }}
        </el-tag>
        <span class="trust-desc">{{ trust?.desc }}</span>
      </div>
      <div class="trust-meta">
        <span>置信度 {{ (violation.confidence * 100).toFixed(0) }}%</span>
        <span v-if="violation.flag" class="trust-flag">{{ violation.flag }}</span>
        <span v-if="violation.evidence_supported === false" class="trust-warn">
          ⚠️ 证据待核（引用未命中召回上下文，需人工核验）
        </span>
      </div>
      <div v-if="violation.risk_reason" class="trust-reason">
        风险定级依据：{{ violation.risk_reason }}
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
/**
 * 违规证据卡（报告页 expand 区）：原文定位 / 法规依据（条款原文可按需展开）/
 * 相似处罚案例 / 引擎判定与信任分级——把"管理表格的行"升级为"证据的卡片"。
 */
import { ref } from 'vue'
import { MagicStick } from '@element-plus/icons-vue'
import { listArticles } from '@/api/regulations'
import { SOURCE_TRUST, collectRegulationRefs, type RegulationRef } from '@/utils/regulationRefs'
import type { Article } from '@/types/regulation'
import type { ViolationItem } from '@/types/report'

const props = defineProps<{
  violation: ViolationItem
  /** 显示「AI 合规改写」入口（有 result_id 的行） */
  rewriteable?: boolean
}>()

const emit = defineEmits<{ rewrite: [row: ViolationItem] }>()

const refs = collectRegulationRefs(props.violation)
const cases = props.violation.related_cases ?? []
const trust = SOURCE_TRUST[props.violation.source]

const trustTagType = (
  { rule: 'primary', llm: 'warning', hybrid: 'success', vlm: 'info' } as const
)[props.violation.source as 'rule' | 'llm' | 'hybrid' | 'vlm']

// ---- 条款原文按需展开（regulation_id 存在时） ----
const expandedKeys = ref(new Set<string>())
const loadingKeys = ref(new Set<string>())
const articleCache = ref(new Map<string, Article[]>())

async function toggleArticle(ref: RegulationRef) {
  const key = ref.name
  if (expandedKeys.value.has(key)) {
    expandedKeys.value.delete(key)
    return
  }
  expandedKeys.value.add(key)
  if (articleCache.value.has(key) || !ref.regulationId) return

  loadingKeys.value.add(key)
  try {
    const page = await listArticles(ref.regulationId, { page: 1, page_size: 100 })
    const all = page.items ?? []
    // 命中的条款优先；无命中时给前 3 条供定位参考
    const hit = ref.articleNo ? all.filter((a) => a.article_no === ref.articleNo) : []
    articleCache.value.set(key, hit.length ? hit : all.slice(0, 3))
  } catch {
    articleCache.value.set(key, [])
  } finally {
    loadingKeys.value.delete(key)
  }
}
</script>

<style scoped>
.evidence-card {
  padding: 4px 16px 8px 24px;
}

.ev-section {
  margin-bottom: 14px;
}

.ev-section--last {
  margin-bottom: 4px;
}

.ev-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--el-text-color-secondary);
  letter-spacing: 0.5px;
  margin-bottom: 6px;
}

/* ---- 原文 ---- */
.ev-original {
  margin: 0 0 6px;
  padding: 8px 12px;
  border-left: 3px solid var(--el-color-primary-light-5);
  background: var(--el-color-primary-light-9);
  border-radius: 0 6px 6px 0;
  font-size: 13px;
  line-height: 1.7;
  color: var(--el-text-color-primary);
}

.ev-orig-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 6px;
}

.ev-loc {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.ev-suggestion {
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--el-text-color-regular);
  background: var(--el-fill-color-lighter);
  border-radius: 6px;
  padding: 6px 10px;
}

.ev-suggestion-tag {
  display: inline-block;
  margin-right: 6px;
  padding: 0 6px;
  font-size: 11px;
  border-radius: 4px;
  background: var(--el-color-success-light-9);
  color: var(--el-color-success-dark-2);
  border: 1px solid var(--el-color-success-light-7);
}

/* ---- 法规 ---- */
.reg-item {
  margin-bottom: 8px;
}

.reg-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.reg-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.reg-toggle {
  padding: 0;
}

.reg-article {
  margin: 6px 0 2px 8px;
  border-left: 2px solid var(--el-border-color-lighter);
  padding-left: 10px;
}

.reg-article-item {
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--el-text-color-regular);
  margin-bottom: 6px;
}

.reg-article-item.hit {
  color: var(--el-text-color-primary);
}

.reg-article-no {
  display: inline-block;
  margin-right: 6px;
  font-weight: 600;
  color: var(--el-color-primary);
}

.reg-article-empty {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

/* ---- 案例 ---- */
.case-item {
  padding: 8px 10px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  margin-bottom: 6px;
  background: var(--el-fill-color-blank);
}

.case-name {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  line-height: 1.6;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.case-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 3px 0;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.case-sim {
  color: var(--el-color-warning-dark-2);
}

.case-result {
  font-size: 12px;
  line-height: 1.6;
  color: var(--el-text-color-regular);
}

/* ---- 信任分级 ---- */
.trust-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.trust-desc {
  font-size: 12.5px;
  color: var(--el-text-color-secondary);
}

.trust-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 6px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.trust-flag {
  color: var(--el-color-warning-dark-2);
}

.trust-warn {
  color: var(--el-color-danger);
  font-weight: 500;
}

.trust-reason {
  margin-top: 4px;
  font-size: 12px;
  line-height: 1.6;
  color: var(--el-text-color-secondary);
}
</style>
