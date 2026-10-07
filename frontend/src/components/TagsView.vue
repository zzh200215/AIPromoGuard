<template>
  <div class="tags-view">
    <el-scrollbar>
      <div class="tags-inner">
        <span
          v-for="tag in tagsStore.tags"
          :key="tag.path"
          class="tag"
          :class="{ active: tag.path === route.path }"
          @click="go(tag)"
          @contextmenu="onContextMenu($event, tag)"
        >
          <span class="tag-dot" />
          <span class="tag-title">{{ tag.title }}</span>
          <el-icon v-if="!tag.affix" class="tag-close" @click.stop="onClose(tag)">
            <Close />
          </el-icon>
        </span>
      </div>
    </el-scrollbar>

    <!-- 标签右键菜单 -->
    <teleport to="body">
      <div v-if="ctx.show" class="ctx-overlay" @click="closeCtx" @contextmenu.prevent="closeCtx" />
      <div v-if="ctx.show" class="ctx-menu" :style="{ left: `${ctx.x}px`, top: `${ctx.y}px` }">
        <div class="ctx-item" @click="onCtxRefresh">
          <el-icon :size="13"><Refresh /></el-icon>刷新页面
        </div>
        <div class="ctx-item" @click="onCtxCloseOthers">
          <el-icon :size="13"><CircleClose /></el-icon>关闭其他
        </div>
      </div>
    </teleport>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { CircleClose, Close, Refresh } from '@element-plus/icons-vue'
import { HOME_PATH, useTagsStore, type TagItem } from '@/stores/tags'

const route = useRoute()
const router = useRouter()
const tagsStore = useTagsStore()

// 会话开始只留固定的工作台标签，再补上当前页；覆盖退出重登后残留旧标签的场景
onMounted(() => {
  tagsStore.resetToHome()
  tagsStore.addRoute(route)
})

watch(
  () => route.path,
  () => tagsStore.addRoute(route),
)

function go(tag: TagItem) {
  if (tag.path !== route.path) router.push(tag.path)
}

function onClose(tag: TagItem) {
  const idx = tagsStore.tags.findIndex((t) => t.path === tag.path)
  if (idx < 0) return
  const isActive = tag.path === route.path
  tagsStore.removeTag(tag.path)
  if (isActive) {
    // 关闭的是当前页：跳到相邻标签（优先右边，没有则左边）
    const next = tagsStore.tags[Math.min(idx, tagsStore.tags.length - 1)]
    router.push(next ? next.path : HOME_PATH)
  }
}

// ---- 右键菜单 ----
const ctx = reactive({ show: false, x: 0, y: 0, path: '' })

function onContextMenu(e: MouseEvent, tag: TagItem) {
  e.preventDefault()
  // 贴近视口边缘时往回收，避免菜单被裁掉
  ctx.x = Math.min(e.clientX, window.innerWidth - 132)
  ctx.y = Math.min(e.clientY, window.innerHeight - 92)
  ctx.path = tag.path
  ctx.show = true
}

function closeCtx() {
  ctx.show = false
}

async function onCtxRefresh() {
  closeCtx()
  // 先等路由切换完成，否则 bump 触发的缓存剔除会落在旧页面名上
  if (route.path !== ctx.path) await router.push(ctx.path)
  // refreshKey 进 router-view 的 key，自增一次即强制当前页重挂载
  tagsStore.bump()
}

function onCtxCloseOthers() {
  closeCtx()
  tagsStore.closeOthers(ctx.path)
  if (route.path !== ctx.path) router.push(ctx.path)
}
</script>

<style scoped lang="scss">
.tags-view {
  flex-shrink: 0;
  padding: 6px 16px 0;
  background: var(--app-surface);
  border-bottom: 1px solid var(--app-border-light);
}

.tags-inner {
  display: flex;
  align-items: center;
  gap: 8px;
}

.tag {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 27px;
  padding: 0 10px;
  border: 1px solid var(--app-border);
  border-radius: 3px 3px 0 0;
  border-bottom: none;
  background: var(--app-surface);
  color: var(--el-text-color-regular);
  font-size: 13px;
  line-height: 1;
  white-space: nowrap;
  cursor: pointer;
  user-select: none;
  transition: color 0.15s, border-color 0.15s, background 0.15s;

  &:hover {
    color: var(--el-color-primary);
  }

  &.active {
    color: var(--el-color-primary);
    border-color: var(--el-color-primary-light-5);
    background: var(--el-color-primary-light-9);

    .tag-dot {
      opacity: 1;
    }
  }
}

.tag-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--el-color-primary);
  opacity: 0;
  flex-shrink: 0;
}

.tag-close {
  padding: 1px;
  margin-right: -4px;
  border-radius: 50%;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  transition: background 0.15s, color 0.15s;

  &:hover {
    background: var(--el-fill-color-dark);
    color: var(--el-color-danger);
  }
}

// ---- 右键菜单（teleport 到 body）----
.ctx-overlay {
  position: fixed;
  inset: 0;
  z-index: 3002;
}

.ctx-menu {
  position: fixed;
  z-index: 3003;
  min-width: 124px;
  padding: 4px;
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  border-radius: 6px;
  box-shadow: var(--app-shadow-pop);
}

.ctx-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 12px;
  border-radius: 4px;
  color: var(--el-text-color-primary);
  font-size: 13px;
  cursor: pointer;

  &:hover {
    background: var(--el-color-primary-light-9);
    color: var(--el-color-primary);
  }
}
</style>
