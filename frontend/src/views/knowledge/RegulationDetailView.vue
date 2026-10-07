<template>
  <div>
    <PageHeader :title="regulation?.regulation_name || '法规详情'">
      <el-button
        v-if="regulation?.regulation_name"
        @click="router.push(`/knowledge/graph?q=${encodeURIComponent(regulation.regulation_name)}`)"
      >
        在图谱中查看
      </el-button>
      <el-button @click="router.push('/knowledge/regulations')">返回列表</el-button>
    </PageHeader>

    <el-card v-if="regulation" class="detail-card">
      <el-descriptions :column="3">
        <el-descriptions-item label="法规名称">{{ regulation.regulation_name }}</el-descriptions-item>
        <el-descriptions-item label="领域">
          {{ (DOMAIN_LABELS as Record<string, string>)[regulation.domain] ?? regulation.domain }}
        </el-descriptions-item>
        <el-descriptions-item label="状态">
          {{ REG_STATUS_LABELS[regulation.status] }}
        </el-descriptions-item>
        <el-descriptions-item label="文号">{{ regulation.regulation_no || '—' }}</el-descriptions-item>
        <el-descriptions-item label="发布机关">{{ regulation.issuer || '—' }}</el-descriptions-item>
        <el-descriptions-item label="发布日期">{{ regulation.publish_date || '—' }}</el-descriptions-item>
        <el-descriptions-item label="生效日期">{{ regulation.effective_date || '—' }}</el-descriptions-item>
      </el-descriptions>
    </el-card>

    <el-card class="articles-card">
      <template #header>
        <div class="card-header">
          <span>条款（{{ total }}）</span>
          <el-button
            v-if="auth.hasPermission('manage_regulations')"
            size="small"
            type="primary"
            @click="openCreateArticle"
          >
            新增条款
          </el-button>
        </div>
      </template>

      <el-table :data="articles">
        <el-table-column label="条款编号" width="130">
          <template #default="{ row }">{{ row.article_no || '—' }}</template>
        </el-table-column>
        <el-table-column label="章 / 节" width="150">
          <template #default="{ row }">
            {{ [row.chapter_no, row.section_no].filter(Boolean).join(' · ') || '—' }}
          </template>
        </el-table-column>
        <el-table-column prop="content" label="内容" min-width="320" show-overflow-tooltip />
        <el-table-column label="向量" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="row.vector_id ? 'success' : 'info'">
              {{ row.vector_id ? '已索引' : '未索引' }}
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
              @click="openEditArticle(row)"
            >
              编辑
            </el-button>
            <el-button
              v-if="auth.hasPermission('manage_regulations')"
              size="small"
              type="danger"
              link
              @click="onDeleteArticle(row)"
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

    <ArticleEditorDialog
      v-model="articleDialogVisible"
      :regulation-id="regulationId"
      :article="editingArticle"
      @submitted="loadArticles"
    />
  </div>
</template>

<script setup lang="ts">
defineOptions({ name: 'regulation-detail' })
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { deleteArticle, getRegulation, listArticles } from '@/api/regulations'
import { DOMAIN_LABELS, REG_STATUS_LABELS } from '@/constants/enums'
import { useAuthStore } from '@/stores/auth'
import type { Article, Regulation } from '@/types/regulation'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const regulationId = Number(route.params.id)

const regulation = ref<Regulation | null>(null)
const articles = ref<Article[]>([])
const loading = ref(false)
const total = ref(0)
const page = ref(1)
const pageSize = ref(50)

const articleDialogVisible = ref(false)
const editingArticle = ref<Article | null>(null)

async function loadRegulation() {
  try {
    regulation.value = await getRegulation(regulationId)
  } catch {
    // 拦截器已提示
  }
}

async function loadArticles() {
  loading.value = true
  try {
    const res = await listArticles(regulationId, { page: page.value, page_size: pageSize.value })
    articles.value = res.items
    total.value = res.total
  } catch {
    // 拦截器已提示
  } finally {
    loading.value = false
  }
}

function onPageChange(p: number) {
  page.value = p
  loadArticles()
}

function openCreateArticle() {
  editingArticle.value = null
  articleDialogVisible.value = true
}

function openEditArticle(row: Article) {
  editingArticle.value = row
  articleDialogVisible.value = true
}

async function onDeleteArticle(row: Article) {
  const ok = await ElMessageBox.confirm(`确定删除该条款？`, '删除确认', {
    type: 'warning',
    confirmButtonText: '删除',
    cancelButtonText: '取消',
  }).catch(() => false)
  if (!ok) return
  try {
    await deleteArticle(row.id)
    ElMessage.success('已删除')
    loadArticles()
  } catch {
    // 拦截器已提示
  }
}

onMounted(() => {
  loadRegulation()
  loadArticles()
})
</script>

<style scoped>
.detail-card {
  margin-bottom: 16px;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}
</style>
