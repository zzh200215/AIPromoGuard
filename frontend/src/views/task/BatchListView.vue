<template>
  <div class="app-page">
    <PageHeader
      title="批量审查"
      description="一次上传多份材料批量送审，每个文件生成独立审查任务，完成后可导出报告压缩包"
    />

    <!-- 发起批次 -->
    <el-card>
      <template #header>
        <span class="card-title">发起批量审查</span>
      </template>
      <div class="upload-row">
        <el-upload
          multiple
          :auto-upload="false"
          :limit="20"
          :accept="'.pdf,.doc,.docx,.txt,.png,.jpg,.jpeg,.bmp'"
          :on-change="onFilesChange"
          :file-list="fileList"
          class="upload-control"
        >
          <el-button type="primary" plain :icon="Upload">选择文件（最多 20 份）</el-button>
        </el-upload>
        <template v-if="fileList.length">
          <el-input
            v-model="batchName"
            placeholder="批次名称（默认 批量审查）"
            style="width: 260px"
          />
          <el-button type="primary" :loading="creating" @click="submitBatch">
            创建批次并审查
          </el-button>
        </template>
      </div>
    </el-card>

    <!-- 批次列表 -->
    <el-card>
      <template #header>
        <span class="card-title">历史批次</span>
      </template>
      <el-table :data="items" v-loading="loading" @row-click="goDetail">
        <el-table-column prop="batch_name" label="批次名称" min-width="200" show-overflow-tooltip />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <TaskStatusTag :status="row.status" />
          </template>
        </el-table-column>
        <el-table-column label="进度" min-width="160">
          <template #default="{ row }">
            <el-progress
              :percentage="row.total_count ? Math.round((row.completed_count / row.total_count) * 100) : 0"
              :stroke-width="6"
            />
          </template>
        </el-table-column>
        <el-table-column prop="total_count" label="总数" width="70" align="center" />
        <el-table-column prop="completed_count" label="完成" width="70" align="center" />
        <el-table-column label="失败" width="70" align="center">
          <template #default="{ row }">
            <span :class="{ 'fail-count': row.failed_count > 0 }">{{ row.failed_count }}</span>
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
defineOptions({ name: 'batch-list' })
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

function goDetail(row: BatchOut) {
  router.push(`/batches/${row.id}`)
}

onMounted(load)
</script>

<style scoped lang="scss">
.card-title {
  font-size: 14px;
  font-weight: 600;
}

.upload-row {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  flex-wrap: wrap;
}

.upload-control :deep(.el-upload-list) {
  width: 100%;
  max-height: 120px;
  overflow: auto;
  margin-top: 4px;
}

table :deep(.el-table__row) {
  cursor: pointer;
}

.fail-count {
  color: var(--el-color-danger);
  font-weight: 600;
}
</style>
