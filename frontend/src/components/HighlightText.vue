<template>
  <span v-html="html" class="highlight-text" />
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { safeHighlightHtml } from '@/composables/useHighlight'

const props = defineProps<{ text?: string; highlight?: string }>()

const html = computed(() => {
  const source = props.highlight || props.text || ''
  return safeHighlightHtml(source)
})
</script>

<style scoped>
.highlight-text :deep(em) {
  color: var(--em-color);
  font-style: normal;
  background: var(--em-bg);
  padding: 0 2px;
  border-radius: 2px;
}
</style>
