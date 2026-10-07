<template>
  <div class="app-page">
    <PageHeader title="审查任务" description="所有单文档审查任务的进度与报告入口，点击行查看审查报告" />

    <el-card>
      <div class="filter-bar">
        <el-radio-group v-model="filterStatus" @change="reload">
          <el-radio-button value="">全部</el-radio-button>
          <el-radio-button v-for="(label, value) in STATUS_OPTIONS" :key="value" :value="value">
            {{ label }}
          </el-radio-button>
        </el-radio-group>
        <el-input
          v-model="q"
          class="search-input"
          placeholder="搜任务名 / 文档名"
          clearable
          :prefix-icon="Search"
          @input="onSearchInput"
          @clear="reload"
        />
      </div>

      <TableToolbar
        v-model:visible-keys="visibleKeys"
        v-model:density="density"
        :columns="TASK_COLUMNS"
        @refresh="reload"
      />

      <el-table
        v-if="rows.length || loading"
        :data="rows"
        v-loading="loading"
        class="task-table"
        :size="density"
        @row-click="goDetail"
      >
        <el-table-column v-if="colOn('task_name')" prop="task_name" label="任务" min-width="200" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="task-name">
              {{ row.task_name }}
              <el-tag v-if="row.base_document_name" size="small" type="info" effect="plain" class="compare-tag">
                对比
              </el-tag>
            </span>
          </template>
        </el-table-column>
        <el-table-column v-if="colOn('document_name')" prop="document_name" label="文档" min-width="180" show-overflow-tooltip />
        <el-table-column v-if="colOn('domain')" label="领域" width="100">
          <template #default="{ row }">
            {{ row.domain ? DOMAIN_LABELS[row.domain] : '—' }}
          </template>
        </el-table-column>
        <el-table-column v-if="colOn('status')" label="状态" width="100">
          <template #default="{ row }"><TaskStatusTag :status="row.status" /></template>
        </el-table-column>
        <el-table-column v-if="colOn('progress')" label="进度" width="150">
          <template #default="{ row }">
            <div class="progress-cell">
              <el-progress :percentage="row.progress" :stroke-width="6" :show-text="false" />
              <span class="num">{{ row.progress }}%</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column v-if="colOn('created_at')" label="创建时间" width="170">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
      </el-table>
      <!-- 空状态区分"第一次来"与"筛选无结果"，各自给下一步动作 -->
      <el-empty v-else-if="!filterStatus && !q.trim()" description="还没有审查任务">
        <el-button
          v-if="auth.hasPermission('create_task')"
          type="primary"
          @click="router.push('/tasks/new')"
        >
          新建第一个审查
        </el-button>
      </el-empty>
      <el-empty v-else description="没有符合条件的结果">
        <el-button @click="clearFilters">清除筛选</el-button>
      </el-empty>

      <div v-if="total > 0" class="pager">
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
defineOptions({ name: 'task-list' })
import { onActivated, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Search } from '@element-plus/icons-vue'
import { listTasks } from '@/api/tasks'
import TableToolbar from '@/components/TableToolbar.vue'
import { DOMAIN_LABELS, TASK_STATUS_LABELS } from '@/constants/enums'
import { formatTime } from '@/composables/useFormat'
import { useTablePrefs } from '@/composables/tablePrefs'
import { useAuthStore } from '@/stores/auth'
import type { TaskOut } from '@/types/task'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

// 列显隐候选（row 点击进详情是主交互，数据列全部允许隐藏）
const TASK_COLUMNS = [
  { key: 'task_name', label: '任务' },
  { key: 'document_name', label: '文档' },
  { key: 'domain', label: '领域' },
  { key: 'status', label: '状态' },
  { key: 'progress', label: '进度' },
  { key: 'created_at', label: '创建时间' },
]
const { visibleKeys, density } = useTablePrefs(
  'app-table-cols.tasks',
  TASK_COLUMNS.map((c) => c.key),
)
const colOn = (key: string) => visibleKeys.value.includes(key)

const rows = ref<TaskOut[]>([])
const loading = ref(false)
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const filterStatus = ref('')
const q = ref('')

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
      search: q.value.trim() || undefined,
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

/** 筛选/页码/关键词写回 URL：刷新、返回、分享链接都不丢上下文 */
function syncQuery() {
  router.replace({
    query: {
      status: filterStatus.value || undefined,
      page: page.value > 1 ? String(page.value) : undefined,
      q: q.value.trim() || undefined,
    },
  })
}

function onPageChange(p: number) {
  page.value = p
  syncQuery()
  load()
}

/** 筛选条件变化：回到第 1 页，否则高页码+新筛选会请求越界页显示空表 */
function reload() {
  page.value = 1
  syncQuery()
  load()
}

// 搜索防抖：停止输入 400ms 后才请求
let searchTimer: ReturnType<typeof setTimeout> | null = null
function onSearchInput() {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(reload, 400)
}

function clearFilters() {
  q.value = ''
  filterStatus.value = ''
  reload()
}

function goDetail(row: TaskOut) {
  router.push(`/tasks/${row.id}`)
}

onMounted(() => {
  // 从 URL 恢复筛选上下文（详情页返回 / 刷新 / 他人分享的链接）
  const query = route.query
  if (typeof query.status === 'string' && query.status in STATUS_OPTIONS) {
    filterStatus.value = query.status
  }
  if (typeof query.page === 'string' && /^\d+$/.test(query.page)) {
    page.value = Math.max(1, Number(query.page))
  }
  if (typeof query.q === 'string') {
    q.value = query.q
  }
  load()
})

onBeforeUnmount(() => {
  if (searchTimer) clearTimeout(searchTimer)
})

// keep-alive 缓存页：切标签回来时静默刷新，避免看到别的会话产生的过期列表
// （首次激活紧随 onMounted，会重复请求，跳过）
let activatedOnce = false
onActivated(() => {
  if (!activatedOnce) {
    activatedOnce = true
    return
  }
  void load()
})
</script>

<style scoped lang="scss">
.task-table :deep(.el-table__row) {
  cursor: pointer;
}

.search-input {
  width: 240px;
  margin-left: auto;
}

.task-name {
  font-weight: 500;
}

.compare-tag {
  margin-left: 6px;
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
