<template>
  <div class="app-page">
    <PageHeader :title="task?.task_name || '任务详情'" />

    <!-- 任务拉取失败（不存在/已删除/无权限）：给明确空态而不是半空白页 -->
    <el-card v-if="!task && pollError" class="task-head">
      <el-empty description="任务不存在、已删除或无权限查看">
        <el-button type="primary" @click="router.push('/tasks')">返回任务列表</el-button>
      </el-empty>
    </el-card>

    <!-- 任务概要：状态 + 关键信息 chips -->
    <el-card v-if="task" class="task-head">
      <div class="head-main">
        <div class="head-chips">
          <TaskStatusTag :status="task.status" />
          <el-tag v-if="task.domain" size="small" effect="plain">
            {{ DOMAIN_LABELS[task.domain] }}
          </el-tag>
          <el-tag v-if="task.profile" size="small" effect="plain" type="info">
            {{ PROFILE_LABELS[task.profile] }}
          </el-tag>
          <el-tag v-if="task.document_type" size="small" effect="plain" type="info">
            {{ task.document_type }}
          </el-tag>
        </div>
        <div class="head-meta">
          <span class="meta-item">文档：{{ task.document_name }}</span>
          <span v-if="task.base_document_name" class="meta-item">
            对比基线：{{ task.base_document_name }}
          </span>
          <span class="meta-item">任务 ID：{{ task.id }}</span>
        </div>
      </div>
    </el-card>

    <el-card v-if="task && isRunning" class="progress-card">
      <TaskProgressBar :status="task.status" :progress="task.progress" :task="task" />
    </el-card>

    <el-alert
      v-if="task?.status === 'failed'"
      type="error"
      :closable="false"
      show-icon
      title="任务审查失败"
      description="常见原因：文档格式异常、依赖服务（MySQL/Redis/Chroma/LLM Key）未就绪"
      class="failed-alert"
    >
      <template #default>
        <div class="failed-actions">
          <el-button
            v-if="auth.hasPermission('create_task')"
            type="primary"
            :loading="retrying"
            @click="onRetry"
          >
            重试任务
          </el-button>
          <el-button plain @click="router.push('/tasks/new')">新建任务</el-button>
        </div>
      </template>
    </el-alert>

    <template v-if="task?.status === 'completed'">
      <el-tabs v-model="activeTab" class="detail-tabs">
        <el-tab-pane label="审查报告" name="report">
          <div v-loading="reportLoading">
            <template v-if="report">
              <RiskSummaryCard v-if="report.summary" :summary="report.summary" class="summary-card" />

              <el-alert
                v-if="usageText"
                :title="usageText"
                type="info"
                :closable="false"
                class="summary-card"
              />
              <el-alert
                v-if="humanReviewText"
                :title="humanReviewText"
                type="success"
                :closable="false"
                class="summary-card"
              />
              <el-alert
                v-if="llmMissingText"
                :title="llmMissingText"
                type="warning"
                :closable="false"
                show-icon
                class="summary-card"
              />
              <el-alert
                v-if="report.message && !report.violations?.length"
                :title="report.message"
                type="success"
                :closable="false"
                class="summary-card"
              />

              <!-- 审核签发：已签发显示结论横幅；未签发且有权者显示签发卡 -->
              <el-alert
                v-if="report.sign_off"
                :title="signOffTitle"
                :description="report.sign_off.note || undefined"
                :type="report.sign_off.decision === 'released' ? 'success' : 'error'"
                :closable="false"
                show-icon
                class="summary-card"
              />
              <el-card v-else-if="canSignOff" shadow="never" class="summary-card signoff-card">
                <div class="signoff-row">
                  <div class="signoff-text">
                    <span class="signoff-title">审核签发</span>
                    <span class="signoff-desc">
                      人工复核完成后正式放行该材料；签发后结论写入报告与导出文件
                    </span>
                  </div>
                  <div class="signoff-actions">
                    <el-button
                      type="success"
                      size="small"
                      :loading="signOffLoading"
                      @click="submitSignOff('released')"
                    >
                      签发放行
                    </el-button>
                    <el-button
                      type="danger"
                      size="small"
                      plain
                      :loading="signOffLoading"
                      @click="submitSignOff('rejected')"
                    >
                      驳回整改
                    </el-button>
                  </div>
                </div>
              </el-card>

              <!-- 审查轨迹（stage_log.detail）：节点级过程明细，审查过程的永久记录 -->
              <el-card shadow="never" class="section-card">
                <template #header>
                  <div class="card-header">
                    <span class="card-title">
                      审查轨迹（{{ stageSummary.count }} 个节点 · {{ stageSummary.seconds }}s）
                    </span>
                    <el-button
                      size="small"
                      text
                      type="primary"
                      @click="traceExpanded = !traceExpanded"
                    >
                      {{ traceExpanded ? '收起' : '展开' }}
                    </el-button>
                  </div>
                </template>
                <TaskProgressBar
                  v-show="traceExpanded"
                  :status="task.status"
                  :progress="100"
                  :task="task"
                  :show-progress="false"
                />
              </el-card>

              <AiSummaryCard :task-id="taskId" />

              <el-card shadow="never" class="section-card">
                <template #header>
                  <div class="card-header">
                    <span class="card-title">违规明细（{{ report.violations?.length ?? 0 }}）</span>
                    <div class="report-actions">
                      <el-button size="small" type="primary" plain :icon="MagicStick" @click="copilotVisible = true">
                        AI 助手
                      </el-button>
                      <el-button size="small" plain @click="download('docx')">Word</el-button>
                      <el-button size="small" plain @click="download('pdf')">PDF</el-button>
                      <el-button size="small" plain @click="download('markdown')">
                        Markdown
                      </el-button>
                      <el-tooltip
                        content="监管取证包（zip）：审查报告 + 每条结论的生命周期 + 操作留痕 + SHA256 完整性清单"
                        placement="top"
                      >
                        <el-button
                          size="small"
                          type="warning"
                          plain
                          :icon="FolderChecked"
                          :loading="evidenceLoading"
                          @click="downloadEvidence"
                        >
                          取证包
                        </el-button>
                      </el-tooltip>
                    </div>
                  </div>
                </template>
                <!-- 批量判定工具条：报告与 results 合并后（行上有 result_id）才可用 -->
                <div
                  v-if="canBulkConfirm"
                  class="bulk-bar"
                  :class="{ active: selectedViolations.length > 0 }"
                >
                  <span class="bulk-count">已选 {{ selectedViolations.length }} 条</span>
                  <el-button
                    size="small"
                    type="success"
                    plain
                    :disabled="!selectedViolations.length"
                    :loading="bulkLoading"
                    @click="submitBulk('confirmed')"
                  >
                    批量确认
                  </el-button>
                  <el-button
                    size="small"
                    type="danger"
                    plain
                    :disabled="!selectedViolations.length"
                    :loading="bulkLoading"
                    @click="submitBulk('false_positive')"
                  >
                    批量剔除误报
                  </el-button>
                </div>
                <ViolationTable
                  ref="violationTableRef"
                  :violations="report.violations ?? []"
                  :selectable="canBulkConfirm"
                  toolbar
                  rewriteable
                  @selection-change="onViolationSelection"
                  @refresh="loadReport"
                  @rewrite="onRewrite"
                />
              </el-card>

              <el-card
                v-if="report.regulations?.length"
                shadow="never"
                class="section-card"
              >
                <template #header>
                  <span class="card-title">相关法规（{{ report.regulations.length }}）</span>
                </template>
                <div class="reg-links">
                  <router-link
                    v-for="reg in report.regulations"
                    :key="reg.id"
                    class="reg-link"
                    :to="`/knowledge/regulations/${reg.id}`"
                  >
                    {{ reg.regulation_name }}
                    <span v-if="reg.regulation_no" class="reg-no">（{{ reg.regulation_no }}）</span>
                  </router-link>
                </div>
              </el-card>

              <el-card
                v-if="report.pending_verification?.length"
                shadow="never"
                class="section-card pending-card"
              >
                <template #header>
                  <span class="card-title pending-title">
                    待人工核验清单（{{ report.pending_verification.length }}）
                  </span>
                </template>
                <ul class="pending-list">
                  <li v-for="(item, i) in report.pending_verification" :key="i">
                    <div class="pending-main">
                      <el-tag
                        :type="SEVERITY_TAG_TYPE[item.risk_level ?? 'low']"
                        size="small"
                        class="pending-risk"
                      >
                        {{ SEVERITY_LABELS[item.risk_level ?? 'low'] }}风险
                      </el-tag>
                      <span class="pending-text">{{ item.original_text }}</span>
                      <span v-if="item.page" class="pending-loc">
                        第{{ item.page }}页/第{{ item.paragraph ?? '-' }}段
                      </span>
                    </div>
                    <div class="pending-reasons">{{ item.reasons.join('；') }}</div>
                  </li>
                </ul>
              </el-card>
            </template>
          </div>
        </el-tab-pane>

        <el-tab-pane label="人工复核" name="review">
          <ReviewWorkbench
            :results="results"
            :can-confirm="auth.hasPermission('confirm')"
            :document-blocks="docBlocks"
            :document-name="task?.document_name"
            :doc-loading="docLoading"
            :document-image-url="docImageUrl"
            :shortcuts-enabled="!confirmVisible"
            @confirm="openConfirm($event, 'confirmed')"
            @false-positive="openConfirm($event, 'false_positive')"
          />
        </el-tab-pane>
      </el-tabs>
    </template>

    <ConfirmResultDialog
      v-model="confirmVisible"
      :row="confirmRow"
      :verdict="confirmVerdict"
      @submitted="onConfirmSubmitted"
      @adopt="onAdoptAdvice"
    />

    <!-- AI 助手：任务报告问答（结论附法规引用，可跳转原文） -->
    <ReviewCopilot v-model="copilotVisible" :task-id="taskId" />
    <RewriteResultDialog v-model="rewriteVisible" :result="rewriteTarget" />
  </div>
