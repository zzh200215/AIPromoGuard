<template>
  <el-container class="layout">
    <el-aside :width="appStore.sidebarCollapsed ? '64px' : '232px'" class="layout-aside">
      <!-- 品牌区 -->
      <div class="brand" @click="router.push('/dashboard')">
        <div class="brand-mark">
          <el-icon :size="18"><Stamp /></el-icon>
        </div>
        <div v-if="!appStore.sidebarCollapsed" class="brand-text">
          <div class="brand-name">智能合规审查</div>
          <div class="brand-sub">金融营销材料送审平台</div>
        </div>
      </div>

      <el-scrollbar class="menu-scroll">
        <el-menu
          :default-active="activePath"
          :collapse="appStore.sidebarCollapsed"
          :collapse-transition="false"
          :default-openeds="openGroups"
          router
          class="layout-menu"
        >
          <template v-for="group in menuGroups" :key="group.name">
            <!-- 单项分组：直接渲染菜单项 -->
            <el-menu-item
              v-if="group.items.length === 1"
              :index="group.items[0].path"
              class="top-item"
            >
              <el-icon><component :is="group.items[0].icon" /></el-icon>
              <template #title>{{ group.items[0].title }}</template>
            </el-menu-item>

            <!-- 多项分组：子菜单 -->
            <el-sub-menu v-else :index="group.name">
              <template #title>
                <el-icon><component :is="group.icon" /></el-icon>
                <span>{{ group.name }}</span>
              </template>
              <el-menu-item v-for="item in group.items" :key="item.path" :index="item.path">
                <el-icon><component :is="item.icon" /></el-icon>
                <template #title>{{ item.title }}</template>
              </el-menu-item>
            </el-sub-menu>
          </template>
        </el-menu>
      </el-scrollbar>

      <div class="aside-footer">
        <div class="collapse-trigger" @click="appStore.toggleSidebar()">
          <el-icon>
            <Expand v-if="appStore.sidebarCollapsed" />
            <Fold v-else />
          </el-icon>
          <span v-if="!appStore.sidebarCollapsed">收起菜单</span>
        </div>
      </div>
    </el-aside>

    <el-container class="layout-body">
      <el-header class="layout-header">
        <el-breadcrumb separator="/" class="breadcrumb">
          <el-breadcrumb-item v-if="currentGroup && currentGroup !== '工作台'">
            {{ currentGroup }}
          </el-breadcrumb-item>
          <el-breadcrumb-item>{{ pageTitle }}</el-breadcrumb-item>
        </el-breadcrumb>

        <div class="header-right">
          <el-tag v-if="auth.role === 'admin'" size="small" class="admin-chip" effect="plain">
            管理员
          </el-tag>

          <!-- 全局命令面板：Ctrl+K 或点搜索 -->
          <span class="palette-trigger" title="全局搜索" @click="paletteVisible = true">
            <el-icon :size="16"><Search /></el-icon>
            <kbd class="palette-kbd">Ctrl K</kbd>
          </span>

          <!-- 明暗主题切换 -->
          <span
            class="palette-trigger"
            :title="appStore.theme === 'dark' ? '切换为浅色' : '切换为深色'"
            @click="appStore.toggleTheme()"
          >
            <el-icon :size="17"><Sunny v-if="appStore.theme === 'dark'" /><Moon v-else /></el-icon>
          </span>

          <!-- 站内通知：铃铛 + 未读角标，30s 轮询 -->
          <el-popover placement="bottom-end" :width="360" trigger="click" @show="loadNotifications">
            <template #reference>
              <span class="bell-trigger">
                <el-badge :value="unread" :hidden="!unread" :max="99">
                  <el-icon :size="18"><Bell /></el-icon>
                </el-badge>
              </span>
            </template>
            <div class="notif-panel">
              <div class="notif-head">
                <span class="notif-title">通知</span>
                <el-button
                  v-if="notifications.length"
                  size="small"
                  link
                  type="primary"
                  @click="onReadAll"
                >
                  全部已读
                </el-button>
              </div>
              <el-empty
                v-if="!notifications.length"
                description="暂无通知"
                :image-size="60"
                style="padding: 12px 0"
              />
              <div
                v-for="n in notifications"
                :key="n.id"
                class="notif-item"
                :class="{ unread: !n.is_read }"
                @click="onOpenNotification(n)"
              >
                <div class="notif-item-title">
                  <span v-if="!n.is_read" class="unread-dot" />
                  {{ n.title }}
                </div>
                <div v-if="n.body" class="notif-item-body">{{ n.body }}</div>
                <div class="notif-item-time">{{ n.created_at ?? '' }}</div>
              </div>
            </div>
          </el-popover>

          <el-dropdown @command="onCommand">
            <span class="user-chip">
              <span class="avatar">{{ avatarChar }}</span>
              <span class="user-name">{{ auth.user?.username }}</span>
              <span class="role-name">{{ ROLE_LABELS[auth.role ?? 'viewer'] }}</span>
              <el-icon class="arrow"><ArrowDown /></el-icon>
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="logout" :icon="SwitchButton">退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>

      <TagsView />

      <el-main class="layout-main">
        <!-- 不加 route transition：过渡完成依赖 requestAnimationFrame，
             webview 被遮挡/节流时 rAF 暂停会让路由切换永久卡住（点了没反应、页面不出现） -->
        <!-- keep-alive 按标签缓存页面：切标签保留工作台进度/滚动位置；include 只含
             当前打开标签的组件名，关标签即剪缓存。:key 里 path 让详情页参数变化时
             重建页面；query 变化（列表筛选）不重建；refreshKey 由标签栏右键「刷新」
             自增，配合短暂移出 include 强制当前页重挂载 -->
        <router-view v-slot="{ Component }">
          <keep-alive :include="cachedNames" :max="12">
            <component :is="Component" :key="`${route.path}|${tagsStore.refreshKey}`" />
          </keep-alive>
        </router-view>
      </el-main>
    </el-container>

    <CommandPalette v-model="paletteVisible" />
    <AppWatermark />
  </el-container>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Aim,
  ArrowDown,
  Bell,
  Collection,
  DataAnalysis,
  Document,
  DocumentAdd,
  DocumentChecked,
  Expand,
  Files,
  Fold,
  HomeFilled,
  Monitor,
  Moon,
  Reading,
  Refresh,
  Search,
  Setting,
  SetUp,
  Share,
  Stamp,
  Sunny,
  SwitchButton,
  User,
} from '@element-plus/icons-vue'
import {
  listNotifications,
  markAllNotificationsRead,
  markNotificationRead,
  type NotificationItem,
} from '@/api/notifications'
import CommandPalette from '@/components/CommandPalette.vue'
import AppWatermark from '@/components/AppWatermark.vue'
import TagsView from '@/components/TagsView.vue'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import { onServerEvent } from '@/composables/useEventStream'
import { useTagsStore } from '@/stores/tags'
import { ROLE_LABELS } from '@/constants/enums'

