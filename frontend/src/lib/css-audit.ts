// 审计工具共享库（批准 1，落位 src/lib）：vitest 测试、%TEMP%\dsh-redtrace-sdd\v1_mutants_regression.mjs
// （visual-qa v1-mutants 回归）与 visual-qa 的专项回归（静态 import 链 + 行为变异穿透）共用
// 【同一实现】，杜绝「测试里复刻一份正则」造成的判定漂移（visual-qa V1 报告修复纪律原文）。
// 本库不被应用代码 import，不进入生产构建图；修改需与审计方同步。
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'

// ── 硬编码色值检测（I-1 补强后的全检测面）──
const HEX_COLOR = /#[0-9a-fA-F]{3,8}\b/g
const URL_HEX = /%23[0-9a-fA-F]{3,8}\b/gi
const FN_COLOR = /\b(?:rgba?|hsla?)\s*\(/gi
const NAMED = [
  'red', 'blue', 'green', 'black', 'white', 'yellow', 'orange', 'purple', 'gray', 'grey',
  'silver', 'maroon', 'navy', 'teal', 'olive', 'lime', 'aqua', 'cyan', 'fuchsia', 'magenta',
  'violet', 'indigo', 'gold', 'brown', 'pink', 'coral', 'salmon', 'khaki', 'plum', 'beige',
  'ivory', 'lavender', 'turquoise', 'tomato', 'crimson', 'darkred', 'darkblue', 'darkgreen',
  'lightgray', 'lightgrey', 'lightblue', 'lightgreen', 'royalblue', 'steelblue', 'skyblue',
  'slategray', 'dimgray', 'firebrick', 'forestgreen', 'goldenrod', 'hotpink', 'midnightblue',
  'orangered', 'palegreen', 'peru', 'orchid', 'darkorange', 'deeppink', 'dodgerblue',
]
const NAMED_COLOR = new RegExp(
  String.raw`\b(?:color|background-color|background|border-color|outline-color|fill|stroke)\s*[:=]\s*["']?\s*` +
    String.raw`(?:` + NAMED.join('|') + String.raw`)\b`,
  'gi',
)

/** 对任意文本跑全检测面（hex / %23hex(data-URI) / rgb()/hsl() 函数式 / 命名色值位）。 */
export function scanTextForColors(text: string): string[] {
  return [
    ...(text.match(HEX_COLOR) ?? []),
    ...(text.match(URL_HEX) ?? []),
    ...(text.match(FN_COLOR) ?? []),
    ...(text.match(NAMED_COLOR) ?? []),
  ]
}

/** 文件级检测：.vue 全文扫描（模板属性/绑定与 style 块一并覆盖，I-1 ①）。 */
export function findHardcodedColors(file: string): string[] {
  return scanTextForColors(readFileSync(file, 'utf8'))
}

function walkIfDir(dir: string, exts: RegExp): string[] {
  if (!existsSync(dir) || !statSync(dir).isDirectory()) return []
  const out: string[] = []
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) out.push(...walkIfDir(p, exts))
    else if (exts.test(name)) out.push(p)
  }
  return out
}

/** 扫描集 = src/**.{vue,css} + public/**.{css,html,js} + index.html（I-1 ③）。 */
export function collectScanTargets(projectRoot: string): string[] {
  const targets = [
    ...walkIfDir(join(projectRoot, 'src'), /\.(vue|css|ts)$/),
    ...walkIfDir(join(projectRoot, 'public'), /\.(css|html|js)$/),
  ]
  const index = join(projectRoot, 'index.html')
  if (existsSync(index)) targets.push(index)
  // src 扩展名已含 .ts（V1 I-1「扩检测面」方向）→ 显式排除本文件自身：
  // 审计 lib 内含 60+ CSS 命名色清单与 hex 正则字面量，不排除即自判硬编码（review-F2 C-2 附带提醒）。
  // 测试侧有「lib 自身不参与扫描」锁死用例。
  return targets.filter((f) => !/[\\/]src[\\/]lib[\\/]css-audit\.ts$/.test(f))
}

// ── token 层叠解析（I-2）──
export function tokenEntries(cssText: string, name: string): string[] {
  return [...cssText.matchAll(new RegExp(`--${name}:\\s*([^;]+);`, 'g'))].map((m) => m[1].trim())
}

/** 按浏览器层叠语义取【最后一个】定义；同名重复且值不一致 → throw（末位劫持必炸）。 */
export function resolveToken(cssText: string, name: string): string {
  const all = tokenEntries(cssText, name)
  if (all.length === 0) throw new Error(`缺少 --${name}`)
  const last = all[all.length - 1]
  for (const v of all) {
    if (v !== last) {
      throw new Error(`--${name} 重复定义且值不一致：${JSON.stringify(all)}（浏览器层叠取末值 ${last}）`)
    }
  }
  return last
}

// ── WCAG 对比度（设计规范 §3.4 公式）──
function channelLuminance(c8: number): number {
  return c8 <= 0.03928 ? c8 / 12.92 : ((c8 + 0.055) / 1.055) ** 2.4
}
export function relativeLuminance(hex: string): number {
  const h = hex.replace('#', '')
  const [r, g, b] = [0, 2, 4].map((i) => channelLuminance(parseInt(h.slice(i, i + 2), 16) / 255))
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}
export function contrast(fg: string, bg: string): number {
  const [l1, l2] = [relativeLuminance(fg), relativeLuminance(bg)].sort((a, b) => b - a)
  return (l1 + 0.05) / (l2 + 0.05)
}
