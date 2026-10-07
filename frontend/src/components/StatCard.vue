<template>
  <div class="stat-card">
    <div class="stat-label">{{ label }}</div>
    <div class="stat-value num" :class="{ muted: value == null }">{{ value ?? '—' }}</div>
  </div>
</template>

<script setup lang="ts">
defineProps<{ label: string; value: number | string | null | undefined }>()
</script>

<style scoped>
.stat-card {
  background: var(--el-fill-color-lighter);
  border-radius: 10px;
  padding: 14px 16px;
}

.stat-label {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.stat-value {
  margin-top: 6px;
  font-size: 24px;
  font-weight: 700;
  line-height: 1.2;
  color: var(--el-text-color-primary);
}

.stat-value.muted {
  color: var(--el-text-color-placeholder);
}
</style>