interface MenuItem {
  title: string
  path: string
  icon: unknown
}

interface MenuGroup {
  name: string
  icon?: unknown
  items: MenuItem[]
}

/** 分组展示顺序 = 用户旅程：工作台 → 审查工作 → 合规运营 → 知识库 → 系统管理 */
const GROUP_ORDER = ['工作台', '审查工作', '合规运营', '知识库', '系统管理']
const GROUP_ICONS: Record<string, unknown> = {
  审查工作: DocumentChecked,
  合规运营: Refresh,
  知识库: Reading,
  系统管理: Setting,
}

const ICONS: Record<string, unknown> = {
  Aim,
  Bell,
  Collection,
  HomeFilled,
  DocumentAdd,
  Document,
  Files,
  Reading,
  SetUp,
  Search,
  Share,
  User,
  Monitor,
  DataAnalysis,
}

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const appStore = useAppStore()
const tagsStore = useTagsStore()

/** 菜单单一来源：路由 meta（menuGroup / icon / menuOrder），避免与视图两处维护 */
const menuGroups = computed<MenuGroup[]>(() => {
  const layoutRoute = router.options.routes.find((r) => r.path === '/')
  const children = layoutRoute?.children ?? []
  const buckets = new Map<string, Array<{ title: string; path: string; icon: unknown; order: number }>>()

  children.forEach((child, index) => {
    const meta = child.meta ?? {}
    if (meta.menuVisible === false || !meta.menuGroup || !meta.title) return
    if (meta.adminOnly && auth.role !== 'admin') return
    if (meta.requiredPermission && !auth.hasPermission(meta.requiredPermission)) return

    const entry = {
      title: meta.title,
      // 子路由 path 是相对路径（如 tasks / knowledge/rules）；el-menu router 模式
      // 直接 push index，相对路径在深层页面（/tasks/15 等）会被解析成 /tasks/tasks，
      // 必须拼出完整路径
      path: `/${child.path}`,
      icon: ICONS[meta.icon ?? ''],
      order: meta.menuOrder ?? index,
    }
    const list = buckets.get(meta.menuGroup) ?? []
    list.push(entry)
    buckets.set(meta.menuGroup, list)
  })

  return GROUP_ORDER.filter((name) => buckets.has(name)).map((name) => ({
    name,
    icon: GROUP_ICONS[name],
    items: (buckets.get(name) ?? []).sort((a, b) => a.order - b.order),
  }))
})

