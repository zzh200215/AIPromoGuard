<template>
  <div class="app-page">
    <PageHeader
      title="法规影响中心"
      description="监管新规或处罚案例触发 → 影响分析定位受影响材料 → 人工确认 → 批量复审 → 整改闭环"
    />

    <!-- 触发源：监管情报 / 处罚案例 -->
    <el-card>
      <template #header>
        <div class="card-header">
          <span class="card-title">触发源</span>
          <span class="header-hint">选择一条新规或罚单，发起影响分析</span>
        </div>
      </template>
      <el-tabs v-model="triggerTab">
        <el-tab-pane :label="`监管情报（${updates.length}）`" name="updates">
          <el-table :data="updates" v-loading="updatesLoading" size="default">
            <el-table-column label="来源" width="100">
              <template #default="{ row }">
                <el-tag size="small" effect="plain">{{ SOURCE_LABELS[row.source] ?? row.source }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="title" label="法规名称" min-width="240" show-overflow-tooltip />
            <el-table-column prop="publish_date" label="发布日期" width="110" />
            <el-table-column prop="llm_summary" label="摘要" min-width="220" show-overflow-tooltip />
            <el-table-column label="" width="110" align="right" fixed="right">
              <template #default="{ row }">
                <el-button
                  type="primary"
                  size="small"
                  :loading="analyzingId === row.id"
                  @click="onAnalyze(row.id)"
                >
                  分析影响
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <el-tab-pane :label="`处罚案例（${penaltyCases.length}）`" name="penalties">
          <el-table :data="penaltyCases" v-loading="penaltiesLoading" size="default">
            <el-table-column prop="case_name" label="案例名称" min-width="240" show-overflow-tooltip />
            <el-table-column prop="penalty_org" label="处罚机构" width="180" show-overflow-tooltip />
            <el-table-column prop="penalty_date" label="处罚日期" width="110" />
            <el-table-column
              prop="violation_summary"
              label="违规摘要"
              min-width="220"
              show-overflow-tooltip
            />
            <el-table-column label="" width="190" align="right" fixed="right">
              <template #default="{ row }">
                <el-button
                  type="primary"
                  size="small"
                  :loading="analyzingPenaltyId === row.id"
                  @click="onAnalyzePenalty(row.id)"
                >
                  分析影响
                </el-button>
                <el-button
                  v-if="auth.hasPermission('manage_rules')"
                  size="small"
                  :loading="miningPenaltyId === row.id"
                  @click="onMineRules(row.id)"
                >
                  挖掘规则
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </el-card>

    <!-- 影响评估列表：点击行打开详情抽屉 -->
    <el-card>
      <template #header>
        <div class="card-header">
          <span class="card-title">影响评估</span>
          <el-select v-model="statusFilter" size="small" style="width: 140px" @change="reload">
            <el-option label="全部状态" value="" />
            <el-option v-for="(label, key) in STATUS_LABELS" :key="key" :label="label" :value="key" />
          </el-select>
        </div>
      </template>
      <el-table :data="assessments" v-loading="listLoading" highlight-current-row @row-click="onSelectAssessment">
        <el-table-column label="评估" min-width="280" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="assess-title">{{ row.update_title || row.title }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="STATUS_TAG[row.status] ?? 'info'" size="small" effect="light">
              {{ STATUS_LABELS[row.status] ?? row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="风险分布" width="170">
          <template #default="{ row }">
            <span class="risk-dist">
              <span v-if="row.high_count" class="dist-high">高 {{ row.high_count }}</span>
              <span v-if="row.medium_count" class="dist-medium">中 {{ row.medium_count }}</span>
              <span v-if="row.low_count" class="dist-low">低 {{ row.low_count }}</span>
              <span v-if="!row.high_count && !row.medium_count && !row.low_count" class="muted">
                —
              </span>
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="170" />
      </el-table>
      <div class="pager">
        <el-pagination
          layout="total, prev, pager, next"
          :total="total"
          v-model:current-page="page"
          :page-size="pageSize"
          @current-change="loadAssessments"
        />
      </div>
    </el-card>

    <!-- 评估详情抽屉 -->
    <el-drawer v-model="drawerVisible" :title="detail ? `影响评估 #${detail.id}` : '影响评估'" size="62%">
      <div v-loading="detailLoading" class="drawer-body">
        <template v-if="detail">
          <div class="detail-head">
            <el-tag :type="STATUS_TAG[detail.status] ?? 'info'" effect="light">
              {{ STATUS_LABELS[detail.status] ?? detail.status }}
            </el-tag>
            <span class="risk-dist">
              <span v-if="detail.high_count" class="dist-high">高风险 {{ detail.high_count }}</span>
              <span v-if="detail.medium_count" class="dist-medium">中风险 {{ detail.medium_count }}</span>
              <span v-if="detail.low_count" class="dist-low">低风险 {{ detail.low_count }}</span>
            </span>
            <div class="head-actions">
              <el-button
                v-if="detail.status === 'draft' || detail.status === 'pending_review'"
                type="primary"
                :loading="confirming"
                @click="onConfirm"
              >
                确认影响
              </el-button>
              <el-button
                v-if="detail.status === 'draft' || detail.status === 'pending_review'"
                @click="onDismiss"
              >
                作废
              </el-button>
              <el-button
                v-if="detail.status === 'confirmed'"
                type="primary"
                :loading="creatingBatch"
                @click="onCreateBatch"
              >
                发起批量复审
              </el-button>
            </div>
          </div>

          <div class="summary-block">{{ detail.summary || '暂无摘要' }}</div>

          <div class="block-title">命中规则（{{ rules.length }}）</div>
          <el-table :data="rules" size="small">
            <el-table-column prop="rule_name" label="规则" min-width="220" show-overflow-tooltip />
            <el-table-column label="严重度" width="80">
              <template #default="{ row }">{{ SEVERITY_LABELS[row.severity] ?? row.severity }}</template>
            </el-table-column>
            <el-table-column label="命中方式" width="110">
              <template #default="{ row }">
                <el-tag size="small" effect="light" :type="row.matched_by === 'link' ? 'success' : 'warning'">
                  {{ row.matched_by === 'link' ? '结构化关联' : '关键词' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="确认状态" width="90">
              <template #default="{ row }">
                {{ row.confirm_status === 'confirmed' ? '已确认' : '待确认' }}
              </template>
            </el-table-column>
          </el-table>

          <div class="block-title">受影响材料（{{ materials.length }}）</div>
          <el-table
            ref="materialTableRef"
            :data="materials"
            size="small"
            row-key="material_id"
            @selection-change="onSelectionChange"
          >
            <el-table-column type="selection" width="42" reserve-selection />
            <el-table-column prop="name" label="材料" min-width="180" show-overflow-tooltip />
            <el-table-column prop="product_type" label="产品" width="80" />
            <el-table-column label="风险" width="110" sortable :sort-by="'risk_score'">
              <template #default="{ row }">
                <el-tag :type="RISK_TAG[row.risk_level] ?? 'info'" size="small" effect="light">
                  {{ RISK_LABELS[row.risk_level] ?? row.risk_level }} {{ row.risk_score }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="reason" label="影响原因" min-width="200" show-overflow-tooltip />
          </el-table>

          <template v-if="detail.batches.length">
            <div class="block-title">关联复审批次</div>
            <el-table :data="detail.batches" size="small" @row-click="goBatch">
              <el-table-column prop="batch_name" label="批次" min-width="220" show-overflow-tooltip />
              <el-table-column label="进度" width="110">
                <template #default="{ row }">
                  {{ row.completed_count }}/{{ row.total_count }}
                </template>
              </el-table-column>
              <el-table-column label="状态" width="100">
                <template #default="{ row }">
                  <TaskStatusTag :status="row.status" />
                </template>
              </el-table-column>
            </el-table>
          </template>

          <template v-if="remediation.length">
            <div class="block-title remediation-title">
              整改清单（复审终态自动生成）
              <el-button size="small" type="primary" plain @click="onExportRemediation">
                导出 Excel
              </el-button>
            </div>
            <el-table :data="remediation" size="small">
              <el-table-column prop="material_name" label="材料" min-width="190" show-overflow-tooltip>
                <template #default="{ row }">
                  {{ row.material_name }}
                  <el-tag v-if="row.retest" size="small" effect="light" class="retest-tag">复测</el-tag>
                  <span v-else-if="row.retest_task_id && row.decision !== 'done'" class="retesting">
                    复测中（任务 #{{ row.retest_task_id }}）
                  </span>
                </template>
              </el-table-column>
              <el-table-column label="违规数" width="80">
                <template #default="{ row }">
                  <el-tag size="small" effect="light" :type="row.violation_count > 0 ? 'danger' : 'success'">
                    {{ row.violation_count }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="需整改" width="80">
                <template #default="{ row }">{{ row.requires_remediation ? '是' : '否' }}</template>
              </el-table-column>
              <el-table-column label="决策" width="96">
                <template #default="{ row }">
                  <el-tag size="small" effect="light" :type="DECISION_TAG[row.decision] ?? 'info'">
                    {{ DECISION_LABELS[row.decision] ?? row.decision }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="250" fixed="right">
                <template #default="{ row }">
                  <template v-if="row.decision === 'pending'">
                    <el-button size="small" type="danger" link @click="onDecide(row, 'remediate')">
                      需整改
                    </el-button>
                    <el-button size="small" link @click="onDecide(row, 'reject')">驳回</el-button>
                  </template>
                  <el-button
                    v-else-if="row.decision === 'remediate'"
                    size="small"
                    type="success"
                    link
                    @click="onDecide(row, 'done')"
                  >
                    完成整改
                  </el-button>
                  <el-button
                    v-if="canRetest(row)"
                    size="small"
                    type="primary"
                    link
                    @click="pickRetestFile(row)"
                  >
                    上传整改版
                  </el-button>
                </template>
              </el-table-column>
            </el-table>
            <input
              ref="retestFileInput"
              type="file"
              accept=".txt,.pdf,.docx,.png,.jpg,.jpeg,.bmp"
              style="display: none"
              @change="onRetestFileChosen"
            />
          </template>
        </template>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
defineOptions({ name: 'impact-center' })
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { ElTable } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import {
  confirmAssessment,
  createAssessment,
  createAssessmentBatch,
  decideRemediation,
  exportRemediation,
  getAssessment,
  listAssessments,
  listImpactPenaltyCases,
  minePenaltyRules,
  retestMaterial,
} from '@/api/impact'
import { listRegulationTrends } from '@/api/regulationTrend'
import { useAuthStore } from '@/stores/auth'
import type { RegulationUpdate } from '@/types/regulationTrend'
import type {
  AssessmentDetail,
  AssessmentStatus,
  ImpactAssessment,
  ImpactPenaltyCase,
  RemediationItem,
} from '@/types/impact'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const SOURCE_LABELS: Record<string, string> = { nfra: '金监总局', csrc: '证监会', pbc: '人民银行' }
const STATUS_LABELS: Record<string, string> = {
  draft: '草稿',
  pending_review: '待复核',
  confirmed: '已确认',
  dismissed: '已作废',
}
const STATUS_TAG: Record<string, string> = {
  draft: 'info',
  pending_review: 'warning',
  confirmed: 'success',
  dismissed: 'danger',
}
const RISK_LABELS: Record<string, string> = { high: '高', medium: '中', low: '低' }
const RISK_TAG: Record<string, string> = { high: 'danger', medium: 'warning', low: 'info' }
const SEVERITY_LABELS: Record<string, string> = { high: '高', medium: '中', low: '低' }
const DECISION_LABELS: Record<string, string> = {
  pending: '待决策',
  remediate: '整改中',
  reject: '已驳回',
  done: '已完成',
}
const DECISION_TAG: Record<string, string> = {
  pending: 'info',
  remediate: 'warning',
  reject: 'danger',
  done: 'success',
}

// ---------- 触发源 ----------
const triggerTab = ref('updates')
const updates = ref<RegulationUpdate[]>([])
const updatesLoading = ref(false)
const analyzingId = ref(0)

const penaltyCases = ref<ImpactPenaltyCase[]>([])
const penaltiesLoading = ref(false)
const analyzingPenaltyId = ref(0)
const miningPenaltyId = ref(0)

// ---------- 评估列表 ----------
const assessments = ref<ImpactAssessment[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 10
const statusFilter = ref<AssessmentStatus | ''>('')
const listLoading = ref(false)
let loadSeq = 0

// ---------- 详情抽屉 ----------
const drawerVisible = ref(false)
const detailLoading = ref(false)
const detail = ref<AssessmentDetail | null>(null)
const confirming = ref(false)
const creatingBatch = ref(false)
const materialTableRef = ref<InstanceType<typeof ElTable>>()
const selectedMaterialIds = ref<number[]>([])

const rules = computed(() => detail.value?.items?.rules ?? [])
const materials = computed(() => detail.value?.items?.materials ?? [])
const remediation = computed<RemediationItem[]>(
  () => (detail.value?.items as { remediation?: RemediationItem[] } | null | undefined)?.remediation ?? [],
)

async function loadUpdates() {
  updatesLoading.value = true
  try {
    const data = await listRegulationTrends({ page: 1, page_size: 10, status: 'imported' })
    updates.value = data.items
  } finally {
    updatesLoading.value = false
  }
}

async function loadPenalties() {
  penaltiesLoading.value = true
  try {
    const data = await listImpactPenaltyCases(1, 10)
    penaltyCases.value = data.items
  } finally {
    penaltiesLoading.value = false
  }
}

async function loadAssessments() {
  const mySeq = ++loadSeq
  listLoading.value = true
  try {
    const data = await listAssessments({
      page: page.value,
      page_size: pageSize,
      status: statusFilter.value === '' ? undefined : statusFilter.value,
    })
    if (mySeq !== loadSeq) return
    total.value = data.total
    assessments.value = data.items
  } finally {
    if (mySeq === loadSeq) listLoading.value = false
  }
}

function reload() {
  page.value = 1
  loadAssessments()
}

async function loadDetail(id: number) {
  detailLoading.value = true
  try {
    detail.value = await getAssessment(id)
    selectedMaterialIds.value = []
  } finally {
    detailLoading.value = false
  }
}

function onSelectAssessment(row: ImpactAssessment) {
  drawerVisible.value = true
  void loadDetail(row.id)
}

function goBatch(row: { id: number }) {
  router.push(`/batches/${row.id}`)
}

// ---------- 触发动作 ----------
async function onAnalyze(updateId: number) {
  analyzingId.value = updateId
  try {
    const created = await createAssessment({ regulation_update_id: updateId })
    ElMessage.success(`影响分析完成：命中规则 ${created.items?.rules.length ?? 0} 条`)
    reload()
    drawerVisible.value = true
    await loadDetail(created.id)
  } finally {
    analyzingId.value = 0
  }
}

async function onAnalyzePenalty(caseId: number) {
  analyzingPenaltyId.value = caseId
  try {
    const created = await createAssessment({ penalty_case_id: caseId })
    ElMessage.success(`影响分析完成：命中规则 ${created.items?.rules.length ?? 0} 条`)
    reload()
    drawerVisible.value = true
    await loadDetail(created.id)
  } finally {
    analyzingPenaltyId.value = 0
  }
}

async function onMineRules(caseId: number) {
  miningPenaltyId.value = caseId
  try {
    const result = await minePenaltyRules(caseId)
    ElMessage.success(`已生成 ${result.items.length} 条规则候选草稿，请到规则库审核发布`)
  } finally {
    miningPenaltyId.value = 0
  }
}

// ---------- 确认 / 作废 / 批量复审 ----------
function onSelectionChange(rows: Array<{ material_id: number }>) {
  selectedMaterialIds.value = rows.map((r) => r.material_id)
}

async function onConfirm() {
  if (!detail.value) return
  confirming.value = true
  try {
    const result = await confirmAssessment(detail.value.id, {
      action: 'confirm',
      material_ids: selectedMaterialIds.value,
    })
    ElMessage.success(
      result.created_links > 0
        ? `影响已确认，沉淀规则关联 ${result.created_links} 条`
        : '影响已确认',
    )
    await loadDetail(detail.value.id)
    loadAssessments()
  } finally {
    confirming.value = false
  }
}

async function onDismiss() {
  if (!detail.value) return
  await ElMessageBox.confirm('作废后该评估不再参与复审流程，确认作废？', '作废评估', {
    type: 'warning',
  })
  await confirmAssessment(detail.value.id, { action: 'dismiss' })
  ElMessage.success('评估已作废')
  drawerVisible.value = false
  detail.value = null
  loadAssessments()
}

async function onCreateBatch() {
  if (!detail.value) return
  creatingBatch.value = true
  try {
    const result = await createAssessmentBatch(detail.value.id, selectedMaterialIds.value)
    const skippedNote =
      result.skipped.length > 0 ? `，${result.skipped.length} 份因无文档被跳过` : ''
    ElMessage.success(`复审批次已创建（${result.total_count} 份${skippedNote}）`)
    await loadDetail(detail.value.id)
    router.push(`/batches/${result.batch_id}`)
  } finally {
    creatingBatch.value = false
  }
}

// ---------- 整改决策 ----------
async function onDecide(row: RemediationItem, decision: 'remediate' | 'reject' | 'done') {
  if (!detail.value) return
  await decideRemediation(detail.value.id, row.task_id, decision)
  ElMessage.success('整改决策已记录')
  await loadDetail(detail.value.id)
}

// ---------- 整改复测：上传整改版 → 单任务复测 → 通过自动关闭原整改项 ----------
const retestFileInput = ref<HTMLInputElement>()
const pendingRetestRow = ref<RemediationItem | null>(null)
const uploadingRetest = ref(false)

function canRetest(row: RemediationItem) {
  return (
    !row.retest &&
    row.requires_remediation &&
    row.material_id !== null &&
    row.decision !== 'done' &&
    !row.retest_task_id
  )
}

function pickRetestFile(row: RemediationItem) {
  pendingRetestRow.value = row
  retestFileInput.value?.click()
}

async function onRetestFileChosen(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = '' // 允许重复选同一文件
  const row = pendingRetestRow.value
  pendingRetestRow.value = null
  if (!file || !row?.material_id || !detail.value) return
  uploadingRetest.value = true
  try {
    const result = await retestMaterial(row.material_id, detail.value.id, file)
    ElMessage.success(
      `整改版已上传（${result.version}），复测任务 #${result.task_id} 已启动，通过后将自动关闭本整改项`,
    )
    await loadDetail(detail.value.id)
  } finally {
    uploadingRetest.value = false
  }
}

async function onExportRemediation() {
  if (!detail.value) return
  try {
    await exportRemediation(detail.value.id)
  } catch {
    // 拦截器已提示
  }
}

onMounted(() => {
  loadUpdates()
  loadPenalties()
  loadAssessments()
  handleDeepLinkQuery()
})

/** 监管动态页「确认并评估」直达：?update_id=xx&analyze=1 自动发起影响分析。 */
function handleDeepLinkQuery() {
  const qid = Number(route.query.update_id)
  if (route.query.analyze !== '1' || !Number.isFinite(qid) || qid <= 0) return
  // 先清 query 再分析：刷新页面不会对同一情报重复建评估
  router.replace({ query: {} })
  triggerTab.value = 'updates'
  void onAnalyze(qid)
}
</script>

<style scoped lang="scss">
.card-title {
  font-size: 14px;
  font-weight: 600;
}

.header-hint {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  font-weight: 400;
}

.assess-title {
  font-weight: 500;
}

.risk-dist {
  display: inline-flex;
  gap: 10px;
  font-size: 13px;

  .dist-high {
    color: var(--el-color-danger);
    font-weight: 600;
  }

  .dist-medium {
    color: var(--el-color-warning);
    font-weight: 600;
  }

  .dist-low {
    color: var(--el-text-color-secondary);
  }
}

.muted {
  color: var(--el-text-color-placeholder);
}

// ---- 抽屉 ----
.drawer-body {
  min-height: 200px;
}

.detail-head {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}

.head-actions {
  margin-left: auto;
  display: flex;
  gap: 8px;
}

.summary-block {
  background: var(--el-color-primary-light-9);
  border-radius: 8px;
  padding: 12px 14px;
  font-size: 14px;
  line-height: 1.7;
  color: var(--el-text-color-regular);
  margin-bottom: 4px;
}

.remediation-title {
  justify-content: space-between;
}

.retest-tag {
  margin-left: 6px;
}

.retesting {
  margin-left: 6px;
  font-size: 12px;
  color: var(--el-color-primary);
}

table :deep(.el-table__row) {
  cursor: pointer;
}
</style>
