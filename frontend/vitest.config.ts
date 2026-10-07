import { fileURLToPath, URL } from 'node:url'
import { defineConfig, mergeConfig } from 'vitest/config'
import viteConfig from './vite.config'

/**
 * 复用 vite.config.ts（@ alias + Element Plus 自动导入插件继续生效），
 * 仅追加测试环境配置：jsdom + globals。
 * 测试文件约定：tests 目录下的 .spec.ts 文件（与 src 平级，对齐后端 tests/ 惯例）。
 */
export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      environment: 'jsdom',
      globals: true,
      include: ['tests/**/*.spec.ts'],
      css: false,
      server: {
        deps: {
          // Element Plus 走 ESM 直引 CSS，node 环境加载 .css 会炸——inline 交给 vitest 转换
          inline: ['element-plus', '@element-plus/icons-vue'],
        },
      },
    },
  }),
)
