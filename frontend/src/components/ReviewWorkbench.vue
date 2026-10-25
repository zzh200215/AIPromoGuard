<template>
  <div class="workbench" :class="{ 'with-doc': hasDoc }">
    <!-- 左侧：违规队列 -->
    <div class="queue">
      <div class="queue-head">
        <div role="group" aria-label="按复核状态筛选">
          <el-radio-group v-model="statusFilter" size="small">
            <el-radio-button value="pending_confirm">
              待复核 {{ countOf('pending_confirm') }}
            </el-radio-button>
            <el-radio-button value="confirmed">已确认 {{ countOf('confirmed') }}</el-radio-button>
            <el-radio-button value="false_positive">误报 {{ countOf('false_positive') }}</el-radio-button>
          </el-radio-group>
        </div>
        <el-tooltip
          content="风险优先：AI 最拿不准（低置信）且危害最大的排前，把判断力放在最需要的地方"
          placement="bottom"
        >
          <el-switch
            v-model="priorityFirst"
            size="small"
            inline-prompt
            active-text="风险优先"
            inactive-text="检出顺序"
            class="order-switch"
          />
        </el-tooltip>
      </div>

      <el-scrollbar class="queue-list" role="listbox" aria-label="违规复核队列">
        <div
          v-for="item in filtered"
          :key="item.result_id"
          class="queue-item"
          :class="{ active: item.result_id === selectedId, 'queue-item--urgent': isUrgent(item) }"
          role="option"
          :aria-selected="item.result_id === selectedId"
          :tabindex="item.result_id === selectedId ? 0 : -1"
          :aria-label="`${SEVERITY_LABELS[item.risk_level]}风险 ${kindLabel(item)} 结论`"
          @click="selectedId = item.result_id"
          @keydown.enter.prevent="selectedId = item.result_id"
          @keydown.space.prevent="selectedId = item.result_id"
        >
          <div class="queue-item-top">
            <SeverityTag :severity="item.risk_level" />
            <el-tooltip placement="top" :content="kindTip(item)">
              <el-tag size="small" :type="kindTag(item).type" :effect="kindTag(item).effect">
                {{ kindLabel(item) }}
              </el-tag>
            </el-tooltip>
            <ResultStatusMini :status="item.status" :auto-confirmed="item.auto_confirmed" />
          </div>
          <div class="queue-item-text">{{ item.original_text }}</div>
          <div class="conf-bar" :class="confClass(item)">
            <span class="conf-bar-fill" :style="{ width: `${Math.round(item.confidence_score * 100)}%` }" />
          </div>
        </div>
        <el-empty
          v-if="!filtered.length"
          :description="statusFilter === 'pending_confirm' ? '待复核已清空' : '暂无数据'"
          :image-size="72"
        />
      </el-scrollbar>

      <div class="queue-foot">
        <span v-if="results.length">
          已复核 {{ countOf('confirmed') + countOf('false_positive') }} / {{ results.length }}
        </span>
        <span v-else>—</span>
        <span class="kbd-hints">
          <kbd>J</kbd>/<kbd>K</kbd> 切换
          <template v-if="canConfirm">
            <kbd>C</kbd> 确认 <kbd>X</kbd> 误报
          </template>
        </span>
      </div>
    </div>

    <!-- 中间：文档原文对照 / 图片原图（有内容时才出现） -->
    <div v-if="hasDoc" class="doc-pane">
      <div class="doc-head">
        <el-icon><Document /></el-icon>
        <span class="doc-name">{{ documentName }}</span>
        <span class="doc-hint">{{ documentImageUrl ? '对照原图核验视觉层结论' : '点击高亮可定位违规' }}</span>
      </div>
      <el-scrollbar class="doc-scroll">
        <!-- F2-2 图片材料：显示原图（视觉层审查的对象本身就是这张图） -->
        <div v-if="documentImageUrl" class="doc-image-wrap">
          <img class="doc-image" :src="documentImageUrl" :alt="documentName || '材料原图'" />
        </div>
        <div v-else ref="docBodyRef" class="doc-body" @click="onDocClick">
          <div
            v-for="(item, i) in renderedBlocks"
            :key="i"
            class="doc-block"
            :class="{ heading: item.block.heading }"
            v-html="item.html"
          />
          <div v-if="docLoading" v-loading="true" class="doc-loading" />
        </div>
      </el-scrollbar>
    </div>

    <!-- 右侧：选中违规详情 -->
    <div class="detail" role="region" aria-label="结论详情">
      <template v-if="current">
        <div class="detail-head">
          <div class="detail-chips">
            <SeverityTag :severity="current.risk_level" />
            <el-tooltip placement="top" :content="kindTip(current)">
              <el-tag size="small" :type="kindTag(current).type" :effect="kindTag(current).effect">
                {{ kindLabel(current) }}
              </el-tag>
            </el-tooltip>
            <el-tag v-if="current.auto_confirmed" size="small" type="success" effect="light">
              系统自动确认
            </el-tag>
            <el-tooltip
              v-if="current.confidence_score < LOW_CONFIDENCE"
              content="AI 对该结论把握不足，建议重点核对判定依据与原图/原文"
              placement="top"
            >
              <el-tag size="small" type="warning" effect="dark">AI 不确定</el-tag>
            </el-tooltip>
            <span v-if="current.location_page != null" class="loc">
              第{{ current.location_page }}页 · 第{{ current.location_paragraph ?? '—' }}段
            </span>
          </div>

          <div class="nav">
            <el-button size="small" :disabled="index <= 0" :icon="ArrowUp" @click="step(-1)">
              上一条
            </el-button>
            <span class="nav-pos num">{{ index + 1 }} / {{ filtered.length }}</span>
            <el-button size="small" :disabled="index >= filtered.length - 1" @click="step(1)">
              下一条 <el-icon class="el-icon--right"><ArrowDown /></el-icon>
            </el-button>
          </div>
        </div>

        <!-- 原文引用（无对照视图时是主要定位手段） -->
        <blockquote class="quote">{{ current.original_text }}</blockquote>

        <!-- PR-6 两路数字对照：疑似篡改结论必须让复核人一眼看到"图片读数 vs
             文字材料读数"，降级条目（OCR 未读到）在此显式标"待人工核验" -->
        <div v-if="tamperRoutes" class="tamper-card">
          <div class="tr-head">
            <span class="tr-title">数字两路对照</span>
            <el-tag v-if="tamperRoutes.unverified" size="small" type="warning" effect="light">
              待人工核验
            </el-tag>
            <span v-else class="tr-note">同位置数字不一致，疑似图片被局部修改</span>
          </div>
          <div class="tr-grid">
            <div class="tr-cell">
              <div class="tr-label">图片（视觉模型读到）</div>
              <div class="tr-value num">{{ tamperRoutes.vlm }}</div>
              <div class="tr-sub">{{ tamperRoutes.label ?? '关键数字' }}</div>
            </div>
            <div class="tr-vs">VS</div>
            <div class="tr-cell" :class="{ 'tr-miss': tamperRoutes.unverified }">
              <div class="tr-label">文字材料（OCR / 解析）</div>
              <div class="tr-value num">{{ tamperRoutes.text ?? '未读到' }}</div>
              <div class="tr-sub">{{ tamperRoutes.label ?? '同位置' }}</div>
            </div>
          </div>
          <div v-if="tamperRoutes.unverified" class="tr-guide">
            文字层未读到该数字（可能为 OCR 漏读小字）——请人工核对原图，确认图中数字是否真实存在
          </div>
        </div>

        <!-- P1-2 证据对照：法规条款全文（选中即自动加载，无需点击）+ 相似罚单案例 -->
        <div v-if="current.regulation_name || articleFull || currentCases.length" class="evidence">
          <div class="ev-seg">
            <div class="ev-seg-head">
              <el-icon><Collection /></el-icon>
              <span>法规条款</span>
              <span v-if="current.regulation_no" class="ev-seg-sub">{{ current.regulation_no }}</span>
            </div>
            <div v-if="current.regulation_name" class="reg-name">
              《{{ current.regulation_name }}》{{ current.article_no || '' }}
            </div>
            <div v-if="articleLoading" v-loading="true" class="reg-full reg-full--loading" />
            <div v-else-if="articleFull" class="reg-full">
              <span v-if="articleFull.no" class="reg-full-no">{{ articleFull.no }}</span>
              {{ articleFull.content }}
            </div>
            <div v-else-if="current.article_excerpt" class="reg-full reg-full--excerpt">
              {{ current.article_excerpt }}…
            </div>
            <div v-else class="reg-empty">未在法规库定位到条款原文</div>
          </div>

          <div v-if="currentCases.length" class="ev-seg">
            <div class="ev-seg-head">
              <el-icon><Document /></el-icon>
              <span>相似处罚案例（{{ currentCases.length }}）</span>
            </div>
            <div v-for="(c, i) in currentCases" :key="i" class="case-card">
              <div class="case-card-name" :title="c.case_name">{{ c.case_name }}</div>
              <div class="case-card-meta">
                <span v-if="c.penalty_org">{{ c.penalty_org }}</span>
                <span v-if="c.penalty_date">{{ c.penalty_date }}</span>
                <span class="case-card-sim">相似度 {{ (c.similarity * 100).toFixed(0) }}%</span>
              </div>
              <div v-if="c.penalty_result" class="case-card-result">{{ c.penalty_result }}</div>
            </div>
          </div>
        </div>

        <!-- AI 判断 -->
        <div class="judge">
          <p v-if="current.description" class="judge-desc">
            <span class="judge-label">判定说明</span>
            <span v-if="descParts.prefixLabel" class="finding-prefix">{{ descParts.prefixLabel }}</span>
            {{ descParts.body }}
          </p>
          <p v-if="current.suggestion" class="judge-suggestion">
            <span class="judge-label">修改建议</span>{{ current.suggestion }}
          </p>
          <div class="judge-confidence">
            <span class="judge-label">置信度</span>
            <el-progress
              class="judge-bar"
              :percentage="Math.round(current.confidence_score * 100)"
              :stroke-width="6"
              :show-text="false"
              :aria-label="`AI 置信度 ${Math.round(current.confidence_score * 100)}%`"
            />
            <span class="num judge-pct">{{ (current.confidence_score * 100).toFixed(0) }}%</span>
          </div>

          <!-- F2-1 不确定性具体化（AISA 模式）：不只说"低置信"，给出 AI 的判断依据，
               让复核从"通读全部"变成"核对这几条" -->
          <el-collapse v-model="adviceOpen" class="advice-collapse">
            <el-collapse-item name="advice">
              <template #title>
                <span class="advice-title">
                  AI 判定依据
                  <span v-if="advice" class="advice-suggest">
                    预判「{{ advice.suggested_verdict === 'confirmed' ? '成立' : '误报' }}」
                  </span>
                </span>
              </template>
              <div v-if="adviceLoading" v-loading="true" class="advice-loading" />
              <ul v-else-if="advice" class="advice-list">
                <li v-for="(reason, i) in advice.reasons" :key="i">{{ reason }}</li>
              </ul>
              <div v-else class="advice-empty">暂无 AI 判定辅助（可能未启用或调用失败）</div>
            </el-collapse-item>
          </el-collapse>
        </div>

        <!-- 生命周期（F2-3）：判定轨迹回放——审计员四问之"能否事后追溯"的页面侧答案 -->
        <el-collapse v-if="current" v-model="trailOpen" class="trail-collapse">
          <el-collapse-item name="trail">
            <template #title>
              <span class="trail-title">
                生命周期
                <span v-if="trailEvents.length" class="trail-count num">
                  {{ trailEvents.length }} 步
                </span>
              </span>
            </template>
            <div v-if="trailLoading" v-loading="true" class="trail-loading" />
            <el-timeline v-else class="trail-list">
              <el-timeline-item
                v-for="(ev, i) in trailEvents"
                :key="i"
                :timestamp="ev.at"
                :type="TRAIL_TYPE[ev.type] ?? 'info'"
                size="small"
              >
                <div class="trail-item">
                  <span class="trail-detail">{{ ev.detail }}</span>
                  <span class="trail-actor">{{ ev.actor }}</span>
                </div>
              </el-timeline-item>
            </el-timeline>
          </el-collapse-item>
        </el-collapse>

        <!-- 复核操作 -->
        <div class="actions">
          <template v-if="current.status === 'pending_confirm'">
            <el-button v-if="canConfirm" plain type="danger" @click="emit('false-positive', current)">
              标记误报
            </el-button>
            <el-button v-if="canConfirm" type="success" @click="emit('confirm', current)">
              确认违规
            </el-button>
            <span v-else class="no-perm">当前账号无复核权限</span>
          </template>
          <template v-else-if="canConfirm">
            <el-button plain @click="overturn">
              翻案为{{ current.status === 'confirmed' ? '误报' : '确认违规' }}
            </el-button>
            <span class="done-hint">已判定结果可翻案，翻案计入人工复核统计</span>
          </template>
        </div>
      </template>
      <el-empty v-else description="左侧选择一条审查结论查看详情" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from 'vue'
