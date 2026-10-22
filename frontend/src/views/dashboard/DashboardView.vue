<template>
  <div class="app-page">
    <!-- 问候 + 主操作 -->
    <div class="greeting-bar">
      <div>
        <h2 class="greeting-title">{{ greeting }}，{{ auth.user?.username }}</h2>
        <p class="greeting-sub">{{ greetingSub }}</p>
      </div>
      <div class="greeting-actions">
        <el-button v-if="auth.hasPermission('create_task')" size="large" @click="router.push('/batches')">
          批量审查
        </el-button>
        <el-button
          v-if="auth.hasPermission('create_task')"
          type="primary"
          size="large"
          @click="router.push('/tasks/new')"
        >
          新建审查
        </el-button>
      </div>
    </div>

    <!-- 待办驾驶舱：合规运营里"需要你处理"的事，点击直达 -->
    <template v-if="auth.hasPermission('create_task')">
      <div v-loading="overviewLoading">
        <div class="section-head">
          <span class="section-title">待办</span>
          <el-tag v-if="allClear" type="success" size="small" effect="light">全部处理完毕</el-tag>
        </div>
        <div class="todo-grid">
          <div
            v-for="todo in todos"
            :key="todo.label"
            class="todo-card"
            :class="[`tone-${todo.tone}`, { 'todo-card--disabled': !todo.count }]"
            @click="onTodoClick(todo)"
          >
            <div class="todo-top">
              <span class="todo-label">{{ todo.label }}</span>
              <el-icon class="todo-arrow"><ArrowRight /></el-icon>
            </div>
            <div class="todo-count num" :class="{ zero: !todo.count }">
              {{ todo.count ?? '—' }}
            </div>
            <div class="todo-hint">{{ todo.hint }}</div>
          </div>
        </div>
      </div>
    </template>

    <!-- 主区：进行中 / 最近任务 -->
    <div class="main-grid">
      <div class="main-col">
        <el-card v-if="runningTasks.length" class="running-card">
          <template #header>
            <div class="card-header">
              <span class="card-title">进行中</span>
            </div>
          </template>
          <div
            v-for="t in runningTasks"
            :key="t.id"
            class="running-row"
            @click="router.push(`/tasks/${t.id}`)"
          >
            <div class="running-info">
              <span class="running-name">{{ t.task_name }}</span>
              <span class="running-meta">
                {{ t.document_name }} · {{ t.domain ? DOMAIN_LABELS[t.domain] : '自动识别' }}
              </span>
            </div>
            <el-progress
              class="running-progress"
              :percentage="t.progress"
              :stroke-width="8"
              :show-text="false"
            />
            <span class="running-pct num">{{ t.progress }}%</span>
          </div>
        </el-card>

        <el-card>
          <template #header>
            <div class="card-header">
              <span class="card-title">最近审查任务</span>
              <el-button text type="primary" @click="router.push('/tasks')">全部任务</el-button>
            </div>
          </template>
          <el-table :data="recentTasks" v-loading="tasksLoading" empty-text="还没有审查任务，点右上角「新建审查」开始">
            <el-table-column prop="task_name" label="任务" min-width="200" show-overflow-tooltip>
              <template #default="{ row }">
                <span class="task-link" @click="router.push(`/tasks/${row.id}`)">
                  {{ row.task_name }}
                </span>
              </template>
            </el-table-column>
            <el-table-column label="领域" width="100">
              <template #default="{ row }">
                {{ row.domain ? DOMAIN_LABELS[row.domain] : '—' }}
              </template>
            </el-table-column>
            <el-table-column label="状态" width="96">
              <template #default="{ row }"><TaskStatusTag :status="row.status" /></template>
            </el-table-column>
            <el-table-column label="进度" width="130">
              <template #default="{ row }">
                <el-progress :percentage="row.progress" :stroke-width="6" :show-text="false" />
              </template>
            </el-table-column>
            <el-table-column label="创建时间" width="160">
              <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
            </el-table-column>
          </el-table>
        </el-card>
      </div>

      <!-- 侧栏：快捷入口 + 知识库资产 -->
      <div class="side-col">
        <el-card>
          <template #header><span class="card-title">快捷入口</span></template>
          <div class="quick-grid">
            <div v-for="q in quickLinks" :key="q.label" class="quick-item" @click="router.push(q.to)">
              <el-icon :size="18" class="quick-icon"><component :is="q.icon" /></el-icon>
              <span>{{ q.label }}</span>
            </div>
          </div>
        </el-card>

        <el-card v-if="monitor">
          <template #header><span class="card-title">知识库资产</span></template>
          <div class="asset-list">
            <div class="asset-row">
              <span>法规库</span>
              <b class="num">{{ monitor.database.knowledge_base.regulations }}</b>
            </div>
            <div class="asset-row">
              <span>审查规则</span>
              <b class="num">{{ monitor.database.knowledge_base.rules }}</b>
            </div>
            <div class="asset-row">
              <span>条款向量</span>
              <b class="num">{{ monitor.vector_store.legal_articles }}</b>
            </div>
            <div class="asset-row">
              <span>处罚案例向量</span>
              <b class="num">{{ monitor.vector_store.legal_penalty_cases }}</b>
            </div>
          </div>
        </el-card>

        <!-- 飞轮动态：最近入库/发布（知识库"看起来在长"——数据飞轮可见化） -->
        <el-card v-if="monitor?.recent_activity" class="flywheel-card">
          <template #header><span class="card-title">飞轮动态</span></template>
          <div class="flywheel-list">
            <div v-if="latestReg" class="flywheel-item">
              <el-tag size="small" effect="plain" type="primary" class="fw-tag">法规</el-tag>
              <span class="fw-text" :title="latestReg.name">入库《{{ latestReg.name }}》</span>
              <span class="fw-time">{{ shortDate(latestReg.created_at) }}</span>
            </div>
            <div v-if="latestRule" class="flywheel-item">
              <el-tag size="small" effect="plain" type="success" class="fw-tag">规则</el-tag>
              <span class="fw-text" :title="latestRule.name">{{ latestRule.name }}</span>
              <span class="fw-time">{{ shortDate(latestRule.updated_at) }}</span>
            </div>
            <div v-if="latestCase" class="flywheel-item">
              <el-tag size="small" effect="plain" type="warning" class="fw-tag">罚单</el-tag>
              <span class="fw-text" :title="latestCase.name">{{ shortCaseName(latestCase.name) }}</span>
              <span class="fw-time">{{ latestCase.penalty_date ?? '' }}</span>
            </div>
          </div>
        </el-card>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
