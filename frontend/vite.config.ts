/// 说明：本文件同时承担 Vite 构建配置与 Vitest 测试配置。
/// Vitest/Playwright 配置属于阶段零F S2「工程与测试基础设施」，不依赖后端契约。
import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    // 开发时把 /api 代理到本地后端（阶段三起接真接口；壳阶段 VITE_USE_MOCK=1 时不会用到）
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
    include: ['tests/**/*.test.ts'],
    setupFiles: ['tests/setup.ts'],
  },
})