import { ArrowDown, ArrowUp, Collection, Document } from '@element-plus/icons-vue'
import { getVerdictAdvice, type VerdictAdvice } from '@/api/ai'
import type { DocumentBlock } from '@/api/tasks'
import { getResultTrail, type TrailEvent } from '@/api/results'
import { resolveKeyAction, shouldIgnoreKeydown } from '@/composables/useKeyboardShortcuts'
import { parseFindingDescription } from '@/utils/findingText'
import { parseTamperRoutes } from '@/utils/tamperRoutes'
import { SEVERITY_LABELS, VIOLATION_SOURCE_LABELS } from '@/constants/enums'
import type { ReviewResult, ResultStatus } from '@/types/result'
import type { RelatedCase } from '@/types/report'
import { listArticles } from '@/api/regulations'
import ResultStatusMini from './ResultStatusMini.vue'
import SeverityTag from './SeverityTag.vue'

const props = defineProps<{
  results: ReviewResult[]
  canConfirm: boolean
  /** 报告侧的相似处罚案例（result_id → cases）；工作台数据源不同，经父级桥接 */
  caseByResultId?: Map<number, RelatedCase[]>
  /** 文档解析原文块；为空时退回两栏布局 */
  documentBlocks?: DocumentBlock[] | null
  documentName?: string
  docLoading?: boolean
  /** 图片材料的原图 objectURL（F2-2）；有值时中栏渲染原图而非文本块 */
  documentImageUrl?: string | null
  /** 快捷键开关：确认/翻案弹窗打开时由父级置 false，避免误触 */
  shortcutsEnabled?: boolean
}>()

