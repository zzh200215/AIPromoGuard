<template>
  <div>
    <PageHeader title="监管动态">
      <el-button
        v-if="auth.hasPermission('manage_regulations')"
        type="primary"
        :loading="fetching"
        @click="onFetch"
      >
        立即抓取
      </el-button>
      <el-button v-if="auth.hasPermission('manage_regulations')" @click="openManual">
        手动录入
      </el-button>
    </PageHeader>

    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="轮询三家监管机构发布源，发现新法规进待确认列表；确认后写入法规库（条款需在法规库补充）"
      style="margin-bottom: 12px"
    />

    <el-card>
      <div class="filter-bar">
        <el-select
          v-model="filterSource"
          placeholder="来源"
          clearable
          style="width: 150px"
          @change="reload"
        >
          <el-option
            v-for="(label, val) in SOURCE_LABELS"
            :key="val"
            :label="label"
            :value="val"
          />
        </el-select>
        <el-select
          v-model="filterStatus"
          placeholder="状态"
          clearable
          style="width: 140px"
          @change="reload"
        >
          <el-option
            v-for="(label, val) in STATUS_LABELS"
            :key="val"
            :label="label"
            :value="val"
          />
        </el-select>
        <el-button type="primary" @click="load">查询</el-button>
      </div>

      <el-table :data="rows" border v-loading="loading">
        <el-table-column label="来源" width="110">
          <template #default="{ row }">
            {{ SOURCE_LABELS[row.source] ?? row.source }}
          </template>
        </el-table-column>
        <el-table-column prop="title" label="法规名称" min-width="240" show-overflow-tooltip />
        <el-table-column prop="doc_no" label="文号" min-width="140" show-overflow-tooltip />
        <el-table-column prop="publish_date" label="发布日期" width="110" />
        <el-table-column label="领域" width="90">
          <template #default="{ row }">
            <span v-if="row.domain">{{ DOMAIN_LABELS_EXT[row.domain] ?? row.domain }}</span>
            <span v-else class="muted">-</span>
          </template>
        </el-table-column>
        <el-table-column label="LLM 摘要" min-width="200" show-overflow-tooltip>
          <template #default="{ row }">
            <span v-if="row.llm_summary">{{ row.llm_summary }}</span>
            <span v-else class="muted">-</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="STATUS_TAG_TYPE[row.status]">
              {{ STATUS_LABELS[row.status] ?? row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="160" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="row.status === 'pending' && auth.hasPermission('manage_regulations')"
              size="small"
              type="primary"
              link
              @click="openConfirm(row)"
            >
              确认
            </el-button>
            <el-button
              v-if="row.status === 'pending' && auth.hasPermission('manage_regulations')"
              size="small"
              type="danger"
              link
              @click="onIgnore(row)"
            >
              忽略
            </el-button>
            <el-button
              v-if="row.url"
              size="small"
              link
              @click="openUrl(row.url)"
            >
              原文
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

    <!-- 确认入库弹窗 -->
    <el-dialog v-model="confirmVisible" title="确认入库" width="560px">
      <template v-if="confirmRow">
        <el-descriptions :column="1" border size="small" class="confirm-desc">
          <el-descriptions-item label="法规名称">{{ confirmRow.title }}</el-descriptions-item>
          <el-descriptions-item v-if="confirmRow.doc_no" label="文号">
            {{ confirmRow.doc_no }}
          </el-descriptions-item>
          <el-descriptions-item label="LLM 摘要">
            {{ confirmRow.llm_summary || '-' }}
          </el-descriptions-item>
        </el-descriptions>

        <el-form :model="confirmForm" label-width="90px" style="margin-top: 14px">
          <el-form-item label="领域">
            <el-select v-model="confirmForm.domain" placeholder="选择领域" style="width: 200px">
              <el-option
                v-for="(label, val) in DOMAIN_LABELS_EXT"
                :key="val"
                :label="label"
                :value="val"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="生效日期">
            <el-date-picker
              v-model="confirmForm.effective_date"
              type="date"
              value-format="YYYY-MM-DD"
              placeholder="可选"
              style="width: 200px"
            />
          </el-form-item>
        </el-form>

        <div v-if="confirmRow.matched_regulations?.length" class="match-block">
          <div class="match-title">可能关联的已入库法规：</div>
          <el-tag
            v-for="m in confirmRow.matched_regulations"
            :key="m.regulation_id"
            class="match-tag"
            size="small"
            type="info"
            @click="router.push(`/knowledge/regulations/${m.regulation_id}`)"
          >
            {{ m.regulation_name }}{{ m.article_no ? ` ${m.article_no}` : '' }}
          </el-tag>
        </div>
      </template>

      <template #footer>
        <el-button @click="confirmVisible = false">取消</el-button>
        <el-button type="primary" :loading="confirming" @click="doConfirm">
          确认入库
        </el-button>
      </template>
    </el-dialog>

    <!-- 手动录入弹窗 -->
    <el-dialog v-model="manualVisible" title="手动录入法规" width="520px">
      <el-form :model="manualForm" label-width="80px">
        <el-form-item label="来源" required>
          <el-select v-model="manualForm.source" style="width: 200px">
            <el-option
              v-for="(label, val) in SOURCE_LABELS"
              :key="val"
              :label="label"
              :value="val"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="名称" required>
          <el-input v-model="manualForm.title" placeholder="法规名称（含文号更佳）" />
        </el-form-item>
        <el-form-item label="文号">
          <el-input v-model="manualForm.doc_no" placeholder="如：银保监规〔2023〕1号" />
        </el-form-item>
        <el-form-item label="原文链接">
          <el-input v-model="manualForm.url" placeholder="https://..." />
        </el-form-item>
        <el-form-item label="发布日期">
          <el-date-picker
            v-model="manualForm.publish_date"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="可选"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="manualVisible = false">取消</el-button>
        <el-button type="primary" :loading="savingManual" @click="doManual">提交</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  confirmRegulationTrend,
  createRegulationTrend,
  fetchRegulationTrends,
  ignoreRegulationTrend,
  listRegulationTrends,
} from '@/api/regulationTrend'
import { useAuthStore } from '@/stores/auth'
import type { RegulationUpdate } from '@/types/regulationTrend'

const router = useRouter()
const auth = useAuthStore()

const SOURCE_LABELS: Record<string, string> = {
  nfra: '金融监管总局',
  csrc: '证监会',
  pbc: '人民银行',
}

const DOMAIN_LABELS_EXT: Record<string, string> = {
  banking: '银行理财',
  fund: '基金销售',
  insurance: '保险产品',
  wealth: '资管',
  other: '其他',
}

const STATUS_LABELS: Record<string, string> = {
  pending: '待确认',
  imported: '已入库',
  ignored: '已忽略',
  in_db: '已在库',
}

const STATUS_TAG_TYPE: Record<string, 'warning' | 'success' | 'info' | 'primary'> = {
  pending: 'warning',
  imported: 'success',
  ignored: 'info',
  in_db: 'primary',
}

const rows = ref<RegulationUpdate[]>([])
const loading = ref(false)
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const filterSource = ref('')
const filterStatus = ref('')
const fetching = ref(false)

const confirmVisible = ref(false)
const confirming = ref(false)
const confirmRow = ref<RegulationUpdate | null>(null)
const confirmForm = reactive<{ domain?: string; effective_date?: string }>({})

const manualVisible = ref(false)
const savingManual = ref(false)
const manualForm = reactive<{
  source: string
  title: string
  doc_no?: string
  url?: string
  publish_date?: string
}>({ source: 'nfra', title: '' })

/** 筛选条件变化:回到第 1 页,避免高页码+新筛选请求越界页 */
function reload() {
  page.value = 1
  load()
}

// 请求序号守卫：快速切换筛选时丢弃过期响应，避免旧结果覆盖新结果
let loadSeq = 0

async function load() {
  const mySeq = ++loadSeq
  loading.value = true
  try {
    const res = await listRegulationTrends({
      page: page.value,
      page_size: pageSize.value,
      status: filterStatus.value || undefined,
      source: filterSource.value || undefined,
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

async function onFetch() {
  fetching.value = true
  try {
    const res = await fetchRegulationTrends()
    const lines = Object.entries(res.sources).map(
      ([name, s]) =>
        `${SOURCE_LABELS[name] ?? name}: 抓到 ${s.fetched}，新增 ${s.new}，重复 ${s.duplicate}，已在库 ${s.in_db}${s.error ? `（错误 ${s.error}）` : ''}`,
    )
    if (res.errors.length) lines.push(`失败源: ${res.errors.join('；')}`)
    await ElMessageBox.alert(lines.join('\n'), '抓取完成', { confirmButtonText: '好' })
    load()
  } catch {
    // 拦截器已提示
  } finally {
    fetching.value = false
  }
}

function openConfirm(row: RegulationUpdate) {
  confirmRow.value = row
  confirmForm.domain = row.domain || undefined
  confirmForm.effective_date = ''
  confirmVisible.value = true
}

async function doConfirm() {
  if (!confirmRow.value) return
  confirming.value = true
  try {
    await confirmRegulationTrend(confirmRow.value.id, {
      domain: confirmForm.domain,
      effective_date: confirmForm.effective_date || undefined,
    })
    ElMessage.success('已确认入库')
    confirmVisible.value = false
    load()
  } catch {
    // 拦截器已提示
  } finally {
    confirming.value = false
  }
}

async function onIgnore(row: RegulationUpdate) {
  const ok = await ElMessageBox.confirm(
    `确定忽略「${row.title}」？可后续重新抓取恢复。`,
    '忽略确认',
    { type: 'warning', confirmButtonText: '忽略', cancelButtonText: '取消' },
  ).catch(() => false)
  if (!ok) return
  try {
    await ignoreRegulationTrend(row.id)
    ElMessage.success('已忽略')
    load()
  } catch {
    // 拦截器已提示
  }
}

function openUrl(url: string) {
  window.open(url, '_blank')
}

function openManual() {
  manualForm.source = 'nfra'
  manualForm.title = ''
  manualForm.doc_no = ''
  manualForm.url = ''
  manualForm.publish_date = ''
  manualVisible.value = true
}

async function doManual() {
  if (!manualForm.title.trim()) {
    ElMessage.warning('请填写法规名称')
    return
  }
  savingManual.value = true
  try {
    await createRegulationTrend({
      source: manualForm.source as RegulationUpdate['source'],
      title: manualForm.title.trim(),
      doc_no: manualForm.doc_no || undefined,
      url: manualForm.url || undefined,
      publish_date: manualForm.publish_date || undefined,
    })
    ElMessage.success('已录入待确认列表')
    manualVisible.value = false
    load()
  } catch {
    // 拦截器已提示
  } finally {
    savingManual.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.filter-bar {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}

.muted {
  color: #c0c4cc;
}

.match-block {
  margin-top: 4px;
}

.match-title {
  font-size: 13px;
  color: #909399;
  margin-bottom: 6px;
}

.match-tag {
  margin: 2px 6px 2px 0;
  cursor: pointer;
}

.confirm-desc {
  margin-bottom: 4px;
}
</style>
