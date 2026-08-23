<template>
  <div class="impact-center">
    <!-- 监管情报候选：选中一条新规触发影响分析 -->
    <el-card shadow="never" class="section-card">
      <template #header>
        <div class="card-header">
          <span>监管情报（待分析）</span>
          <el-button size="small" :loading="updatesLoading" @click="loadUpdates">刷新</el-button>
        </div>
      </template>
      <el-table :data="updates" border v-loading="updatesLoading" size="small">
        <el-table-column label="来源" width="90">
          <template #default="{ row }">{{ SOURCE_LABELS[row.source] ?? row.source }}</template>
        </el-table-column>
        <el-table-column prop="title" label="法规名称" min-width="260" show-overflow-tooltip />
        <el-table-column prop="publish_date" label="发布日期" width="110" />
        <el-table-column prop="domain" label="领域" width="90" />
        <el-table-column prop="llm_summary" label="摘要" min-width="220" show-overflow-tooltip />
        <el-table-column label="操作" width="120" fixed="right">
          <template #default="{ row }">
            <el-button
              size="small"
              type="primary"
              :loading="analyzingId === row.id"
              @click="onAnalyze(row.id)"
            >
              分析影响
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card shadow="never" class="section-card">
      <template #header>
        <div class="card-header">
          <span>影响评估</span>
          <el-select v-model="statusFilter" size="small" style="width: 140px" @change="reload">
            <el-option label="全部状态" value="" />
            <el-option v-for="(label, key) in STATUS_LABELS" :key="key" :label="label" :value="key" />
          </el-select>
        </div>
      </template>
      <el-table
        :data="assessments"
        border
        v-loading="listLoading"
        size="small"
        highlight-current-row
        @current-change="onSelectAssessment"
      >
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column label="评估标题" min-width="240" show-overflow-tooltip>
          <template #default="{ row }">{{ row.update_title || row.title }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="STATUS_TAG[row.status] ?? 'info'" size="small">
              {{ STATUS_LABELS[row.status] ?? row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="风险分布" width="150">
          <template #default="{ row }">
            高 {{ row.high_count }} / 中 {{ row.medium_count }} / 低 {{ row.low_count }}
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

    <el-card v-if="detail" shadow="never" class="section-card">
      <template #header>
        <div class="card-header">
          <span>评估详情 #{{ detail.id }}</span>
          <div>
            <el-button
              v-if="detail.status === 'draft' || detail.status === 'pending_review'"
              size="small"
              type="primary"
              :loading="confirming"
              @click="onConfirm"
            >
              确认影响
            </el-button>
            <el-button
              v-if="detail.status === 'draft' || detail.status === 'pending_review'"
              size="small"
              @click="onDismiss"
            >
              作废
            </el-button>
            <el-button
              v-if="detail.status === 'confirmed'"
              size="small"
              type="primary"
              :loading="creatingBatch"
              @click="onCreateBatch"
            >
              发起批量复审
            </el-button>
          </div>
        </div>
      </template>

      <el-alert type="info" :closable="false" class="summary" :title="detail.summary || '暂无摘要'" />

      <h4 class="block-title">命中规则（{{ rules.length }}）</h4>
      <el-table :data="rules" border size="small">
        <el-table-column prop="rule_name" label="规则" min-width="240" show-overflow-tooltip />
        <el-table-column prop="domain" label="领域" width="90" />
        <el-table-column label="严重度" width="90">
          <template #default="{ row }">{{ SEVERITY_LABELS[row.severity] ?? row.severity }}</template>
        </el-table-column>
        <el-table-column label="命中方式" width="110">
          <template #default="{ row }">
            <el-tag size="small" :type="row.matched_by === 'link' ? 'success' : 'warning'">
              {{ row.matched_by === 'link' ? '结构化关联' : '关键词' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="确认状态" width="100">
          <template #default="{ row }">
            {{ row.confirm_status === 'confirmed' ? '已确认' : '待确认' }}
          </template>
        </el-table-column>
      </el-table>

      <h4 class="block-title">受影响材料（{{ materials.length }}）</h4>
      <el-table
        ref="materialTableRef"
        :data="materials"
        border
        size="small"
        row-key="material_id"
        @selection-change="onSelectionChange"
      >
        <el-table-column type="selection" width="42" reserve-selection />
        <el-table-column prop="name" label="材料" min-width="200" show-overflow-tooltip />
        <el-table-column prop="product_type" label="产品" width="90" />
        <el-table-column prop="material_type" label="类型" width="110" />
        <el-table-column prop="owner" label="负责人" width="90" />
        <el-table-column label="风险" width="120" sortable :sort-by="'risk_score'">
          <template #default="{ row }">
            <el-tag :type="RISK_TAG[row.risk_level] ?? 'info'" size="small">
              {{ RISK_LABELS[row.risk_level] ?? row.risk_level }} {{ row.risk_score }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="reason" label="影响原因" min-width="220" show-overflow-tooltip />
        <el-table-column label="确认状态" width="90">
          <template #default="{ row }">
            {{ row.confirm_status === 'confirmed' ? '已确认' : '待确认' }}
          </template>
        </el-table-column>
      </el-table>

      <template v-if="detail.batches.length">
        <h4 class="block-title">关联复审批次</h4>
        <el-table :data="detail.batches" border size="small">
          <el-table-column prop="id" label="批次" width="80" />
          <el-table-column prop="batch_name" label="名称" min-width="240" show-overflow-tooltip />
          <el-table-column label="进度" width="120">
            <template #default="{ row }">{{ row.completed_count }}/{{ row.total_count }}</template>
          </el-table-column>
          <el-table-column label="状态" width="100">
            <template #default="{ row }">{{ row.status }}</template>
          </el-table-column>
          <el-table-column label="操作" width="100">
            <template #default="{ row }">
              <el-button size="small" link type="primary" @click="router.push(`/batches/${row.id}`)">
                查看
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </template>

      <template v-if="remediation.length">
        <h4 class="block-title">整改清单（复审终态自动生成）</h4>
        <el-table :data="remediation" border size="small">
          <el-table-column prop="material_name" label="材料" min-width="200" show-overflow-tooltip />
          <el-table-column label="违规数" width="80">
            <template #default="{ row }">
              <el-tag
                size="small"
                :type="row.violation_count > 0 ? 'danger' : 'success'"
              >
                {{ row.violation_count }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="需整改" width="80">
            <template #default="{ row }">{{ row.requires_remediation ? '是' : '否' }}</template>
          </el-table-column>
          <el-table-column label="决策" width="110">
            <template #default="{ row }">
              <el-tag size="small" :type="DECISION_TAG[row.decision] ?? 'info'">
                {{ DECISION_LABELS[row.decision] ?? row.decision }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="220" fixed="right">
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
            </template>
          </el-table-column>
        </el-table>
      </template>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { ElTable } from 'element-plus'
import { useRouter } from 'vue-router'
import {
  confirmAssessment,
  createAssessment,
  createAssessmentBatch,
  decideRemediation,
  getAssessment,
  listAssessments,
} from '@/api/impact'
import { listRegulationTrends } from '@/api/regulationTrend'
import type { RegulationUpdate } from '@/types/regulationTrend'
import type { AssessmentDetail, AssessmentStatus, ImpactAssessment, RemediationItem } from '@/types/impact'

const router = useRouter()

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

const updates = ref<RegulationUpdate[]>([])
const updatesLoading = ref(false)
const analyzingId = ref(0)

const assessments = ref<ImpactAssessment[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 10
const statusFilter = ref<AssessmentStatus | ''>('')
const listLoading = ref(false)
let loadSeq = 0

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

async function onAnalyze(updateId: number) {
  analyzingId.value = updateId
  try {
    const created = await createAssessment(updateId)
    ElMessage.success(`影响分析完成：命中规则 ${created.items?.rules.length ?? 0} 条`)
    reload()
    await loadDetail(created.id)
  } finally {
    analyzingId.value = 0
  }
}

async function loadDetail(id: number) {
  detail.value = await getAssessment(id)
  selectedMaterialIds.value = []
}

function onSelectAssessment(row: AssessmentDetail | null) {
  if (row) loadDetail(row.id)
}

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

async function onDecide(row: RemediationItem, decision: 'remediate' | 'reject' | 'done') {
  if (!detail.value) return
  await decideRemediation(detail.value.id, row.task_id, decision)
  ElMessage.success('整改决策已记录')
  await loadDetail(detail.value.id)
}

onMounted(() => {
  loadUpdates()
  loadAssessments()
})
</script>

<style scoped>
.impact-center {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.summary {
  margin-bottom: 12px;
}
.block-title {
  margin: 16px 0 8px;
  font-weight: 600;
}
.pager {
  margin-top: 12px;
  display: flex;
  justify-content: flex-end;
}
</style>
