<template>
  <div class="app-page">
    <PageHeader
      title="材料台账"
      description="在用营销材料全生命周期台账：登记材料与审查文档的对应关系，复审与整改都在这里追溯"
    >
      <el-button
        v-if="auth.hasPermission('manage_rules')"
        type="primary"
        @click="openCreate"
      >
        新增材料
      </el-button>
    </PageHeader>

    <el-card>
      <div class="filter-bar">
        <el-select v-model="filterProduct" placeholder="产品类型" clearable style="width: 150px" @change="applyFilters">
          <el-option label="基金" value="fund" />
          <el-option label="保险" value="insurance" />
          <el-option label="银行理财" value="wealth" />
        </el-select>
        <el-select v-model="filterStatus" placeholder="台账状态" clearable style="width: 130px" @change="applyFilters">
          <el-option label="在用" value="active" />
          <el-option label="已归档" value="archived" />
        </el-select>
        <el-select v-model="filterReview" placeholder="最近审查" clearable style="width: 150px" @change="applyFilters">
          <el-option label="存在违规" value="violation" />
          <el-option label="干净" value="clean" />
          <el-option label="失败" value="failed" />
        </el-select>
        <el-select v-model="filterPatrol" placeholder="线上巡检" clearable style="width: 150px" @change="applyFilters">
          <el-option
            v-for="(label, key) in PATROL_LABELS"
            :key="key"
            :label="label"
            :value="key"
          />
        </el-select>
      </div>

      <el-table :data="rows" v-loading="loading">
        <el-table-column prop="name" label="材料名称" min-width="200" show-overflow-tooltip />
        <el-table-column label="产品" width="100">
          <template #default="{ row }">{{ PRODUCT_LABELS[row.product_type] ?? row.product_type }}</template>
        </el-table-column>
        <el-table-column prop="material_type" label="材料类型" width="110" />
        <el-table-column prop="version" label="版本" width="80" />
        <el-table-column prop="owner" label="负责人" width="100" />
        <el-table-column prop="document_id" label="关联文档" width="130" show-overflow-tooltip />
        <el-table-column label="台账状态" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="row.status === 'active' ? 'success' : 'info'">
              {{ row.status === 'active' ? '在用' : '已归档' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="最近审查" width="100">
          <template #default="{ row }">
            <el-tag v-if="row.last_review_status" size="small" :type="REVIEW_TAG[row.last_review_status] ?? 'info'">
              {{ REVIEW_LABELS[row.last_review_status] ?? row.last_review_status }}
            </el-tag>
            <span v-else>—</span>
          </template>
        </el-table-column>
        <el-table-column label="线上巡检" width="132">
          <template #default="{ row }">
            <template v-if="row.patrol_status">
              <el-tooltip
                :content="`${PATROL_TIP[row.patrol_status] ?? ''}（点击查看差异详情）`"
                placement="top"
              >
                <el-tag
                  size="small"
                  class="patrol-tag"
                  :type="PATROL_TAG[row.patrol_status] ?? 'info'"
                  @click="openPatrolDiff(row)"
                >
                  {{ PATROL_LABELS[row.patrol_status] ?? row.patrol_status }}
                </el-tag>
              </el-tooltip>
              <el-button link size="small" class="patrol-diff-link" @click="openPatrolDiff(row)">
                差异详情
              </el-button>
            </template>
            <span v-else class="patrol-none">{{ row.publish_url ? '未巡检' : '未登记渠道' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="250" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="row.document_id && auth.hasPermission('create_task')"
              size="small"
              type="primary"
              link
              @click="startReview(row)"
            >
              发起审查
            </el-button>
            <el-button
              v-if="row.publish_url && auth.hasPermission('create_task')"
              size="small"
              :loading="patrollingId === row.id"
              type="warning"
              link
              @click="patrolOne(row)"
            >
              巡检
            </el-button>
            <el-button
              v-if="auth.hasPermission('manage_rules')"
              size="small"
              type="primary"
              link
              @click="openEdit(row)"
            >
              编辑
            </el-button>
            <el-button
              v-if="auth.hasPermission('manage_rules')"
              size="small"
              :type="row.status === 'active' ? 'info' : 'success'"
              link
              @click="toggleArchive(row)"
            >
              {{ row.status === 'active' ? '归档' : '恢复' }}
            </el-button>
          </template>
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

    <el-dialog v-model="dialogVisible" :title="editing ? '编辑材料' : '新增材料'" width="480px">
      <el-form :model="form" label-width="90px">
        <el-form-item label="材料名称" required>
          <el-input v-model="form.name" maxlength="255" placeholder="如：稳健回报混合基金单页A" />
        </el-form-item>
        <el-form-item label="产品类型" required>
          <el-select v-model="form.product_type" style="width: 100%" :disabled="!!editing">
            <el-option label="基金" value="fund" />
            <el-option label="保险" value="insurance" />
            <el-option label="银行理财" value="wealth" />
          </el-select>
        </el-form-item>
        <el-form-item label="材料类型" required>
          <el-input v-model="form.material_type" placeholder="宣传单页 / 海报 / 推文 / 直播话术稿" />
        </el-form-item>
        <el-form-item label="版本">
          <el-input v-model="form.version" placeholder="v1" />
        </el-form-item>
        <el-form-item label="负责人">
          <el-input v-model="form.owner" placeholder="材料责任人" />
        </el-form-item>
        <el-form-item label="关联文档">
          <el-input v-model="form.document_id" placeholder="doc_xxxxxxxx（已上传文档 ID）" />
        </el-form-item>
        <el-form-item label="发布渠道">
          <el-select v-model="form.channel" style="width: 120px" clearable placeholder="渠道">
            <el-option label="官网" value="web" />
            <el-option label="公众号" value="wechat" />
            <el-option label="抖音" value="douyin" />
          </el-select>
        </el-form-item>
        <el-form-item label="发布地址">
          <el-input v-model="form.publish_url" placeholder="https://（已授权的自有渠道地址，登记后可巡检）" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="onSubmit">保存</el-button>
      </template>
    </el-dialog>

    <!-- 巡检差异详情（R3-1 下钻）：批准版 vs 线上存档快照 -->
    <el-drawer
      v-model="patrolDrawerVisible"
      :title="patrolDiff ? `巡检差异 · ${patrolDiff.name}` : '巡检差异'"
      size="600px"
    >
      <div v-loading="patrolDiffLoading" class="patrol-diff-body">
        <template v-if="patrolDiff">
          <div class="diff-head">
            <el-tag size="small" :type="PATROL_TAG[patrolDiff.patrol_status ?? ''] ?? 'info'">
              {{ PATROL_LABELS[patrolDiff.patrol_status ?? ''] ?? patrolDiff.patrol_status ?? '未巡检' }}
            </el-tag>
            <span class="muted">当前版本 {{ patrolDiff.version }}</span>
            <span v-if="patrolDiff.patrol_checked_at" class="muted">
              巡检于 {{ patrolDiff.patrol_checked_at }}
            </span>
          </div>

          <template v-if="patrolDiff.available">
            <div class="diff-metrics">
              <div class="metric">
                <div class="metric-label">内容保留率（批准版在线上）</div>
                <div class="metric-value similarity">{{ similarityText(patrolDiff.similarity) }}</div>
              </div>
              <div class="metric">
                <div class="metric-label">关键数字缺失</div>
                <div class="metric-value">
                  <template v-if="patrolDiff.missing_numbers.length">
                    <el-tag
                      v-for="num in patrolDiff.missing_numbers"
                      :key="num"
                      type="danger"
                      size="small"
                      effect="dark"
                      class="missing-num"
                    >
                      {{ num }}
                    </el-tag>
                  </template>
                  <span v-else class="ok-text">无（关键数字齐全）</span>
                </div>
              </div>
            </div>

            <div class="block-title">
              变更片段（{{ patrolDiff.change_count }} 处<span v-if="patrolDiff.change_count > patrolDiff.changes.length">
                ，展示前 {{ patrolDiff.changes.length }} 处</span>）
            </div>
            <div v-if="patrolDiff.changes.length" class="diff-list">
              <div v-for="change in patrolDiff.changes" :key="change.change_id" class="diff-item">
                <div class="diff-item-head">
                  {{ CHANGE_LABELS[change.change_type] ?? change.change_type }}
                </div>
                <div v-if="change.old_text" class="diff-block diff-old">
                  <span class="diff-tag">批准版</span>
                  <span class="diff-text">{{ change.old_text }}</span>
                </div>
                <div v-if="change.new_text" class="diff-block diff-new">
                  <span class="diff-tag">线上版</span>
                  <span class="diff-text">{{ change.new_text }}</span>
                </div>
              </div>
            </div>
            <el-empty
              v-else
              description="无文本块级变更（差异可能仅在空白或标点）"
              :image-size="60"
            />

            <div class="diff-foot">
              <span v-if="patrolDiff.online_archived_at" class="muted">
                线上快照存档于 {{ patrolDiff.online_archived_at }}
              </span>
              <el-button
                v-if="patrolDiff.review_task_id"
                type="primary"
                size="small"
                @click="goReviewTask(patrolDiff.review_task_id)"
              >
                查看复审任务 #{{ patrolDiff.review_task_id }}
              </el-button>
            </div>
          </template>

          <el-alert
            v-else
            :title="patrolDiff.reason ?? '暂无线上快照可对比'"
            type="info"
            :closable="false"
            show-icon
          />
        </template>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
defineOptions({ name: 'material-ledger' })
import { onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import {
  createMaterial,
  getPatrolDiff,
  listMaterials,
  patrolMaterials,
  updateMaterial,
} from '@/api/impact'
import { useAuthStore } from '@/stores/auth'
import {
  buildMaterialQuery,
  parseMaterialFilters,
  type MaterialFilters,
} from '@/utils/materialFilters'
import { CHANGE_LABELS, similarityText } from '@/utils/patrolDiff'
import type { MaterialLedger, PatrolDiff } from '@/types/impact'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const PRODUCT_LABELS: Record<string, string> = { fund: '基金', insurance: '保险', wealth: '银行理财' }
const REVIEW_LABELS: Record<string, string> = { violation: '违规', clean: '干净', failed: '失败' }
const REVIEW_TAG: Record<string, string> = { violation: 'danger', clean: 'success', failed: 'warning' }

/** R3-1 巡检结论的呈现语义：对网页导航/页脚噪声免疫的 containment 判定 + 关键数字校验 */
const PATROL_LABELS: Record<string, string> = {
  ok: '与批准版一致',
  drift: '轻微漂移',
  changed: '已变更',
  gone: '已失联',
  error: '巡检异常',
}
const PATROL_TAG: Record<string, string> = {
  ok: 'success',
  drift: 'warning',
  changed: 'danger',
  gone: 'danger',
  error: 'info',
}
const PATROL_TIP: Record<string, string> = {
  ok: '线上内容与批准版一致（containment ≥0.98）',
  drift: '个别文字漂移但关键数字齐全，建议关注',
  changed: '关键数字缺失或内容实质变更，已自动创建复审任务',
  gone: '页面已下线（HTTP 404/410）',
  error: '抓取失败（网络/超时），需人工检查',
}
const patrollingId = ref<number | null>(null)

// ---------- 巡检差异抽屉（批准版 vs 线上快照） ----------
const patrolDrawerVisible = ref(false)
const patrolDiffLoading = ref(false)
const patrolDiff = ref<PatrolDiff | null>(null)

async function openPatrolDiff(row: MaterialLedger) {
  patrolDrawerVisible.value = true
  patrolDiffLoading.value = true
  patrolDiff.value = null
  try {
    patrolDiff.value = await getPatrolDiff(row.id)
  } catch {
    // 拦截器已提示；抽屉保留为空态
  } finally {
    patrolDiffLoading.value = false
  }
}

function goReviewTask(taskId: number) {
  patrolDrawerVisible.value = false
  router.push(`/tasks/${taskId}`)
}

const rows = ref<MaterialLedger[]>([])
const loading = ref(false)
const total = ref(0)
const page = ref(1)
const pageSize = 20
const filterProduct = ref('')
const filterStatus = ref('')
const filterReview = ref('')
const filterPatrol = ref('')

const dialogVisible = ref(false)
const submitting = ref(false)
const editing = ref<MaterialLedger | null>(null)
const form = ref({
  name: '',
  product_type: 'fund' as 'fund' | 'insurance' | 'wealth',
  material_type: '',
  version: 'v1',
  owner: '',
  document_id: '',
  channel: '',
  publish_url: '',
})

let loadSeq = 0

/** 当前筛选态（与 URL query 双向映射，见 utils/materialFilters） */
function currentFilters(): MaterialFilters {
  return {
    product: filterProduct.value,
    status: filterStatus.value,
    review: filterReview.value,
    patrol: filterPatrol.value,
  }
}

/**
 * 筛选器变更统一入口：重载 + 同步 URL（replace 不产生历史记录；
 * 全空时 query 清空，URL 保持干净）。
 */
function applyFilters() {
  router.replace({ query: buildMaterialQuery(currentFilters()) })
  reload()
}

function reload() {
  page.value = 1
  load()
}

async function load() {
  const mySeq = ++loadSeq
  loading.value = true
  try {
    const data = await listMaterials({
      page: page.value,
      page_size: pageSize,
      product_type: filterProduct.value || undefined,
      status: filterStatus.value || undefined,
      last_review_status: filterReview.value || undefined,
      patrol_status: filterPatrol.value || undefined,
    })
    if (mySeq !== loadSeq) return
    rows.value = data.items
    total.value = data.total
  } finally {
    if (mySeq === loadSeq) loading.value = false
  }
}

function onPageChange(next: number) {
  page.value = next
  load()
}

/** 台账 → 审查打通：携带已关联文档直达新建审查（跳过上传步骤） */
function startReview(row: MaterialLedger) {
  router.push({
    path: '/tasks/new',
    query: { document_id: row.document_id as string, material: row.name },
  })
}

function openCreate() {
  editing.value = null
  form.value = { name: '', product_type: 'fund', material_type: '', version: 'v1', owner: '', document_id: '', channel: '', publish_url: '' }
  dialogVisible.value = true
}

function openEdit(row: MaterialLedger) {
  editing.value = row
  form.value = {
    name: row.name,
    product_type: row.product_type as 'fund' | 'insurance' | 'wealth',
    material_type: row.material_type,
    version: row.version,
    owner: row.owner ?? '',
    document_id: row.document_id ?? '',
    channel: row.channel ?? '',
    publish_url: row.publish_url ?? '',
  }
  dialogVisible.value = true
}

async function onSubmit() {
  if (!form.value.name || !form.value.material_type) {
    ElMessage.warning('请填写材料名称与材料类型')
    return
  }
  submitting.value = true
  try {
    const body = {
      ...form.value,
      owner: form.value.owner || undefined,
      document_id: form.value.document_id || undefined,
      version: form.value.version || 'v1',
      channel: form.value.channel || undefined,
      publish_url: form.value.publish_url || undefined,
    }
    if (editing.value) {
      await updateMaterial(editing.value.id, {
        name: body.name,
        version: body.version,
        owner: body.owner,
        document_id: body.document_id,
        channel: body.channel,
        publish_url: body.publish_url,
      })
    } else {
      await createMaterial(body)
    }
    ElMessage.success(editing.value ? '已更新' : '已新增')
    dialogVisible.value = false
    load()
  } catch {
    // 拦截器已提示
  } finally {
    submitting.value = false
  }
}

/** 单材料巡检：抓取线上内容与批准版比对；changed 时后端已自动创建复审任务 */
async function patrolOne(row: MaterialLedger) {
  patrollingId.value = row.id
  try {
    const data = await patrolMaterials([row.id])
    const outcome = data.outcomes[0]
    if (!outcome) {
      ElMessage.warning('巡检未执行（材料可能未登记发布地址）')
      return
    }
    if (outcome.status === 'changed') {
      ElMessage.warning(`线上内容已变更，已自动创建复审任务（${outcome.detail ?? ''}）`)
    } else if (outcome.status === 'gone') {
      ElMessage.error(`页面已失联：${outcome.detail ?? 'HTTP 404/410'}`)
    } else if (outcome.status === 'error') {
      ElMessage.error(`巡检异常：${outcome.detail ?? ''}`)
    } else if (outcome.status === 'drift') {
      ElMessage.warning('线上内容有轻微漂移，关键数字齐全，建议关注')
    } else {
      ElMessage.success('线上内容与批准版一致')
    }
    await load()
    // 变更/失联是需人工介入的结论：直接打开差异抽屉（drift/ok 不打扰）
    if (outcome.status === 'changed' || outcome.status === 'gone') {
      void openPatrolDiff(row)
    }
  } catch {
    // 拦截器已提示
  } finally {
    patrollingId.value = null
  }
}

async function toggleArchive(row: MaterialLedger) {
  await updateMaterial(row.id, { status: row.status === 'active' ? 'archived' : 'active' })
  ElMessage.success(row.status === 'active' ? '已归档' : '已恢复在用')
  load()
}

// 初始化：URL query（含 ?filter=patrol_changed 下钻别名）→ 筛选态 → 加载
onMounted(() => {
  const initial = parseMaterialFilters(route.query)
  filterProduct.value = initial.product
  filterStatus.value = initial.status
  filterReview.value = initial.review
  filterPatrol.value = initial.patrol
  void load()
})

// 浏览器前进/后退或外部链接变更：以 URL 为准同步筛选态（值相同则短路，
// 避免与 applyFilters 的 replace 形成循环）
watch(
  () => route.query,
  (query) => {
    const next = parseMaterialFilters(query)
    const cur = currentFilters()
    if (
      next.product === cur.product &&
      next.status === cur.status &&
      next.review === cur.review &&
      next.patrol === cur.patrol
    ) {
      return
    }
    filterProduct.value = next.product
    filterStatus.value = next.status
    filterReview.value = next.review
    filterPatrol.value = next.patrol
    reload()
  },
)
</script>

<style scoped>
.filter-bar {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
}
.pager {
  margin-top: 12px;
  display: flex;
  justify-content: flex-end;
}
.patrol-tag {
  cursor: pointer;
}
.patrol-diff-link {
  margin-left: 6px;
  padding: 0;
}
.patrol-none {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

/* ---------- 巡检差异抽屉 ---------- */
.patrol-diff-body {
  min-height: 200px;
}
.diff-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
}
.muted {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.diff-metrics {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin-bottom: 16px;
}
.metric {
  border: 1px solid var(--app-border-light, var(--el-border-color-lighter));
  border-radius: 6px;
  padding: 10px 12px;
}
.metric-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-bottom: 6px;
}
.metric-value {
  font-size: 14px;
  font-weight: 600;
}
.metric-value.similarity {
  font-size: 20px;
  color: var(--el-color-warning);
}
.missing-num {
  margin-right: 6px;
}
.ok-text {
  color: var(--el-color-success);
  font-weight: 500;
}
.block-title {
  font-size: 13px;
  font-weight: 600;
  margin: 14px 0 8px;
}
.diff-item {
  border: 1px solid var(--app-border-light, var(--el-border-color-lighter));
  border-radius: 6px;
  margin-bottom: 10px;
  overflow: hidden;
}
.diff-item-head {
  font-size: 12px;
  padding: 4px 10px;
  background: var(--el-fill-color-light);
  color: var(--el-text-color-secondary);
}
.diff-block {
  display: flex;
  gap: 8px;
  padding: 8px 10px;
  font-size: 13px;
  line-height: 1.6;
}
.diff-block + .diff-block {
  border-top: 1px dashed var(--el-border-color-lighter);
}
.diff-old {
  background: var(--el-fill-color-lighter);
}
.diff-new {
  background: var(--el-color-danger-light-9);
}
.diff-tag {
  flex: none;
  font-size: 11px;
  color: var(--el-text-color-secondary);
  padding-top: 2px;
}
.diff-text {
  word-break: break-all;
}
.diff-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px solid var(--el-border-color-lighter);
}
</style>
