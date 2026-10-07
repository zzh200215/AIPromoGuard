<template>
  <teleport to="body">
    <transition name="palette-fade">
      <div v-if="modelValue" class="palette-overlay" @click.self="close" @keydown.esc="close">
        <div class="palette-panel" role="dialog" aria-label="全局命令面板">
          <div class="palette-search">
            <el-icon :size="16"><Search /></el-icon>
            <input
              ref="inputRef"
              v-model="query"
              class="palette-input"
              placeholder="搜索页面 / 执行操作…"
              @keydown="onKeydown"
            />
            <kbd class="palette-esc">Esc</kbd>
          </div>

          <div ref="listRef" class="palette-list">
            <template v-if="filtered.length">
              <div v-for="(item, index) in filtered" :key="item.key" ref="itemRefs">
                <div v-if="item.group && index === groupStartIndex(item)" class="palette-group">
                  {{ item.group }}
                </div>
                <div
                  class="palette-item"
                  :class="{ active: index === activeIndex }"
                  @mouseenter="activeIndex = index"
                  @click="execute(item)"
                >
                  <span class="palette-item-title">{{ item.title }}</span>
                  <el-icon v-if="item.path" class="palette-item-go"><Right /></el-icon>
                </div>
              </div>
            </template>
            <div v-else class="palette-empty">没有匹配的结果</div>
          </div>

          <div class="palette-foot">
            <span><kbd>↑</kbd><kbd>↓</kbd> 选择</span>
            <span><kbd>Enter</kbd> 打开</span>
            <span><kbd>Esc</kbd> 关闭</span>
          </div>
        </div>
      </div>
    </transition>
  </teleport>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Right, Search } from '@element-plus/icons-vue'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean] }>()

const router = useRouter()
const auth = useAuthStore()
const appStore = useAppStore()

const query = ref('')
const activeIndex = ref(0)
const inputRef = ref<HTMLInputElement>()
const listRef = ref<HTMLElement>()

interface PaletteItem {
  key: string
  title: string
  group?: string
  path?: string
  action?: () => void
  /** 检索别名：主题类动作两种说法都能搜到 */
  keywords?: string
}

/** 导航项 = 菜单可见路由（同 MainLayout 过滤规则）；动作项固定在最后 */
const items = computed<PaletteItem[]>(() => {
  const layoutRoute = router.options.routes.find((r) => r.path === '/')
  const list: PaletteItem[] = []
  for (const child of layoutRoute?.children ?? []) {
    const meta = child.meta ?? {}
    if (meta.menuVisible === false || !meta.title) continue
    if (meta.adminOnly && auth.role !== 'admin') continue
    if (meta.requiredPermission && !auth.hasPermission(meta.requiredPermission)) continue
    list.push({
      key: `nav-${child.path}`,
      title: String(meta.title),
      group: meta.menuGroup ? String(meta.menuGroup) : undefined,
      path: `/${child.path}`,
    })
  }
  list.push({
    key: 'act-theme',
    title: appStore.theme === 'dark' ? '切换为浅色模式' : '切换为深色模式',
    action: () => appStore.toggleTheme(),
    keywords: '主题 明暗 深色 浅色 黑夜 白天 dark light theme',
  })
  return list
})

const filtered = computed<PaletteItem[]>(() => {
  const q = query.value.trim().toLowerCase()
  if (!q) return items.value
  return items.value.filter(
    (i) =>
      i.title.toLowerCase().includes(q) ||
      (i.group ?? '').toLowerCase().includes(q) ||
      (i.keywords ?? '').toLowerCase().includes(q),
  )
})

function groupStartIndex(item: PaletteItem) {
  return filtered.value.findIndex((i) => i.group === item.group)
}

watch(
  () => props.modelValue,
  (open) => {
    if (open) {
      // 每次打开都是新意图：清空上次查询并聚焦
      query.value = ''
      activeIndex.value = 0
      nextTick(() => inputRef.value?.focus())
    }
  },
)

watch(filtered, () => {
  activeIndex.value = 0
})

watch(activeIndex, async (index) => {
  // 键盘导航时保持高亮项在可视区内
  await nextTick()
  listRef.value
    ?.querySelectorAll('.palette-item')
    [index]?.scrollIntoView({ block: 'nearest' })
})

function close() {
  emit('update:modelValue', false)
}

function execute(item: PaletteItem) {
  close()
  if (item.path) {
    router.push(item.path)
  } else {
    item.action?.()
  }
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    activeIndex.value = (activeIndex.value + 1) % filtered.value.length
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    activeIndex.value = (activeIndex.value - 1 + filtered.value.length) % filtered.value.length
  } else if (e.key === 'Enter') {
    e.preventDefault()
    const item = filtered.value[activeIndex.value]
    if (item) execute(item)
  } else if (e.key === 'Escape') {
    close()
  }
}

defineExpose({ inputRef })
</script>

<style scoped lang="scss">
.palette-overlay {
  position: fixed;
  inset: 0;
  z-index: 3001;
  background: rgba(12, 20, 32, 0.45);
  display: flex;
  justify-content: center;
  align-items: flex-start;
  padding-top: 18vh;
}

.palette-panel {
  width: min(580px, calc(100vw - 48px));
  border-radius: 14px;
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  box-shadow: var(--app-shadow-pop);
  overflow: hidden;
}

.palette-search {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 16px;
  border-bottom: 1px solid var(--app-border-light);
  color: var(--el-text-color-secondary);
}

.palette-input {
  flex: 1;
  border: none;
  outline: none;
  background: transparent;
  font-size: 15px;
  color: var(--el-text-color-primary);

  &::placeholder {
    color: var(--el-text-color-placeholder);
  }
}

.palette-esc,
.palette-foot kbd {
  display: inline-block;
  padding: 1px 6px;
  border: 1px solid var(--app-border);
  border-bottom-width: 2px;
  border-radius: 5px;
  font-size: 11px;
  line-height: 16px;
  color: var(--el-text-color-secondary);
  background: var(--app-surface-2);
}

.palette-list {
  max-height: 320px;
  overflow-y: auto;
  padding: 6px;
}

.palette-group {
  padding: 8px 10px 4px;
  font-size: 12px;
  color: var(--el-text-color-placeholder);
}

.palette-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 9px 10px;
  border-radius: 8px;
  font-size: 14px;
  color: var(--el-text-color-primary);
  cursor: pointer;

  &.active {
    background: var(--el-color-primary-light-9);
    color: var(--el-color-primary);
  }
}

.palette-item-go {
  font-size: 13px;
  opacity: 0.5;
}

.palette-empty {
  padding: 28px 0;
  text-align: center;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.palette-foot {
  display: flex;
  gap: 16px;
  padding: 10px 16px;
  border-top: 1px solid var(--app-border-light);
  font-size: 12px;
  color: var(--el-text-color-secondary);

  kbd {
    margin-right: 4px;
  }
}

.palette-fade-enter-active,
.palette-fade-leave-active {
  transition: opacity 0.15s ease;
}

.palette-fade-enter-from,
.palette-fade-leave-to {
  opacity: 0;
}
</style>
