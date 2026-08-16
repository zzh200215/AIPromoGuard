<template>
  <div>
    <el-card class="welcome-card">
      <h2 class="welcome-title">欢迎，{{ auth.user?.username }}</h2>
      <p class="welcome-sub">金融产品合规智能审查系统 · 工作台</p>
      <el-button
        v-if="auth.hasPermission('create_task')"
        type="primary"
        size="large"
        @click="router.push('/tasks/new')"
      >
        新建审查
      </el-button>
    </el-card>

    <el-card class="section-card">
      <template #header>
        <div class="card-header">
          <span>最近任务</span>
          <el-link type="primary" @click="router.push('/tasks')">查看全部</el-link>
        </div>
      </template>
      <el-table :data="recentTasks" v-loading="loading">
        <el-table-column prop="task_name" label="任务名称" min-width="180" show-overflow-tooltip />
        <el-table-column label="状态" width="110">
          <template #default="{ row }"><TaskStatusTag :status="row.status" /></template>
        </el-table-column>
        <el-table-column label="进度" width="160">
          <template #default="{ row }">
            <el-progress :percentage="row.progress" :stroke-width="8" />
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="170">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="" width="80">
          <template #default="{ row }">
            <el-button size="small" type="primary" link @click="router.push(`/tasks/${row.id}`)">
              查看
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card v-if="auth.hasPermission('monitor')" class="section-card">
      <template #header><span>系统概览</span></template>
      <el-row :gutter="12">
        <el-col :span="6"><StatCard label="法规库" :value="kb?.regulations" /></el-col>
        <el-col :span="6"><StatCard label="规则库" :value="kb?.rules" /></el-col>
        <el-col :span="6">
          <StatCard label="条款向量" :value="monitor?.vector_store.legal_articles" />
        </el-col>
        <el-col :span="6">
          <StatCard label="审计(24h)" :value="monitor?.audit.last_24h" />
        </el-col>
      </el-row>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { systemMonitor } from '@/api/monitor'
import { listTasks } from '@/api/tasks'
import { formatTime } from '@/composables/useFormat'
import { useAuthStore } from '@/stores/auth'
import type { SystemMonitor } from '@/api/monitor'
import type { TaskOut } from '@/types/task'

const router = useRouter()
const auth = useAuthStore()

const recentTasks = ref<TaskOut[]>([])
const loading = ref(false)
const monitor = ref<SystemMonitor | null>(null)

const kb = computed(() => monitor.value?.database.knowledge_base)

onMounted(async () => {
  loading.value = true
  try {
    const res = await listTasks({ page: 1, page_size: 5 })
    recentTasks.value = res.items
  } catch {
    // 拦截器已提示
  } finally {
    loading.value = false
  }

  if (auth.hasPermission('monitor')) {
    try {
      monitor.value = await systemMonitor()
    } catch {
      // 拦截器已提示
    }
  }
})
</script>

<style scoped>
.welcome-card {
  margin-bottom: 16px;
}

.welcome-title {
  margin: 0 0 4px;
  font-size: 20px;
  color: #303133;
}

.welcome-sub {
  margin: 0 0 16px;
  color: #909399;
  font-size: 13px;
}

.section-card {
  margin-bottom: 16px;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
</style>
