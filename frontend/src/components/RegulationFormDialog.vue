<template>
  <el-dialog
    v-model="visible"
    :title="isEdit ? '编辑法规' : '新增法规'"
    width="560px"
    destroy-on-close
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-width="100px">
      <el-form-item label="领域" prop="domain">
        <el-select v-model="form.domain" placeholder="选择领域">
          <el-option
            v-for="d in DOMAIN_OPTIONS"
            :key="d.value"
            :label="d.label"
            :value="d.value"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="法规名称" prop="regulation_name">
        <el-input v-model="form.regulation_name" placeholder="如：商业银行理财业务监督管理办法" />
      </el-form-item>
      <el-form-item label="文号">
        <el-input v-model="form.regulation_no" placeholder="选填" />
      </el-form-item>
      <el-form-item label="发布机关">
        <el-input v-model="form.issuer" placeholder="选填" />
      </el-form-item>
      <el-form-item label="发布日期">
        <el-date-picker
          v-model="form.publish_date"
          type="date"
          value-format="YYYY-MM-DD"
          placeholder="选填"
          style="width: 100%"
        />
      </el-form-item>
      <el-form-item label="生效日期">
        <el-date-picker
          v-model="form.effective_date"
          type="date"
          value-format="YYYY-MM-DD"
          placeholder="选填"
          style="width: 100%"
        />
      </el-form-item>
      <el-form-item label="状态">
        <el-select v-model="form.status">
          <el-option label="现行有效" value="effective" />
          <el-option label="已修订" value="amended" />
          <el-option label="已废止" value="repealed" />
        </el-select>
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
import { createRegulation, updateRegulation } from '@/api/regulations'
import { DOMAIN_OPTIONS } from '@/constants/enums'
import type { Regulation } from '@/types/regulation'

const props = defineProps<{
  modelValue: boolean
  regulation?: Regulation | null
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', v: boolean): void
  (e: 'submitted'): void
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

const isEdit = computed(() => !!props.regulation)

const formRef = ref<FormInstance>()
const submitting = ref(false)

const form = reactive({
  domain: '',
  regulation_name: '',
  regulation_no: '',
  issuer: '',
  publish_date: '',
  effective_date: '',
  status: 'effective',
})

const rules: FormRules = {
  domain: [{ required: true, message: '请选择领域', trigger: 'change' }],
  regulation_name: [{ required: true, message: '请输入法规名称', trigger: 'blur' }],
}

watch(
  () => props.modelValue,
  (v) => {
    if (!v) return
    const r = props.regulation
    form.domain = r?.domain ?? ''
    form.regulation_name = r?.regulation_name ?? ''
    form.regulation_no = r?.regulation_no ?? ''
    form.issuer = r?.issuer ?? ''
    form.publish_date = r?.publish_date ?? ''
    form.effective_date = r?.effective_date ?? ''
    form.status = r?.status ?? 'effective'
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
      domain: form.domain,
      regulation_name: form.regulation_name,
      regulation_no: form.regulation_no || undefined,
      issuer: form.issuer || undefined,
      publish_date: form.publish_date || undefined,
      effective_date: form.effective_date || undefined,
      status: form.status as never,
    }
    if (props.regulation) {
      await updateRegulation(props.regulation.id, body)
    } else {
      await createRegulation(body)
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
