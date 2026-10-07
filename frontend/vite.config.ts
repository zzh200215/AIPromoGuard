import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'

export default defineConfig({
  plugins: [
    vue(),
    AutoImport({
      imports: ['vue', 'vue-router', 'pinia'],
      resolvers: [ElementPlusResolver()],
      dts: 'auto-imports.d.ts',
    }),
    Components({
      resolvers: [ElementPlusResolver()],
      dts: 'components.d.ts',
    }),
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      // 后端所有接口前缀 /api/v1，这里不重写路径
      // 注意：Windows 下 Node 解析 localhost 可能在 IPv4/IPv6 间摇摆，显式钉死 127.0.0.1
      // 本机 8000 被其它项目占用时，可用 VITE_API_TARGET 指向 mock/后端实际端口
      '/api/v1': {
        target: process.env.VITE_API_TARGET || 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  preview: {
    // 生产构建预览（npm run build && npm run preview）：proxy 与 dev 同口径——
    // preview 不继承 server.proxy，需显式声明，否则预览页调不到后端
    port: 5173,
    proxy: {
      '/api/v1': {
        target: process.env.VITE_API_TARGET || 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    chunkSizeWarningLimit: 1024,
  },
})
