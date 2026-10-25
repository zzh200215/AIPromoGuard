<template>
  <div class="app-page">
    <PageHeader :title="detail?.batch?.batch_name || '批次详情'">
      <el-button plain @click="router.push('/batches')">返回批次列表</el-button>
      <el-button
        v-if="failedCount > 0 && auth.hasPermission('create_task')"
        type="warning"
        plain
        :loading="retryingAll"
        @click="onRetryAll"
      >
        重试失败任务（{{ failedCount }}）
      </el-button>
      <el-button type="primary" :loading="exporting" @click="doExport">导出报告 (zip)</el-button>
      <el-button plain @click="doExportSummary">导出汇总 (xlsx)</el-button>
    </PageHeader>

    <!-- 批次拉取失败：给明确空态而不是半空白页 -->
    <el-card v-if="!detail && loadFailed">
      <el-empty description="批次不存在、已删除或无权限查看">
        <el-button type="primary" @click="router.push('/batches')">返回批次列表</el-button>
      </el-empty>
    </el-card>

    <!-- 批次进度总览 -->
    <el-card v-if="detail" class="batch-head">
      <div class="summary-row">
        <div class="summary-item">
          <span class="summary-label">状态</span>
          <TaskStatusTag :status="detail.batch.status" />
        </div>
        <div class="summary-item">
          <span class="summary-label">完成进度</span>
          <span class="num summary-strong">
            {{ detail.batch.completed_count }}/{{ detail.batch.total_count }}
          </span>
        </div>
        <div class="summary-item">
          <span class="summary-label">失败</span>
          <span class="num summary-strong" :class="{ 'fail-text': detail.batch.failed_count > 0 }">
            {{ detail.batch.failed_count }}
          </span>
        </div>
        <div class="summary-progress">
          <el-progress
            :percentage="
              detail.batch.total_count
                ? Math.round((detail.batch.completed_count / detail.batch.total_count) * 100)
                : 0
            "
            :stroke-width="8"
          />
        </div>
      </div>
    </el-card>

    <!-- 任务明细 -->
    <el-card>
      <template #header>
        <span class="card-title">批次内任务（{{ detail?.tasks.length ?? 0 }}）</span>
      </template>
      <el-table :data="detail?.tasks ?? []" v-loading="loading" @row-click="goTask">
        <el-table-column prop="task_name" label="文档" min-width="220" show-overflow-tooltip />
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <TaskStatusTag :status="row.status" />
          </template>
        </el-table-column>
        <el-table-column label="进度" width="180">
          <template #default="{ row }">
            <div class="progress-cell">
              <el-progress :percentage="row.progress" :stroke-width="6" :show-text="false" />
              <span class="num">{{ row.progress }}%</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="170" align="right">
          <template #default="{ row }">
            <el-button
              v-if="row.status === 'failed' && auth.hasPermission('create_task')"
              size="small"
              type="warning"
              plain
              :loading="retryingId === row.id"
              @click.stop="onRetryOne(row)"
            >
              重试
            </el-button>
            <el-button v-else link type="primary">查看报告</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
defineOptions({ name: 'batch-detail' })
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { eventStreamStatus, onServerEvent } from '@/composables/useEventStream'
import { useRoute, useRouter } from 'vue-router'
import { downloadBatchSummary, downloadBatchZip, getBatch, retryBatchFailed } from '@/api/batches'
import { retryTask } from '@/api/tasks'
import { useAuthStore } from '@/stores/auth'
import type { BatchDetail } from '@/types/batch'
import type { TaskOut } from '@/types/task'

const POLL_INTERVAL = 2000
/** 批次终态（对齐 src/services/review_service.py: batch.status 置 completed/failed） */
const TERMINAL = ['completed', 'failed']

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const parsedBatchId = Number(route.params.id)
const batchId = Number.isFinite(parsedBatchId) && parsedBatchId > 0 ? parsedBatchId : 0
const detail = ref<BatchDetail | null>(null)
const loading = ref(false)
const exporting = ref(false)
const retryingAll = ref(false)
const retryingId = ref<number | null>(null)

const failedCount = computed(
  () => detail.value?.tasks.filter((t) => t.status === 'failed').length ?? 0,
)

let timer: ReturnType<typeof setInterval> | null = null

const stopPolling = () => {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}

