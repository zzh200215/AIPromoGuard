<template>
  <div>
    <PageHeader :title="task?.task_name || '任务详情'" />

    <el-card v-if="task" class="task-head">
      <el-descriptions :column="4" border size="small">
        <el-descriptions-item label="任务ID">{{ task.id }}</el-descriptions-item>
        <el-descriptions-item label="文档">{{ task.document_name }}</el-descriptions-item>
        <el-descriptions-item label="领域">
          {{ task.domain ? DOMAIN_LABELS[task.domain] : '—' }}
        </el-descriptions-item>
        <el-descriptions-item label="状态">
          <TaskStatusTag :status="task.status" />
        </el-descriptions-item>
      </el-descriptions>
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
      description="请确认后端服务与依赖（MySQL/Redis/Chroma/LLM Key）就绪后重试"
      class="failed-alert"
    >
      <template #default>
        <el-button type="primary" @click="router.push('/tasks/new')">重新创建任务</el-button>
      </template>
    </el-alert>

    <template v-if="task?.status === 'completed'">
      <el-tabs v-model="activeTab">
        <el-tab-pane label="审查报告" name="report">
          <div v-loading="reportLoading">
            <template v-if="report">
              <RiskSummaryCard
                v-if="report.summary"
                :summary="report.summary"
                class="summary-card"
              />
              <el-alert
                v-if="report.message && !report.violations?.length"
                :title="report.message"
                type="warning"
                :closable="false"
                class="summary-card"
              />
              <div class="report-actions">
                <el-button type="primary" plain @click="download('markdown')">
                  下载 Markdown
                </el-button>
                <el-button type="primary" plain @click="download('pdf')">下载 PDF</el-button>
              </div>
              <ViolationTable :violations="report.violations ?? []" />
            </template>
          </div>
        </el-tab-pane>

        <el-tab-pane label="人工复核" name="review">
          <div v-loading="resultsLoading">
            <ResultReviewTable
              :results="results"
              :can-confirm="auth.hasPermission('confirm')"
              @confirm="openConfirm($event, 'confirmed')"
              @false-positive="openConfirm($event, 'false_positive')"
            />
          </div>
        </el-tab-pane>
      </el-tabs>
    </template>

    <ConfirmResultDialog
      v-model="confirmVisible"
      :row="confirmRow"
      :verdict="confirmVerdict"
      @submitted="loadResults"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { downloadReport, getReport } from '@/api/reports'
import { listResults } from '@/api/results'
import { useTaskPolling } from '@/composables/useTaskPolling'
import { DOMAIN_LABELS } from '@/constants/enums'
import { useAuthStore } from '@/stores/auth'
import type { ReportData } from '@/types/report'
import type { ReviewResult } from '@/types/result'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

// 非法路由参数得 NaN，NaN == null 为 false 会穿过判空发出 /tasks/NaN 请求
const parsedTaskId = Number(route.params.id)
const taskId = ref<number | null>(Number.isFinite(parsedTaskId) ? parsedTaskId : null)
const { task, start } = useTaskPolling(taskId)

const isRunning = computed(() => {
  const s = task.value?.status
  return s === 'pending' || s === 'running' || s === 'processing'
})

const activeTab = ref('report')

const report = ref<ReportData | null>(null)
const reportLoading = ref(false)

const results = ref<ReviewResult[]>([])
const resultsLoading = ref(false)

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

async function download(format: 'markdown' | 'pdf') {
  if (taskId.value == null) return
  try {
    await downloadReport(taskId.value, format)
  } catch {
    // 拦截器已提示
  }
}

onMounted(() => {
  start()
})
</script>

<style scoped>
.task-head {
  margin-bottom: 16px;
}

.progress-card {
  margin-bottom: 16px;
}

.failed-alert {
  margin-bottom: 16px;
}

.summary-card {
  margin-bottom: 16px;
}

.report-actions {
  margin-bottom: 16px;
}
</style>