defineOptions({ name: 'dashboard' })
import { computed, onActivated, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  Aim,
  ArrowRight,
  Bell,
  Collection,
  EditPen,
  Reading,
  Search,
  Share,
  UploadFilled,
} from '@element-plus/icons-vue'
import { impactOverview } from '@/api/impact'
import { systemMonitor } from '@/api/monitor'
import { listTasks } from '@/api/tasks'
import { formatTime } from '@/composables/useFormat'
import { DOMAIN_LABELS } from '@/constants/enums'
import { useAuthStore } from '@/stores/auth'
import type { SystemMonitor } from '@/api/monitor'
import type { ImpactOverview } from '@/types/impact'
import type { TaskOut } from '@/types/task'

const router = useRouter()
const auth = useAuthStore()

const recentTasks = ref<TaskOut[]>([])
const tasksLoading = ref(false)
const monitor = ref<SystemMonitor | null>(null)

// ---- 飞轮动态（最近入库/发布，每类取最新一条） ----
const latestReg = computed(() => monitor.value?.recent_activity?.regulations?.[0])
const latestRule = computed(() => monitor.value?.recent_activity?.rules?.[0])
const latestCase = computed(() => monitor.value?.recent_activity?.penalty_cases?.[0])

function shortDate(s?: string | null): string {
  return s ? s.slice(0, 10) : ''
}

function shortCaseName(name: string): string {
  return name.length > 24 ? `${name.slice(0, 24)}…` : name
}
const overview = ref<ImpactOverview | null>(null)
const overviewLoading = ref(false)

const greeting = computed(() => {
  const h = new Date().getHours()
  if (h < 6) return '夜深了'
  if (h < 12) return '上午好'
  if (h < 14) return '中午好'
  if (h < 18) return '下午好'
  return '晚上好'
})

const runningTasks = computed(() =>
  recentTasks.value.filter((t) => t.status === 'running' || t.status === 'processing'),
)

