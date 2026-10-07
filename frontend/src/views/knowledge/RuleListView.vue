<template>
  <div>
    <PageHeader
      title="规则库"
      description="规则引擎的字面红线规则：支持版本化发布与启停，命中结果在审查报告中直接采信"
    >
      <el-button v-if="auth.hasPermission('manage_rules')" type="primary" @click="openCreate">
        新增规则
      </el-button>
    </PageHeader>

    <el-card>
      <div class="filter-bar">
        <el-select
          v-model="filterDomain"
          placeholder="领域"
          clearable
          style="width: 140px"
          @change="reload"
        >
          <el-option
            v-for="d in DOMAIN_OPTIONS"
            :key="d.value"
            :label="d.label"
            :value="d.value"
          />
        </el-select>
        <el-select
          v-model="filterActive"
          placeholder="启用状态"
          clearable
          style="width: 140px"
          @change="reload"
        >
          <el-option label="启用" :value="1" />
          <el-option label="停用" :value="0" />
        </el-select>
      </div>

      <el-table :data="rows">
        <el-table-column prop="rule_name" label="规则名称" min-width="200" show-overflow-tooltip />
        <el-table-column label="领域" width="100">
          <template #default="{ row }">
            {{ (DOMAIN_LABELS as Record<string, string>)[row.domain] ?? row.domain }}
          </template>
        </el-table-column>
        <el-table-column label="类型" width="90">
          <template #default="{ row }">
            <el-tag size="small" type="info">{{ RULE_TYPE_LABELS[row.rule_type] }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="严重度" width="90">
          <template #default="{ row }"><SeverityTag :severity="row.severity" /></template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="RULE_STATUS_TAG[row.status ?? 'active'] ?? 'success'">
              {{ RULE_STATUS_LABELS[row.status ?? 'active'] ?? row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="复核质量" width="150">
          <template #default="{ row }">
            <template v-if="qualityMap[row.id]">
              <div class="quality-cell">
                <el-tag
                  size="small"
                  effect="light"
                  :type="fpTagType(qualityMap[row.id].false_positive_rate)"
                >
                  误报 {{ (qualityMap[row.id].false_positive_rate * 100).toFixed(0) }}%
                </el-tag>
                <span class="quality-sub">复核 {{ qualityMap[row.id].confirmed + qualityMap[row.id].false_positive }} 条</span>
              </div>
              <el-tooltip
                v-if="suggestionMap[row.id]"
                :content="`精调建议：${SUGGEST_LABEL[suggestionMap[row.id].action]} — ${suggestionMap[row.id].reason}`"
                placement="top"
              >
                <el-button
                  size="small"
                  type="warning"
                  link
                  @click="router.push('/admin/feedback')"
                >
                  有精调建议
                </el-button>
              </el-tooltip>
            </template>
            <span v-else class="quality-empty">—</span>
          </template>
        </el-table-column>
        <el-table-column label="启用" width="110">
          <template #default="{ row }">
            <el-switch
              v-if="auth.hasPermission('manage_rules') && row.status === 'active'"
              :model-value="row.is_active === 1"
              @change="toggleActive(row)"
            />
            <el-tooltip
              v-else-if="auth.hasPermission('manage_rules')"
              content="草稿/待复核规则须发布后才生效"
              placement="top"
            >
              <el-tag size="small" type="info">未发布</el-tag>
            </el-tooltip>
            <el-tag v-else size="small" :type="row.is_active === 1 ? 'success' : 'info'">
              {{ row.is_active === 1 ? '启用' : '停用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="version" label="版本" width="70" />
        <el-table-column label="操作" width="300" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="auth.hasPermission('manage_rules') && row.status !== 'draft' && row.status !== 'pending_review'"
              size="small"
              type="primary"
              link
              @click="onDraftVersion(row)"
            >
              新版本
            </el-button>
            <el-button
              v-if="auth.hasPermission('manage_rules') && (row.status === 'draft' || row.status === 'pending_review')"
              size="small"
              type="success"
              link
              @click="onPublish(row)"
            >
              发布
            </el-button>
            <el-button
              v-if="auth.hasPermission('manage_rules') && row.status === 'active'"
              size="small"
              type="warning"
              link
              @click="onRereview(row)"
            >
              重审历史
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
              type="danger"
              link
              @click="onDelete(row)"
            >
              删除
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

    <RuleEditorDialog v-model="dialogVisible" :rule="editingRule" @submitted="load" />
  </div>
</template>

<script setup lang="ts">
defineOptions({ name: 'rule-list' })
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  deleteRule,
  draftRuleVersion,
  listRules,
  publishRule,
  rereviewRule,
  updateRule,
} from '@/api/rules'
import { listRuleSuggestions, rulesQuality } from '@/api/results'
import { DOMAIN_LABELS, DOMAIN_OPTIONS, RULE_TYPE_LABELS } from '@/constants/enums'
import { useAuthStore } from '@/stores/auth'
import type { Rule } from '@/types/rule'
import type { RuleQualityItem, RuleSuggestion } from '@/types/result'

const auth = useAuthStore()
const router = useRouter()

const RULE_STATUS_LABELS: Record<string, string> = {
  draft: '草稿',
  pending_review: '待复核',
  active: '生效',
}
const RULE_STATUS_TAG: Record<string, string> = {
  draft: 'info',
  pending_review: 'warning',
  active: 'success',
}

const rows = ref<Rule[]>([])
const loading = ref(false)
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const filterDomain = ref('')
const filterActive = ref<number | ''>('')

const dialogVisible = ref(false)
const editingRule = ref<Rule | null>(null)

// ---- 复核质量列：误报率/精调建议（数据来自反馈闭环统计，无复核数据时显示 —）----
const qualityMap = ref<Record<number, RuleQualityItem>>({})
const suggestionMap = ref<Record<number, RuleSuggestion>>({})
const SUGGEST_LABEL: Record<string, string> = {
  deactivate: '停用规则',
  remove_keyword: '移除关键词',
  set_threshold: '抬高阈值',
}

function fpTagType(rate: number) {
  if (rate >= 0.5) return 'danger'
  if (rate >= 0.2) return 'warning'
  return 'success'
}

async function loadQuality() {
  if (!auth.hasPermission('view_report')) return
  try {
    const [quality, suggestions] = await Promise.all([rulesQuality(), listRuleSuggestions()])
    qualityMap.value = Object.fromEntries(quality.items.map((q) => [q.rule_id, q]))
    suggestionMap.value = Object.fromEntries(suggestions.items.map((s) => [s.rule_id, s]))
  } catch {
    // 质量列是辅助信息，加载失败不阻断规则列表
  }
}

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
    const res = await listRules({
      page: page.value,
      page_size: pageSize.value,
      domain: filterDomain.value || undefined,
      is_active: filterActive.value === '' ? undefined : filterActive.value === 1,
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

function openCreate() {
  editingRule.value = null
  dialogVisible.value = true
}

function openEdit(row: Rule) {
  editingRule.value = row
  dialogVisible.value = true
}

async function toggleActive(row: Rule) {
  const next = row.is_active === 1 ? 0 : 1
  try {
    await updateRule(row.id, { is_active: next === 1 })
    row.is_active = next
    ElMessage.success(next === 1 ? '已启用' : '已停用')
  } catch {
    // 拦截器已提示
  }
}

async function onDelete(row: Rule) {
  const ok = await ElMessageBox.confirm(`确定删除规则「${row.rule_name}」？`, '删除确认', {
    type: 'warning',
    confirmButtonText: '删除',
    cancelButtonText: '取消',
  }).catch(() => false)
  if (!ok) return
  try {
    await deleteRule(row.id)
    ElMessage.success('已删除')
    load()
  } catch {
    // 拦截器已提示
  }
}

async function onDraftVersion(row: Rule) {
  try {
    const draft = await draftRuleVersion(row.id)
    ElMessage.success(`已起草 v${draft.version} 草稿，编辑后点击发布生效`)
    load()
  } catch {
    // 拦截器已提示
  }
}

async function onPublish(row: Rule) {
  const ok = await ElMessageBox.confirm(
    `发布「${row.rule_name}」v${row.version}？同名旧版本将自动停用。`,
    '发布确认',
    { type: 'warning', confirmButtonText: '发布', cancelButtonText: '取消' },
  ).catch(() => false)
  if (!ok) return
  try {
    const res = await publishRule(row.id)
    const note =
      res.superseded_rule_ids.length > 0 ? `，旧版本 ${res.superseded_rule_ids.join('、')} 已停用` : ''
    ElMessage.success(`已发布生效${note}`)
    load()
  } catch {
    // 拦截器已提示
  }
}

/** 规则重审：用当前规则集重跑历史上命中过该规则的任务，生成重审批次 */
async function onRereview(row: Rule) {
  const ok = await ElMessageBox.confirm(
    `将用当前生效规则集重跑历史上命中过「${row.rule_name}」的任务，并生成一个重审批次（原文档已删除的任务会跳过）。继续？`,
    '规则重审确认',
    { type: 'warning', confirmButtonText: '发起重审', cancelButtonText: '取消' },
  ).catch(() => false)
  if (!ok) return
  try {
    const res = await rereviewRule(row.id)
    const skipNote = res.skipped.length > 0 ? `，跳过 ${res.skipped.length} 个（文档缺失）` : ''
    await ElMessageBox.alert(
      `已创建重审批次「${res.batch_name}」：${res.total_count} 个任务${skipNote}。`,
      '重审已发起',
      { confirmButtonText: '查看批次' },
    )
    router.push(`/batches/${res.batch_id}`)
  } catch {
    // 拦截器已提示
  }
}

onMounted(() => {
  load()
  loadQuality()
})
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

.quality-cell {
  display: flex;
  align-items: center;
  gap: 6px;
}

.quality-sub {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.quality-empty {
  color: var(--el-text-color-placeholder);
}

</style>
