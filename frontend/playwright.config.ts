import { defineConfig } from '@playwright/test'

// e2e 构建/预览命令走 bundled pnpm（本机无全局 pnpm，见 RUNBOOK「环境」）。
const NODE = process.execPath
const PNPM =
  process.env.DSH_PNPM_CLI ??
  'C:\\Users\\HP\\.dsh\\dsh-runtimes\\dsh-primary-runtime\\dependencies\\pnpm\\bin\\pnpm.mjs'

// 端口：4173 落在本机 Windows 系统保留段（netsh excludedportrange：4097–4196），
// 实测 EACCES，改用保留段外的 8973。
export default defineConfig({
  testDir: './tests/e2e',
  timeout: 30_000,
  use: {
    baseURL: 'http://127.0.0.1:8973',
  },
  projects: [
    { name: 'desktop', use: { viewport: { width: 1024, height: 768 } } },
    { name: 'narrow', use: { viewport: { width: 375, height: 720 } } },
    // 简报 S5/S8 的判定点：768px 窄屏冲突堆叠
    { name: '768', use: { viewport: { width: 767, height: 900 } } },
  ],
  webServer: {
    // 构建（mock 模式）后用 vite preview 起静态服务
    command: `"${NODE}" "${PNPM}" preview --host 127.0.0.1 --port 8973 --strictPort`,
    cwd: process.cwd(),
    url: 'http://127.0.0.1:8973',
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
  globalSetup: './tests/e2e/global-setup.ts',
})
