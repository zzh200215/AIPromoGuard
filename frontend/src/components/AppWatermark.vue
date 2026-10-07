<template>
  <div v-if="visible" class="app-watermark" :style="{ backgroundImage: `url(${dataUrl})` }" />
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'

/**
 * 合规水印：登录用户名 + 日期平铺内容区，穿透交互不影响操作。
 * 中性灰低透明度，明暗主题下都保持可辨但不干扰阅读。
 */
const auth = useAuthStore()
const appStore = useAppStore()

const dataUrl = computed(() => {
  const name = auth.user?.username
  if (!name) return ''
  const text = `${name} · ${new Date().toLocaleDateString('zh-CN')}`
  const canvas = document.createElement('canvas')
  canvas.width = 280
  canvas.height = 190
  const ctx = canvas.getContext('2d')
  if (!ctx) return ''
  ctx.translate(canvas.width / 2, canvas.height / 2)
  ctx.rotate((-22 * Math.PI) / 180)
  ctx.font = '600 13px sans-serif'
  ctx.fillStyle = 'rgba(96, 116, 148, 0.13)'
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText(text, 0, 0)
  return canvas.toDataURL()
})

const visible = computed(() => appStore.watermark && Boolean(auth.user?.username))
</script>

<style scoped>
.app-watermark {
  position: fixed;
  inset: 0;
  z-index: 3000;
  pointer-events: none;
}
</style>
