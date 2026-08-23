<template>
  <div>
    <PageHeader title="法规库">
      <el-button
        v-if="auth.hasPermission('manage_regulations')"
        type="primary"
        @click="openCreate"
      >
        新增法规
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
        <el-input
          v-model="filterKeyword"
          placeholder="法规名称 / 文号关键词"
          clearable
          style="width: 240px"
          @keyup.enter="load"
          @clear="load"
        />
        <el-button type="primary" @click="load">查询</el-button>
      </div>

      <el-table
        :data="rows"
        border
        v-loading="loading"
        class="reg-table"
        @row-click="goDetail"
      >
        <el-table-column
          prop="regulation_name"
          label="法规名称"
          min-width="240"
          show-overflow-tooltip
        />
        <el-table-column label="领域" width="110">
          <template #default="{ row }">
            {{ (DOMAIN_LABELS as Record<string, string>)[row.domain] ?? row.domain }}
          </template>
        </el-table-column>
        <el-table-column prop="regulation_no" label="文号" min-width="160" show-overflow-tooltip />
        <el-table-column prop="issuer" label="发布机关" min-width="160" show-overflow-tooltip />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag
              size="small"
              :type="
                row.status === 'effective'
                  ? 'success'
                  : row.status === 'amended'
                    ? 'warning'
                    : 'info'
              "
            >
              {{ REG_STATUS_LABELS[row.status] }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="auth.hasPermission('manage_regulations')"
              size="small"
              type="primary"
              link
              @click.stop="openEdit(row)"
            >
              编辑
            </el-button>
            <el-button
              v-if="auth.hasPermission('manage_regulations')"
              size="small"
              type="danger"
              link
              @click.stop="onDelete(row)"
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

    <RegulationFormDialog
      v-model="dialogVisible"
      :regulation="editingRegulation"
      @submitted="load"
    />
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { deleteRegulation, listRegulations } from '@/api/regulations'
import { DOMAIN_OPTIONS, REG_STATUS_LABELS } from '@/constants/enums'
import { useAuthStore } from '@/stores/auth'
import type { Regulation } from '@/types/regulation'

const router = useRouter()
const auth = useAuthStore()

const rows = ref<Regulation[]>([])
const loading = ref(false)
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const filterDomain = ref('')
const filterKeyword = ref('')

const dialogVisible = ref(false)
const editingRegulation = ref<Regulation | null>(null)

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
    const res = await listRegulations({
      page: page.value,
      page_size: pageSize.value,
      domain: filterDomain.value || undefined,
      keyword: filterKeyword.value || undefined,
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

function goDetail(row: Regulation) {
  router.push(`/knowledge/regulations/${row.id}`)
}

function openCreate() {
  editingRegulation.value = null
  dialogVisible.value = true
}

function openEdit(row: Regulation) {
  editingRegulation.value = row
  dialogVisible.value = true
}

async function onDelete(row: Regulation) {
  const ok = await ElMessageBox.confirm(
    `确定删除法规「${row.regulation_name}」？其下条款会一并删除。`,
    '删除确认',
    { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
  ).catch(() => false)
  if (!ok) return
  try {
    await deleteRegulation(row.id)
    ElMessage.success('已删除')
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

.reg-table :deep(.el-table__row) {
  cursor: pointer;
}

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}
</style>