/** 待办清单：每项都可点击直达处理页面 */
const todos = computed(() => {
  const o = overview.value
  if (!o) return []
  return [
    {
      label: '影响评估待确认',
      count: o.pending_assessments,
      hint: '新规 / 罚单影响分析结果待人工确认',
      to: '/impact',
      tone: 'blue',
    },
    {
      label: '整改项待决策',
      count: o.remediation_pending,
      hint: '复审发现的违规材料需决定整改方式',
      to: '/impact',
      tone: 'red',
    },
    {
      label: '监管情报待分析',
      count: o.updates_to_analyze,
      hint: '抓取到的新规尚未做影响分析',
      to: '/impact',
      tone: 'amber',
    },
    {
      label: '情报待确认入库',
      count: o.pending_updates,
      hint: '新法规待确认后写入法规库',
      to: '/knowledge/trends',
      tone: 'amber',
    },
    {
      label: '高风险在用材料',
      count: o.high_risk_materials,
      hint: '台账中风险预扫为高分的材料',
      to: '/materials',
      tone: 'red',
    },
    {
      label: '线上内容已变更',
      count: o.patrol_changed,
      hint: '巡检发现线上内容与批准版不一致，已自动建复审任务',
      to: '/materials?filter=patrol_changed',
      tone: 'red',
    },
    {
      label: '线上页面失联',
      count: o.patrol_gone,
      hint: '已登记渠道页面下线（404/410），需人工确认',
      to: '/materials?filter=patrol_gone',
      tone: 'red',
    },
    {
      label: '依据失效待更新',
      count: o.stale_materials?.stale_count ?? 0,
      hint: '规则停用或法规废止，引用该依据的在用材料需更新（影响中心可写入整改清单）',
      to: '/impact?tab=stale',
      tone: 'amber',
    },
    {
      label: '规则待发布',
      count: o.rules_pending_publish,
      hint: '草稿规则审核后即可生效',
      to: '/knowledge/rules',
      tone: 'blue',
    },
  ]
})

/** 0 值卡片置灰不可点：跳入空清单没有意义，也避免演示时误点 */
function onTodoClick(todo: { to: string; count?: number }) {
  if (!todo.count) return
  void router.push(todo.to)
}

const allClear = computed(
  () =>
    overview.value != null &&
    todos.value.every((t) => !t.count) &&
    !overview.value.running_batches,
)

const greetingSub = computed(() => {
  const o = overview.value
  if (!o) return '金融营销材料合规审查 · 双引擎审查 + 人工复核闭环'
  const total =
    o.pending_assessments + o.remediation_pending + o.updates_to_analyze + o.rules_pending_publish
  if (o.running_batches > 0) {
    return `有 ${o.running_batches} 个复审批次正在运行，${total} 项待办等待处理`
  }
  if (total > 0) return `有 ${total} 项待办需要你处理`
  return '暂无待办，可发起新的审查或维护知识库'
})

const quickLinks = computed(() => {
  const links = [
    { label: '新建审查', to: '/tasks/new', icon: UploadFilled },
    { label: '法规检索', to: '/knowledge/search', icon: Search },
    { label: '法规库', to: '/knowledge/regulations', icon: Reading },
    { label: '监管动态', to: '/knowledge/trends', icon: Bell },
  ]
  if (auth.hasPermission('create_task')) {
    links.push({ label: '影响中心', to: '/impact', icon: Aim })
  }
  links.push(
    { label: '材料台账', to: '/materials', icon: Collection },
    { label: '知识图谱', to: '/knowledge/graph', icon: Share },
  )
  if (auth.hasPermission('manage_rules')) {
    links.push({ label: '规则库', to: '/knowledge/rules', icon: EditPen })
  }
  return links
})

async function loadDashboard() {
  tasksLoading.value = true
  try {
    const res = await listTasks({ page: 1, page_size: 8 })
    recentTasks.value = res.items
  } catch {
    // 拦截器已提示
  } finally {
    tasksLoading.value = false
  }

  if (auth.hasPermission('monitor')) {
    try {
      monitor.value = await systemMonitor()
    } catch {
      // 拦截器已提示
    }
  }

  if (auth.hasPermission('create_task')) {
    overviewLoading.value = true
    try {
      overview.value = await impactOverview()
    } catch {
      // 拦截器已提示
    } finally {
      overviewLoading.value = false
    }
  }
}

onMounted(() => void loadDashboard())

// keep-alive 缓存页：切标签回来时静默刷新待办与统计（首次激活紧随 onMounted，跳过）
let activatedOnce = false
onActivated(() => {
  if (!activatedOnce) {
    activatedOnce = true
    return
  }
  void loadDashboard()
})
</script>

