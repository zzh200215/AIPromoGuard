<template>
  <div>
    <PageHeader title="产品材料台账">
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
        <el-select v-model="filterProduct" placeholder="产品类型" clearable style="width: 150px" @change="reload">
          <el-option label="基金" value="fund" />
          <el-option label="保险" value="insurance" />
          <el-option label="银行理财" value="wealth" />
        </el-select>
        <el-select v-model="filterStatus" placeholder="台账状态" clearable style="width: 130px" @change="reload">
          <el-option label="在用" value="active" />
          <el-option label="已归档" value="archived" />
        </el-select>
        <el-select v-model="filterReview" placeholder="最近审查" clearable style="width: 150px" @change="reload">
          <el-option label="存在违规" value="violation" />
          <el-option label="干净" value="clean" />
          <el-option label="失败" value="failed" />
        </el-select>
      </div>

      <el-table :data="rows" border v-loading="loading">
        <el-table-column prop="id" label="ID" width="70" />
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
        <el-table-column label="操作" width="130" fixed="right">
          <template #default="{ row }">
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
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="onSubmit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { createMaterial, listMaterials, updateMaterial } from '@/api/impact'
import { useAuthStore } from '@/stores/auth'
import type { MaterialLedger } from '@/types/impact'

const auth = useAuthStore()

const PRODUCT_LABELS: Record<string, string> = { fund: '基金', insurance: '保险', wealth: '银行理财' }
const REVIEW_LABELS: Record<string, string> = { violation: '违规', clean: '干净', failed: '失败' }
const REVIEW_TAG: Record<string, string> = { violation: 'danger', clean: 'success', failed: 'warning' }

const rows = ref<MaterialLedger[]>([])
const loading = ref(false)
const total = ref(0)
const page = ref(1)
const pageSize = 20
const filterProduct = ref('')
const filterStatus = ref('')
const filterReview = ref('')

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
})

let loadSeq = 0

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

function openCreate() {
  editing.value = null
  form.value = { name: '', product_type: 'fund', material_type: '', version: 'v1', owner: '', document_id: '' }
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
    }
    if (editing.value) {
      await updateMaterial(editing.value.id, {
        name: body.name,
        version: body.version,
        owner: body.owner,
        document_id: body.document_id,
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

async function toggleArchive(row: MaterialLedger) {
  await updateMaterial(row.id, { status: row.status === 'active' ? 'archived' : 'active' })
  ElMessage.success(row.status === 'active' ? '已归档' : '已恢复在用')
  load()
}

onMounted(load)
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
</style>
