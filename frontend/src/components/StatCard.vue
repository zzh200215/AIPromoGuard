<template>
  <div class="stat-card">
    <div class="stat-label">{{ label }}</div>
    <div class="stat-value" :class="{ muted: value == null }">{{ value ?? '—' }}</div>
  </div>
</template>

<script setup lang="ts">
defineProps<{ label: string; value: number | string | null | undefined }>()
</script>

<style scoped>
.stat-card {
  background: #fff;
  border: 1px solid var(--app-border);
  border-radius: 8px;
  padding: 16px;
  text-align: center;
}

.stat-label {
  font-size: 13px;
  color: #909399;
}

.stat-value {
  margin-top: 6px;
  font-size: 24px;
  font-weight: 700;
  color: #303133;
}

.stat-value.muted {
  color: #c0c4cc;
}
</style>
