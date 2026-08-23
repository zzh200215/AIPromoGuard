<template>
  <div>
    <PageHeader title="用户管理">
      <el-button type="primary" @click="openCreate">新增用户</el-button>
    </PageHeader>

    <el-card>
      <div class="filter-bar">
        <el-select
          v-model="filterRole"
          placeholder="角色"
          clearable
          style="width: 140px"
          @change="reload"
        >
          <el-option v-for="(label, value) in ROLE_LABELS" :key="value" :label="label" :value="value" />
        </el-select>
        <el-select
          v-model="filterStatus"
          placeholder="状态"
          clearable
          style="width: 140px"
          @change="reload"
        >
          <el-option label="启用" :value="1" />
          <el-option label="停用" :value="0" />
        </el-select>
      </div>

      <el-table :data="rows" border v-loading="loading">
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column prop="username" label="用户名" min-width="120" />
        <el-table-column label="角色" width="110">
          <template #default="{ row }">
            <el-tag size="small" :type="row.role === 'admin' ? 'danger' : row.role === 'reviewer' ? 'primary' : 'info'">
              {{ ROLE_LABELS[row.role] }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="department" label="部门" min-width="120" show-overflow-tooltip>
          <template #default="{ row }">{{ row.department || '—' }}</template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="row.status === 1 ? 'success' : 'info'">
              {{ row.status === 1 ? '启用' : '停用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="170">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="230" fixed="right">
          <template #default="{ row }">
            <el-button
              size="small"
              type="primary"
              link
              :disabled="isSelf(row)"
              @click="openEdit(row)"
            >
              编辑
            </el-button>
            <el-button
              size="small"
              type="warning"
              link
              :disabled="isSelf(row)"
              @click="openResetPassword(row)"
            >
              重置密码
            </el-button>
            <el-button
              size="small"
              type="danger"
              link
              :disabled="isSelf(row)"
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

    <!-- 新增/编辑 -->
    <el-dialog
      v-model="dialogVisible"
      :title="editingUser ? '编辑用户' : '新增用户'"
      width="480px"
      destroy-on-close
    >
      <el-form ref="formRef" :model="form" :rules="formRules" label-width="90px">
        <el-form-item label="用户名" prop="username">
          <el-input v-model="form.username" :disabled="!!editingUser" placeholder="2-64 字符" />
        </el-form-item>
        <el-form-item v-if="!editingUser" label="密码" prop="password">
          <el-input
            v-model="form.password"
            type="password"
            show-password
            placeholder="至少 6 位"
          />
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="form.role">
            <el-option
              v-for="(label, value) in ROLE_LABELS"
              :key="value"
              :label="label"
              :value="value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="部门">
          <el-input v-model="form.department" maxlength="128" placeholder="选填" />
        </el-form-item>
        <el-form-item v-if="editingUser" label="状态">
          <el-switch v-model="form.status" :active-value="1" :inactive-value="0" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <!-- 重置密码 -->
    <el-dialog v-model="pwdVisible" title="重置密码" width="420px">
      <el-form label-width="90px">
        <el-form-item label="新密码">
          <el-input v-model="newPassword" type="password" show-password placeholder="至少 6 位" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="pwdVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="savePassword">确认</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import type { FormInstance, FormRules } from 'element-plus'
import { createUser, deleteUser, listUsers, resetPassword, updateUser } from '@/api/users'
import { ROLE_LABELS } from '@/constants/enums'
import { formatTime } from '@/composables/useFormat'
import { useAuthStore } from '@/stores/auth'
import type { Role } from '@/types/auth'
import type { UserItem } from '@/types/user'

const auth = useAuthStore()

const rows = ref<UserItem[]>([])
const loading = ref(false)
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const filterRole = ref<Role | ''>('')
const filterStatus = ref<number | ''>('')

const dialogVisible = ref(false)
const editingUser = ref<UserItem | null>(null)
const saving = ref(false)

const pwdVisible = ref(false)
const newPassword = ref('')
const pwdTarget = ref<UserItem | null>(null)

const formRef = ref<FormInstance>()
const form = reactive({
  username: '',
  password: '',
  role: 'reviewer' as Role,
  department: '',
  status: 1,
})

const formRules: FormRules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { min: 2, max: 64, message: '用户名长度 2-64', trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, max: 128, message: '密码长度 6-128', trigger: 'blur' },
  ],
}

function isSelf(row: UserItem) {
  return auth.user?.id === row.id
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
    const res = await listUsers({
      page: page.value,
      page_size: pageSize.value,
      role: filterRole.value || undefined,
      status: filterStatus.value === '' ? undefined : filterStatus.value,
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
  editingUser.value = null
  form.username = ''
  form.password = ''
  form.role = 'reviewer'
  form.department = ''
  form.status = 1
  dialogVisible.value = true
}

function openEdit(row: UserItem) {
  editingUser.value = row
  form.username = row.username
  form.password = ''
  form.role = row.role
  form.department = row.department ?? ''
  form.status = row.status
  dialogVisible.value = true
}

async function save() {
  if (!formRef.value) return
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return
  saving.value = true
  try {
    if (editingUser.value) {
      await updateUser(editingUser.value.id, {
        role: form.role,
        department: form.department || undefined,
        status: form.status,
      })
    } else {
      await createUser({
        username: form.username,
        password: form.password,
        role: form.role,
        department: form.department || undefined,
      })
    }
    ElMessage.success('保存成功')
    dialogVisible.value = false
    load()
  } catch {
    // 拦截器已提示
  } finally {
    saving.value = false
  }
}

function openResetPassword(row: UserItem) {
  pwdTarget.value = row
  newPassword.value = ''
  pwdVisible.value = true
}

async function savePassword() {
  if (!pwdTarget.value) return
  if (newPassword.value.length < 6) {
    ElMessage.warning('密码至少 6 位')
    return
  }
  saving.value = true
  try {
    await resetPassword(pwdTarget.value.id, newPassword.value)
    ElMessage.success('密码已重置')
    pwdVisible.value = false
  } catch {
    // 拦截器已提示
  } finally {
    saving.value = false
  }
}

async function onDelete(row: UserItem) {
  const ok = await ElMessageBox.confirm(
    `确定删除用户「${row.username}」？此操作不可恢复。`,
    '删除确认',
    { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
  ).catch(() => false)
  if (!ok) return
  try {
    await deleteUser(row.id)
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

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}
</style>