const activePath = computed(() => `/${route.path.split('/')[1]}`)

const currentGroup = computed(() => {
  const found = menuGroups.value.find((g) => g.items.some((i) => route.path.startsWith(i.path)))
  if (found && found.items.length > 1) return found.name
  return route.meta.menuGroup as string | undefined
})

const pageTitle = computed(() => (route.meta.title as string) ?? '')

const openGroups = computed(() =>
  menuGroups.value.filter((g) => g.items.some((i) => route.path.startsWith(i.path))).map((g) => g.name),
)

const avatarChar = computed(() => (auth.user?.username ?? '?').slice(0, 1).toUpperCase())

/** keep-alive 白名单：当前打开标签的组件名，刷新中的组件临时剔除以剪掉旧缓存 */
const cachedNames = computed(() =>
  tagsStore.tags
    .map((t) => t.name)
    .filter((n): n is string => !!n && !tagsStore.evicting.includes(n)),
)

// 右键「刷新」：key 自增强制重挂载的同时把组件名短暂移出 include，
// 让 keep-alive 剪掉旧实例，下个 tick 恢复后新实例重新入缓存
watch(
  () => tagsStore.refreshKey,
  async () => {
    const name = route.name as string | undefined
    if (!name) return
    tagsStore.evictForRefresh(name)
    await nextTick()
    tagsStore.restoreEvicted(name)
  },
)

function onCommand(command: string) {
  if (command === 'logout') {
    auth.logout()
    router.push('/login')
  }
}

// ---- 全局命令面板：Ctrl/⌘+K 唤起 ----
const paletteVisible = ref(false)

function onGlobalKeydown(e: KeyboardEvent) {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault()
    paletteVisible.value = !paletteVisible.value
  }
}

// SSE 通知事件：到达即刷新铃铛（30s 轮询降级为断线兜底）
const offNotificationEvent = onServerEvent('notification', () => loadNotifications())

onMounted(() => {
  appStore.applyTheme()
  window.addEventListener('keydown', onGlobalKeydown)
  void loadNotifications()
  pollTimer = setInterval(loadNotifications, 30_000)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onGlobalKeydown)
  if (pollTimer) clearInterval(pollTimer)
  offNotificationEvent()
})

// ---- 站内通知：未读数 30s 轮询；打开面板拉列表；点击跳转并标记已读 ----
const notifications = ref<NotificationItem[]>([])
const unread = ref(0)
let pollTimer: ReturnType<typeof setInterval> | null = null

