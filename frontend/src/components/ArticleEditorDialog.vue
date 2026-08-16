<template>
  <el-dialog
    v-model="visible"
    :title="isEdit ? '编辑条款' : '新增条款'"
    width="640px"
    destroy-on-close
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
      <el-row :gutter="12">
        <el-col :span="8">
          <el-form-item label="章">
            <el-input v-model="form.chapter_no" placeholder="如：第二章" />
          </el-form-item>
        </el-col>
        <el-col :span="8">
          <el-form-item label="节">
            <el-input v-model="form.section_no" placeholder="选填" />
          </el-form-item>
        </el-col>
        <el-col :span="8">
          <el-form-item label="条">
            <el-input v-model="form.article_no" placeholder="如：第二十六条" />
          </el-form-item>
        </el-col>
      </el-row>
      <el-form-item label="内容" prop="content">
        <el-input
          v-model="form.content"
          type="textarea"
          :rows="6"
          placeholder="条款正文"
        />
      </el-form-item>
    </el-form>

    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="submit">保存</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import type { FormInstance, FormRules } from 'element-plus'
import { createArticle, updateArticle } from '@/api/regulations'
import type { Article } from '@/types/regulation'

const props = defineProps<{
  modelValue: boolean
  regulationId?: number
  article?: Article | null
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', v: boolean): void
  (e: 'submitted'): void
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

const isEdit = computed(() => !!props.article)

const formRef = ref<FormInstance>()
const submitting = ref(false)

const form = reactive({
  chapter_no: '',
  section_no: '',
  article_no: '',
  content: '',
})

const rules: FormRules = {
  content: [{ required: true, message: '请输入条款内容', trigger: 'blur' }],
}

watch(
  () => props.modelValue,
  (v) => {
    if (!v) return
    const a = props.article
    form.chapter_no = a?.chapter_no ?? ''
    form.section_no = a?.section_no ?? ''
    form.article_no = a?.article_no ?? ''
    form.content = a?.content ?? ''
    formRef.value?.clearValidate()
  },
)

async function submit() {
  if (!formRef.value) return
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return
  submitting.value = true
  try {
    const body = {
      chapter_no: form.chapter_no || undefined,
      section_no: form.section_no || undefined,
      article_no: form.article_no || undefined,
      content: form.content,
    }
    if (props.article) {
      await updateArticle(props.article.id, body)
      ElMessage.warning('条款已更新，其向量索引已失效，请重跑 index_articles.py 重新索引')
    } else {
      if (!props.regulationId) return
      await createArticle(props.regulationId, body)
    }
    ElMessage.success('保存成功')
    visible.value = false
    emit('submitted')
  } catch {
    // 拦截器已提示
  } finally {
    submitting.value = false
  }
}
</script>