</template>

<script setup lang="ts">
defineOptions({ name: 'task-detail' })
import { computed, h, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { MagicStick, FolderChecked } from '@element-plus/icons-vue'
import { downloadEvidencePack, downloadReport, getReport } from '@/api/reports'
import { bulkConfirmResults, listResults, revertResults } from '@/api/results'
import {
  fetchTaskDocumentObjectUrl,
  getTaskDocumentContent,
  isImageDocument,
  retryTask,
  signOffTask,
  type DocumentBlock,
} from '@/api/tasks'
import { useTaskPolling } from '@/composables/useTaskPolling'
import { DOMAIN_LABELS, PROFILE_LABELS, SEVERITY_LABELS, SEVERITY_TAG_TYPE } from '@/constants/enums'
import ReviewCopilot from '@/components/ReviewCopilot.vue'
import RewriteResultDialog from '@/components/RewriteResultDialog.vue'
import AiSummaryCard from '@/components/AiSummaryCard.vue'
import ReviewWorkbench from '@/components/ReviewWorkbench.vue'
import ViolationTable from '@/components/ViolationTable.vue'
import { useAuthStore } from '@/stores/auth'
import type { ReportData, ViolationItem } from '@/types/report'
import type { ReviewResult } from '@/types/result'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

// 非法路由参数得 NaN，NaN == null 为 false 会穿过判空发出 /tasks/NaN 请求
const parsedTaskId = Number(route.params.id)
const taskId = ref<number | null>(Number.isFinite(parsedTaskId) ? parsedTaskId : null)
const { task, error: pollError, start, stop } = useTaskPolling(taskId)

const isRunning = computed(() => {
  const s = task.value?.status
  return s === 'pending' || s === 'running' || s === 'processing'
})

// ---- 审查轨迹（报告页回看）：节点数与总耗时（stage_log 由后端各节点写入） ----
const traceExpanded = ref(false)
const stageSummary = computed(() => {
  const stages = Object.values(task.value?.stages ?? {})
  const seconds = stages.reduce((sum, s) => sum + (s.cost_ms ?? 0), 0) / 1000
  return { count: stages.length, seconds: seconds.toFixed(1) }
})

// ---- 失败重试：复位重新入队后恢复轮询；文档缺失时接口会明确报错 ----
const retrying = ref(false)

async function onRetry() {
  if (taskId.value == null || retrying.value) return
  retrying.value = true
  try {
    await retryTask(taskId.value)
    ElMessage.success('任务已重新入队')
    start()
  } catch {
    // 拦截器已提示
  } finally {
    retrying.value = false
  }
}

/** LLM 用量一行文案（成本归因，无 LLM 调用时报告省略该字段） */
const usageText = computed(() => {
  const u = report.value?.llm_usage
  if (!u?.calls) return ''
  const parts = [
    `LLM 用量：${u.model || '—'}`,
    `${u.calls} 次调用`,
    `${(u.total_tokens ?? 0).toLocaleString()} tokens`,
  ]
  if (u.priced && u.estimated_cost_cny != null) {
    parts.push(`预估 ¥${u.estimated_cost_cny.toFixed(2)}（按牌价）`)
  }
  if (u.failed_blocks) parts.push(`${u.failed_blocks} 块降级`)
  return parts.join(' · ')
})

/** 人工复核结论一行文案（报告已与 results 最新判定同步） */
const humanReviewText = computed(() => {
  const hr = report.value?.human_review
  if (!hr) return ''
  const parts = [
    `人工复核：已确认 ${hr.confirmed} · 剔除误报 ${hr.false_positive} · 待复核 ${hr.pending_confirm}`,
    `剔除误报后最终确认违规 ${hr.final_total} 处（高 ${hr.final_high} / 中 ${hr.final_medium} / 低 ${hr.final_low}）`,
  ]
  return `${parts.join('；')}。报告已同步最新人工结论。`
})

/** LLM 降级透明：报告无任何 LLM/视觉调用记录时明示引擎覆盖范围 */
const llmMissingText = computed(() => {
  const r = report.value
  if (!r || r.llm_usage || r.message) return ''
  return '本次审查仅完成规则引擎检查（未调用 LLM 语义引擎）：未配置 LLM API Key 或调用已降级，语义类违规可能未被覆盖。'
})

const activeTab = ref('report')

// 首次打开人工复核 Tab 时才拉取原文对照与复核列表
watch(activeTab, (tab) => {
  if (tab === 'review') {
    void loadDocContent()
    void loadDocImage()
  }
})

const report = ref<ReportData | null>(null)
const reportLoading = ref(false)

const results = ref<ReviewResult[]>([])
const resultsLoading = ref(false)

// 原文对照（懒加载）：解析可能较慢（尤其 OCR），首次切到「人工复核」才请求
const docBlocks = ref<DocumentBlock[] | null>(null)
const docLoading = ref(false)
let docRequested = false

async function loadDocContent() {
  if (docRequested || taskId.value == null) return
  docRequested = true
  docLoading.value = true
  try {
    const data = await getTaskDocumentContent(taskId.value)
    docBlocks.value = data.blocks
  } catch {
    docBlocks.value = null // 拉不到原文时工作台自动退回两栏
  } finally {
    docLoading.value = false
  }
}

// F2-2 图片材料原图（懒加载）：视觉层审查的对象就是这张图，
// 复核人必须能看到它才能核验"疑似篡改/视觉弱化"类结论。
const docImageUrl = ref<string | null>(null)
let imageRequested = false

async function loadDocImage() {
  if (imageRequested || taskId.value == null) return
  if (!isImageDocument(task.value?.document_name)) return
  imageRequested = true
  try {
    docImageUrl.value = await fetchTaskDocumentObjectUrl(taskId.value)
  } catch {
    docImageUrl.value = null // 取不到原图时退回文本对照
  }
}

const confirmVisible = ref(false)
const confirmRow = ref<ReviewResult | null>(null)
const confirmVerdict = ref<'confirmed' | 'false_positive'>('confirmed')

// 极端时序：任务状态已完成但报告还没落盘，延迟重拉。
// "有 message 且零违规"是合规文档的正常终态，必须设上限，否则会无限轮询
const REPORT_RETRY_LIMIT = 3
let reportRetryCount = 0
let reportRetryTimer: ReturnType<typeof setTimeout> | null = null

async function loadReport() {
  if (taskId.value == null) return
  reportLoading.value = true
  try {
    report.value = await getReport(taskId.value)
    if (
      report.value.message &&
      !report.value.violations?.length &&
      reportRetryCount < REPORT_RETRY_LIMIT
    ) {
      reportRetryCount += 1
      reportRetryTimer = setTimeout(loadReport, 1500)
    }
  } catch {
    // 拦截器已提示
  } finally {
    reportLoading.value = false
  }
}

onBeforeUnmount(() => {
  if (reportRetryTimer) {
    clearTimeout(reportRetryTimer)
    reportRetryTimer = null
  }
  // objectURL 必须显式释放，否则大图会滞留内存
  if (docImageUrl.value) {
    URL.revokeObjectURL(docImageUrl.value)
    docImageUrl.value = null
  }
})

async function loadResults() {
  if (taskId.value == null) return
  resultsLoading.value = true
  try {
    const res = await listResults(taskId.value)
    results.value = res.items
  } catch {
    // 拦截器已提示
  } finally {
    resultsLoading.value = false
  }
}

/** 复核结论提交后同步刷新：工作台列表 + 报告（后端按最新结论重算） */
function onConfirmSubmitted() {
  void loadResults()
  void loadReport()
}

// ---- 审核签发：人工复核收口后的正式放行/驳回，结论随报告导出 ----
const signOffLoading = ref(false)

const canSignOff = computed(
  () => auth.hasPermission('confirm') && !report.value?.sign_off && isReportFinal.value,
)

const isReportFinal = computed(() => Boolean(report.value && !report.value.message))

const signOffTitle = computed(() => {
  const so = report.value?.sign_off
  if (!so) return ''
  const verdict = so.decision === 'released' ? '同意放行' : '驳回整改'
  return `已签发：${verdict} — ${so.username} · ${so.created_at}`
})

async function submitSignOff(decision: 'released' | 'rejected') {
  if (taskId.value == null || signOffLoading.value) return
  const label = decision === 'released' ? '签发放行' : '驳回整改'
  let note: string
  try {
    const { value } = await ElMessageBox.prompt(
      decision === 'released'
        ? '将正式放行该材料，签发结论写入报告与导出文件。'
        : '将驳回该材料并要求整改，签发结论写入报告与导出文件。',
      label,
      {
        confirmButtonText: label,
        cancelButtonText: '取消',
        inputPlaceholder: '签发意见（选填，最多 500 字）',
        inputType: 'textarea',
        inputValidator: (v: string) => !v || v.length <= 500 || '意见最多 500 字',
      },
    )
    note = value?.trim() || undefined
  } catch {
    return
  }
  signOffLoading.value = true
  try {
    await signOffTask(taskId.value, { decision, note })
    ElMessage.success(`已${label}`)
    onConfirmSubmitted()
  } catch {
    // 拦截器已提示（含"待复核未清零"门槛报错）
  } finally {
    signOffLoading.value = false
  }
}

watch(
  () => task.value?.status,
  (s) => {
    if (s === 'completed') {
      loadReport()
      loadResults()
    }
  },
)

function openConfirm(row: ReviewResult, verdict: 'confirmed' | 'false_positive') {
  confirmRow.value = row
  confirmVerdict.value = verdict
  confirmVisible.value = true
}

// ---- 报告页批量判定：多选违规一次提交确认 / 误报，免去逐条点击 ----
const violationTableRef = ref<InstanceType<typeof ViolationTable> | null>(null)
const selectedViolations = ref<ViolationItem[]>([])
const bulkLoading = ref(false)

const canBulkConfirm = computed(
  () => auth.hasPermission('confirm') && (report.value?.violations ?? []).some((v) => v.result_id != null),
)

function onViolationSelection(rows: ViolationItem[]) {
  selectedViolations.value = rows
}

// ---- AI Copilot：报告问答抽屉 + 单条违规合规改写 ----
const copilotVisible = ref(false)
const rewriteVisible = ref(false)
const rewriteTarget = ref<ViolationItem | null>(null)

function onRewrite(row: ViolationItem) {
  rewriteTarget.value = row
  rewriteVisible.value = true
}

/** 采纳 AI 判定建议：切换本次提交的结论 */
function onAdoptAdvice(verdict: 'confirmed' | 'false_positive') {
  confirmVerdict.value = verdict
}

const BULK_LABEL = { confirmed: '确认违规', false_positive: '剔除误报' } as const

/** 批量操作前每条结论的快照：撤销时按「操作前状态」分组还原 */
interface BulkSnapshot {
  pending: number[]
  confirmed: number[]
  false_positive: number[]
}

function snapshotBulkPrev(rows: ViolationItem[]): BulkSnapshot {
  const snap: BulkSnapshot = { pending: [], confirmed: [], false_positive: [] }
  for (const row of rows) {
    if (row.result_id == null) continue
    const prev = row.human_status ?? 'pending_confirm'
    if (prev === 'confirmed' || prev === 'false_positive') snap[prev].push(row.result_id)
    else snap.pending.push(row.result_id)
  }
  return snap
}

async function undoBulk(snap: BulkSnapshot) {
  try {
    let restored = 0
    // 操作前是待复核的 → 撤销回待复核；操作前已有结论的 → 用原结论覆盖回去
    if (snap.pending.length) {
      restored += (await revertResults({ result_ids: snap.pending })).updated
    }
    const reapply: Array<{ result_ids: number[]; verdict: 'confirmed' | 'false_positive' }> = [
      { result_ids: snap.confirmed, verdict: 'confirmed' },
      { result_ids: snap.false_positive, verdict: 'false_positive' },
    ]
    for (const part of reapply) {
      if (!part.result_ids.length) continue
      restored += (await bulkConfirmResults(part)).updated
    }
    ElMessage.success(`已撤销 ${restored} 条，恢复到操作前的结论`)
    onConfirmSubmitted()
  } catch {
    // 拦截器已提示
  }
}

async function submitBulk(verdict: 'confirmed' | 'false_positive') {
  const rows = selectedViolations.value
  const ids = rows.map((v) => v.result_id).filter((id): id is number => id != null)
  if (!ids.length) return
  try {
    await ElMessageBox.confirm(
      `将对选中的 ${ids.length} 条违规执行「${BULK_LABEL[verdict]}」，已判定过的条目会被覆盖为本次结论。`,
      '批量判定确认',
      { type: 'warning', confirmButtonText: '执行', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  bulkLoading.value = true
  try {
    const snapshot = snapshotBulkPrev(rows)
    const res = await bulkConfirmResults({ result_ids: ids, verdict })
    const skipped = res.skipped.length ? `，跳过 ${res.skipped.length} 条（无权限或已删除）` : ''
    // 成功提示内嵌「撤销」按钮：6 秒内可一键恢复到操作前状态
    const toast = ElMessage({
      type: 'success',
      duration: 6000,
      message: h('span', { class: 'bulk-toast' }, [
        `已${BULK_LABEL[verdict]} ${res.updated} 条${skipped}`,
        h(
          'button',
          {
            class: 'bulk-toast-undo',
            type: 'button',
            onClick: () => {
              toast.close()
              void undoBulk(snapshot)
            },
          },
          '撤销',
        ),
      ]),
    })
    violationTableRef.value?.clearSelection()
    onConfirmSubmitted()
  } catch {
    // 拦截器已提示
  } finally {
    bulkLoading.value = false
  }
}

async function download(format: 'markdown' | 'pdf') {
  if (taskId.value == null) return
  try {
    await downloadReport(taskId.value, format)
  } catch {
    // 拦截器已提示
  }
}

/** 监管取证证据包（zip）：报告 + 结论生命周期 + 操作留痕 + manifest(SHA256) */
const evidenceLoading = ref(false)
async function downloadEvidence() {
  if (taskId.value == null) return
  evidenceLoading.value = true
  try {
    await downloadEvidencePack(taskId.value)
    ElMessage.success('取证包已导出（含完整性校验清单）')
  } catch {
    // 拦截器已提示
  } finally {
    evidenceLoading.value = false
  }
}

onMounted(() => {
  start()
})

// keep-alive 缓存下切走时停表（隐藏页不该继续 2s 轮询）；
// 切回时仅对未终态任务恢复
onDeactivated(() => stop())
onActivated(() => {
  if (task.value && !['completed', 'failed', 'cancelled'].includes(task.value.status)) start()
})
</script>

<style scoped lang="scss">
.task-head :deep(.el-card__body) {
  padding: 16px 20px;
}

.head-chips {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.head-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 20px;
  margin-top: 10px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.progress-card {
  :deep(.el-card__body) {
    padding: 18px 20px;
  }
}

.failed-alert {
  :deep(.el-alert__description) {
    width: 100%;
  }
}

.failed-actions {
  margin-top: 8px;
  display: flex;
  gap: 10px;
}

.detail-tabs {
  background: transparent;

  :deep(.el-tabs__header) {
    background: var(--app-surface);
    border: 1px solid var(--app-border);
    border-radius: 12px;
    padding: 0 16px;
    margin-bottom: 16px;
  }

  :deep(.el-tabs__nav-wrap::after) {
    height: 0;
  }
}

.summary-card {
  margin-bottom: 16px;
}

.section-card {
  box-shadow: none !important;
}

.card-title {
  font-size: 14px;
  font-weight: 600;
}

.report-actions {
  display: flex;
  gap: 8px;
}

.pending-title {
  color: var(--el-color-warning-dark-2);
}

.pending-card :deep(.el-card__header) {
  padding: 10px 16px;
}

.pending-list {
  margin: 0;
  padding: 0;
  list-style: none;
}

.pending-list li + li {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px dashed var(--app-border-light);
}

.pending-main {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.pending-text {
  color: var(--el-text-color-primary);
}

.pending-loc {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.pending-reasons {
  margin-top: 4px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
  line-height: 1.6;
}

.reg-links {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 20px;
}

.reg-link {
  color: var(--el-color-primary);
  text-decoration: none;

  &:hover {
    text-decoration: underline;
  }
}

.reg-no {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.bulk-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  margin-bottom: 12px;
  border: 1px dashed var(--app-border);
  border-radius: 8px;
  color: var(--el-text-color-secondary);
  transition: border-color 0.15s, background 0.15s;

  &.active {
    border-color: var(--el-color-primary-light-5);
    background: var(--el-color-primary-light-9);
  }
}

.bulk-count {
  font-size: 13px;
  font-weight: 500;
}

.signoff-card :deep(.el-card__body) {
  padding: 14px 20px;
}

.signoff-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.signoff-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.signoff-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.signoff-desc {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.signoff-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
</style>
