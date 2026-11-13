import { execFileSync } from 'node:child_process'
import { existsSync } from 'node:fs'

const NODE = process.execPath
const PNPM =
  process.env.DSH_PNPM_CLI ??
  'C:\\Users\\HP\\.dsh\\dsh-runtimes\\dsh-primary-runtime\\dependencies\\pnpm\\bin\\pnpm.mjs'

export default async function globalSetup() {
  process.env.VITE_USE_MOCK = '1' // e2e 一律吃契约样例（构建期内联）
  execFileSync(NODE, [PNPM, 'build'], { stdio: 'inherit', env: process.env })
  if (!existsSync('dist/index.html')) throw new Error('e2e 需要 dist 产物')
}