const emit = defineEmits<{
  (e: 'confirm', row: ReviewResult): void
  (e: 'false-positive', row: ReviewResult): void
}>()

/** 双引擎信任分级的口径说明：规则命中=确定模式，LLM 单独命中=AI 疑似，交叉=高置信 */
const SOURCE_TIP: Record<string, string> = {
  rule: '规则引擎命中预设风险模式，确定性高',
  llm: 'LLM 语义判定的疑似风险，需人工判断',
  hybrid: '规则与 LLM 双引擎交叉命中，置信度高',
  vlm: '视觉模型识别（图片材料）',
}

/** F1-2 内置维度的身份标签：finding_kind 优先于来源标签（六维度在 UI 可分辨） */
const KIND_LABELS: Record<string, string> = {
  pii: 'PII 敏感信息',
  consistency: '数字勾稽',
  tamper: '疑似篡改',
  visual: '视觉层',
}
const KIND_TAG: Record<string, { type: 'danger' | 'warning' | 'info'; effect: 'dark' | 'light' }> = {
  pii: { type: 'danger', effect: 'dark' }, // 身份泄露=确定性红线
  tamper: { type: 'danger', effect: 'light' }, // 对抗性风险，待人工核验
  consistency: { type: 'warning', effect: 'light' }, // 确定性算术校验
  visual: { type: 'info', effect: 'light' },
}
const KIND_TIP: Record<string, string> = {
  pii: '内置检测（代码级不可停用）：材料含客户身份/联系方式，一票命中',
  tamper: '图片数字与文字材料不一致：同位置数值不同=疑似 P 图（一票命中）；文字层未读到=待人工核验（可能 OCR 漏读小字）',
  consistency: '演示表算术校验：期末金额、收益测算、正文与表格的数字一致性',
  visual: '视觉模型识别的排版/符号/弱化类风险',
}

