<template>
  <el-dialog
    v-model="visible"
    :title="isEdit ? `编辑规则（v${props.rule?.version}）` : '新增规则'"
    width="720px"
    destroy-on-close
    top="6vh"
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
      <el-row :gutter="12">
        <el-col :span="12">
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
        </el-col>
        <el-col :span="12">
          <el-form-item label="严重度">
            <el-select v-model="form.severity">
              <el-option label="高" value="high" />
              <el-option label="中" value="medium" />
              <el-option label="低" value="low" />
            </el-select>
          </el-form-item>
        </el-col>
      </el-row>

      <el-form-item label="规则名称" prop="rule_name">
        <el-input v-model="form.rule_name" placeholder="如：禁止保本保收益承诺" />
      </el-form-item>

      <el-form-item label="描述">
        <el-input v-model="form.description" type="textarea" :rows="2" placeholder="选填" />
      </el-form-item>

      <el-divider content-position="left">匹配条件（复合规则 = 多行 + OR/AND）</el-divider>

      <el-form-item label="组合方式">
        <el-radio-group v-model="form.operator" :disabled="form.conditions.length < 2">
          <el-radio value="OR">任一命中（OR）</el-radio>
          <el-radio value="AND">全部命中（AND）</el-radio>
        </el-radio-group>
      </el-form-item>

      <div v-for="(cond, idx) in form.conditions" :key="idx" class="condition-row">
        <el-select v-model="cond.type" style="width: 110px" @change="onTypeChange(cond)">
          <el-option label="关键词" value="keyword" />
          <el-option label="正则" value="regex" />
        </el-select>

        <template v-if="cond.type === 'regex'">
          <el-input
            v-model="cond.pattern"
            placeholder="正则表达式，如：保本保收益|本金不受损失"
            style="flex: 1"
          />
        </template>
        <template v-else>
          <el-select
            v-model="cond.keywords"
            multiple
            filterable
            allow-create
            default-first-option
            placeholder="输入关键词后回车"
            style="flex: 1"
          />
          <el-select v-model="cond.match_mode" style="width: 90px">
            <el-option label="任一" value="any" />
            <el-option label="全部" value="all" />
          </el-select>
        </template>

        <el-input-number
          v-model="cond.context_window"
          :min="0"
          :max="100"
          placeholder="上下文"
          style="width: 90px"
          title="context_window"
        />
        <el-input-number
          v-model="cond.negation_window"
          :min="0"
          :max="30"
          placeholder="否定"
          style="width: 90px"
          title="negation_window（0=不抑制否定）"
        />

        <el-button
          type="danger"
          text
          :icon="Delete"
          @click="form.conditions.splice(idx, 1)"
        />
      </div>

      <el-form-item>
        <el-button type="primary" plain :icon="Plus" @click="addCondition">添加条件</el-button>
      </el-form-item>

      <el-divider content-position="left">关联法规（选填）</el-divider>
      <el-form-item label="法规">
        <el-select
          v-model="form.related_regulations"
          multiple
          filterable
          allow-create
          default-first-option
          placeholder="输入法规名称后回车（去《》），如：商业银行理财业务监督管理办法"
          style="width: 100%"
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
import { Delete, Plus } from '@element-plus/icons-vue'
import type { FormInstance, FormRules } from 'element-plus'
import { createRule, updateRule } from '@/api/rules'
import { DOMAIN_OPTIONS } from '@/constants/enums'
import type { Rule, RuleCondition, RuleContent, RuleType } from '@/types/rule'

const props = defineProps<{
  modelValue: boolean
  rule?: Rule | null
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', v: boolean): void
  (e: 'submitted'): void
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

const isEdit = computed(() => !!props.rule)

const formRef = ref<FormInstance>()
const submitting = ref(false)

function blankCondition(): RuleCondition {
  return {
    type: 'keyword',
    keywords: [],
    match_mode: 'any',
    context_window: 15,
    negation_window: 8,
  }
}

const form = reactive({
  domain: '',
  rule_name: '',
  description: '',
  severity: 'medium' as Rule['severity'],
  operator: 'OR' as 'OR' | 'AND',
  conditions: [] as RuleCondition[],
  related_regulations: [] as string[],
})

const rules: FormRules = {
  domain: [{ required: true, message: '请选择领域', trigger: 'change' }],
  rule_name: [{ required: true, message: '请输入规则名称', trigger: 'blur' }],
}

watch(
  () => props.modelValue,
  (v) => {
    if (!v) return
    const r = props.rule
    const content: RuleContent = r?.rule_content ?? { operator: 'OR', conditions: [] }
    form.domain = r?.domain ?? ''
    form.rule_name = r?.rule_name ?? ''
    form.description = r?.description ?? ''
    form.severity = (r?.severity ?? 'medium') as Rule['severity']
    form.operator = content.operator ?? 'OR'
    form.conditions = content.conditions?.length
      ? content.conditions.map((c) => ({ ...c }))
      : [blankCondition()]
    form.related_regulations = content.related_regulations ?? []
    formRef.value?.clearValidate()
  },
)

function onTypeChange(cond: RuleCondition) {
  if (cond.type === 'regex') {
    cond.pattern = cond.pattern ?? ''
    delete cond.keywords
    delete cond.match_mode
  } else {
    cond.keywords = cond.keywords ?? []
    cond.match_mode = cond.match_mode ?? 'any'
    delete cond.pattern
  }
}

function addCondition() {
  form.conditions.push(blankCondition())
}

function inferRuleType(conditions: RuleCondition[]): RuleType {
  if (conditions.length > 1) return 'composite'
  const c = conditions[0]
  if (!c) return 'keyword'
  return c.type === 'regex' ? 'regex' : 'keyword'
}

async function submit() {
  if (!formRef.value) return
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return
  // 空条件校验：正则/关键词至少一个有效
  const hasAny = form.conditions.some(
    (c) => (c.type === 'regex' ? c.pattern : (c.keywords?.length ?? 0) > 0),
  )
  if (!hasAny) {
    ElMessage.warning('至少需要一个有效匹配条件')
    return
  }
  submitting.value = true
  try {
    const body = {
      domain: form.domain,
      rule_name: form.rule_name,
      rule_type: inferRuleType(form.conditions),
      rule_content: {
        operator: form.conditions.length > 1 ? form.operator : 'OR',
        conditions: form.conditions,
        related_regulations: form.related_regulations.length
          ? form.related_regulations
          : undefined,
      },
      severity: form.severity,
      description: form.description || undefined,
    }
    if (props.rule) {
      await updateRule(props.rule.id, body)
    } else {
      await createRule(body)
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

<style scoped>
.condition-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}
</style>
