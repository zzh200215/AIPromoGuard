<template>
  <div class="page-header">
    <div class="header-main">
      <h2 class="title">{{ title }}</h2>
      <p v-if="description" class="desc">{{ description }}</p>
    </div>
    <div v-if="$slots.default" class="actions">
      <slot />
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  title: string
  /** 一句话说明该页面的用途，消除"功能不明确"的困惑 */
  description?: string
}>()
</script>

<style scoped>
.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.title {
  margin: 0;
  /* 页面标题 = 公报标题位：宋体系 + 正字距（Editorial 语言的关键笔触） */
  font-family: var(--app-font-display);
  font-size: 22px;
  font-weight: 700;
  letter-spacing: 0.06em;
  line-height: 1.3;
  color: var(--el-text-color-primary);
}

.desc {
  margin: 6px 0 0;
  font-size: 13px;
  line-height: 1.5;
  color: var(--el-text-color-secondary);
}

.actions {
  display: flex;
  flex-shrink: 0;
  align-items: center;
  gap: 10px;
  padding-top: 2px;
}
</style>