function kindLabel(item: ReviewResult): string {
  const kind = item.finding_kind
  if (kind && KIND_LABELS[kind]) return KIND_LABELS[kind]
  return VIOLATION_SOURCE_LABELS[item.violation_type] ?? item.violation_type
}
function kindTag(item: ReviewResult): { type: string; effect: 'dark' | 'light' } {
  const kind = item.finding_kind
  if (kind && KIND_TAG[kind]) return KIND_TAG[kind]
  return { type: sourceTagType(item.violation_type), effect: 'light' }
}
function kindTip(item: ReviewResult): string {
  const kind = item.finding_kind
  if (kind && KIND_TIP[kind]) return KIND_TIP[kind]
  return SOURCE_TIP[item.violation_type] ?? ''
}

const statusFilter = ref<ResultStatus>('pending_confirm')
const selectedId = ref<number | null>(null)
const docBodyRef = ref<HTMLElement>()
/** R4-3 复核路由：风险优先（低置信×高风险排前）默认开——把最贵的判断力放在最需要的地方 */
const priorityFirst = ref(true)

const hasDoc = computed(
  () => Boolean(props.documentImageUrl) || (props.documentBlocks?.length ?? 0) > 0,
)

const countOf = (s: ResultStatus) => props.results.filter((r) => r.status === s).length

const RISK_WEIGHT: Record<string, number> = { high: 3, medium: 2, low: 1 }

const filtered = computed(() => {
  const list = props.results.filter((r) => r.status === statusFilter.value)
  if (!priorityFirst.value) {
    // 检出顺序 = result_id 升序显式重建：接口自 PR-2 起默认按 priority 返回，
    // 不能依赖返回顺序，否则关掉开关看到的仍是风险序
    return [...list].sort((a, b) => a.result_id - b.result_id)
  }
  // 与后端 R4-3 同口径：不确定度×风险权重 降序（低置信高风险最前）
  return [...list].sort(
    (a, b) =>
      (1 - b.confidence_score) * (RISK_WEIGHT[b.risk_level] ?? 1) -
      (1 - a.confidence_score) * (RISK_WEIGHT[a.risk_level] ?? 1),
  )
})

/** 低置信 × 高风险：复核路由的最高优先级组合（行级高亮引导注意力，PR-2） */
function isUrgent(item: ReviewResult): boolean {
  return item.confidence_score < LOW_CONFIDENCE && item.risk_level === 'high'
}

/** 置信度三段色：低置信红（AI 拿不准，优先看）/ 中黄 / 高绿 */
function confClass(item: ReviewResult): string {
  const c = item.confidence_score
  if (c < 0.5) return 'conf-low'
  if (c < 0.85) return 'conf-mid'
  return 'conf-high'
}

