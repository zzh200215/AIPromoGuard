<template>
  <div>
    <PageHeader :title="detail?.batch.batch_name || '批次详情'" />

    <el-card v-if="detail" class="batch-head">
      <el-descriptions :column="4" border size="small">
        <el-descriptions-item label="批次ID">{{ detail.batch.id }}</el-descriptions-item>
        <el-descriptions-item label="状态">
          <TaskStatusTag :status="detail.batch.status" />
        </el-descriptions-item>
        <el-descriptions-item label="完成">
          {{ detail.batch.completed_count }}/{{ detail.batch.total_count }}
        </el-descriptions-item>
        <el-descriptions-item label="失败">{{ detail.batch.failed_count }}</el-descriptions-item>
      </el-descriptions>
      <div class="head-actions">
        <el-button type="primary" plain :loading="exporting" @click="doExport">
          导出报告 (zip)
        </el-button>
      </div>
    </el-card>

    <el-card>
      <el-table :data="detail?.tasks ?? []" v-loading="loading">
        <el-table-column prop="id" label="任务ID" width="90" />
        <el-table-column prop="task_name" label="文档" min-width="160" show-overflow-tooltip />
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <TaskStatusTag :status="row.status" />
          </template>
        </el-table-column>
        <el-table-column label="进度" width="140">
          <template #default="{ row }">
            <el-progress :percentage="row.progress" :stroke-width="8" />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button link type="primary" @click="router.push(`/tasks/${row.id}`)">
              查看报告
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { downloadBatchZip, getBatch } from '@/api/batches'
import type { BatchDetail } from '@/types/batch'

const POLL_INTERVAL = 2000
/** 批次终态（对齐 src/services/review_service.py: batch.status 置 completed/failed） */
const TERMINAL = ['completed', 'failed']

const route = useRoute()
const router = useRouter()

const parsedBatchId = Number(route.params.id)
const batchId = Number.isFinite(parsedBatchId) && parsedBatchId > 0 ? parsedBatchId : 0
const detail = ref<BatchDetail | null>(null)
const loading = ref(false)
const exporting = ref(false)

let timer: ReturnType<typeof setInterval> | null = null

const stopPolling = () => {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}

/** 瞬时网络抖动不应永久停止进度刷新；连续失败多次才停 */
const MAX_CONSECUTIVE_FAILURES = 3
let failureCount = 0

async function load() {
  if (!batchId) return
  loading.value = true
  try {
    detail.value = await getBatch(batchId)
    failureCount = 0
    if (detail.value.batch.status && TERMINAL.includes(detail.value.batch.status)) {
      stopPolling()
    }
  } catch {
    failureCount += 1
    if (failureCount >= MAX_CONSECUTIVE_FAILURES) {
      stopPolling()
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

onMounted(() => {
  void load()
  timer = setInterval(load, POLL_INTERVAL)
})

onBeforeUnmount(stopPolling)
</script>

<style scoped>
.batch-head {
  margin-bottom: 16px;
}

.head-actions {
  margin-top: 12px;
}
</style>