const ensurePolling = () => {
  if (!timer) timer = setInterval(load, POLL_INTERVAL)
}

/** 瞬时网络抖动不应永久停止进度刷新；连续失败多次才停 */
const MAX_CONSECUTIVE_FAILURES = 3
let failureCount = 0
const loadFailed = ref(false)

async function load() {
  if (!batchId) return
  loading.value = true
  try {
    detail.value = await getBatch(batchId)
    failureCount = 0
    loadFailed.value = false
    if (detail.value.batch.status && TERMINAL.includes(detail.value.batch.status)) {
      stopPolling()
    }
  } catch {
    failureCount += 1
    if (failureCount >= MAX_CONSECUTIVE_FAILURES) {
      stopPolling()
      // 连续失败视为批次不存在/已删除：展示明确空态，而不是半空白页
      loadFailed.value = detail.value === null
    }
  } finally {
    loading.value = false
  }
}

async function doExport() {
  exporting.value = true
  try {
    await downloadBatchZip(batchId, detail.value?.batch.batch_name ?? '批次')
  } catch {
    // 拦截器已提示（含"尚有 N 个任务未完成"）
  } finally {
    exporting.value = false
  }
}

/** 批次汇总表（xlsx）：逐任务违规统计，未完成任务也在列 */
async function doExportSummary() {
  exporting.value = true
  try {
    await downloadBatchSummary(batchId, detail.value?.batch?.batch_name ?? '批次')
  } catch {
    // 拦截器已提示
  } finally {
    exporting.value = false
  }
}

// ---- 失败任务重试：单条与一键全部；批次回到 running 后恢复轮询 ----
async function onRetryOne(row: TaskOut) {
  if (retryingId.value != null) return
  retryingId.value = row.id
  try {
    await retryTask(row.id)
    ElMessage.success(`任务 #${row.id} 已重新入队`)
    await load()
    ensurePolling()
  } catch {
    // 拦截器已提示
  } finally {
    retryingId.value = null
  }
}

async function onRetryAll() {
  if (retryingAll.value) return
  retryingAll.value = true
  try {
    const res = await retryBatchFailed(batchId)
    const note = res.skipped > 0 ? `，${res.skipped} 个因文档文件缺失被跳过` : ''
    ElMessage.success(`已重新入队 ${res.retried.length} 个失败任务${note}`)
    await load()
    ensurePolling()
  } catch {
    // 拦截器已提示
  } finally {
    retryingAll.value = false
  }
}

function goTask(row: TaskOut) {
  router.push(`/tasks/${row.id}`)
}

// SSE 事件驱动刷新（batch_progress），轮询仅作断线兜底
let eventDebounce: ReturnType<typeof setTimeout> | null = null
const loadDebounced = () => {
  if (eventDebounce) return
  eventDebounce = setTimeout(() => {
    eventDebounce = null
    void load()
  }, 500)
}

const stream = eventStreamStatus()
const offBatchEvent = onServerEvent('batch_progress', (e) => {
  if (e.batch_id === batchId) loadDebounced()
})
// 连接状态兜底：SSE 断开启用轮询，恢复即停
const stopWatch = watch(stream, (s) => {
  if (s === 'open') stopPolling()
  else if (!timer) timer = setInterval(load, POLL_INTERVAL)
})

onMounted(() => {
  void load()
  if (stream.value !== 'open') timer = setInterval(load, POLL_INTERVAL)
})

onBeforeUnmount(() => {
  stopPolling()
  if (eventDebounce) clearTimeout(eventDebounce)
  offBatchEvent()
  stopWatch()
})
</script>

<style scoped lang="scss">
.card-title {
  font-size: 14px;
  font-weight: 600;
}

.summary-row {
  display: flex;
  align-items: center;
  gap: 40px;
}

.summary-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.summary-label {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.summary-strong {
  font-size: 20px;
  font-weight: 700;
  line-height: 1.2;
}

.fail-text {
  color: var(--el-color-danger);
}

.summary-progress {
  flex: 1;
  min-width: 160px;
}

table :deep(.el-table__row) {
  cursor: pointer;
}

.progress-cell {
  display: flex;
  align-items: center;
  gap: 8px;

  .el-progress {
    flex: 1;
  }

  span {
    font-size: 12px;
    color: var(--el-text-color-secondary);
    width: 34px;
    text-align: right;
  }
}
</style>