// ---- F2-3 生命周期时间线：展开时拉取（不缓存，避免复核后轨迹陈旧）----
const trailOpen = ref<string[]>([])
const trailEvents = ref<TrailEvent[]>([])
const trailLoading = ref(false)
const TRAIL_TYPE: Record<string, 'primary' | 'success' | 'warning' | 'danger' | 'info'> = {
  detected: 'info',
  auto_confirmed: 'success',
  confirm: 'primary',
  overturn: 'danger',
  revert: 'warning',
}

async function fetchTrail() {
  if (!trailOpen.value.length || selectedId.value == null) {
    trailEvents.value = []
    return
  }
  trailLoading.value = true
  try {
    const data = await getResultTrail(selectedId.value)
    trailEvents.value = data.events
  } catch {
    // 拦截器已提示；时间线留空（不阻断复核主流程）
    trailEvents.value = []
  } finally {
    trailLoading.value = false
  }
}

watch([selectedId, () => trailOpen.value.length], fetchTrail)

// ---- F2-1 AI 判定依据：展开时拉取（失败静默，不阻断复核）----
const adviceOpen = ref<string[]>([])
const advice = ref<VerdictAdvice | null>(null)
const adviceLoading = ref(false)
/** 低置信阈值：与置信度条三段色、后端分流口径一致 */
const LOW_CONFIDENCE = 0.5

async function fetchAdvice() {
  if (!adviceOpen.value.length || selectedId.value == null) return
  adviceLoading.value = true
  try {
    advice.value = await getVerdictAdvice(selectedId.value)
  } catch {
    advice.value = null // 静默：AI 辅助不可用不影响人工判断
  } finally {
    adviceLoading.value = false
  }
}

watch([selectedId, () => adviceOpen.value.length], fetchAdvice)

const index = computed(() => filtered.value.findIndex((r) => r.result_id === selectedId.value))
const current = computed(() => (index.value >= 0 ? filtered.value[index.value] : null))

/** F2-4：判定说明的 [维度前缀] 与正文分开渲染，避免前缀与正文重复造成阅读噪音 */
const descParts = computed(() => parseFindingDescription(current.value?.description))

/** PR-6：疑似篡改结论的两路数字（图片读数 vs 文字材料读数）；解析不到为 null */
const tamperRoutes = computed(() => parseTamperRoutes(current.value?.original_text))

// 默认选中：优先第一条待复核；筛选切换后选中项不在新分组时重置到第一条
watch(
  () => props.results,
  (list) => {
    if (!list.some((r) => r.result_id === selectedId.value)) {
      const firstPending = list.find((r) => r.status === 'pending_confirm')
      if (firstPending) {
        statusFilter.value = 'pending_confirm'
        // PR-2：选中"效果队列（排序后）的首条"而非数据原始序首条——风险优先
        // 开启时即最该先看的那条（低置信×高风险），与左侧队列视觉首条一致
        selectedId.value = filtered.value[0]?.result_id ?? firstPending.result_id
      } else {
        selectedId.value = list[0]?.result_id ?? null
      }
    }
  },
  { immediate: true },
)

watch(statusFilter, () => {
  if (!filtered.value.some((r) => r.result_id === selectedId.value)) {
    selectedId.value = filtered.value[0]?.result_id ?? null
  }
})

function step(delta: number) {
  const next = filtered.value[index.value + delta]
  if (next) selectedId.value = next.result_id
}

function sourceTagType(s: string) {
  return s === 'rule' ? 'primary' : s === 'llm' ? 'warning' : 'success'
}

/** 翻案：目标 verdict 取当前状态相反值 */
function overturn() {
  if (!current.value) return
  emit(current.value.status === 'confirmed' ? 'false-positive' : 'confirm', current.value)
}

// ---- 键盘快捷键：J/K 或 ↑/↓ 切换，C 确认违规方向，X 误报方向 ----
// 已判定项按同方向键即翻案；输入框聚焦或弹窗打开时不响应。
// 判定逻辑抽在 composables/useKeyboardShortcuts.ts（纯函数，可测），
// 这里只做"忽略判定 → 动作分发"的薄壳。
function onKeydown(e: KeyboardEvent) {
  if (shouldIgnoreKeydown(e, props.shortcutsEnabled)) return
  const action = resolveKeyAction(e.key, current.value, props.canConfirm)
  if (!action) return
  e.preventDefault()
  if (action === 'step-next') step(1)
  else if (action === 'step-prev') step(-1)
  else if (action === 'confirm' && current.value) emit('confirm', current.value)
  else if (action === 'false-positive' && current.value) emit('false-positive', current.value)
}

// 快捷键只在该页激活时生效：keep-alive 缓存下切到别的标签页时，
// 缓存实例的 window 监听不能继续抢 J/K/C/X（addEventListener 同引用幂等，双挂安全）
onMounted(() => window.addEventListener('keydown', onKeydown))
onActivated(() => window.addEventListener('keydown', onKeydown))
onDeactivated(() => window.removeEventListener('keydown', onKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))

