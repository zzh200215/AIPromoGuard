<template>
  <el-empty :description="description ?? '暂无数据'" />
</template>

<script setup lang="ts">
defineProps<{ description?: string }>()
</script>
