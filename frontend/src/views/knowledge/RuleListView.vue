<template>
  <div>
    <PageHeader title="规则库">
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

      <el-table :data="rows" border v-loading="loading">
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
        <el-table-column label="启用" width="80">
          <template #default="{ row }">
            <el-switch
              v-if="auth.hasPermission('manage_rules')"
              :model-value="row.is_active === 1"
              @change="toggleActive(row)"
            />
            <el-tag v-else size="small" :type="row.is_active === 1 ? 'success' : 'info'">
              {{ row.is_active === 1 ? '启用' : '停用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="version" label="版本" width="70" />
        <el-table-column label="操作" width="230" fixed="right">
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
import { onMounted, ref } from 'vue'
import { deleteRule, draftRuleVersion, listRules, publishRule, updateRule } from '@/api/rules'
import { DOMAIN_OPTIONS, RULE_TYPE_LABELS } from '@/constants/enums'
import { useAuthStore } from '@/stores/auth'
import type { Rule } from '@/types/rule'

const auth = useAuthStore()

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
</style>
