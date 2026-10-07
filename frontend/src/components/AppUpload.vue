<template>
  <div>
    <el-upload
      drag
      :auto-upload="false"
      :limit="1"
      :accept="'.pdf,.docx,.txt,.pptx,.xlsx,.png,.jpg,.jpeg,.bmp'"
      :on-change="onChange"
      :on-remove="onRemove"
    >
      <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
      <div class="el-upload__text">拖拽文件到此处，或<em>点击选择</em></div>
      <template #tip>
        <div class="el-upload__tip">
          支持 pdf / docx / txt / ppt / excel（xlsx）/ 图片，不超过 50MB；旧版 .doc/.xls 请先另存为新格式
        </div>
      </template>
    </el-upload>

    <div v-if="documentId" class="upload-result">
      <el-tag type="success" :closable="false">
        <el-icon><CircleCheck /></el-icon>
        {{ fileName }}（document_id: {{ documentId }}）
      </el-tag>
    </div>

    <el-button
      v-else-if="file"
      type="primary"
      :loading="uploading"
      class="upload-btn"
      @click="doUpload"
    >
      {{ uploading ? '上传中…' : '上传文档' }}
    </el-button>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { CircleCheck, UploadFilled } from '@element-plus/icons-vue'
import type { UploadFile, UploadFiles } from 'element-plus'
import { uploadDocument } from '@/api/documents'

const emit = defineEmits<{
  (e: 'uploaded', documentId: string, fileName: string): void
  (e: 'reset'): void
}>()

const file = ref<File | null>(null)
const uploading = ref(false)
const documentId = ref<string | null>(null)
const fileName = ref('')

function onChange(uploadFile: UploadFile) {
  file.value = uploadFile.raw ?? null
  documentId.value = null
}

function onRemove(_file: UploadFile, _files: UploadFiles) {
  file.value = null
  documentId.value = null
  emit('reset')
}

async function doUpload() {
  if (!file.value || uploading.value) return
  uploading.value = true
  try {
    const res = await uploadDocument(file.value)
    documentId.value = res.document_id
    fileName.value = res.file_name
    ElMessage.success('上传成功')
    emit('uploaded', res.document_id, res.file_name)
  } catch {
    // 拦截器已提示
  } finally {
    uploading.value = false
  }
}
</script>

<style scoped>
.upload-result {
  margin-top: 12px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.upload-btn {
  margin-top: 12px;
}
</style>
