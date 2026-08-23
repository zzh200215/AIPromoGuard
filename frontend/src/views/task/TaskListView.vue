<template>
  <div>
    <PageHeader title="审查任务">
      <el-button
        v-if="auth.hasPermission('create_task')"
        type="primary"
        @click="router.push('/tasks/new')"
      >
        新建审查
      </el-button>
    </PageHeader>

    <el-card>
      <div class="filter-bar">
        <el-select
          v-model="filterStatus"
          placeholder="任务状态"
          clearable
          style="width: 160px"
          @change="reload"
        >
          <el-option
            v-for="(label, value) in STATUS_OPTIONS"
            :key="value"
            :label="label"
            :value="value"
          />
        </el-select>
      </div>

      <el-table
        :data="rows"
        border
        v-loading="loading"
        class="task-table"
        @row-click="goDetail"
      >
        <el-table-column prop="id" label="ID" width="80" />
        <el-table-column prop="task_name" label="任务名称" min-width="160" show-overflow-tooltip />
        <el-table-column prop="document_name" label="文档" min-width="160" show-overflow-tooltip />
        <el-table-column label="领域" width="100">
          <template #default="{ row }">
            {{ row.domain ? DOMAIN_LABELS[row.domain] : '—' }}
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }"><TaskStatusTag :status="row.status" /></template>
        </el-table-column>
        <el-table-column label="进度" width="150">
          <template #default="{ row }">
            <el-progress :percentage="row.progress" :stroke-width="8" />
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="170">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
      </el-table>

      <div class="pager">
        <el-pagination
          background
          layout="total, prev, pager, next"
          :total="total"
          :page-size="pageSize"
          :current-page="page"
          @current-change="onPageChange"
        />
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { listTasks } from '@/api/tasks'
import { DOMAIN_LABELS, TASK_STATUS_LABELS } from '@/constants/enums'
import { formatTime } from '@/composables/useFormat'
import { useAuthStore } from '@/stores/auth'
import type { TaskOut } from '@/types/task'

const router = useRouter()
const auth = useAuthStore()

const rows = ref<TaskOut[]>([])
const loading = ref(false)
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const filterStatus = ref('')

const STATUS_OPTIONS = Object.fromEntries(
  Object.entries(TASK_STATUS_LABELS).filter(([k]) => k !== 'processing'),
)

// 请求序号守卫：快速切换筛选时丢弃过期响应，避免旧结果覆盖新结果
let loadSeq = 0

async function load() {
  const mySeq = ++loadSeq
  loading.value = true
  try {
    const res = await listTasks({
      page: page.value,
      page_size: pageSize.value,
      status: filterStatus.value || undefined,
    })
    if (mySeq !== loadSeq) return
    rows.value = res.items
    total.value = res.total
  } catch {
    // 拦截器已提示
  } finally {
    loading.value = false
  }
}

function onPageChange(p: number) {
  page.value = p
  load()
}

/** 筛选条件变化：回到第 1 页，否则高页码+新筛选会请求越界页显示空表 */
function reload() {
  page.value = 1
  load()
}

function goDetail(row: TaskOut) {
  router.push(`/tasks/${row.id}`)
}

onMounted(load)
</script>

<style scoped>
.filter-bar {
  margin-bottom: 12px;
}

.task-table :deep(.el-table__row) {
  cursor: pointer;
}

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}
</style>
