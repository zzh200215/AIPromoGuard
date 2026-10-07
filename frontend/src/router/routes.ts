import type { RouteRecordRaw } from 'vue-router'
import type { PermissionCode } from '@/constants/permission'

declare module 'vue-router' {
  interface RouteMeta {
    /** 页面标题（顶栏面包屑显示） */
    title?: string
    /** 需要的权限码；缺省表示登录即可访问 */
    requiredPermission?: PermissionCode
    /** 侧栏菜单分组；分组顺序由 MainLayout 的 GROUP_ORDER 决定 */
    menuGroup?: string
    /** 侧栏菜单图标（Element Plus 图标组件名） */
    icon?: string
    /** 是否出现在侧栏菜单（默认 true） */
    menuVisible?: boolean
    /** 菜单排序（同组内升序，缺省按路由声明顺序） */
    menuOrder?: number
    /** 仅管理员可见（菜单层过滤） */
    adminOnly?: boolean
  }
}

/**
 * 侧栏信息架构按「角色旅程」组织，而不是按后端模块：
 *   工作台 → 我要送审（审查工作）→ 合规运营闭环 → 知识库 → 系统管理
 * 菜单项 = 带 menuGroup 的路由，MainLayout 据此渲染，避免两处维护。
 */
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
        meta: { title: '工作台', icon: 'HomeFilled', menuGroup: '工作台' },
      },
      // ---- 审查工作：送审入口与任务跟踪 ----
      {
        path: 'tasks/new',
        name: 'task-create',
        component: () => import('@/views/task/TaskCreateView.vue'),
        meta: {
          title: '新建审查',
          icon: 'DocumentAdd',
          requiredPermission: 'create_task',
          menuGroup: '审查工作',
          menuOrder: 1,
        },
      },
      {
        path: 'tasks',
        name: 'task-list',
        component: () => import('@/views/task/TaskListView.vue'),
        meta: { title: '审查任务', icon: 'Document', menuGroup: '审查工作', menuOrder: 2 },
      },
      {
        path: 'tasks/:id(\\d+)',
        name: 'task-detail',
        component: () => import('@/views/task/TaskDetailView.vue'),
        meta: { title: '任务详情', requiredPermission: 'view_report', menuVisible: false },
      },
      {
        path: 'batches',
        name: 'batch-list',
        component: () => import('@/views/task/BatchListView.vue'),
        meta: {
          title: '批量审查',
          icon: 'Files',
          requiredPermission: 'create_task',
          menuGroup: '审查工作',
          menuOrder: 3,
        },
      },
      {
        path: 'batches/:id(\\d+)',
        name: 'batch-detail',
        component: () => import('@/views/task/BatchDetailView.vue'),
        meta: { title: '批次详情', requiredPermission: 'view_report', menuVisible: false },
      },
      // ---- 合规运营：监管变化驱动的整改闭环 ----
      {
        path: 'impact',
        name: 'impact-center',
        component: () => import('@/views/impact/ImpactCenterView.vue'),
        meta: {
          title: '法规影响中心',
          icon: 'Aim',
          requiredPermission: 'create_task',
          menuGroup: '合规运营',
          menuOrder: 1,
        },
      },
      {
        path: 'materials',
        name: 'material-ledger',
        component: () => import('@/views/impact/MaterialLedgerView.vue'),
        meta: {
          title: '材料台账',
          icon: 'Collection',
          menuGroup: '合规运营',
          menuOrder: 2,
        },
      },
      // ---- 知识库：法规 / 规则 / 检索 / 图谱 / 动态 ----
      {
        path: 'knowledge/regulations',
        name: 'regulation-list',
        component: () => import('@/views/knowledge/RegulationListView.vue'),
        meta: {
          title: '法规库',
          icon: 'Collection',
          menuGroup: '知识库',
          menuOrder: 1,
        },
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
        meta: { title: '规则库', icon: 'SetUp', menuGroup: '知识库', menuOrder: 2 },
      },
      {
        path: 'knowledge/search',
        name: 'regulation-search',
        component: () => import('@/views/knowledge/RegulationSearchView.vue'),
        meta: { title: '法规检索', icon: 'Search', menuGroup: '知识库', menuOrder: 3 },
      },
      {
        path: 'knowledge/graph',
        name: 'graph',
        component: () => import('@/views/knowledge/GraphView.vue'),
        meta: { title: '知识图谱', icon: 'Share', menuGroup: '知识库', menuOrder: 4 },
      },
      {
        path: 'knowledge/trends',
        name: 'regulation-trend',
        component: () => import('@/views/knowledge/RegulationTrendView.vue'),
        meta: { title: '监管动态', icon: 'Bell', menuGroup: '知识库', menuOrder: 5 },
      },
      // ---- 系统管理 ----
      {
        path: 'admin/users',
        name: 'user-manage',
        component: () => import('@/views/admin/UserManageView.vue'),
        meta: {
          title: '用户管理',
          icon: 'User',
          requiredPermission: 'manage_users',
          menuGroup: '系统管理',
          menuOrder: 1,
        },
      },
      {
        path: 'admin/monitor',
        name: 'monitor',
        component: () => import('@/views/admin/MonitorView.vue'),
        meta: {
          title: '系统监控',
          icon: 'Monitor',
          requiredPermission: 'monitor',
          menuGroup: '系统管理',
          menuOrder: 2,
        },
      },
      {
        path: 'admin/feedback',
        name: 'feedback-stats',
        component: () => import('@/views/admin/FeedbackStatsView.vue'),
        meta: {
          title: '反馈统计',
          icon: 'DataAnalysis',
          requiredPermission: 'view_report',
          menuGroup: '系统管理',
          menuOrder: 3,
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