async function loadNotifications() {
  if (!auth.token) return
  try {
    const res = await listNotifications({ page: 1, page_size: 8 })
    notifications.value = res.items
    unread.value = res.unread
  } catch {
    // 静默：通知拉取失败不打扰用户
  }
}

async function onOpenNotification(n: NotificationItem) {
  if (!n.is_read) {
    try {
      await markNotificationRead(n.id)
      n.is_read = 1
      unread.value = Math.max(0, unread.value - 1)
    } catch {
      // 已读标记失败不阻断跳转
    }
  }
  if (n.link) {
    router.push(n.link)
  }
}

async function onReadAll() {
  try {
    await markAllNotificationsRead()
    notifications.value = notifications.value.map((n) => ({ ...n, is_read: 1 }))
    unread.value = 0
  } catch {
    // 拦截器已提示
  }
}
</script>

<style scoped lang="scss">
.layout {
  height: 100%;
}

// ---- 侧栏：深海军蓝墨色，品牌区 + 分组子菜单 + 底部收起 ----
.layout-aside {
  background: var(--app-ink);
  transition: width 0.2s;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 16px 16px 14px;
  cursor: pointer;
  flex-shrink: 0;
}

.brand-mark {
  width: 34px;
  height: 34px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  /* 印章式标记：金铜细描边 + 透明底（与登录页同一语言，替代原蓝色渐变方块） */
  border-radius: 4px;
  color: var(--app-accent);
  border: 1px solid rgba(200, 150, 60, 0.55);
  background: rgba(200, 150, 60, 0.08);
}

.brand-text {
  min-width: 0;
}

.brand-name {
  color: #f3eee3;
  /* 宋体系：公报标题的文书感 */
  font-family: var(--app-font-display);
  font-size: 15px;
  font-weight: 700;
  letter-spacing: 0.08em;
  white-space: nowrap;
}

.brand-sub {
  margin-top: 1px;
  color: rgba(243, 238, 227, 0.42);
  font-size: 12px;
  letter-spacing: 0.04em;
  white-space: nowrap;
}

.menu-scroll {
  flex: 1;
}

.layout-menu {
  border-right: none;
  background: transparent;
  padding: 0 10px;
  --el-menu-bg-color: transparent;
  --el-menu-text-color: rgba(243, 238, 227, 0.62);
  --el-menu-hover-bg-color: rgba(243, 238, 227, 0.07);
  --el-menu-active-color: var(--app-accent);
  --el-menu-item-height: 42px;
}

// 子菜单内菜单项
.layout-menu :deep(.el-menu-item) {
  border-radius: 4px;
  margin: 2px 0;
  height: 42px;
  line-height: 42px;
}

// 激活项：公报目录的「当前条目」——金铜竖线 + 暖金极浅底（克制的品牌强调）
.layout-menu :deep(.el-menu-item.is-active) {
  position: relative;
  background: rgba(200, 150, 60, 0.14);
  color: var(--app-accent);
  font-weight: 500;

  &::before {
    content: '';
    position: absolute;
    left: 0;
    top: 50%;
    transform: translateY(-50%);
    width: 3px;
    height: 18px;
    border-radius: 2px;
    background: var(--app-accent);
  }
}

.layout-menu :deep(.el-sub-menu__title) {
  border-radius: 4px;
  margin: 2px 0;
  height: 42px;
  line-height: 42px;
  color: rgba(243, 238, 227, 0.78);
  font-weight: 500;
}

.layout-menu :deep(.el-sub-menu.is-active > .el-sub-menu__title) {
  color: var(--app-accent);
}

.layout-menu :deep(.el-sub-menu .el-menu) {
  background: rgba(243, 238, 227, 0.03);
  border-radius: 4px;
  padding: 2px 0;
  margin: 2px 0 6px;
}

.layout-menu :deep(.el-sub-menu .el-menu .el-menu-item) {
  padding-left: 44px !important;
  font-size: 14px;
}

// 顶级单项（工作台）
.layout-menu :deep(.top-item) {
  font-weight: 500;
}