// ============================================================
// 原文对照：把违规结论以 <mark> 标进原文块，点击高亮即选中该结论
// ============================================================

function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

/** 原文匹配做空白容忍（LLM 回填文本与解析文本可能差换行/空格） */
function buildNeedleRegex(needle: string): RegExp | null {
  const escaped = needle.trim().replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  if (!escaped) return null
  return new RegExp(escaped.replace(/\s+/g, '\\s+'))
}

interface Segment {
  start: number
  end: number
  vid: number
}

const renderedBlocks = computed(() => {
  const blocks = props.documentBlocks ?? []
  return blocks.map((block) => {
    const text = block.text ?? ''
    const segments: Segment[] = []
    for (const v of props.results) {
      const re = buildNeedleRegex(v.original_text ?? '')
      if (!re) continue
      const m = re.exec(text)
      if (m && m[0]) segments.push({ start: m.index, end: m.index + m[0].length, vid: v.result_id })
    }
    // 越长越优先；重叠段丢弃，保证 mark 不嵌套
    segments.sort((a, b) => a.start - b.start || b.end - b.start - (a.end - a.start))
    let html = ''
    let pos = 0
    for (const seg of segments) {
      if (seg.start < pos) continue
      const selected = seg.vid === selectedId.value
      html += escapeHtml(text.slice(pos, seg.start))
      html += `<mark data-vid="${seg.vid}" class="vmark${selected ? ' vmark-selected' : ''}">${escapeHtml(text.slice(seg.start, seg.end))}</mark>`
      pos = seg.end
    }
    html += escapeHtml(text.slice(pos))
    return { block, html }
  })
})

function onDocClick(event: Event) {
  const target = event.target as HTMLElement
  if (target.tagName !== 'MARK') return
  const vid = Number(target.dataset.vid)
  if (!Number.isFinite(vid)) return
  // 高亮可能在非当前筛选分组：切到该结论所在分组再选中
  const row = props.results.find((r) => r.result_id === vid)
  if (!row) return
  statusFilter.value = row.status
  selectedId.value = vid
}

// 选中变化时把对应高亮滚进视野
// ---- P1-2 证据对照：选中即自动加载条款全文（无需点击） ----
const articleLoading = ref(false)
const articleFull = ref<{ no: string; content: string } | null>(null)
const currentCases = computed<RelatedCase[]>(() => {
  const rid = current.value?.result_id
  return (rid != null && props.caseByResultId?.get(rid)) || []
})

watch(
  () => [current.value?.regulation_id, current.value?.article_no] as const,
  async ([regId, artNo]) => {
    articleFull.value = null
    if (!regId) return
    articleLoading.value = true
    try {
      const page = await listArticles(regId, { page: 1, page_size: 100 })
      const all = page.items ?? []
      const hit = artNo ? all.find((a) => a.article_no === artNo) : undefined
      articleFull.value = hit
        ? { no: hit.article_no || '', content: hit.content }
        : all.length
          ? { no: all[0].article_no || '', content: all[0].content }
          : null
    } catch {
      articleFull.value = null // 加载失败回落 excerpt 展示
    } finally {
      articleLoading.value = false
    }
  },
  { immediate: true },
)

watch(selectedId, async (vid) => {
  if (!vid || !hasDoc.value) return
  await nextTick()
  const mark = docBodyRef.value?.querySelector(`mark[data-vid="${vid}"]`)
  mark?.scrollIntoView({ block: 'center', behavior: 'smooth' })
})
</script>

<style scoped lang="scss">
.workbench {
  display: grid;
  grid-template-columns: 300px minmax(0, 1fr);
  gap: 16px;
  align-items: start;

  &.with-doc {
    grid-template-columns: 264px minmax(0, 1fr) 360px;
  }
}

// ---- 左侧队列 ----
.queue {
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  border-radius: 12px;
  display: flex;
  flex-direction: column;
  max-height: 640px;
}

.queue-head {
  padding: 12px 10px;
  border-bottom: 1px solid var(--app-border-light);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;

  :deep(.el-radio-button__inner) {
    padding: 5px 9px;
    font-size: 12px;
  }
}

.queue-list {
  flex: 1;
  min-height: 200px;
}

.queue-item {
  padding: 10px 14px;
  cursor: pointer;
  border-bottom: 1px solid var(--app-border-light);
  border-left: 3px solid transparent;
  transition: background 0.12s;

  &:hover {
    background: var(--el-fill-color-light);
  }

  // PR-2：低置信×高风险（复核路由最高优先级）行级引导——淡红渐变底 + 左缘警示；
  // 选中态（active）语义更强，沿用主色边
  &.queue-item--urgent:not(.active) {
    background: linear-gradient(90deg, var(--el-color-danger-light-9) 0%, transparent 72%);
    border-left-color: var(--el-color-danger);
  }

  &.active {
    background: var(--el-color-primary-light-9);
    border-left-color: var(--el-color-primary);
  }
}

