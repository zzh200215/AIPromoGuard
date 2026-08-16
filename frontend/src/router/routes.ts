import type { RouteRecordRaw } from 'vue-router'
import type { PermissionCode } from '@/constants/permission'

declare module 'vue-router' {
  interface RouteMeta {
    /** 页面标题（顶栏面包屑显示） */
    title?: string
    /** 需要的权限码；缺省表示登录即可访问 */
    requiredPermission?: PermissionCode
    /** 侧栏菜单分组 */
    menuGroup?: string
    /** 是否出现在侧栏菜单（默认 true） */
    menuVisible?: boolean
    /** 仅管理员可见（菜单层过滤） */
    adminOnly?: boolean
  }
}

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/login/LoginView.vue'),
    meta: { title: '登录' },
  },
  {
    path: '/',
    component: () => import('@/layouts/MainLayout.vue'),
    redirect: '/dashboard',
    children: [
      {
        path: 'dashboard',
        name: 'dashboard',
        component: () => import('@/views/dashboard/DashboardView.vue'),
        meta: { title: '工作台', menuGroup: '工作台' },
      },
      {
        path: 'tasks/new',
        name: 'task-create',
        component: () => import('@/views/task/TaskCreateView.vue'),
        meta: {
          title: '新建审查',
          requiredPermission: 'create_task',
          menuGroup: '审查任务',
        },
      },
      {
        path: 'tasks',
        name: 'task-list',
        component: () => import('@/views/task/TaskListView.vue'),
        meta: { title: '审查任务', menuGroup: '审查任务' },
      },
      {
        path: 'tasks/:id',
        name: 'task-detail',
        component: () => import('@/views/task/TaskDetailView.vue'),
        meta: { title: '任务详情', requiredPermission: 'view_report', menuVisible: false },
      },
      {
        path: 'batches',
        name: 'batch-list',
        component: () => import('@/views/task/BatchListView.vue'),
        meta: { title: '批量审查', requiredPermission: 'create_task', menuGroup: '审查任务' },
      },
      {
        path: 'batches/:id',
        name: 'batch-detail',
        component: () => import('@/views/task/BatchDetailView.vue'),
        meta: { title: '批次详情', requiredPermission: 'view_report', menuVisible: false },
      },
      {
        path: 'knowledge/regulations',
        name: 'regulation-list',
        component: () => import('@/views/knowledge/RegulationListView.vue'),
        meta: { title: '法规库', menuGroup: '知识库' },
      },
      {
        path: 'knowledge/regulations/:id',
        name: 'regulation-detail',
        component: () => import('@/views/knowledge/RegulationDetailView.vue'),
        meta: { title: '法规详情', menuVisible: false },
      },
      {
        path: 'knowledge/rules',
        name: 'rule-list',
        component: () => import('@/views/knowledge/RuleListView.vue'),
        meta: { title: '规则库', menuGroup: '知识库' },
      },
      {
        path: 'knowledge/search',
        name: 'regulation-search',
        component: () => import('@/views/knowledge/RegulationSearchView.vue'),
        meta: { title: '法规检索', menuGroup: '知识库' },
      },
      {
        path: 'knowledge/graph',
        name: 'graph',
        component: () => import('@/views/knowledge/GraphView.vue'),
        meta: { title: '知识图谱', menuGroup: '知识库' },
      },
      {
        path: 'knowledge/trends',
        name: 'regulation-trend',
        component: () => import('@/views/knowledge/RegulationTrendView.vue'),
        meta: { title: '监管动态', menuGroup: '知识库' },
      },
      {
        path: 'admin/users',
        name: 'user-manage',
        component: () => import('@/views/admin/UserManageView.vue'),
        meta: {
          title: '用户管理',
          requiredPermission: 'manage_users',
          menuGroup: '系统管理',
        },
      },
      {
        path: 'admin/monitor',
        name: 'monitor',
        component: () => import('@/views/admin/MonitorView.vue'),
        meta: { title: '系统监控', requiredPermission: 'monitor', menuGroup: '系统管理' },
      },
      {
        path: 'admin/feedback',
        name: 'feedback-stats',
        component: () => import('@/views/admin/FeedbackStatsView.vue'),
        meta: {
          title: '反馈统计',
          requiredPermission: 'view_report',
          menuGroup: '系统管理',
          adminOnly: true,
        },
      },
    ],
  },
  {
    path: '/403',
    name: 'forbidden',
    component: () => import('@/views/error/ForbiddenView.vue'),
    meta: { title: '无权限' },
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'not-found',
    component: () => import('@/views/error/NotFoundView.vue'),
    meta: { title: '页面不存在' },
  },
]

export default routes