.aside-footer {
  flex-shrink: 0;
  padding: 10px;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
}

.collapse-trigger {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  height: 36px;
  border-radius: 8px;
  color: rgba(255, 255, 255, 0.55);
  font-size: 13px;
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
  white-space: nowrap;
}

.collapse-trigger:hover {
  background: rgba(255, 255, 255, 0.07);
  color: #fff;
}

// ---- 顶栏 ----
.layout-body {
  min-width: 0;
}

.layout-header {
  height: 56px;
  background: var(--app-surface);
  border-bottom: 1px solid var(--app-border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
}

.breadcrumb {
  font-size: 14px;

  :deep(.el-breadcrumb__inner) {
    color: var(--el-text-color-secondary);
    font-weight: 400;
  }

  :deep(.el-breadcrumb__item:last-child .el-breadcrumb__inner) {
    color: var(--el-text-color-primary);
    font-weight: 600;
  }
}

.header-right {
  display: flex;
  align-items: center;
  gap: 14px;
}

.admin-chip {
  --el-tag-text-color: var(--el-color-primary);
  --el-tag-bg-color: var(--el-color-primary-light-9);
}

.bell-trigger {
  display: inline-flex;
  align-items: center;
  padding: 6px;
  border-radius: 8px;
  cursor: pointer;
  color: var(--el-text-color-regular);
  transition: background 0.15s;

  &:hover {
    background: var(--el-fill-color-light);
  }
}

// 命令面板/主题切换触发器：与铃铛同款 hover 行为
.palette-trigger {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 6px 9px;
  border-radius: 8px;
  cursor: pointer;
  color: var(--el-text-color-regular);
  transition: background 0.15s;

  &:hover {
    background: var(--el-fill-color-light);
    color: var(--el-color-primary);
  }
}

.palette-kbd {
  padding: 0 5px;
  border: 1px solid var(--app-border);
  border-bottom-width: 2px;
  border-radius: 5px;
  font-size: 11px;
  line-height: 16px;
  font-family: inherit;
  color: var(--el-text-color-secondary);
  background: var(--app-surface-2);
}

.notif-panel {
  max-height: 380px;
  overflow-y: auto;
}

.notif-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
}

.notif-title {
  font-weight: 600;
  font-size: 14px;
}

.notif-item {
  padding: 8px 6px;
  border-bottom: 1px dashed var(--el-border-color-lighter);
  cursor: pointer;
  border-radius: 6px;

  &:hover {
    background: var(--el-fill-color-light);
  }

  &:last-child {
    border-bottom: none;
  }

  &.unread .notif-item-title {
    font-weight: 600;
  }
}

.notif-item-title {
  font-size: 13px;
  color: var(--el-text-color-primary);
  display: flex;
  align-items: center;
  gap: 6px;
}

.unread-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--el-color-danger);
  flex-shrink: 0;
}

.notif-item-body {
  margin-top: 2px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.notif-item-time {
  margin-top: 2px;
  font-size: 12px;
  color: var(--el-text-color-placeholder);
}

.user-chip {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  color: var(--el-text-color-primary);
  outline: none;
  padding: 4px 6px;
  border-radius: 8px;
  transition: background 0.15s;
}

.user-chip:hover {
  background: var(--el-fill-color-light);
}

.avatar {
  width: 30px;
  height: 30px;
  border-radius: 50%;
  background: var(--el-color-primary-light-8);
  color: var(--el-color-primary-dark-2);
  font-size: 13px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
}

.user-name {
  font-size: 14px;
  font-weight: 500;
}

.role-name {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.arrow {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

// ---- 内容区 ----
// Fluid 布局（对齐 Ant Design Pro contentWidth: Fluid 惯例）：
// 数据密集页（表格/图表/看板）铺满可用宽度，只留内边距；
// 表单/阅读类页面用 .app-page--narrow 自行收窄居中。
.layout-main {
  padding: 20px 28px;
  overflow-y: auto;
  background: var(--app-bg);
}
</style>