.queue-item-top {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.queue-item-text {
  margin-top: 6px;
  font-size: 13px;
  line-height: 1.5;
  color: var(--el-text-color-regular);
  display: -webkit-box;
  -webkit-line-clamp: 2;  -webkit-box-orient: vertical;
  overflow: hidden;
}

/** 置信度微型条（R4-3 路由的可视化）：三段色与排序权重同一口径 */
.conf-bar {
  margin-top: 6px;
  height: 3px;
  border-radius: 2px;
  background: var(--app-border-light);
  overflow: hidden;
}
.conf-bar-fill {
  display: block;
  height: 100%;
  border-radius: 2px;
}
.conf-low .conf-bar-fill {
  background: var(--el-color-danger);
}
.conf-mid .conf-bar-fill {
  background: var(--el-color-warning);
}
.conf-high .conf-bar-fill {
  background: var(--el-color-success);
}

/* F2-3 生命周期时间线 */
.trail-collapse {
  margin-top: 12px;
  border-top: 1px solid var(--app-border-light);

  :deep(.el-collapse-item__header) {
    font-size: 13px;
    height: 38px;
    line-height: 38px;
  }
  :deep(.el-collapse-item__content) {
    padding-bottom: 6px;
  }
}
.trail-title {
  font-size: 13px;
  color: var(--el-text-color-primary);
}
.trail-count {
  margin-left: 6px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.trail-loading {
  height: 48px;
}
.trail-list {
  padding-top: 4px;
  :deep(.el-timeline-item__timestamp) {
    font-size: 12px;
  }
}
.trail-item {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
  font-size: 13px;
  line-height: 1.5;
}
.trail-detail {
  color: var(--el-text-color-regular);
}
.trail-actor {
  flex: none;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  white-space: nowrap;
}

/* F2-1 AI 判定依据 */
.advice-collapse {  margin-top: 8px;
  border-top: 1px dashed var(--app-border-light);

  :deep(.el-collapse-item__header) {
    font-size: 13px;
    height: 34px;
    line-height: 34px;
  }
}
.advice-title {
  font-size: 13px;
  color: var(--el-text-color-primary);
}
.advice-suggest {
  margin-left: 6px;
  font-size: 12px;
  color: var(--el-color-primary);
}
.advice-loading {
  height: 40px;
}
.advice-list {
  margin: 0;
  padding-left: 18px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--el-text-color-regular);

  li + li {
    margin-top: 2px;
  }
}
.advice-empty {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

/* F2-4 维度前缀（弱化标签，正文为主） */
.finding-prefix {
  display: inline-block;
  margin-right: 6px;
  padding: 0 6px;
  border-radius: 3px;
  font-size: 12px;
  color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
}

/* F2-2 图片材料原图视图 */
.doc-image-wrap {
  padding: 12px;
  display: flex;
  justify-content: center;
}
.doc-image {
  max-width: 100%;
  border: 1px solid var(--app-border);
  border-radius: 4px;
  background: var(--app-surface);
}

.queue-foot {
  padding: 10px 14px;
  border-top: 1px solid var(--app-border-light);
  font-size: 13px;
  color: var(--el-text-color-secondary);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
}

.kbd-hints {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: 12px;
  white-space: nowrap;

  kbd {
    display: inline-block;
    min-width: 16px;
    padding: 0 4px;
    text-align: center;
    border: 1px solid var(--app-border);
    border-bottom-width: 2px;
    border-radius: 4px;
    background: var(--el-fill-color-light);
    font-family: inherit;
    font-size: 12px;
    line-height: 16px;
    color: var(--el-text-color-regular);
  }
}

// ---- 中间原文对照 ----
.doc-pane {
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  border-radius: 12px;
  display: flex;
  flex-direction: column;
  max-height: 640px;
  min-width: 0;
}

.doc-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--app-border-light);
}

