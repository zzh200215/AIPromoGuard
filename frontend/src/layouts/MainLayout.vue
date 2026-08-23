<template>
  <el-container class="layout">
    <el-aside :width="appStore.sidebarCollapsed ? '64px' : '220px'" class="layout-aside">
      <div class="logo">
        <el-icon class="logo-icon"><Odometer /></el-icon>
        <span v-if="!appStore.sidebarCollapsed">合规审查</span>
      </div>
      <el-menu
        :default-active="$route.path"
        :collapse="appStore.sidebarCollapsed"
        :collapse-transition="false"
        router
        class="layout-menu"
      >
        <template v-for="group in menuGroups" :key="group.name">
          <el-menu-item-group :title="group.name">
            <el-menu-item v-for="item in group.items" :key="item.path" :index="item.path">
              <el-icon><component :is="item.icon" /></el-icon>
              <template #title>{{ item.title }}</template>
            </el-menu-item>
          </el-menu-item-group>
        </template>
      </el-menu>
    </el-aside>

    <el-container>
      <el-header class="layout-header">
        <div class="header-left">
          <el-icon class="collapse-btn" @click="appStore.toggleSidebar()">
            <Expand v-if="appStore.sidebarCollapsed" />
            <Fold v-else />
          </el-icon>
          <el-breadcrumb separator="/">
            <el-breadcrumb-item>首页</el-breadcrumb-item>
            <el-breadcrumb-item>{{ $route.meta.title }}</el-breadcrumb-item>
          </el-breadcrumb>
        </div>
        <el-dropdown @command="onCommand">
          <span class="user-chip">
            <el-icon><UserFilled /></el-icon>
            <span class="user-name">{{ auth.user?.username }}</span>
            <el-tag size="small" type="info">{{ ROLE_LABELS[auth.role ?? 'viewer'] }}</el-tag>
          </span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="logout" :icon="SwitchButton">退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </el-header>

      <el-main class="layout-main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import {
  Aim,
  Bell,
  Document,
  DocumentAdd,
  DataAnalysis,
  Expand,
  Files,
  Fold,
  HomeFilled,
  Monitor,
  Odometer,
  Search,
  SetUp,
  Share,
  SwitchButton,
  User,
  UserFilled,
} from '@element-plus/icons-vue'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import { ROLE_LABELS } from '@/constants/enums'
import type { PermissionCode } from '@/constants/permission'

interface MenuItem {
  group: string
  title: string
  path: string
  icon: string
  permission?: PermissionCode
  adminOnly?: boolean
}

const MENU_ITEMS: MenuItem[] = [
  { group: '工作台', title: '工作台', path: '/dashboard', icon: 'HomeFilled' },
  {
    group: '审查任务',
    title: '新建审查',
    path: '/tasks/new',
    icon: 'DocumentAdd',
    permission: 'create_task',
  },
  { group: '审查任务', title: '审查任务', path: '/tasks', icon: 'Document' },
  {
    group: '审查任务',
    title: '批量审查',
    path: '/batches',
    icon: 'Files',
    permission: 'create_task',
  },
  {
    group: '审查任务',
    title: '法规影响中心',
    path: '/impact',
    icon: 'Aim',
    permission: 'create_task',
  },
  { group: '知识库', title: '法规库', path: '/knowledge/regulations', icon: 'Files' },
  { group: '知识库', title: '规则库', path: '/knowledge/rules', icon: 'SetUp' },
  { group: '知识库', title: '法规检索', path: '/knowledge/search', icon: 'Search' },
  { group: '知识库', title: '知识图谱', path: '/knowledge/graph', icon: 'Share' },
  { group: '知识库', title: '监管动态', path: '/knowledge/trends', icon: 'Bell' },
  { group: '系统管理', title: '用户管理', path: '/admin/users', icon: 'User', permission: 'manage_users' },
  { group: '系统管理', title: '系统监控', path: '/admin/monitor', icon: 'Monitor', permission: 'monitor' },
  { group: '系统管理', title: '反馈统计', path: '/admin/feedback', icon: 'DataAnalysis', adminOnly: true },
]

const ICONS: Record<string, unknown> = {
  Aim,
  Bell,
  HomeFilled,
  DocumentAdd,
  Document,
  Files,
  SetUp,
  Search,
  Share,
  User,
  Monitor,
  DataAnalysis,
}

const router = useRouter()
const auth = useAuthStore()
const appStore = useAppStore()

/** 按权限过滤后分组菜单 */
const menuGroups = computed(() => {
  const groups = new Map<string, Array<{ title: string; path: string; icon: unknown }>>()
  for (const item of MENU_ITEMS) {
    if (item.adminOnly && auth.role !== 'admin') continue
    if (item.permission && !auth.hasPermission(item.permission)) continue
    const entry = { title: item.title, path: item.path, icon: ICONS[item.icon] }
    const list = groups.get(item.group) ?? []
    list.push(entry)
    groups.set(item.group, list)
  }
  return Array.from(groups.entries()).map(([name, items]) => ({ name, items }))
})

function onCommand(command: string) {
  if (command === 'logout') {
    auth.logout()
    router.push('/login')
  }
}
</script>

<style scoped>
.layout {
  height: 100%;
}

.layout-aside {
  background: #001529;
  transition: width 0.2s;
  overflow-x: hidden;
}

.logo {
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: #fff;
  font-size: 16px;
  font-weight: 600;
  white-space: nowrap;
}

.logo-icon {
  font-size: 22px;
  color: #409eff;
}

.layout-menu {
  border-right: none;
  background: transparent;
  --el-menu-bg-color: #001529;
  --el-menu-text-color: rgba(255, 255, 255, 0.68);
  --el-menu-hover-bg-color: rgba(255, 255, 255, 0.08);
  --el-menu-active-color: #fff;
  --el-menu-item-group-title-color: rgba(255, 255, 255, 0.45);
}

.layout-header {
  height: 56px;
  background: #fff;
  border-bottom: 1px solid var(--app-border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 16px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.collapse-btn {
  font-size: 18px;
  cursor: pointer;
  color: #606266;
}

.collapse-btn:hover {
  color: #409eff;
}

.user-chip {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  color: #303133;
  outline: none;
}

.user-name {
  font-size: 14px;
}

.layout-main {
  padding: 16px;
  overflow-y: auto;
}
</style>
