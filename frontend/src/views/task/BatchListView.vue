<template>
  <div>
    <PageHeader title="批量审查" />

    <el-card>
      <template #header>
        <div class="batch-header">
          <span class="batch-title">批次列表</span>
          <el-upload
            multiple
            :auto-upload="false"
            :limit="20"
            :accept="'.pdf,.doc,.docx,.txt,.png,.jpg,.jpeg,.bmp'"
            :on-change="onFilesChange"
            :file-list="fileList"
          >
            <el-button type="primary" :icon="Upload">选择文件（最多 20 份）</el-button>
          </el-upload>
        </div>
      </template>

      <div v-if="fileList.length" class="pick-actions">
        <el-input
          v-model="batchName"
          placeholder="批次名称（默认 批量审查）"
          style="width: 320px"
        />
        <el-button type="success" :loading="creating" @click="submitBatch">
          创建批次并审查
        </el-button>
      </div>

      <el-table :data="items" v-loading="loading" border>
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column prop="batch_name" label="批次名称" min-width="160" show-overflow-tooltip />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <TaskStatusTag :status="row.status" />
          </template>
        </el-table-column>
        <el-table-column prop="total_count" label="总数" width="70" />
        <el-table-column prop="completed_count" label="完成" width="70" />
        <el-table-column prop="failed_count" label="失败" width="70" />
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button link type="primary" @click="router.push(`/batches/${row.id}`)">
              详情
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
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Upload } from '@element-plus/icons-vue'
import type { UploadFile, UploadFiles } from 'element-plus'
import { createBatch, listBatches } from '@/api/batches'
import type { BatchOut } from '@/types/batch'

const router = useRouter()

const items = ref<BatchOut[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)

const fileList = ref<UploadFile[]>([])
const batchName = ref('')
const creating = ref(false)

/** el-upload on-change 签名 (uploadFile, uploadFiles)；文件被移除时同样会触发，取完整列表 */
function onFilesChange(_file: UploadFile, files: UploadFiles) {
  fileList.value = files
}

async function submitBatch() {
  if (!fileList.value.length || creating.value) return
  creating.value = true
  try {
    const raws = fileList.value.map((f) => f.raw).filter((f): f is File => !!f)
    if (!raws.length) {
      ElMessage.warning('未读取到有效文件，请重新选择')
      return
    }
    const res = await createBatch(raws, batchName.value || '批量审查')
    ElMessage.success(`批次已创建，共 ${res.total_count} 个任务`)
    fileList.value = []
    batchName.value = ''
    router.push(`/batches/${res.batch_id}`)
  } catch {
    // 拦截器已提示
  } finally {
    creating.value = false
  }
}

async function load() {
  loading.value = true
  try {
    const res = await listBatches({ page: page.value, page_size: pageSize.value })
    items.value = res.items
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

onMounted(load)
</script>

<style scoped>
.batch-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.batch-title {
  font-size: 14px;
  font-weight: 600;
}

.pick-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}
</style>