<style scoped lang="scss">
.greeting-bar {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.greeting-title {
  margin: 0;
  font-size: 22px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.greeting-sub {
  margin: 6px 0 0;
  font-size: 14px;
  color: var(--el-text-color-secondary);
}

.greeting-actions {
  display: flex;
  gap: 10px;
  flex-shrink: 0;
}

.section-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}

.section-title {
  font-size: 16px;
  font-weight: 600;
}

// ---- 待办卡：左侧色条语义 = 紧急程度 ----
.todo-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(210px, 1fr));
  gap: 12px;
}

.todo-card {
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  border-radius: 12px;
  padding: 14px 16px;
  cursor: pointer;
  transition: box-shadow 0.15s, transform 0.15s, border-color 0.15s;
  position: relative;
  overflow: hidden;

  &::before {
    content: '';
    position: absolute;
    left: 0;
    top: 0;
    bottom: 0;
    width: 3px;
  }

  &:hover {
    transform: translateY(-2px);
    box-shadow: 0 6px 18px rgba(12, 26, 42, 0.08);
    border-color: var(--el-color-primary-light-7);

    .todo-arrow {
      color: var(--el-color-primary);
    }
  }

  &.tone-blue::before {
    background: var(--el-color-primary);
  }

  &.tone-red::before {
    background: var(--el-color-danger);
  }

  &.tone-amber::before {
    background: var(--el-color-warning);
  }

  // 0 值（无事可办）：置灰且不可点，hover 反馈一并关闭
  &.todo-card--disabled {
    opacity: 0.55;
    cursor: not-allowed;

    &:hover {
      transform: none;
      box-shadow: none;
      border-color: var(--app-border);

      .todo-arrow {
        color: var(--el-text-color-placeholder);
      }
    }
  }
}

.todo-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.todo-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.todo-arrow {
  color: var(--el-text-color-placeholder);
  font-size: 13px;
  transition: color 0.15s;
}

.todo-count {
  margin-top: 8px;
  font-size: 30px;
  font-weight: 700;
  line-height: 1;
  color: var(--el-text-color-primary);

  &.zero {
    color: var(--el-text-color-placeholder);
  }
}

.todo-hint {
  margin-top: 8px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.5;
}

// ---- 主区两栏 ----
.main-grid {
  display: grid;
  // 320px：保证快捷入口 13px×4 字标签在卡片 24px 内边距下不换行
  grid-template-columns: minmax(0, 1fr) 320px;
  gap: 16px;
  align-items: start;
}

.main-col {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
}

.side-col {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.card-title {
  font-size: 14px;
  font-weight: 600;
}

.running-card :deep(.el-card__body) {
  padding: 8px 20px;
}

.running-row {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 12px 0;

  & + .running-row {
    border-top: 1px solid var(--app-border-light);
  }

  &:hover .running-name {
    color: var(--el-color-primary);
  }
}

.running-info {
  width: 260px;
  min-width: 0;
}

.running-name {
  display: block;
  font-size: 14px;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  transition: color 0.15s;
}

.running-meta {
  display: block;
  margin-top: 2px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.running-progress {
  flex: 1;
}

.running-pct {
  width: 42px;
  text-align: right;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.task-link {
  cursor: pointer;
  font-weight: 500;

  &:hover {
    color: var(--el-color-primary);
  }
}

.quick-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
}

.quick-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 12px 4px;
  border-radius: 10px;
  font-size: 13px;
  color: var(--el-text-color-regular);
  cursor: pointer;
  transition: background 0.15s, color 0.15s;

  &:hover {
    background: var(--el-color-primary-light-9);
    color: var(--el-color-primary);
  }
}

.quick-icon {
  color: inherit;
}

.asset-list {
  display: flex;
  flex-direction: column;
}

.asset-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 0;
  font-size: 14px;
  color: var(--el-text-color-regular);

  & + .asset-row {
    border-top: 1px dashed var(--app-border-light);
  }

  b {
    font-size: 16px;
    color: var(--el-text-color-primary);
  }
}

/* ---- 飞轮动态 ---- */
.flywheel-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.flywheel-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12.5px;
  min-width: 0;
}

.fw-tag {
  flex-shrink: 0;
}

.fw-text {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--el-text-color-regular);
}

.fw-time {
  flex-shrink: 0;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

@media (max-width: 1100px) {
  .main-grid {
    grid-template-columns: 1fr;
  }
}
</style>