.doc-name {
  font-size: 14px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.doc-hint {
  margin-left: auto;
  flex-shrink: 0;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.doc-scroll {
  flex: 1;
}

.doc-body {
  padding: 18px 22px;
  font-size: 14px;
  line-height: 1.9;
  color: var(--el-text-color-primary);
}

.doc-block {
  margin-bottom: 10px;

  &.heading {
    font-weight: 600;
    margin: 16px 0 8px;
  }

  :deep(.vmark) {
    background: var(--el-color-warning-light-8);
    color: inherit;
    padding: 1px 0;
    border-radius: 3px;
    cursor: pointer;
    transition: background 0.12s;
  }

  :deep(.vmark:hover) {
    background: var(--el-color-warning-light-5);
  }

  :deep(.vmark-selected) {
    background: var(--el-color-warning);
    color: #fff;
    box-shadow: 0 0 0 2px var(--el-color-warning-light-5);
  }
}

.doc-loading {
  height: 120px;
}

// ---- 右侧详情 ----
.detail {
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  border-radius: 12px;
  padding: 18px 22px;
  min-height: 420px;
  display: flex;
  flex-direction: column;
}

.detail-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.detail-chips {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.loc {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.nav {
  display: flex;
  align-items: center;
  gap: 8px;
}

.nav-pos {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  min-width: 36px;
  text-align: center;
}

.quote {
  margin: 14px 0;
  padding: 12px 16px;
  background: var(--el-fill-color-light);
  border-left: 3px solid var(--el-color-primary-light-5);
  border-radius: 0 8px 8px 0;
  font-size: 14px;
  line-height: 1.8;
  color: var(--el-text-color-primary);
}

.reg-card {
  border: 1px solid var(--el-color-primary-light-8);
  background: var(--el-color-primary-light-9);
  border-radius: 10px;
  padding: 12px 16px;
}

/* ---- P1-2 证据对照段：法规条款全文 + 相似罚单案例 ---- */
.evidence {
  margin-top: 14px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.ev-seg {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px;
  padding: 10px 14px;
  background: var(--el-fill-color-blank);
}

.ev-seg-head {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 600;
  color: var(--el-text-color-secondary);
  letter-spacing: 0.5px;
  margin-bottom: 8px;
}

.ev-seg-sub {
  font-weight: 400;
}

.reg-full {
  font-size: 13px;
  line-height: 1.8;
  color: var(--el-text-color-primary);
  background: var(--el-color-primary-light-9);
  border-left: 3px solid var(--el-color-primary-light-5);
  border-radius: 0 6px 6px 0;
  padding: 8px 12px;
  white-space: pre-wrap;
  word-break: break-word;
}

.reg-full--loading {
  min-height: 48px;
}

.reg-full--excerpt {
  color: var(--el-text-color-regular);
  font-style: italic;
}

.reg-full-no {
  font-weight: 600;
  color: var(--el-color-primary);
  margin-right: 6px;
}

.reg-empty {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.case-card {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  padding: 8px 10px;
  margin-bottom: 6px;
}

.case-card:last-child {
  margin-bottom: 0;
}

.case-card-name {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  line-height: 1.6;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.case-card-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 3px 0;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.case-card-sim {
  color: var(--el-color-warning-dark-2);
}

.case-card-result {
  font-size: 12px;
  line-height: 1.6;
  color: var(--el-text-color-regular);
}

/* PR-6 两路数字对照卡：疑似篡改结论的核验面板 */
.tamper-card {
  margin: 14px 0 0;
  border: 1px solid var(--el-color-danger-light-7);
  background: var(--el-color-danger-light-9);
  border-radius: 10px;
  padding: 12px 16px;
}

.tr-head {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.tr-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--el-color-danger-dark-2);
}

.tr-note {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.tr-grid {
  margin-top: 10px;
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  align-items: stretch;
  gap: 10px;
}

.tr-cell {
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  padding: 8px 12px;
  min-width: 0;
}

.tr-cell.tr-miss {
  border-style: dashed;
  border-color: var(--el-color-warning);
}

.tr-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.tr-value {
  margin-top: 2px;
  font-size: 18px;
  font-weight: 700;
  color: var(--el-text-color-primary);
  word-break: break-all;
}

.tr-miss .tr-value {
  color: var(--el-color-warning);
}

.tr-sub {
  margin-top: 2px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.tr-vs {
  align-self: center;
  font-size: 12px;
  font-weight: 700;
  color: var(--el-color-danger);
}

.tr-guide {
  margin-top: 10px;
  font-size: 12px;
  line-height: 1.7;
  color: var(--el-color-warning-dark-2);
}

.reg-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
  color: var(--el-color-primary-dark-2);
}

.reg-name {
  margin-top: 6px;
  font-size: 14px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.reg-excerpt {
  margin-top: 4px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--el-text-color-regular);
}

.judge {
  margin-top: 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.judge-desc,
.judge-suggestion {
  margin: 0;
  font-size: 14px;
  line-height: 1.7;
  color: var(--el-text-color-regular);
}

.judge-suggestion {
  color: var(--el-color-primary-dark-2);
  background: var(--el-color-primary-light-9);
  border-radius: 8px;
  padding: 8px 12px;
}

.judge-label {
  display: inline-block;
  margin-right: 10px;
  font-size: 12px;
  font-weight: 600;
  color: var(--el-text-color-secondary);
}

.judge-confidence {
  display: flex;
  align-items: center;
}

.judge-bar {
  flex: 1;
  max-width: 220px;
}

.judge-pct {
  margin-left: 10px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.actions {
  margin-top: auto;
  padding-top: 16px;
  border-top: 1px dashed var(--app-border-light);
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.done-hint,
.no-perm {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

@media (max-width: 1280px) {
  .workbench.with-doc {
    grid-template-columns: 240px minmax(0, 1fr) 320px;
  }
}

@media (max-width: 1100px) {
  .workbench,
  .workbench.with-doc {
    grid-template-columns: 1fr;
  }
}
</style>
